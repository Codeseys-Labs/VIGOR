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
)
from vigor_core.schemas import ArtifactIR, Budgets, PatchPlan, ReviewReport, TaskSpec
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

    task = TaskSpec(task_id="t_accept", goal="hello", modalities=["toy_text"])
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

    # Candidate-level files land where expected.
    candidate_dirs = list((run_dir / "candidates").iterdir())
    assert len(candidate_dirs) >= 1
    for cand_dir in candidate_dirs:
        assert (cand_dir / "ir.json").exists()
        assert (cand_dir / "compile_result.json").exists()
        assert (cand_dir / "adjudication.json").exists()
        assert (cand_dir / "reviews").exists()
        assert any((cand_dir / "reviews").glob("*.json"))

    # Provenance activities cover the full loop.
    activity_types = {a.type for a in result.provenance.activities}
    assert {"generation", "compile", "review", "adjudication", "export"} <= activity_types


class _FailingReviewBackend(AgentBackend):
    """Backend whose review is a strict critic: any text not containing 'GOOD'
    fails. propose_patch requests the adapter append '!' until it passes.
    """

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
    """Toy adapter variant that implements 'append 'GOOD'' as an apply_patch
    operation so we can exercise the patch loop end to end.
    """

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
    """apply_patch must be invoked by the orchestrator and improve the IR."""

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
        budgets=Budgets(max_iterations=4),
    )
    result = await orchestrator.run(task)

    assert result.accepted is True, "patch loop should converge"
    assert backend.propose_calls >= 1, "backend.propose_patch must be invoked"

    run_dir = archive.run_dir("t_patch_loop")
    candidate_dirs = sorted((run_dir / "candidates").iterdir())
    # At least one candidate is a patched child (contains '_p' in candidate id).
    assert any("_p" in d.name for d in candidate_dirs), candidate_dirs
    # A patch_plan.json was persisted at least once.
    assert any((d / "patch_plan.json").exists() for d in candidate_dirs)

    # Provenance includes patch activity.
    activity_types = {a.type for a in result.provenance.activities}
    assert "patch" in activity_types


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
        budgets=Budgets(max_iterations=2),
    )
    result = await orchestrator.run(task)

    # The echo backend proposes a no-op patch and adapter cannot improve the
    # empty seed, so the run exhausts budget without acceptance.
    assert result.accepted is False
    assert result.stop_reason in {"budget_exhausted", "failed"}


class _RaisingCompileAdapter(ToyTextAdapter):
    async def compile(self, ir, context):  # type: ignore[override,no-untyped-def]
        raise VigorError("boom", kind="compile_error", retryable=False)


@pytest.mark.asyncio
async def test_orchestrator_converts_compile_exception_to_failure(
    tmp_path: Path,
) -> None:
    archive = RunArchive(tmp_path)
    adapter = _RaisingCompileAdapter()
    backend = EchoAgentBackend(seed_ir_factory=_seed_with_goal)
    orchestrator = Orchestrator(adapter=adapter, backend=backend, archive=archive)

    task = TaskSpec(
        task_id="t_compile_error",
        goal="hello",
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1),
    )
    result = await orchestrator.run(task)

    assert result.accepted is False
    assert result.stop_reason == "failed"

    # Compile result records the structured error.
    cand_dir = next((archive.run_dir("t_compile_error") / "candidates").iterdir())
    compile_result_json = json.loads((cand_dir / "compile_result.json").read_text())
    assert compile_result_json["status"] == "failure"
    assert compile_result_json["errors"], "compile errors must be persisted"
    assert compile_result_json["errors"][0]["type"] == "compile_error"
