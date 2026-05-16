"""Runtime orchestrator + toy adapter end-to-end tests."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from vigor_core.archive import RunArchive
from vigor_core.errors import (
    ArchiveBusyError,
    ArchiveLockedError,
    NoCheckpointError,
    VigorError,
)
from vigor_core.interfaces import (
    AgentBackend,
    GenerationRequest,
    GenerationResult,
    PatchProposal,
    PatchProposalRequest,
    ReviewRequest,
    ReviewResult,
    RunContext,
    ToolBackend,
)
from vigor_core.interfaces import ToolResult as _ToolResult
from vigor_core.schemas import (
    ArtifactIR,
    Budgets,
    CompileResult,
    ExportBundle,
    ObservableArtifact,
    PatchPlan,
    ReviewReport,
    TaskSpec,
    ToolManifest,
    Usage,
)
from vigor_core.scoring import ScoringPolicy
from vigor_runtime.backends import EchoAgentBackend
from vigor_runtime.orchestrator import Orchestrator
from vigor_runtime.toy_adapter import ToyTextAdapter


def _seed_with_goal(request: GenerationRequest) -> dict[str, Any]:
    return {"text": request.task.goal}


def _seed_empty(_request: GenerationRequest) -> dict[str, Any]:
    return {"text": ""}


@pytest.mark.asyncio
async def test_toy_adapter_accepts(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    adapter = ToyTextAdapter()
    backend = EchoAgentBackend(seed_ir_factory=_seed_with_goal)
    orchestrator = Orchestrator(adapter=adapter, backend=backend, archive=archive)

    task = TaskSpec(
        task_id="t_accept",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    result = await orchestrator.run(task)

    assert result.accepted is True
    assert result.stop_reason == "accepted"
    assert result.selected_candidate_id is not None

    run_dir = archive.run_dir("t_accept")
    assert (run_dir / "task.json").exists()
    assert (run_dir / "adapter_manifest.json").exists()
    assert (run_dir / "frontier.json").exists()
    assert (run_dir / "final" / "export_bundle.json").exists()
    assert (run_dir / "final" / "provenance.json").exists()

    candidate_dirs = list((run_dir / "candidates").iterdir())
    assert len(candidate_dirs) == 1
    for cand_dir in candidate_dirs:
        assert (cand_dir / "ir.json").exists()
        assert (cand_dir / "compile_result.json").exists()
        assert (cand_dir / "adjudication.json").exists()
        assert any((cand_dir / "reviews").glob("*.json"))

    activity_types = {a.type for a in result.provenance.activities}
    assert {"generation", "compile", "review", "adjudication", "export"} <= activity_types


class _FailingReviewBackend(AgentBackend):
    def __init__(self) -> None:
        self.propose_calls = 0

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
        self.propose_calls += 1
        plan = PatchPlan(
            patch_id=f"patch_strict_{request.ir.candidate_id}",
            source_candidate_id=request.ir.candidate_id,
            basis=[r.review_id for r in request.reviews],
            objectives=["append 'GOOD'"],
        )
        return PatchProposal(patch=plan, rationale="append GOOD to satisfy critic")


class _ToyAdapterWithAppendPatch(ToyTextAdapter):
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
async def test_patch_loop_actually_applies_patches(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    adapter = _ToyAdapterWithAppendPatch()
    backend = _FailingReviewBackend()
    orchestrator = Orchestrator(
        adapter=adapter,
        backend=backend,
        archive=archive,
        policy=ScoringPolicy(policy_id="strict", minimums={"quality": 0.5}),
    )

    task = TaskSpec(
        task_id="t_patch_loop",
        goal="require GOOD",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=4, max_candidates=1),
    )
    result = await orchestrator.run(task)

    assert result.accepted is True
    assert backend.propose_calls >= 1
    run_dir = archive.run_dir("t_patch_loop")
    candidate_dirs = sorted((run_dir / "candidates").iterdir())
    assert any("_p" in d.name for d in candidate_dirs), candidate_dirs
    assert any((d / "patch_plan.json").exists() for d in candidate_dirs)
    assert "patch" in {a.type for a in result.provenance.activities}


class _RankedBackend(AgentBackend):
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
                review_id=f"rev_rank_{request.ir.candidate_id}",
                candidate_id=request.ir.candidate_id,
                artifact_id=request.artifact.artifact_id,
                reviewer_id=request.reviewer_id,
                reviewer_type="model_critic",
                summary=f"rank score {rank}",
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
async def test_best_of_n_uses_max_candidates_and_selects_best(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=_RankedBackend(),
        archive=archive,
        policy=ScoringPolicy(policy_id="best", weights={"quality": 1.0}),
    )
    task = TaskSpec(
        task_id="t_best_of_n",
        goal="pick best",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=3),
    )
    result = await orchestrator.run(task)
    assert result.accepted is True
    assert result.selected_candidate_id == "cand_t_best_of_n_0002"
    candidate_dirs = sorted((archive.run_dir("t_best_of_n") / "candidates").iterdir())
    assert [d.name for d in candidate_dirs] == [
        "cand_t_best_of_n_0000",
        "cand_t_best_of_n_0001",
        "cand_t_best_of_n_0002",
    ]


class _InvalidFirstBackend(_RankedBackend):
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        result = await super().generate(request)
        if not request.prior_candidates:
            result.ir.body = {"wrong": "shape"}
        return result


@pytest.mark.asyncio
async def test_best_of_n_continues_after_invalid_candidate(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=_InvalidFirstBackend(),
        archive=archive,
        policy=ScoringPolicy(
            policy_id="best", weights={"quality": 1.0}, disagreement_threshold=1.0
        ),
    )
    task = TaskSpec(
        task_id="t_invalid_best_of_n",
        goal="pick valid",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=2),
    )
    result = await orchestrator.run(task)
    assert result.accepted is True
    assert result.selected_candidate_id == "cand_t_invalid_best_of_n_0001"


class _ExportFailAdapter(ToyTextAdapter):
    async def export(
        self,
        ir: ArtifactIR,
        artifact: ObservableArtifact,
        context: RunContext,
    ) -> ExportBundle:
        raise VigorError("export boom", kind="export_error")


@pytest.mark.asyncio
async def test_export_failure_is_not_accepted(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    orchestrator = Orchestrator(
        adapter=_ExportFailAdapter(),
        backend=EchoAgentBackend(seed_ir_factory=_seed_with_goal),
        archive=archive,
    )
    task = TaskSpec(
        task_id="t_export_fail",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    result = await orchestrator.run(task)
    assert result.accepted is False
    assert result.stop_reason == "failed"
    assert result.export_bundle is None
    assert not (archive.run_dir("t_export_fail") / "final" / "export_bundle.json").exists()


@pytest.mark.asyncio
async def test_toy_adapter_fails_when_text_empty(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    adapter = ToyTextAdapter()
    backend = EchoAgentBackend(seed_ir_factory=_seed_empty)
    policy = ScoringPolicy(policy_id="strict", minimums={"quality": 0.5})
    orchestrator = Orchestrator(adapter=adapter, backend=backend, archive=archive, policy=policy)

    task = TaskSpec(
        task_id="t_empty",
        goal="",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=2, max_candidates=1),
    )
    result = await orchestrator.run(task)
    assert result.accepted is False
    assert result.stop_reason in {"budget_exhausted", "failed"}


class _RaisingCompileAdapter(ToyTextAdapter):
    async def compile(self, ir: ArtifactIR, context: RunContext) -> CompileResult:
        raise VigorError("boom", kind="compile_error", retryable=False)


class _RecordingToolBackend(ToolBackend):
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], frozenset[str] | None]] = []

    async def call_tool(
        self,
        tool_id: str,
        payload: dict[str, Any],
        *,
        capabilities: frozenset[str] | None = None,
    ) -> _ToolResult:
        self.calls.append((tool_id, payload, capabilities))
        return _ToolResult(tool_id=tool_id, status="success", output={"echo": payload})

    async def list_tools(self) -> list[ToolManifest]:
        return []


class _ToolUsingAdapter(ToyTextAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.observed_tools: ToolBackend | None = None

    async def compile(self, ir: ArtifactIR, context: RunContext) -> CompileResult:
        self.observed_tools = context.tools
        return await super().compile(ir, context)


@pytest.mark.asyncio
async def test_orchestrator_passes_tools_into_run_context(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    tools = _RecordingToolBackend()
    adapter = _ToolUsingAdapter()
    backend = EchoAgentBackend(seed_ir_factory=_seed_with_goal)
    orchestrator = Orchestrator(adapter=adapter, backend=backend, archive=archive, tools=tools)

    task = TaskSpec(
        task_id="t_tools",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    await orchestrator.run(task)

    assert adapter.observed_tools is tools


class _CapabilityObservingAdapter(ToyTextAdapter):
    """Captures the ``tool_capabilities`` frozenset from the run context."""

    def __init__(self) -> None:
        super().__init__()
        self.observed_capabilities: frozenset[str] | None = None

    async def compile(self, ir: ArtifactIR, context: RunContext) -> CompileResult:
        self.observed_capabilities = context.tool_capabilities
        return await super().compile(ir, context)


@pytest.mark.asyncio
async def test_orchestrator_default_tool_capabilities_is_empty(tmp_path: Path) -> None:
    """Default-deny: capabilities default to an empty frozenset."""

    archive = RunArchive(tmp_path)
    adapter = _CapabilityObservingAdapter()
    backend = EchoAgentBackend(seed_ir_factory=_seed_with_goal)
    orchestrator = Orchestrator(adapter=adapter, backend=backend, archive=archive)

    task = TaskSpec(
        task_id="t_caps_default",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    await orchestrator.run(task)

    assert adapter.observed_capabilities == frozenset()


@pytest.mark.asyncio
async def test_orchestrator_threads_tool_capabilities_into_context(tmp_path: Path) -> None:
    """Capabilities passed to the constructor surface on ``RunContext``."""

    archive = RunArchive(tmp_path)
    adapter = _CapabilityObservingAdapter()
    backend = EchoAgentBackend(seed_ir_factory=_seed_with_goal)
    granted = frozenset({"mcp.alpha.write", "mcp.beta.export"})
    orchestrator = Orchestrator(
        adapter=adapter,
        backend=backend,
        archive=archive,
        tool_capabilities=granted,
    )

    task = TaskSpec(
        task_id="t_caps_grant",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    await orchestrator.run(task)

    assert adapter.observed_capabilities == granted


@pytest.mark.asyncio
async def test_orchestrator_tools_default_is_none(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    adapter = _ToolUsingAdapter()
    backend = EchoAgentBackend(seed_ir_factory=_seed_with_goal)
    orchestrator = Orchestrator(adapter=adapter, backend=backend, archive=archive)

    task = TaskSpec(
        task_id="t_tools_none",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    await orchestrator.run(task)

    assert adapter.observed_tools is None


@pytest.mark.asyncio
async def test_orchestrator_converts_compile_exception_to_failure(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    adapter = _RaisingCompileAdapter()
    backend = EchoAgentBackend(seed_ir_factory=_seed_with_goal)
    orchestrator = Orchestrator(adapter=adapter, backend=backend, archive=archive)

    task = TaskSpec(
        task_id="t_compile_error",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    result = await orchestrator.run(task)

    assert result.accepted is False
    assert result.stop_reason == "failed"
    cand_dir = next((archive.run_dir("t_compile_error") / "candidates").iterdir())
    compile_result_json = json.loads((cand_dir / "compile_result.json").read_text())
    assert compile_result_json["status"] == "failure"
    assert compile_result_json["errors"]
    assert compile_result_json["errors"][0]["type"] == "compile_error"


class _CountingToolBackend(ToolBackend):
    """A ToolBackend that records how many times aclose is invoked."""

    def __init__(self) -> None:
        self.aclose_calls = 0

    async def call_tool(
        self,
        tool_id: str,
        payload: dict[str, Any],
        *,
        capabilities: frozenset[str] | None = None,
    ) -> _ToolResult:
        return _ToolResult(tool_id=tool_id, status="success", output={})

    async def list_tools(self) -> list[ToolManifest]:
        return []

    async def aclose(self) -> None:
        self.aclose_calls += 1


@pytest.mark.asyncio
async def test_runtime_orchestrator_does_not_close_injected_tools(tmp_path: Path) -> None:
    """Tool backends are owned by the agent layer; runtime must NOT close them."""

    archive = RunArchive(tmp_path)
    tools = _CountingToolBackend()
    adapter = ToyTextAdapter()
    backend = EchoAgentBackend(seed_ir_factory=_seed_with_goal)
    orchestrator = Orchestrator(adapter=adapter, backend=backend, archive=archive, tools=tools)
    task = TaskSpec(
        task_id="t_tools_lifetime",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    await orchestrator.run(task)
    # First run does NOT close tools (ownership lives with AgentOrchestrator)
    assert tools.aclose_calls == 0
    # A second run reuses the same tools instance unchanged
    task2 = TaskSpec(
        task_id="t_tools_lifetime_2",
        goal="hello again",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    await orchestrator.run(task2)
    assert tools.aclose_calls == 0


class _CostlyBackend(EchoAgentBackend):
    """Echo backend that reports a scripted usage curve.

    Iteration N returns ``usd = (N+1) * per_iter_usd`` so callers can
    bound the iteration on which the ceiling is crossed.
    """

    def __init__(self, per_iter_usd: float) -> None:
        super().__init__(seed_ir_factory=_seed_with_goal)
        self._per_iter = per_iter_usd
        self._calls = 0

    async def usage(self) -> Usage:
        self._calls += 1
        return Usage(
            input_tokens=100 * self._calls,
            output_tokens=50 * self._calls,
            usd=self._per_iter * self._calls,
        )


@pytest.mark.asyncio
async def test_orchestrator_stops_on_cost_ceiling(tmp_path: Path) -> None:
    """A backend that crosses ``max_cost_usd`` triggers ``stop_reason=cost_exceeded``."""

    archive = RunArchive(tmp_path)

    class _NeverAcceptAdapter(ToyTextAdapter):
        async def review(
            self,
            artifact: ObservableArtifact,
            ir: ArtifactIR,
            context: RunContext,
        ) -> list[ReviewReport]:
            reports = await super().review(artifact, ir, context)
            for report in reports:
                report.scores["quality"] = 0.0
                report.passed = False
                report.recommended_action = "patch"
            return reports

    backend = _CostlyBackend(per_iter_usd=2.0)
    orchestrator = Orchestrator(
        adapter=_NeverAcceptAdapter(),
        backend=backend,
        archive=archive,
        policy=ScoringPolicy(policy_id="strict", minimums={"quality": 0.5}),
    )

    task = TaskSpec(
        task_id="t_cost_cap",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=10, max_candidates=1, max_cost_usd=5.0),
    )
    result = await orchestrator.run(task)

    assert result.stop_reason == "cost_exceeded"
    assert result.accepted is False
    assert result.usage.usd is not None
    assert result.usage.usd >= 5.0


@pytest.mark.asyncio
async def test_orchestrator_unset_max_cost_usd_does_not_short_circuit(tmp_path: Path) -> None:
    """When ``max_cost_usd`` is unset, even an expensive backend runs to completion."""

    archive = RunArchive(tmp_path)
    backend = _CostlyBackend(per_iter_usd=999.99)
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=backend,
        archive=archive,
    )
    task = TaskSpec(
        task_id="t_no_cost_cap",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    result = await orchestrator.run(task)

    assert result.stop_reason == "accepted"
    assert result.accepted is True
    # Usage is surfaced even without enforcement so operators can audit spend.
    assert result.usage.usd is not None
    assert result.usage.usd > 0


@pytest.mark.asyncio
async def test_orchestrator_default_backend_reports_zero_usage(tmp_path: Path) -> None:
    """Backends inheriting the ABC default ``usage()`` surface zero on RunResult."""

    archive = RunArchive(tmp_path)
    backend = EchoAgentBackend(seed_ir_factory=_seed_with_goal)
    orchestrator = Orchestrator(adapter=ToyTextAdapter(), backend=backend, archive=archive)
    task = TaskSpec(
        task_id="t_default_usage",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    result = await orchestrator.run(task)
    assert result.accepted is True
    assert result.usage.input_tokens == 0
    assert result.usage.output_tokens == 0
    assert result.usage.usd is None


class _CounterBackend(AgentBackend):
    """Backend whose ``generate`` is deterministic *per call* via a counter.

    Under parallel fanout every coroutine in a chunk sees the same
    ``prior_candidates`` snapshot, so any backend that derives content
    from ``len(prior_candidates)`` collapses to identical bodies. This
    backend instead tracks a monotonic counter that increments as each
    ``generate`` coroutine *completes*, giving each call a distinct body
    and a recorded completion order.

    Optional ``per_call_delay_factory(call_index) -> float`` lets tests
    inject submission-order-vs-completion-order skew (slot 0 sleeps
    longest → completes last under real fanout).
    """

    def __init__(
        self,
        *,
        per_call_delay_factory: Callable[[int], float] | None = None,
    ) -> None:
        self._counter = 0
        self._submit_counter = 0
        self._per_call_delay = per_call_delay_factory
        self.completion_order: list[str] = []
        self.in_flight = 0
        self.peak_in_flight = 0
        self.task_id_observed: str | None = None

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        # Submission order is captured *before* the first await; every
        # coroutine in a parallel chunk sees the same prior_candidates
        # snapshot, so we cannot use that for ordering — use our own
        # synchronous counter that increments at entry, before yielding.
        submit_index = self._submit_counter
        self._submit_counter += 1
        self.in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        try:
            if self._per_call_delay is not None:
                await asyncio.sleep(self._per_call_delay(submit_index))
            self._counter += 1
            seq = self._counter
            ir = ArtifactIR(
                # Backend assigns its own (intentionally unstable) id; the
                # orchestrator re-stamps via slot index post-gather.
                candidate_id=f"raw_{request.task.task_id}_{seq:04d}",
                ir_type=request.plan.ir_type,
                body={"text": f"candidate seq={seq}", "seq": seq},
            )
            self.task_id_observed = request.task.task_id
            self.completion_order.append(f"submit{submit_index:04d}_seq{seq:04d}")
            return GenerationResult(ir=ir)
        finally:
            self.in_flight -= 1

    async def review(self, request: ReviewRequest) -> ReviewResult:
        seq = float(request.ir.body.get("seq", 0))
        return ReviewResult(
            report=ReviewReport(
                review_id=f"rev_seq_{request.ir.candidate_id}",
                candidate_id=request.ir.candidate_id,
                artifact_id=request.artifact.artifact_id,
                reviewer_id=request.reviewer_id,
                reviewer_type="model_critic",
                summary=f"seq score {seq}",
                # Normalize so the highest-seq candidate wins on composite.
                scores={"quality": min(1.0, seq / 10.0)},
                passed=True,
                recommended_action="accept",
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
async def test_parallel_candidates_default_one_preserves_sequential_order(
    tmp_path: Path,
) -> None:
    """Default ``parallel_candidates=1`` is byte-identical to the serial loop.

    ADR-0034 commits to sequential equivalence under the default cap; this
    asserts the candidate-id sequence and the per-candidate archive layout
    match what the existing best-of-N test already exercises.
    """

    archive = RunArchive(tmp_path)
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=_RankedBackend(),
        archive=archive,
        policy=ScoringPolicy(policy_id="best", weights={"quality": 1.0}),
    )
    task = TaskSpec(
        task_id="t_par_default",
        goal="pick best",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=3),  # parallel_candidates omitted
    )
    result = await orchestrator.run(task)

    assert task.budgets.parallel_candidates == 1
    assert result.accepted is True
    assert result.selected_candidate_id == "cand_t_par_default_0002"
    candidate_dirs = sorted((archive.run_dir("t_par_default") / "candidates").iterdir())
    assert [d.name for d in candidate_dirs] == [
        "cand_t_par_default_0000",
        "cand_t_par_default_0001",
        "cand_t_par_default_0002",
    ]


@pytest.mark.asyncio
async def test_parallel_candidates_four_writes_all_artifacts(tmp_path: Path) -> None:
    """``parallel_candidates=4`` materializes all four candidate JSONs."""

    archive = RunArchive(tmp_path)
    backend = _CounterBackend()
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=backend,
        archive=archive,
        policy=ScoringPolicy(
            policy_id="best", weights={"quality": 1.0}, disagreement_threshold=1.0
        ),
    )
    task = TaskSpec(
        task_id="t_par_four",
        goal="pick best",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=4, parallel_candidates=4),
    )
    result = await orchestrator.run(task)

    assert result.accepted is True
    candidate_dirs = sorted((archive.run_dir("t_par_four") / "candidates").iterdir())
    # Orchestrator re-stamps IDs by slot index, so directory names are
    # deterministic even though the backend's internal IDs (``raw_…``)
    # are not. ADR-0034 §Negative §2 — stable ids, nondeterministic write
    # order. Sorting by name is the documented test pattern.
    assert [d.name for d in candidate_dirs] == [
        "cand_t_par_four_0000",
        "cand_t_par_four_0001",
        "cand_t_par_four_0002",
        "cand_t_par_four_0003",
    ]
    for cand_dir in candidate_dirs:
        assert (cand_dir / "ir.json").exists()
        assert (cand_dir / "compile_result.json").exists()
        assert (cand_dir / "adjudication.json").exists()
        assert any((cand_dir / "reviews").glob("*.json"))


@pytest.mark.asyncio
async def test_parallel_candidates_actually_fans_out(tmp_path: Path) -> None:
    """Submission and completion order diverge under real ``asyncio.gather``."""

    archive = RunArchive(tmp_path)
    # Earlier-submitted slots take longer to complete than later-submitted
    # slots. Under a serial loop, completion order matches submission order
    # (slot 0 first, slot 3 last). Under real fanout the order *inverts* —
    # slot 0 sleeps longest and completes last while slot 3 finishes first.
    # peak_in_flight directly observes that multiple coroutines are awaiting
    # concurrently inside the same gather batch.
    backend = _CounterBackend(per_call_delay_factory=lambda i: 0.02 * max(0, 4 - i))
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=backend,
        archive=archive,
        policy=ScoringPolicy(
            policy_id="best", weights={"quality": 1.0}, disagreement_threshold=1.0
        ),
    )
    task = TaskSpec(
        task_id="t_par_fanout",
        goal="pick best",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=4, parallel_candidates=4),
    )
    await orchestrator.run(task)

    assert backend.peak_in_flight == 4, "all four generate calls must overlap"
    # First completion is submit-3 (shortest delay); last is submit-0 (longest).
    # That inversion is the unforgeable signal that gather is real fanout.
    assert backend.completion_order[0].startswith("submit0003_")
    assert backend.completion_order[-1].startswith("submit0000_")


@pytest.mark.asyncio
async def test_parallel_candidates_chunked_below_max(tmp_path: Path) -> None:
    """``parallel_candidates < max_candidates`` chunks the fanout."""

    archive = RunArchive(tmp_path)
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=_RankedBackend(),
        archive=archive,
        policy=ScoringPolicy(policy_id="best", weights={"quality": 1.0}),
    )
    task = TaskSpec(
        task_id="t_par_chunk",
        goal="pick best",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=5, parallel_candidates=2),
    )
    result = await orchestrator.run(task)

    assert result.accepted is True
    candidate_dirs = sorted((archive.run_dir("t_par_chunk") / "candidates").iterdir())
    # Five candidates, three chunks of (2, 2, 1). All five must materialize.
    assert [d.name for d in candidate_dirs] == [f"cand_t_par_chunk_{i:04d}" for i in range(5)]


class _ExplodingEvaluateAdapter(ToyTextAdapter):
    """Adapter that raises a bare ``RuntimeError`` from ``validate_ir``.

    ``_evaluate_candidate`` does NOT catch arbitrary exceptions from
    ``validate_ir`` — only from ``compile`` and ``review``. So a
    ``RuntimeError`` from ``validate_ir`` is exactly the escape path
    ``return_exceptions=True`` is meant to cover.
    """

    async def validate_ir(self, ir):  # type: ignore[no-untyped-def]
        raise RuntimeError(f"validate exploded for {ir.candidate_id}")


@pytest.mark.asyncio
async def test_escaped_exception_becomes_failure_outcome(tmp_path: Path) -> None:
    """An exception escaping ``_evaluate_candidate`` is wrapped, not raised.

    ADR-0034 §Decision Outcome paragraph on failure handling: gather
    catches stray exceptions; the orchestrator coerces them into a
    failure-shaped CandidateOutcome and the iteration continues.
    """

    archive = RunArchive(tmp_path)
    orchestrator = Orchestrator(
        adapter=_ExplodingEvaluateAdapter(),
        backend=_RankedBackend(),
        archive=archive,
    )
    task = TaskSpec(
        task_id="t_escape",
        goal="pick best",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=2, parallel_candidates=2),
    )
    result = await orchestrator.run(task)

    # Both candidates fail (no acceptance), but the run completes without
    # raising — the iteration drains via the failure adjudication path.
    assert result.accepted is False
    errors_dir = archive.run_dir("t_escape") / "errors"
    error_files = list(errors_dir.glob("err_evaluate_*.json"))
    assert len(error_files) == 2  # one per slot
    payload = json.loads(error_files[0].read_text())
    assert "RuntimeError" in payload["message"]


class _ExplodingFirstCallBackend(_CounterBackend):
    """Counter-based backend whose first ``generate`` call raises.

    Unlike a backend that branches on ``len(prior_candidates)``, this one
    branches on its own call counter. Under parallel fanout every
    coroutine in a chunk starts with the same ``prior_candidates``
    snapshot, so prior-based branching would either explode every slot
    or no slot at all. The call-order counter is the right discriminator
    for this test (the orchestrator's per-slot ID re-stamp lives at the
    *post-gather* boundary, so slot identity is preserved).
    """

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self._counter += 1
        seq = self._counter
        if seq == 1:
            raise RuntimeError(f"generate exploded for call {seq}")
        ir = ArtifactIR(
            candidate_id=f"raw_{request.task.task_id}_{seq:04d}",
            ir_type=request.plan.ir_type,
            body={"text": f"candidate seq={seq}", "seq": seq},
        )
        return GenerationResult(ir=ir)


@pytest.mark.asyncio
async def test_parallel_generation_exception_drops_one_slot(tmp_path: Path) -> None:
    """An exception in one parallel ``generate`` call drops only that slot.

    The exploding call increments the backend counter to 1; the other
    two calls in the same chunk return successfully. The orchestrator
    coerces the gathered ``BaseException`` into an archive error record
    and keeps only the survivors. The returned slot indices are
    contiguous from the *front* (the first slot is dropped).
    """

    archive = RunArchive(tmp_path)
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=_ExplodingFirstCallBackend(),
        archive=archive,
        policy=ScoringPolicy(
            policy_id="best", weights={"quality": 1.0}, disagreement_threshold=1.0
        ),
    )
    task = TaskSpec(
        task_id="t_gen_explode",
        goal="pick best",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=3, parallel_candidates=3),
    )
    result = await orchestrator.run(task)

    # Whichever slot landed the exploding call lost its candidate dir.
    # The other two survivors got slot indices from the global numbering;
    # because gather preserves submission order in the result list, the
    # explosion lands on whichever slot was scheduled first by the loop —
    # we don't pin that ordering, but we *do* require that exactly two
    # candidate directories materialize.
    candidate_dirs = sorted((archive.run_dir("t_gen_explode") / "candidates").iterdir())
    assert len(candidate_dirs) == 2
    error_files = list((archive.run_dir("t_gen_explode") / "errors").glob("err_generate_*.json"))
    assert len(error_files) == 1
    payload = json.loads(error_files[0].read_text())
    assert "RuntimeError" in payload["message"]
    # The surviving candidates' adjudications still resolve; the run
    # accepts because nothing is failing.
    assert result.accepted is True


@pytest.mark.asyncio
async def test_parallel_candidates_must_be_at_least_one() -> None:
    """``Budgets.parallel_candidates`` rejects values below 1 at validation."""

    with pytest.raises(ValidationError):
        Budgets(parallel_candidates=0)


@pytest.mark.asyncio
async def test_tool_backend_aclose_default_is_noop() -> None:
    """The default ``aclose`` on ToolBackend is callable and returns None."""

    class _MinimalTools(ToolBackend):
        async def call_tool(
            self,
            tool_id: str,
            payload: dict[str, Any],
            *,
            capabilities: frozenset[str] | None = None,
        ) -> _ToolResult:
            return _ToolResult(tool_id=tool_id, status="success", output={})

        async def list_tools(self) -> list[ToolManifest]:
            return []

    tools = _MinimalTools()
    # Default aclose is a no-op coroutine inherited from the ABC.
    result = await tools.aclose()
    assert result is None


# ---------------------------------------------------------------------------
# ADR-0036: iteration-boundary checkpoint + Orchestrator.resume(run_id)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_iteration_checkpoint_written_on_accept(tmp_path: Path) -> None:
    """A successful run writes a parseable iteration checkpoint."""

    archive = RunArchive(tmp_path)
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=EchoAgentBackend(seed_ir_factory=_seed_with_goal),
        archive=archive,
    )
    task = TaskSpec(
        task_id="t_ckpt_accept",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    result = await orchestrator.run(task)
    assert result.accepted is True

    ckpt = archive.read_checkpoint("t_ckpt_accept")
    assert ckpt.next_iteration == 1
    assert ckpt.prior_candidate_ids == ["cand_t_ckpt_accept_0000"]
    assert ckpt.current_candidate_id is None
    assert ckpt.last_candidate_id == "cand_t_ckpt_accept_0000"
    assert {a.type for a in ckpt.activities} >= {"generation", "compile", "review"}


@pytest.mark.asyncio
async def test_iteration_checkpoint_written_on_patch_iteration_end(tmp_path: Path) -> None:
    """An iteration that ends without acceptance still writes a checkpoint."""

    archive = RunArchive(tmp_path)
    orchestrator = Orchestrator(
        adapter=_ToyAdapterWithAppendPatch(),
        backend=_FailingReviewBackend(),
        archive=archive,
        policy=ScoringPolicy(policy_id="strict", minimums={"quality": 0.5}),
    )
    task = TaskSpec(
        task_id="t_ckpt_patch",
        goal="require GOOD",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=2, max_candidates=1),
    )
    await orchestrator.run(task)

    ckpt = archive.read_checkpoint("t_ckpt_patch")
    assert ckpt.next_iteration >= 1
    assert ckpt.prior_candidate_ids


@pytest.mark.asyncio
async def test_resume_continues_from_next_iteration(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    # ``_ToyAdapterWithAppendPatch`` materializes the "append 'GOOD'" patch
    # objective; ``_FailingReviewBackend`` accepts text containing "GOOD".
    # First run gets one iteration → patch loop generates a patched IR but
    # cannot evaluate it (budget cap hit). Resume re-enters at iteration 1
    # and accepts on the patched IR.
    orchestrator1 = Orchestrator(
        adapter=_ToyAdapterWithAppendPatch(),
        backend=_FailingReviewBackend(),
        archive=archive,
        policy=ScoringPolicy(policy_id="strict", minimums={"quality": 0.5}),
    )
    task = TaskSpec(
        task_id="t_resume",
        goal="require GOOD",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    first = await orchestrator1.run(task)
    assert first.accepted is False

    ckpt = archive.read_checkpoint("t_resume")
    assert ckpt.next_iteration == 1
    assert ckpt.current_candidate_id is not None  # patched IR awaiting evaluation

    bumped = task.model_copy(update={"budgets": Budgets(max_iterations=4, max_candidates=1)})
    archive.write_task(bumped)

    orchestrator2 = Orchestrator(
        adapter=_ToyAdapterWithAppendPatch(),
        backend=_FailingReviewBackend(),
        archive=archive,
        policy=ScoringPolicy(policy_id="strict", minimums={"quality": 0.5}),
    )
    second = await orchestrator2.resume("t_resume")
    assert second.accepted is True
    assert second.run_id == "t_resume"
    # Resume picks up where iteration 0 left off — the patched IR is the
    # selected candidate, not a fresh generation from iteration 0.
    assert second.selected_candidate_id is not None
    assert second.selected_candidate_id.startswith("cand_t_resume_0000_p")


@pytest.mark.asyncio
async def test_resume_raises_when_no_checkpoint(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    archive.write_task(TaskSpec(task_id="t_no_ckpt", goal="x", modalities=["toy_text"]))
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=EchoAgentBackend(seed_ir_factory=_seed_with_goal),
        archive=archive,
    )
    with pytest.raises(NoCheckpointError):
        await orchestrator.resume("t_no_ckpt")


# ---------------------------------------------------------------------------
# ADR-0035 §Negative #1 in-process guardrail (VIGOR-c2ec)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_runs_same_archive_raises_busy(tmp_path: Path) -> None:
    """Two concurrent ``Orchestrator.run`` calls on one archive raise busy.

    The canonical caller mistake: gather two ``run()`` coroutines on the
    same archive. The synchronous ``claim_active_run`` check on the second
    runner fires as soon as the first runner yields at its first ``await``.
    At least one ``ArchiveBusyError`` is observed; the other call may
    succeed or fail, but the archive must not be corrupted (task.json must
    parse and match one of the two task_ids).
    """

    archive = RunArchive(tmp_path)
    orch_a = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=EchoAgentBackend(seed_ir_factory=_seed_with_goal),
        archive=archive,
    )
    orch_b = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=EchoAgentBackend(seed_ir_factory=_seed_with_goal),
        archive=archive,
    )
    task_a = TaskSpec(
        task_id="t_busy_a",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    task_b = TaskSpec(
        task_id="t_busy_b",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )

    results = await asyncio.gather(
        orch_a.run(task_a),
        orch_b.run(task_b),
        return_exceptions=True,
    )

    busy_errors = [r for r in results if isinstance(r, ArchiveBusyError)]
    assert len(busy_errors) >= 1, results
    # No archive corruption: each task.json that *was* written parses
    # cleanly through TaskSpec and matches the originating task_id
    # (write_task is the orchestrator's first archive I/O after the claim,
    # so the loser of the race never reaches it).
    for task_id in ("t_busy_a", "t_busy_b"):
        task_path = archive.run_dir(task_id) / "task.json"
        if task_path.exists():
            roundtrip = TaskSpec.model_validate_json(task_path.read_text())
            assert roundtrip.task_id == task_id


@pytest.mark.asyncio
async def test_sequential_runs_same_archive_succeed(tmp_path: Path) -> None:
    """Two sequential runs on the same archive both succeed.

    The marker must release between calls — otherwise the second run would
    raise ``ArchiveBusyError``. This is the regression test for a leaked
    marker that would brick the archive for the rest of the process.
    """

    archive = RunArchive(tmp_path)
    orchestrator = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=EchoAgentBackend(seed_ir_factory=_seed_with_goal),
        archive=archive,
    )
    task1 = TaskSpec(
        task_id="t_seq_one",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    task2 = TaskSpec(
        task_id="t_seq_two",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    first = await orchestrator.run(task1)
    # Construct a fresh backend for the second run because EchoAgentBackend
    # closes itself in the orchestrator's finally (aclose). Adapter and
    # archive are reusable.
    orchestrator2 = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=EchoAgentBackend(seed_ir_factory=_seed_with_goal),
        archive=archive,
    )
    second = await orchestrator2.run(task2)
    assert first.accepted is True
    assert second.accepted is True


@pytest.mark.asyncio
async def test_export_during_run_still_works(tmp_path: Path) -> None:
    """A transient ``RunArchive`` constructed mid-run does not raise busy.

    Adapter ``export()`` paths legitimately build
    ``RunArchive(run_dir.parent)`` to write export-bundle artifacts
    (mx-7ce41e + mx-514b28). The new guard is at ``Orchestrator.run``,
    not at ``RunArchive.__init__``, so transient-archive construction
    on the same root must continue to work even while a run is in flight.
    We simulate the export-time construction by building a second
    ``RunArchive(tmp_path)`` directly mid-claim.
    """

    archive = RunArchive(tmp_path)
    with archive.claim_active_run():
        # The OS lock refcount allows same-process re-construction; the
        # active-runs registry must NOT block this transient archive.
        transient = RunArchive(tmp_path)
        try:
            assert transient.root.resolve() == archive.root.resolve()
        finally:
            transient.close()


class _PlanFailingAdapter(ToyTextAdapter):
    async def plan_representation(self, task: TaskSpec):  # type: ignore[no-untyped-def]
        raise VigorError("plan boom", kind="adapter_contract")


@pytest.mark.asyncio
async def test_run_releases_marker_on_failure(tmp_path: Path) -> None:
    """A failed run must release the active-runs marker.

    If the marker leaks on the exception path, the second
    ``orchestrator.run`` raises ``ArchiveBusyError`` even though the first
    is no longer in flight. Inducing the failure inside ``_execute``
    (``plan_representation`` raising ``VigorError``) is the most realistic
    leakage probe — the orchestrator's existing ``except VigorError`` path
    converts it into a ``stop_reason='failed'`` result rather than a raise,
    so we don't need ``pytest.raises`` here, just to assert that a
    follow-up run is not blocked.
    """

    archive = RunArchive(tmp_path)
    failing = Orchestrator(
        adapter=_PlanFailingAdapter(),
        backend=EchoAgentBackend(seed_ir_factory=_seed_with_goal),
        archive=archive,
    )
    bad_task = TaskSpec(
        task_id="t_fail_release",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    failed = await failing.run(bad_task)
    assert failed.accepted is False
    assert failed.stop_reason == "failed"

    # Marker must have been released — a second run on the same archive
    # succeeds without raising ArchiveBusyError.
    healthy = Orchestrator(
        adapter=ToyTextAdapter(),
        backend=EchoAgentBackend(seed_ir_factory=_seed_with_goal),
        archive=archive,
    )
    good_task = TaskSpec(
        task_id="t_fail_release_then_ok",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    result = await healthy.run(good_task)
    assert result.accepted is True


def test_busy_error_distinct_from_archive_locked_error() -> None:
    """ArchiveBusyError is a sibling of ArchiveLockedError, not a subclass.

    Catch-by-type semantics matter: callers wrapping cross-process retry
    around ``ArchiveLockedError`` must NOT swallow the in-process busy
    error (which signals a code bug, not a transient peer-process state).
    """

    assert not issubclass(ArchiveBusyError, ArchiveLockedError)
    assert not issubclass(ArchiveLockedError, ArchiveBusyError)
    assert ArchiveBusyError.kind == "archive_busy"
    assert ArchiveBusyError.retryable is False
