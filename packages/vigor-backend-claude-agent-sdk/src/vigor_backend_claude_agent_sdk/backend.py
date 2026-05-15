"""Claude Agent SDK-backed VIGOR `AgentBackend` (optional dependency).

Research references:
* https://docs.anthropic.com/en/api/agent-sdk/python
* https://docs.anthropic.com/en/agent-sdk/permissions
* https://pypi.org/project/claude-agent-sdk/

Design:
* `query(prompt, options)` is used for every call (stateless).
* `permission_mode="dontAsk"` + `setting_sources=[]` keeps runs hermetic.
* Success = `ResultMessage.subtype == "success"` and `not is_error`.
* Canonical text output = `ResultMessage.result` (fallback to concatenated
  `TextBlock.text` from assistant messages).
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
from vigor_core.schemas import ArtifactIR, PatchPlan, ReviewReport, Usage
from vigor_core.util import utcnow_iso

_INSTALL_HINT = (
    "claude-agent-sdk is not installed. Add the 'claude' extra: "
    "`uv add 'vigor-backend-claude-agent-sdk[claude]'`."
)


@dataclass(slots=True)
class ClaudeBackendConfig:
    model: str = "claude-sonnet-4-5"
    max_turns: int = 8
    permission_mode: str = "dontAsk"
    allowed_tools: list[str] = field(default_factory=lambda: ["Read", "Glob", "Grep"])
    disallowed_tools: list[str] = field(default_factory=list)
    system_prompt_generate: str = "You are the VIGOR generator. Return structured JSON only."
    system_prompt_review: str = "You are a VIGOR reviewer. Be concise and evidence-grounded."
    system_prompt_patch: str = (
        "You are the VIGOR patch planner. Emit 1-5 actionable change objectives."
    )
    cwd: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    setting_sources: list[str] = field(default_factory=list)


class ClaudeAgentBackend(AgentBackend):
    """Claude Agent SDK-backed agent backend."""

    def __init__(self, config: ClaudeBackendConfig | None = None) -> None:
        self._config = config or ClaudeBackendConfig()
        self._input_tokens: int = 0
        self._output_tokens: int = 0
        self._usd: float = 0.0
        self._priced: bool = False

    def _import_sdk(self) -> Any:
        try:
            import claude_agent_sdk
        except ImportError as exc:
            raise ImportError(_INSTALL_HINT) from exc
        return claude_agent_sdk

    def _options(self, system_prompt: str) -> Any:  # pragma: no cover
        sdk = self._import_sdk()
        return sdk.ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=self._config.model,
            max_turns=self._config.max_turns,
            permission_mode=self._config.permission_mode,
            allowed_tools=list(self._config.allowed_tools),
            disallowed_tools=list(self._config.disallowed_tools),
            setting_sources=list(self._config.setting_sources),
            cwd=self._config.cwd,
            env=dict(self._config.env) if self._config.env else None,
        )

    async def _run(self, prompt: str, system_prompt: str) -> tuple[bool, str]:
        sdk = self._import_sdk()
        options = self._options(system_prompt)
        fallback: list[str] = []
        async for msg in sdk.query(prompt=prompt, options=options):  # pragma: no cover
            if isinstance(msg, sdk.AssistantMessage):
                for block in msg.content:
                    if isinstance(block, sdk.TextBlock):
                        fallback.append(block.text)
            elif isinstance(msg, sdk.ResultMessage):
                self._accumulate_usage(msg)
                ok = msg.subtype == "success" and not msg.is_error
                return ok, (msg.result or "".join(fallback))
        return False, "".join(fallback)

    def _accumulate_usage(self, msg: Any) -> None:
        """Roll the per-call ResultMessage telemetry into running totals.

        ``ResultMessage.usage`` is a dict-like mapping of token counters
        (``input_tokens``, ``output_tokens`` and cache variants); we sum
        the two top-level counters across calls. ``total_cost_usd`` is
        the SDK-priced run cost — we mark the backend as "priced" the
        first time we see one so :meth:`usage` can decide whether to
        report ``usd`` or fall open with ``None``.
        """
        usage = getattr(msg, "usage", None)
        if isinstance(usage, dict):
            self._input_tokens += int(usage.get("input_tokens", 0) or 0)
            self._output_tokens += int(usage.get("output_tokens", 0) or 0)
        cost = getattr(msg, "total_cost_usd", None)
        if cost is not None:
            self._priced = True
            self._usd += float(cost)

    async def usage(self) -> Usage:
        return Usage(
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            usd=self._usd if self._priced else None,
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        prompt = (
            f"Task goal: {request.task.goal}\n"
            f"IR type: {request.plan.ir_type}\n"
            "Respond with a JSON object describing the IR body."
        )
        ok, text = await self._run(prompt, self._config.system_prompt_generate)
        ir = ArtifactIR(
            candidate_id=f"cand_{request.task.task_id}_{len(request.prior_candidates):04d}",
            ir_type=request.plan.ir_type,
            hypothesis="claude-agent-sdk generator",
            body={"raw_output": text, "ok": ok},
            generator={
                "backend": "claude-agent-sdk",
                "model": self._config.model,
                "timestamp": utcnow_iso(),
            },
        )
        return GenerationResult(ir=ir, reasoning=text)

    async def review(self, request: ReviewRequest) -> ReviewResult:
        prompt = (
            "Critique the VIGOR artifact.\n"
            f"artifact uri: {request.artifact.uri}\n"
            f"ir type: {request.ir.ir_type}\n"
            "Return PASS or FAIL followed by a one-line reason."
        )
        ok, text = await self._run(prompt, self._config.system_prompt_review)
        passed = ok and "PASS" in text.upper()
        report = ReviewReport(
            review_id=f"rev_claude_{request.ir.candidate_id}",
            candidate_id=request.ir.candidate_id,
            artifact_id=request.artifact.artifact_id,
            reviewer_id=request.reviewer_id,
            reviewer_type="model_critic",
            summary=text[:400] if text else "claude agent returned empty response",
            scores={"quality": 1.0 if passed else 0.0},
            passed=passed,
            recommended_action="accept" if passed else "patch",
        )
        return ReviewResult(report=report)

    async def propose_patch(self, request: PatchProposalRequest) -> PatchProposal:
        review_summaries = "\n".join(f"- [{r.reviewer_id}] {r.summary}" for r in request.reviews)
        prompt = "Given the reviews below, list 1-5 concrete patch objectives.\n" + review_summaries
        _ok, text = await self._run(prompt, self._config.system_prompt_patch)
        objectives = [
            line.strip("- ").strip()
            for line in text.splitlines()
            if line.strip().startswith(("-", "*"))
            or (line.strip()[:1].isdigit() if line.strip() else False)
        ] or ["improve based on reviews"]
        plan = PatchPlan(
            patch_id=f"patch_claude_{request.ir.candidate_id}",
            source_candidate_id=request.ir.candidate_id,
            basis=[r.review_id for r in request.reviews],
            objectives=objectives,
        )
        return PatchProposal(patch=plan, rationale=text[:400])
