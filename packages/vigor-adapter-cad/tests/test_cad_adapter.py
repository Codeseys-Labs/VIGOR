"""Tests for the OpenSCAD CAD adapter."""

from __future__ import annotations

from pathlib import Path

import pytest
from vigor_adapter_cad import CadOpenScadAdapter, CadParametricIRV1, render_openscad, validate_cad
from vigor_core.archive import RunArchive
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


def _seed_cad(_request):
    model = CadParametricIRV1(intent="wall bracket")
    return model.model_dump(by_alias=True, mode="json")


def test_render_openscad_contains_expected_primitives() -> None:
    model = CadParametricIRV1(intent="wall bracket")
    source = render_openscad(model)
    assert "difference()" in source
    assert "cube([100" in source
    assert "cylinder" in source


def test_render_openscad_respects_zero_holes() -> None:
    model = CadParametricIRV1.model_validate(
        {
            "intent": "no holes",
            "features": [
                {"type": "base_plate"},
                {"type": "mounting_holes", "count": 0},
            ],
        }
    )
    assert "cylinder" not in render_openscad(model)


def test_validate_rejects_thin_plate() -> None:
    model = CadParametricIRV1.model_validate(
        {
            "intent": "too thin",
            "parameters": {"thicknessMm": 1.0, "ribThicknessMm": 1.0},
        }
    )
    validation = validate_cad(model)
    assert validation.ok is False
    assert validation.errors


@pytest.mark.asyncio
async def test_cad_adapter_end_to_end(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    adapter = CadOpenScadAdapter()
    backend = EchoAgentBackend(seed_ir_factory=_seed_cad)
    orchestrator = Orchestrator(adapter=adapter, backend=backend, archive=archive)
    task = TaskSpec(
        task_id="cad_demo",
        goal="generate a wall bracket",
        modalities=["cad", "cad_parametric"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    result = await orchestrator.run(task)
    assert result.accepted is True
    run_dir = archive.run_dir("cad_demo")
    assert (run_dir / "final" / "export_bundle.json").exists()
    assert (run_dir / "final" / "exports" / "cad_validation.json").exists()
    assert any(
        (candidate / "artifacts" / "model.scad").exists()
        for candidate in (run_dir / "candidates").iterdir()
    )


@pytest.mark.asyncio
async def test_adapter_validate_ir_reports_schema_errors() -> None:
    adapter = CadOpenScadAdapter()
    ir = ArtifactIR(
        candidate_id="bad",
        ir_type="cad_parametric.v1",
        body={"intent": "bad", "parameters": {"thicknessMm": "thin"}},
    )
    report = await adapter.validate_ir(ir)
    assert report.ok is False
    assert report.errors


class _ThinCadBackend(AgentBackend):
    async def generate(self, request: GenerationRequest) -> GenerationResult:
        model = CadParametricIRV1.model_validate(
            {"intent": "too thin", "parameters": {"thicknessMm": 1.0, "ribThicknessMm": 1.0}}
        )
        return GenerationResult(
            ir=ArtifactIR(
                candidate_id=f"cand_{request.task.task_id}_{len(request.prior_candidates):04d}",
                ir_type=request.plan.ir_type,
                body=model.model_dump(by_alias=True, mode="json"),
            )
        )

    async def review(self, request: ReviewRequest) -> ReviewResult:
        return ReviewResult(
            report=ReviewReport(
                review_id=f"rev_backend_{request.ir.candidate_id}",
                candidate_id=request.ir.candidate_id,
                artifact_id=request.artifact.artifact_id,
                reviewer_id=request.reviewer_id,
                reviewer_type="model_critic",
                summary="backend neutral",
                scores={"quality": 1.0},
                passed=True,
            )
        )

    async def propose_patch(self, request: PatchProposalRequest) -> PatchProposal:
        return PatchProposal(
            patch=PatchPlan(
                patch_id=f"patch_{request.ir.candidate_id}",
                source_candidate_id=request.ir.candidate_id,
                objectives=["increase wall thickness"],
            )
        )


@pytest.mark.asyncio
async def test_invalid_cad_candidate_is_reviewed_patched_and_accepted(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    adapter = CadOpenScadAdapter()
    backend = _ThinCadBackend()
    orchestrator = Orchestrator(
        adapter=adapter,
        backend=backend,
        archive=archive,
        policy=ScoringPolicy(policy_id="cad", minimums={"quality": 0.5}),
    )
    task = TaskSpec(
        task_id="cad_patch",
        goal="fix thin bracket",
        modalities=["cad", "cad_parametric"],
        budgets=Budgets(max_iterations=4, max_candidates=1),
    )
    result = await orchestrator.run(task)
    assert result.accepted is True
    assert "patch" in {activity.type for activity in result.provenance.activities}
