"""Runtime orchestrator + toy adapter end-to-end tests."""

from __future__ import annotations

import json
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
from vigor_core.schemas import (
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
