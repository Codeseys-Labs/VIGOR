"""Unit tests for ``RunBudgetTracker``."""

from __future__ import annotations

import pytest
from vigor_core.interfaces import (
    AgentBackend,
    GenerationRequest,
    GenerationResult,
    PatchProposal,
    PatchProposalRequest,
    ReviewRequest,
    ReviewResult,
)
from vigor_core.schemas import ArtifactIR, Budgets, PatchPlan, ReviewReport, Usage
from vigor_runtime.budget import RunBudgetTracker


class _ScriptedUsageBackend(AgentBackend):
    """Backend whose ``usage()`` returns a scripted sequence of snapshots."""

    def __init__(self, snapshots: list[Usage]) -> None:
        self._snapshots = snapshots
        self._idx = 0
        self.usage_calls = 0

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        ir = ArtifactIR(
            candidate_id=f"cand_{request.task.task_id}_{len(request.prior_candidates):04d}",
            ir_type=request.plan.ir_type,
            body={},
        )
        return GenerationResult(ir=ir)

    async def review(self, request: ReviewRequest) -> ReviewResult:
        return ReviewResult(
            report=ReviewReport(
                review_id=f"rev_{request.ir.candidate_id}",
                candidate_id=request.ir.candidate_id,
                artifact_id=request.artifact.artifact_id,
                reviewer_id=request.reviewer_id,
                reviewer_type="model_critic",
                summary="ok",
                passed=True,
            )
        )

    async def propose_patch(self, request: PatchProposalRequest) -> PatchProposal:
        return PatchProposal(
            patch=PatchPlan(
                patch_id=f"patch_{request.ir.candidate_id}",
                source_candidate_id=request.ir.candidate_id,
                objectives=["noop"],
            )
        )

    async def usage(self) -> Usage:
        self.usage_calls += 1
        idx = min(self._idx, len(self._snapshots) - 1)
        self._idx += 1
        return self._snapshots[idx]


@pytest.mark.asyncio
async def test_check_falls_open_when_max_cost_unset() -> None:
    backend = _ScriptedUsageBackend([Usage(usd=99.0)])
    tracker = RunBudgetTracker(backend, Budgets())
    assert tracker.latest.input_tokens == 0
    exceeded = await tracker.check()
    assert exceeded is False
    assert tracker.latest.usd == 99.0  # snapshot still refreshed


@pytest.mark.asyncio
async def test_check_falls_open_when_backend_reports_no_usd() -> None:
    snap = Usage(input_tokens=1_000_000, output_tokens=500_000, usd=None)
    backend = _ScriptedUsageBackend([snap])
    tracker = RunBudgetTracker(backend, Budgets(max_cost_usd=0.01))
    exceeded = await tracker.check()
    assert exceeded is False
    assert tracker.latest.input_tokens == 1_000_000


@pytest.mark.asyncio
async def test_check_returns_true_when_ceiling_crossed() -> None:
    snapshots = [
        Usage(input_tokens=100, output_tokens=50, usd=1.50),
        Usage(input_tokens=400, output_tokens=200, usd=4.99),
        Usage(input_tokens=800, output_tokens=400, usd=5.01),
    ]
    backend = _ScriptedUsageBackend(snapshots)
    tracker = RunBudgetTracker(backend, Budgets(max_cost_usd=5.00))
    assert await tracker.check() is False
    assert await tracker.check() is False
    assert await tracker.check() is True
    assert tracker.latest.usd == 5.01


@pytest.mark.asyncio
async def test_check_returns_true_at_exact_ceiling() -> None:
    backend = _ScriptedUsageBackend([Usage(usd=2.50)])
    tracker = RunBudgetTracker(backend, Budgets(max_cost_usd=2.50))
    assert await tracker.check() is True


@pytest.mark.asyncio
async def test_snapshot_polls_backend_without_enforcement() -> None:
    backend = _ScriptedUsageBackend([Usage(input_tokens=10, output_tokens=5, usd=0.10)])
    tracker = RunBudgetTracker(backend, Budgets())
    snap = await tracker.snapshot()
    assert snap.input_tokens == 10
    assert backend.usage_calls == 1


@pytest.mark.asyncio
async def test_default_agent_backend_usage_returns_zeros() -> None:
    """ABC default ``usage()`` returns zeros so non-reporting backends fall open."""
    backend = _ScriptedUsageBackend([])

    class _DefaultUsageBackend(_ScriptedUsageBackend):
        async def usage(self) -> Usage:  # type: ignore[override]
            return await AgentBackend.usage(self)

    backend = _DefaultUsageBackend([])
    tracker = RunBudgetTracker(backend, Budgets(max_cost_usd=1.0))
    assert await tracker.check() is False
    assert tracker.latest.usd is None
    assert tracker.latest.input_tokens == 0
