"""Tests for the ADR-0037 RuntimeObserver Protocol seam."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
from vigor_core.archive import RunArchive
from vigor_core.errors import VigorError
from vigor_core.interfaces import (
    AgentBackend,
    GenerationRequest,
    GenerationResult,
    PatchProposal,
    PatchProposalRequest,
    ReviewRequest,
    ReviewResult,
    RunContext,
)
from vigor_core.observability import RuntimeObserver
from vigor_core.schemas import (
    AdjudicationReport,
    ArtifactIR,
    Budgets,
    CompileResult,
    ExportBundle,
    ObservableArtifact,
    PatchPlan,
    ReviewReport,
    TaskSpec,
)
from vigor_core.scoring import ScoringPolicy
from vigor_runtime.backends import EchoAgentBackend
from vigor_runtime.orchestrator import Orchestrator
from vigor_runtime.toy_adapter import ToyTextAdapter


def _seed_with_goal(request: GenerationRequest) -> dict[str, Any]:
    return {"text": request.task.goal}


class _RecordingObserver:
    """Captures every lifecycle call. Structurally satisfies RuntimeObserver."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.calls.append((name, args, kwargs))

    def on_run_start(self, run_id: str, task: TaskSpec) -> None:
        self._record("on_run_start", run_id, task)

    def on_iteration_start(self, run_id: str, iteration: int) -> None:
        self._record("on_iteration_start", run_id, iteration)

    def on_candidate_start(self, run_id: str, iteration: int, candidate_id: str) -> None:
        self._record("on_candidate_start", run_id, iteration, candidate_id)

    def on_candidate_end(
        self,
        run_id: str,
        iteration: int,
        candidate_id: str,
        compile_result: CompileResult,
        reviews: list[ReviewReport],
        adjudication: AdjudicationReport,
    ) -> None:
        self._record(
            "on_candidate_end",
            run_id,
            iteration,
            candidate_id,
            compile_result,
            reviews,
            adjudication,
        )

    def on_iteration_end(
        self,
        run_id: str,
        iteration: int,
        candidate_count: int,
        accepted_candidate_id: str | None,
    ) -> None:
        self._record("on_iteration_end", run_id, iteration, candidate_count, accepted_candidate_id)

    def on_run_end(
        self,
        run_id: str,
        accepted: bool,
        stop_reason: str,
        selected_candidate_id: str | None,
    ) -> None:
        self._record("on_run_end", run_id, accepted, stop_reason, selected_candidate_id)

    def on_event(self, name: str, attributes: dict[str, object]) -> None:
        self._record("on_event", name, attributes)


def test_recording_observer_satisfies_protocol() -> None:
    """``runtime_checkable`` Protocol accepts a structurally-conforming object."""

    observer = _RecordingObserver()
    assert isinstance(observer, RuntimeObserver)


def test_partial_observer_fails_protocol_check() -> None:
    """Object missing a lifecycle method is rejected at Orchestrator construction."""

    class _PartialObserver:
        def on_run_start(self, run_id: str, task: TaskSpec) -> None:
            del run_id, task

        # missing the rest

    archive = RunArchive(Path("/tmp/_unused_observer_test"))
    try:
        with pytest.raises(TypeError, match="RuntimeObserver"):
            Orchestrator(
                adapter=ToyTextAdapter(),
                backend=EchoAgentBackend(seed_ir_factory=_seed_with_goal),
                archive=archive,
                observer=_PartialObserver(),  # type: ignore[arg-type]
            )
    finally:
        archive.close()


