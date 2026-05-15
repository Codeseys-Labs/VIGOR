"""Tests for the minimal harness evaluator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from vigor_core.schemas import Budgets, TaskSpec
from vigor_harness import HarnessCandidate, SplitManifest, evaluate_candidate


def _write_task(path: Path, task_id: str, goal: str) -> str:
    task = TaskSpec(
        task_id=task_id,
        goal=goal,
        modalities=["toy_text"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    path.write_text(task.model_dump_json(by_alias=True), encoding="utf-8")
    return str(path)


@pytest.mark.asyncio
async def test_evaluate_candidate_over_split(tmp_path: Path) -> None:
    split = SplitManifest(
        split_id="toy.search.v1",
        role="search",
        task_uris=[
            _write_task(tmp_path / "task1.json", "harness_task_1", "hello harness"),
            _write_task(tmp_path / "task2.json", "harness_task_2", "hello again"),
        ],
    )
    candidate = HarnessCandidate(
        candidate_id="toy_candidate_v1",
        hypothesis="toy backend should pass toy adapter",
        adapter_factory="vigor_harness.testing:toy_adapter_factory",
        backend_factory="vigor_harness.testing:toy_backend_factory",
        allowed_factory_prefixes=["vigor_harness"],
    )
    result = await evaluate_candidate(candidate, split, tmp_path / "meta_runs")
    assert result.report.n_tasks == 2
    assert result.report.n_succeeded == 2
    aggregate = result.output_dir / "aggregate.json"
    assert aggregate.exists()
    payload = json.loads(aggregate.read_text(encoding="utf-8"))
    assert payload["candidateId"] == "toy_candidate_v1"


@pytest.mark.asyncio
async def test_evaluate_candidate_rejects_untrusted_factory_prefix(tmp_path: Path) -> None:
    split = SplitManifest(
        split_id="toy.search.v1",
        role="search",
        task_uris=[_write_task(tmp_path / "task.json", "harness_task_1", "hello")],
    )
    candidate = HarnessCandidate(
        candidate_id="bad_candidate",
        hypothesis="should be rejected",
        adapter_factory="os:path",
        backend_factory="vigor_harness.testing:toy_backend_factory",
        allowed_factory_prefixes=["vigor_harness"],
    )
    with pytest.raises(ValueError, match="allowed prefixes"):
        await evaluate_candidate(candidate, split, tmp_path / "meta_runs")


@pytest.mark.asyncio
async def test_evaluate_candidate_rejects_typosquat_prefix(tmp_path: Path) -> None:
    split = SplitManifest(
        split_id="toy.search.v1",
        role="search",
        task_uris=[_write_task(tmp_path / "task.json", "harness_task_1", "hello")],
    )
    candidate = HarnessCandidate(
        candidate_id="typosquat_candidate",
        hypothesis="substring-prefix should not satisfy namespace boundary",
        adapter_factory="vigor_harness_evil.foo:bar",
        backend_factory="vigor_harness.testing:toy_backend_factory",
        allowed_factory_prefixes=["vigor_harness"],
    )
    with pytest.raises(ValueError, match="allowed prefixes"):
        await evaluate_candidate(candidate, split, tmp_path / "meta_runs")
