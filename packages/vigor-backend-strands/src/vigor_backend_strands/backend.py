"""Strands-backed implementation of the VIGOR `AgentBackend`.

Strands is an optional dependency. We import lazily and raise a helpful
`ImportError` if the user has not installed the `strands` extra. This keeps
`vigor-core` and `vigor-runtime` usable in minimal environments.

Research references:
* https://strandsagents.com/docs/user-guide/quickstart/python/
* https://strandsagents.com/docs/api/python/strands.agent.agent_result/
* https://strandsagents.com/docs/user-guide/concepts/streaming/async-iterators/
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from vigor_core.interfaces import (
    AgentBackend,
    GenerationRequest,
    GenerationResult,
    PatchProposal,
    PatchProposalRequest,
    ReviewRequest,
    ReviewResult,
)
from vigor_core.schemas import ArtifactIR, PatchPlan, ReviewReport
from vigor_core.util import utcnow_iso

_INSTALL_HINT = (
    "strands-agents is not installed. Add the 'strands' extra: "
    "`uv add 'vigor-backend-strands[strands]'` or install strands-agents directly."
)


@dataclass(slots=True)
class StrandsBackendConfig:
    """Minimal configuration for the Strands backend."""

    model: str = "claude-sonnet-4-5"
    provider: str = "bedrock"  # "bedrock" | "anthropic" | "openai"
    system_prompt_generate: str = (
        "You are the VIGOR generator. Produce a structured editable representation."
    )
    system_prompt_review: str = (
        "You are a VIGOR reviewer. Produce a concise critique with evidence."
    )
    system_prompt_patch: str = (
        "You are the VIGOR patch planner. Convert reviewer findings into targeted changes."
    )
    provider_kwargs: dict[str, Any] = field(default_factory=dict)


class StrandsAgentBackend(AgentBackend):
    """Strands-backed agent backend.

    The real Strands SDK is imported lazily. This class can be instantiated
    and passed around without Strands installed; the first `await` into it
    that actually needs Strands will raise `ImportError` with a helpful hint.
    """

    def __init__(self, config: StrandsBackendConfig | None = None) -> None:
        self._config = config or StrandsBackendConfig()
        self._agent: Any | None = None

    def _load_agent(self) -> Any:
        if self._agent is not None:
            return self._agent
        try:
            from strands import Agent
        except ImportError as exc:  # pragma: no cover - exercised via test shim
            raise ImportError(_INSTALL_HINT) from exc

        model = self._build_model()
        self._agent = Agent(
            model=model,
            system_prompt=self._config.system_prompt_generate,
            callback_handler=None,
        )
        return self._agent

    def _build_model(self) -> Any:  # pragma: no cover - requires strands at runtime
        provider = self._config.provider
        if provider == "bedrock":
            from strands.models import BedrockModel

            return BedrockModel(model_id=self._config.model, **self._config.provider_kwargs)
        if provider == "anthropic":
            from strands.models.anthropic import AnthropicModel

            return AnthropicModel(model_id=self._config.model, **self._config.provider_kwargs)
        if provider == "openai":
            from strands.models.openai import OpenAIModel

            return OpenAIModel(model_id=self._config.model, **self._config.provider_kwargs)
        raise ValueError(f"unknown strands provider: {provider}")

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        agent = self._load_agent()
        prompt = (
            "Task goal: " + request.task.goal + "\n"
            "Desired IR type: " + request.plan.ir_type + "\n"
            "Return ONLY a JSON object matching the IR schema."
        )
        result = await agent.invoke_async(prompt)  # pragma: no cover
        text = str(result) if not hasattr(result, "message") else str(result.message)
        ir = ArtifactIR(
            candidate_id=f"cand_{request.task.task_id}_{len(request.prior_candidates):04d}",
            ir_type=request.plan.ir_type,
            hypothesis="strands generator",
            body={"raw_output": text},
            generator={
                "backend": "strands",
                "model": self._config.model,
                "provider": self._config.provider,
                "timestamp": utcnow_iso(),
            },
        )
        return GenerationResult(ir=ir, reasoning=text)

    async def review(self, request: ReviewRequest) -> ReviewResult:
        agent = self._load_agent()
        prompt = (
            "Critique the following artifact produced by VIGOR.\n"
            f"artifact uri: {request.artifact.uri}\n"
            f"ir type: {request.ir.ir_type}\n"
            "Return PASS or FAIL with a one-sentence reason."
        )
        result = await agent.invoke_async(prompt)  # pragma: no cover
        text = str(result) if not hasattr(result, "message") else str(result.message)
        passed = "PASS" in text.upper()
        report = ReviewReport(
            review_id=f"rev_strands_{request.ir.candidate_id}",
            candidate_id=request.ir.candidate_id,
            artifact_id=request.artifact.artifact_id,
            reviewer_id=request.reviewer_id,
            reviewer_type="model_critic",
            summary=text[:400],
            scores={"quality": 1.0 if passed else 0.0},
            passed=passed,
            recommended_action="accept" if passed else "patch",
        )
        return ReviewResult(report=report)

    async def propose_patch(self, request: PatchProposalRequest) -> PatchProposal:
        agent = self._load_agent()
        review_summaries = "\n".join(f"- [{r.reviewer_id}] {r.summary}" for r in request.reviews)
        prompt = (
            "Given the reviews below, list 1-5 concrete patch objectives for the IR.\n"
            + review_summaries
        )
        result = await agent.invoke_async(prompt)  # pragma: no cover
        text = str(result) if not hasattr(result, "message") else str(result.message)
        objectives = [
            line.strip("- ").strip()
            for line in text.splitlines()
            if line.strip().startswith(("-", "*")) or line.strip().startswith(tuple("0123456789"))
        ] or ["improve based on reviews"]
        plan = PatchPlan(
            patch_id=f"patch_strands_{request.ir.candidate_id}",
            source_candidate_id=request.ir.candidate_id,
            basis=[r.review_id for r in request.reviews],
            objectives=objectives,
        )
        return PatchProposal(patch=plan, rationale=text[:400])
