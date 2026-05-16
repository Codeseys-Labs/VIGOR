"""Schema round-trip and invariant tests."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from vigor_core.schemas import (
    AdjudicationReport,
    ArtifactIR,
    CompileResult,
    ExportBundle,
    Finding,
    Frontier,
    FrontierCandidate,
    IterationCheckpoint,
    ObservableArtifact,
    PatchPlan,
    ProvenanceActivity,
    ProvenanceRecord,
    ReviewReport,
    TaskSpec,
    Usage,
)
from vigor_core.schemas import (
    RuntimeErrorRecord as VigorRuntimeError,
)


def _roundtrip(model) -> None:
    data = model.model_dump(by_alias=True, mode="json")
    rebuilt = type(model).model_validate(data)
    assert rebuilt.model_dump(by_alias=True, mode="json") == data


def test_task_roundtrip() -> None:
    task = TaskSpec(
        task_id="task_001",
        goal="Edit photo cinematically",
        modalities=["image", "photo_edit_recipe"],
    )
    _roundtrip(task)
    assert task.schema_version == "vigor.task.v1"


def test_strict_mode_rejects_extra() -> None:
    with pytest.raises(ValidationError):
        TaskSpec.model_validate(
            {
                "taskId": "t",
                "goal": "g",
                "modalities": ["x"],
                "unknown": True,
            }
        )


def test_camelcase_aliases_on_wire() -> None:
    task = TaskSpec(task_id="t1", goal="g", modalities=["m"])
    payload = task.model_dump(by_alias=True, mode="json")
    assert "taskId" in payload
    assert "task_id" not in payload


def test_snake_case_accepted_on_input() -> None:
    task = TaskSpec.model_validate({"task_id": "t2", "goal": "g", "modalities": ["m"]})
    assert task.task_id == "t2"


def test_artifact_ir_with_parent() -> None:
    ir = ArtifactIR(
        candidate_id="cand_1",
        ir_type="photo_edit_recipe.v1",
        parent_candidate_id="cand_0",
        body={"intent": "test"},
    )
    _roundtrip(ir)


def test_compile_result_carries_errors() -> None:
    compile_result = CompileResult(
        compile_id="compile_1",
        candidate_id="cand_1",
        tool_id="photo.renderer",
        status="failure",
        errors=[
            VigorRuntimeError(
                error_id="err_1",
                type="compile_error",
                severity="high",
                message="boom",
            )
        ],
    )
    _roundtrip(compile_result)
    assert compile_result.status == "failure"


def test_review_report_recommendation_enum() -> None:
    review = ReviewReport(
        review_id="rev_1",
        candidate_id="cand_1",
        reviewer_id="photo.histogram",
        reviewer_type="objective_metric",
        summary="highlights within tolerance",
        passed=True,
        findings=[
            Finding(
                id="find_1",
                severity="low",
                category="tonality",
                evidence="1% clipping",
            )
        ],
    )
    _roundtrip(review)


def test_patch_plan_requires_objectives() -> None:
    patch = PatchPlan(
        patch_id="patch_1",
        source_candidate_id="cand_1",
        objectives=["reduce green saturation"],
    )
    _roundtrip(patch)


def test_export_bundle_and_frontier() -> None:
    export = ExportBundle(
        export_id="export_1",
        candidate_id="cand_1",
    )
    _roundtrip(export)

    frontier = Frontier(
        frontier_id="frontier_1",
        run_id="run_1",
        selection_policy="photo.default.v1",
        candidates=[
            FrontierCandidate(
                candidate_id="cand_1",
                status="selected",
                scores={"composite": 0.8},
                hard_gate_passed=True,
                rank=1,
            )
        ],
    )
    _roundtrip(frontier)


def test_provenance_record_lists_activities() -> None:
    record = ProvenanceRecord(
        provenance_id="prov_1",
        run_id="run_1",
        task_id="task_1",
        activities=[
            ProvenanceActivity(activity_id="gen", type="generation", agent="echo"),
            ProvenanceActivity(activity_id="cmp", type="compile", tool_id="t"),
        ],
        stop_reason="accepted",
    )
    _roundtrip(record)
    assert len(record.activities) == 2


def test_adjudication_decision_literal() -> None:
    adj = AdjudicationReport(
        adjudication_id="adj_1",
        candidate_id="cand_1",
        policy_id="p",
        hard_gate_passed=True,
        decision="accept",
    )
    _roundtrip(adj)


def test_observable_artifact_media_type_required() -> None:
    with pytest.raises(ValidationError):
        ObservableArtifact.model_validate({"artifact_id": "a", "uri": "x"})


def test_roundtrip_stable_json() -> None:
    task = TaskSpec(task_id="t", goal="g", modalities=["x"])
    one = task.model_dump_json(by_alias=True)
    two = TaskSpec.model_validate_json(one).model_dump_json(by_alias=True)
    assert json.loads(one) == json.loads(two)


def test_usage_defaults_zero_and_unpriced() -> None:
    usage = Usage()
    _roundtrip(usage)
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.usd is None
    assert usage.schema_version == "vigor.usage.v1"


def test_usage_carries_priced_telemetry() -> None:
    usage = Usage(input_tokens=1234, output_tokens=567, usd=0.0421)
    _roundtrip(usage)
    payload = usage.model_dump(by_alias=True, mode="json")
    assert payload["inputTokens"] == 1234
    assert payload["outputTokens"] == 567
    assert payload["usd"] == 0.0421


def test_provenance_record_accepts_cost_exceeded_stop_reason() -> None:
    record = ProvenanceRecord(
        provenance_id="prov_cost",
        run_id="run_cost",
        task_id="task_cost",
        stop_reason="cost_exceeded",
    )
    _roundtrip(record)
    assert record.stop_reason == "cost_exceeded"


def test_iteration_checkpoint_roundtrip() -> None:
    ckpt = IterationCheckpoint(
        checkpoint_id="ckpt_run_iter_0001",
        run_id="run_iter",
        next_iteration=2,
        prior_candidate_ids=["cand_run_iter_0000", "cand_run_iter_0001"],
        current_candidate_id="cand_run_iter_0001",
        adjudication_ids=["cand_run_iter_0000", "cand_run_iter_0001"],
        last_candidate_id="cand_run_iter_0001",
        activities=[
            ProvenanceActivity(activity_id="generate_x", type="generation"),
            ProvenanceActivity(activity_id="adjudication_y", type="adjudication"),
        ],
    )
    _roundtrip(ckpt)
    assert ckpt.schema_version == "vigor.iteration_checkpoint.v1"


def test_iteration_checkpoint_rejects_negative_iteration() -> None:
    with pytest.raises(ValidationError):
        IterationCheckpoint(
            checkpoint_id="ckpt_x_0000",
            run_id="x",
            next_iteration=-1,
        )
