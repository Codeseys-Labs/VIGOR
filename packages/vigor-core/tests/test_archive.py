"""Run archive tests."""

from __future__ import annotations

from pathlib import Path

from vigor_core.archive import RunArchive
from vigor_core.schemas import (
    AdapterManifest,
    AdjudicationReport,
    ArtifactIR,
    CompileResult,
    ExportBundle,
    Frontier,
    FrontierCandidate,
    ObservableArtifact,
    PatchPlan,
    ProvenanceRecord,
    ReviewReport,
    TaskSpec,
)


def _demo_task() -> TaskSpec:
    return TaskSpec(task_id="run_001", goal="demo", modalities=["toy"])


def test_write_and_read_task(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    task = _demo_task()
    archive.write_task(task)
    loaded = archive.read_task("run_001")
    assert loaded.task_id == "run_001"


def test_full_run_write_cycle(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    task = _demo_task()
    archive.write_task(task)

    manifest = AdapterManifest(
        adapter_id="toy.v1",
        domain="toy",
        version="0.1.0",
        supported_ir=["toy.v1"],
    )
    archive.write_manifest(task.task_id, manifest)

    ir = ArtifactIR(
        candidate_id="cand_0001",
        ir_type="toy.v1",
        body={"text": "hello"},
    )
    archive.write_ir(task.task_id, ir)

    artifact = ObservableArtifact(
        artifact_id="art_0001",
        uri="artifacts/hello.txt",
        media_type="text/plain",
    )
    compile_result = CompileResult(
        compile_id="compile_0001",
        candidate_id="cand_0001",
        tool_id="toy.compile",
        status="success",
        outputs=[artifact],
    )
    archive.write_compile_result(task.task_id, compile_result)

    review = ReviewReport(
        review_id="rev_0001",
        candidate_id="cand_0001",
        reviewer_id="toy.reviewer",
        reviewer_type="objective_metric",
        summary="ok",
        passed=True,
    )
    archive.write_review(task.task_id, review)

    reviews = archive.list_reviews(task.task_id, "cand_0001")
    assert len(reviews) == 1
    assert reviews[0].passed is True

    adjudication = AdjudicationReport(
        adjudication_id="adj_0001",
        candidate_id="cand_0001",
        policy_id="toy.default",
        hard_gate_passed=True,
        decision="accept",
    )
    archive.write_adjudication(task.task_id, adjudication)

    patch = PatchPlan(
        patch_id="patch_0001",
        source_candidate_id="cand_0001",
        objectives=["noop"],
    )
    archive.write_patch(task.task_id, patch)

    frontier = Frontier(
        frontier_id="frontier_0001",
        run_id=task.task_id,
        selection_policy="toy.default",
        candidates=[
            FrontierCandidate(
                candidate_id="cand_0001",
                status="selected",
                hard_gate_passed=True,
                rank=1,
                scores={"composite": 1.0},
            )
        ],
    )
    archive.write_frontier(task.task_id, frontier)

    export = ExportBundle(
        export_id="export_0001",
        candidate_id="cand_0001",
    )
    provenance = ProvenanceRecord(
        provenance_id="prov_0001",
        run_id=task.task_id,
        task_id=task.task_id,
        selected_candidate_id="cand_0001",
        stop_reason="accepted",
    )
    archive.write_final(task.task_id, export, provenance)

    assert archive.list_candidates(task.task_id) == ["cand_0001"]
    assert (archive.run_dir(task.task_id) / "frontier.json").exists()
    assert (archive.run_dir(task.task_id) / "final" / "export_bundle.json").exists()
    assert (archive.run_dir(task.task_id) / "final" / "provenance.json").exists()
