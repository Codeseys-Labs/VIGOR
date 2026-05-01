"""In-process reference backends used for testing and demos."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from vigor_core.interfaces import (
    AgentBackend,
    GenerationRequest,
    GenerationResult,
    PatchProposal,
    PatchProposalRequest,
    ReviewRequest,
    ReviewResult,
    ToolBackend,
    ToolResult,
)
from vigor_core.schemas import ArtifactIR, PatchPlan, ReviewReport, ToolManifest
from vigor_core.util import utcnow_iso

SeedIRFactory = Callable[[GenerationRequest], dict[str, Any]]


class EchoAgentBackend(AgentBackend):
    """Deterministic agent backend that returns canned outputs."""

    def __init__(self, seed_ir_factory: SeedIRFactory | None = None) -> None:
        self._seed_ir_factory = seed_ir_factory

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        candidate_id = f"cand_{request.task.task_id}_{len(request.prior_candidates):04d}"
        if self._seed_ir_factory is not None:
            body = self._seed_ir_factory(request)
        else:
            body = {"echo": request.task.goal}
        ir = ArtifactIR(
            candidate_id=candidate_id,
            ir_type=request.plan.ir_type,
            hypothesis="echo",
            body=body,
            generator={"backend": "echo", "timestamp": utcnow_iso()},
        )
        return GenerationResult(ir=ir, reasoning="echo backend")

    async def review(self, request: ReviewRequest) -> ReviewResult:
        report = ReviewReport(
            review_id=f"rev_{request.reviewer_id}_{request.ir.candidate_id}",
            candidate_id=request.ir.candidate_id,
            artifact_id=request.artifact.artifact_id,
            reviewer_id=request.reviewer_id,
            reviewer_type="model_critic",
            summary="echo reviewer: no critique",
            scores={"quality": 1.0},
            passed=True,
            confidence=0.5,
            recommended_action="accept",
        )
        return ReviewResult(report=report)

    async def propose_patch(self, request: PatchProposalRequest) -> PatchProposal:
        plan = PatchPlan(
            patch_id=f"patch_echo_{request.ir.candidate_id}",
            source_candidate_id=request.ir.candidate_id,
            objectives=["no-op"],
            allowed_operations=[],
        )
        return PatchProposal(patch=plan, rationale="echo backend never patches")


class NullToolBackend(ToolBackend):
    """Tool backend that exposes no tools."""

    async def call_tool(self, tool_id: str, payload: dict[str, Any]) -> ToolResult:
        return ToolResult(tool_id=tool_id, status="failure", error="no tools registered")

    async def list_tools(self) -> list[ToolManifest]:
        return []


def _seed_text_from_goal(request: GenerationRequest) -> dict[str, Any]:
    return {"text": request.task.goal}


def make_toy_echo_backend() -> EchoAgentBackend:
    """No-arg factory: an `EchoAgentBackend` that produces ``{"text": goal}`` IR.

    Useful as a default backend in `AgentConfig` factory refs when the
    consumer wants the toy text adapter to work end-to-end without
    writing a custom backend.
    """

    return EchoAgentBackend(seed_ir_factory=_seed_text_from_goal)