@pytest.mark.asyncio
async def test_default_no_observer_emits_no_calls(tmp_path: Path) -> None:
    """When observer kwarg is omitted, no observer methods are invoked.

    Asserted indirectly: a run with default kwargs must succeed and the
    orchestrator's ``_observer`` attribute must be ``None``.
    """

    archive = RunArchive(tmp_path)
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=EchoAgentBackend(seed_ir_factory=_seed_with_goal),
        archive=archive,
    )
    assert orchestrator._observer is None
    task = TaskSpec(
        task_id="t_no_observer",
        goal="hi",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    result = await orchestrator.run(task)
    assert result.accepted is True


@pytest.mark.asyncio
async def test_observer_receives_lifecycle_in_order_for_accepted_run(
    tmp_path: Path,
) -> None:
    """A successful single-candidate run fires the canonical lifecycle sequence."""

    archive = RunArchive(tmp_path)
    observer = _RecordingObserver()
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=EchoAgentBackend(seed_ir_factory=_seed_with_goal),
        archive=archive,
        observer=observer,
    )
    task = TaskSpec(
        task_id="t_observer_accept",
        goal="hi",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    result = await orchestrator.run(task)

    assert result.accepted is True
    names = [call[0] for call in observer.calls]
    assert names == [
        "on_run_start",
        "on_iteration_start",
        "on_candidate_start",
        "on_candidate_end",
        "on_iteration_end",
        "on_run_end",
    ]

    # on_candidate_end carries Pydantic objects, not strings.
    cand_end = next(call for call in observer.calls if call[0] == "on_candidate_end")
    _, args, _ = cand_end
    _, _, candidate_id, compile_result, reviews, adjudication = args
    assert candidate_id == "cand_t_observer_accept_0000"
    assert isinstance(compile_result, CompileResult)
    assert all(isinstance(r, ReviewReport) for r in reviews)
    assert isinstance(adjudication, AdjudicationReport)
    assert adjudication.decision == "accept"

    # on_iteration_end reports the accepted candidate id.
    iter_end = next(call for call in observer.calls if call[0] == "on_iteration_end")
    _, args, _ = iter_end
    _, _, candidate_count, accepted_candidate_id = args
    assert candidate_count == 1
    assert accepted_candidate_id == "cand_t_observer_accept_0000"

    # on_run_end carries the canonical outcome triple.
    run_end = next(call for call in observer.calls if call[0] == "on_run_end")
    _, args, _ = run_end
    _, accepted, stop_reason, selected_candidate_id = args
    assert accepted is True
    assert stop_reason == "accepted"
    assert selected_candidate_id == "cand_t_observer_accept_0000"


class _RaisingObserver(_RecordingObserver):
    """Records calls but raises on every method to exercise the try/except wrapper."""

    def on_run_start(self, run_id: str, task: TaskSpec) -> None:
        super().on_run_start(run_id, task)
        raise RuntimeError("observer boom — on_run_start")

    def on_iteration_start(self, run_id: str, iteration: int) -> None:
        super().on_iteration_start(run_id, iteration)
        raise RuntimeError("observer boom — on_iteration_start")

    def on_candidate_start(self, run_id: str, iteration: int, candidate_id: str) -> None:
        super().on_candidate_start(run_id, iteration, candidate_id)
        raise RuntimeError("observer boom — on_candidate_start")

    def on_candidate_end(
        self,
        run_id: str,
        iteration: int,
        candidate_id: str,
        compile_result: CompileResult,
        reviews: list[ReviewReport],
        adjudication: AdjudicationReport,
    ) -> None:
        super().on_candidate_end(
            run_id, iteration, candidate_id, compile_result, reviews, adjudication
        )
        raise RuntimeError("observer boom — on_candidate_end")

    def on_iteration_end(
        self,
        run_id: str,
        iteration: int,
        candidate_count: int,
        accepted_candidate_id: str | None,
    ) -> None:
        super().on_iteration_end(run_id, iteration, candidate_count, accepted_candidate_id)
        raise RuntimeError("observer boom — on_iteration_end")

    def on_run_end(
        self,
        run_id: str,
        accepted: bool,
        stop_reason: str,
        selected_candidate_id: str | None,
    ) -> None:
        super().on_run_end(run_id, accepted, stop_reason, selected_candidate_id)
        raise RuntimeError("observer boom — on_run_end")


@pytest.mark.asyncio
async def test_raising_observer_does_not_break_run(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """ADR-0037: observer bugs are caught + logged but never propagate."""

    archive = RunArchive(tmp_path)
    observer = _RaisingObserver()
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=EchoAgentBackend(seed_ir_factory=_seed_with_goal),
        archive=archive,
        observer=observer,
    )
    task = TaskSpec(
        task_id="t_observer_raises",
        goal="hi",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    with caplog.at_level("WARNING", logger="vigor.runtime"):
        result = await orchestrator.run(task)

    # Run completes successfully despite every observer method raising.
    assert result.accepted is True
    # Each lifecycle method was attempted at least once.
    names = {call[0] for call in observer.calls}
    assert names == {
        "on_run_start",
        "on_iteration_start",
        "on_candidate_start",
        "on_candidate_end",
        "on_iteration_end",
        "on_run_end",
    }
    # WARNING-level logs surface the observer failure for debugging.
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("RuntimeObserver" in r.getMessage() for r in warnings)


class _RankedBackend(AgentBackend):
    """Same shape as test_orchestrator's _RankedBackend, kept local for isolation."""

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        rank = len(request.prior_candidates)
        ir = ArtifactIR(
            candidate_id=f"cand_{request.task.task_id}_{rank:04d}",
            ir_type=request.plan.ir_type,
            body={"text": f"candidate {rank}", "rank": rank},
        )
        return GenerationResult(ir=ir)

    async def review(self, request: ReviewRequest) -> ReviewResult:
        rank = float(request.ir.body["rank"])
        return ReviewResult(
            report=ReviewReport(
                review_id=f"rev_{request.ir.candidate_id}",
                candidate_id=request.ir.candidate_id,
                artifact_id=request.artifact.artifact_id,
                reviewer_id=request.reviewer_id,
                reviewer_type="model_critic",
                summary="ranked",
                scores={"quality": rank / 2.0},
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


@pytest.mark.asyncio
async def test_observer_emits_per_candidate_under_parallel_fanout(
    tmp_path: Path,
) -> None:
    """ADR-0034 + ADR-0037: every candidate in a parallel batch fires a pair."""

    archive = RunArchive(tmp_path)
    observer = _RecordingObserver()
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=_RankedBackend(),
        archive=archive,
        policy=ScoringPolicy(
            policy_id="best", weights={"quality": 1.0}, disagreement_threshold=1.0
        ),
        observer=observer,
    )
    task = TaskSpec(
        task_id="t_observer_parallel",
        goal="parallel",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=4, parallel_candidates=4),
    )
    result = await orchestrator.run(task)
    assert result.accepted is True

    starts = [call[1][2] for call in observer.calls if call[0] == "on_candidate_start"]
    ends = [call[1][2] for call in observer.calls if call[0] == "on_candidate_end"]
    assert sorted(starts) == [
        "cand_t_observer_parallel_0000",
        "cand_t_observer_parallel_0001",
        "cand_t_observer_parallel_0002",
        "cand_t_observer_parallel_0003",
    ]
    assert sorted(ends) == sorted(starts)


class _FailingReviewBackend(AgentBackend):
    """Always rates 'needs GOOD' until the candidate text contains GOOD."""

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        candidate_id = f"cand_{request.task.task_id}_{len(request.prior_candidates):04d}"
        ir = ArtifactIR(
            candidate_id=candidate_id,
            ir_type=request.plan.ir_type,
            body={"text": "seed"},
            generator={"backend": "failing-review"},
        )
        return GenerationResult(ir=ir)

    async def review(self, request: ReviewRequest) -> ReviewResult:
        text = request.ir.body.get("text", "")
        passed = "GOOD" in text
        return ReviewResult(
            report=ReviewReport(
                review_id=f"rev_strict_{request.ir.candidate_id}",
                candidate_id=request.ir.candidate_id,
                artifact_id=request.artifact.artifact_id,
                reviewer_id=request.reviewer_id,
                reviewer_type="model_critic",
                summary="passed" if passed else "needs GOOD",
                scores={"quality": 1.0 if passed else 0.0},
                thresholds={"quality": 0.5},
                passed=passed,
                recommended_action="accept" if passed else "patch",
            )
        )

    async def propose_patch(self, request: PatchProposalRequest) -> PatchProposal:
        plan = PatchPlan(
            patch_id=f"patch_strict_{request.ir.candidate_id}",
            source_candidate_id=request.ir.candidate_id,
            basis=[r.review_id for r in request.reviews],
            objectives=["append 'GOOD'"],
        )
        return PatchProposal(patch=plan, rationale="append GOOD to satisfy critic")


class _AppendPatchAdapter(ToyTextAdapter):
    async def apply_patch(self, ir: ArtifactIR, patch: PatchPlan) -> ArtifactIR:
        text = ir.body.get("text", "")
        for objective in patch.objectives:
            if "append 'GOOD'" in objective:
                text = f"{text}GOOD"
        suffix = uuid.uuid4().hex[:8]
        return ArtifactIR(
            candidate_id=f"{ir.candidate_id}_p{suffix}",
            ir_type=ir.ir_type,
            parent_candidate_id=ir.candidate_id,
            hypothesis="applied append GOOD",
            body={"text": text},
            generator={"source": "toy_adapter.apply_patch"},
        )


@pytest.mark.asyncio
async def test_observer_emits_patch_applied_event(tmp_path: Path) -> None:
    """The runtime emits a canonical 'patch_applied' on_event during the patch loop."""

    archive = RunArchive(tmp_path)
    observer = _RecordingObserver()
    orchestrator = Orchestrator(
        adapter=_AppendPatchAdapter(),
        backend=_FailingReviewBackend(),
        archive=archive,
        policy=ScoringPolicy(policy_id="strict", minimums={"quality": 0.5}),
        observer=observer,
    )
    task = TaskSpec(
        task_id="t_observer_patch",
        goal="require GOOD",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=4, max_candidates=1),
    )
    result = await orchestrator.run(task)
    assert result.accepted is True

    events = [call for call in observer.calls if call[0] == "on_event"]
    patch_events = [call for call in events if call[1][0] == "patch_applied"]
    assert patch_events, observer.calls
    _, args, _ = patch_events[0]
    name, attrs = args
    assert name == "patch_applied"
    assert isinstance(attrs, dict)
    assert "patch_id" in attrs
    assert "iteration" in attrs


class _ExportFailAdapter(ToyTextAdapter):
    async def export(
        self,
        ir: ArtifactIR,
        artifact: ObservableArtifact,
        context: RunContext,
    ) -> ExportBundle:
        raise VigorError("export boom", kind="export_error")


@pytest.mark.asyncio
async def test_run_end_fires_even_on_failure(tmp_path: Path) -> None:
    """A failed run still emits on_run_end with the failure shape + export_failed event."""

    archive = RunArchive(tmp_path)
    observer = _RecordingObserver()
    orchestrator = Orchestrator(
        adapter=_ExportFailAdapter(),
        backend=EchoAgentBackend(seed_ir_factory=_seed_with_goal),
        archive=archive,
        observer=observer,
    )
    task = TaskSpec(
        task_id="t_observer_failed",
        goal="fail",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    result = await orchestrator.run(task)
    assert result.accepted is False

    run_end = next(call for call in observer.calls if call[0] == "on_run_end")
    _, args, _ = run_end
    _, accepted, stop_reason, _ = args
    assert accepted is False
    assert stop_reason == "failed"

    export_events = [
        call for call in observer.calls if call[0] == "on_event" and call[1][0] == "export_failed"
    ]
    assert export_events, observer.calls
