"""Tests for the archive-anchored harness comparator (ADR-0031 §2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from vigor_harness import (
    ComparisonInputError,
    HarnessComparison,
    HarnessEvalReport,
    compare_candidates,
)


def _write_frontier(
    archive_root: Path,
    task_id: str,
    *,
    selected_composite: float | None,
) -> None:
    """Write a minimal frontier.json. ``None`` composite => no selected candidate."""

    task_dir = archive_root / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    if selected_composite is None:
        # Failed run: only kept/rejected candidates, no "selected" entry.
        candidates: list[dict[str, Any]] = [
            {
                "candidateId": "cand_a",
                "status": "rejected",
                "decision": "fail",
                "scores": {"composite": 0.0},
                "hardGatePassed": False,
                "rank": 1,
                "selectionReason": "rejected by hard gate",
            }
        ]
    else:
        candidates = [
            {
                "candidateId": "cand_a",
                "status": "selected",
                "decision": "accept",
                "scores": {"composite": selected_composite},
                "hardGatePassed": True,
                "rank": 1,
                "selectionReason": "top-ranked accepted candidate passing hard gates",
            }
        ]
    payload = {
        "schemaVersion": "vigor.frontier.v1",
        "frontierId": f"frontier_{task_id}",
        "createdAt": "2026-05-15T00:00:00Z",
        "runId": task_id,
        "selectionPolicy": "toy.default",
        "candidates": candidates,
    }
    (task_dir / "frontier.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _make_report(candidate_id: str, *, split_id: str = "toy.search.v1") -> HarnessEvalReport:
    return HarnessEvalReport(
        candidate_id=candidate_id,
        split_id=split_id,
        n_tasks=2,
        n_succeeded=2,
        hard_gate_pass_rate=1.0,
        accept_rate=1.0,
        mean_composite=0.5,
    )


@pytest.mark.asyncio
async def test_compare_candidates_paired_happy_path(tmp_path: Path) -> None:
    a_archive = tmp_path / "a"
    b_archive = tmp_path / "b"
    _write_frontier(a_archive, "task_1", selected_composite=0.5)
    _write_frontier(a_archive, "task_2", selected_composite=0.6)
    _write_frontier(b_archive, "task_1", selected_composite=0.7)
    _write_frontier(b_archive, "task_2", selected_composite=0.5)

    comparison = await compare_candidates(
        _make_report("cand_a"),
        _make_report("cand_b"),
        a_archive,
        b_archive,
        bootstrap_resamples=200,
    )

    assert isinstance(comparison, HarnessComparison)
    assert comparison.schema_version == "vigor.harness_comparison.v1"
    assert comparison.a_candidate_id == "cand_a"
    assert comparison.b_candidate_id == "cand_b"
    assert comparison.split_id == "toy.search.v1"
    assert comparison.n_paired_tasks == 2
    assert comparison.wins == 1  # task_1: 0.5 -> 0.7
    assert comparison.losses == 1  # task_2: 0.6 -> 0.5
    assert comparison.ties == 0
    assert comparison.delta_composite is not None
    assert comparison.delta_composite == pytest.approx(0.05)
    assert comparison.delta_composite_ci_low is not None
    assert comparison.delta_composite_ci_high is not None
    assert comparison.delta_composite_ci_low <= comparison.delta_composite
    assert comparison.delta_composite_ci_high >= comparison.delta_composite
    assert comparison.regressed_task_ids == ["task_2"]


@pytest.mark.asyncio
async def test_compare_candidates_split_mismatch_fails_closed(tmp_path: Path) -> None:
    a_archive = tmp_path / "a"
    b_archive = tmp_path / "b"
    _write_frontier(a_archive, "task_1", selected_composite=0.5)
    _write_frontier(b_archive, "task_1", selected_composite=0.7)

    a = _make_report("cand_a", split_id="toy.search.v1")
    b = _make_report("cand_b", split_id="toy.validation.v1")
    with pytest.raises(ComparisonInputError, match="split_id mismatch"):
        await compare_candidates(a, b, a_archive, b_archive)


@pytest.mark.asyncio
async def test_compare_candidates_missing_archive_fails_closed(tmp_path: Path) -> None:
    a_archive = tmp_path / "a"
    b_archive = tmp_path / "b_does_not_exist"
    _write_frontier(a_archive, "task_1", selected_composite=0.5)

    with pytest.raises(ComparisonInputError, match="archive for candidate"):
        await compare_candidates(
            _make_report("cand_a"),
            _make_report("cand_b"),
            a_archive,
            b_archive,
        )


@pytest.mark.asyncio
async def test_compare_candidates_no_common_tasks_fails_closed(tmp_path: Path) -> None:
    a_archive = tmp_path / "a"
    b_archive = tmp_path / "b"
    _write_frontier(a_archive, "task_1", selected_composite=0.5)
    _write_frontier(b_archive, "task_2", selected_composite=0.6)

    with pytest.raises(ComparisonInputError, match=r"no per-task frontier\.json"):
        await compare_candidates(
            _make_report("cand_a"),
            _make_report("cand_b"),
            a_archive,
            b_archive,
        )


@pytest.mark.asyncio
async def test_compare_candidates_ties_when_scores_equal(tmp_path: Path) -> None:
    a_archive = tmp_path / "a"
    b_archive = tmp_path / "b"
    _write_frontier(a_archive, "task_1", selected_composite=0.5)
    _write_frontier(b_archive, "task_1", selected_composite=0.5)

    comparison = await compare_candidates(
        _make_report("cand_a"),
        _make_report("cand_b"),
        a_archive,
        b_archive,
        bootstrap_resamples=50,
    )

    assert comparison.wins == 0
    assert comparison.losses == 0
    assert comparison.ties == 1
    assert comparison.delta_composite == pytest.approx(0.0)
    assert comparison.regressed_task_ids == []
    # Identical accept outcomes => no discordant pairs => mcnemar undefined.
    assert comparison.mcnemar_p is None


@pytest.mark.asyncio
async def test_compare_candidates_mcnemar_on_accept_rate(tmp_path: Path) -> None:
    """Mismatched accept outcomes drive McNemar.

    Construct 4 paired tasks where A accepts all four but B rejects two of
    them. Discordant pairs: b=2 (A accept, B reject), c=0 (A reject, B accept).
    Two-sided exact binomial p = min(1, 2 * sum_{i=0..0} C(2,i)*0.5^2) = 0.5.
    """

    a_archive = tmp_path / "a"
    b_archive = tmp_path / "b"
    for i in range(4):
        _write_frontier(a_archive, f"task_{i}", selected_composite=0.5)
    _write_frontier(b_archive, "task_0", selected_composite=0.4)
    _write_frontier(b_archive, "task_1", selected_composite=0.6)
    _write_frontier(b_archive, "task_2", selected_composite=None)
    _write_frontier(b_archive, "task_3", selected_composite=None)

    comparison = await compare_candidates(
        _make_report("cand_a"),
        _make_report("cand_b"),
        a_archive,
        b_archive,
        bootstrap_resamples=100,
    )

    assert comparison.n_paired_tasks == 4
    assert comparison.mcnemar_p == pytest.approx(0.5)
    # task_0 regressed on composite (0.5 -> 0.4); task_2 and task_3 regressed
    # on accept (A accepted, B rejected). task_1 improved on composite.
    assert set(comparison.regressed_task_ids) == {"task_0", "task_2", "task_3"}
    assert comparison.wins == 1  # task_1
    assert comparison.losses == 3  # task_0, task_2, task_3
    assert comparison.ties == 0


@pytest.mark.asyncio
async def test_compare_candidates_round_trips_via_alias(tmp_path: Path) -> None:
    a_archive = tmp_path / "a"
    b_archive = tmp_path / "b"
    _write_frontier(a_archive, "task_1", selected_composite=0.5)
    _write_frontier(b_archive, "task_1", selected_composite=0.6)

    comparison = await compare_candidates(
        _make_report("cand_a"),
        _make_report("cand_b"),
        a_archive,
        b_archive,
        bootstrap_resamples=50,
    )
    payload = json.loads(comparison.model_dump_json(by_alias=True))
    # camelCase wire format per repo convention.
    assert payload["schemaVersion"] == "vigor.harness_comparison.v1"
    assert payload["aCandidateId"] == "cand_a"
    assert payload["bCandidateId"] == "cand_b"
    assert "deltaCompositeCiLow" in payload
    assert "regressedTaskIds" in payload


@pytest.mark.asyncio
async def test_compare_candidates_deterministic_ci(tmp_path: Path) -> None:
    a_archive = tmp_path / "a"
    b_archive = tmp_path / "b"
    for i in range(5):
        _write_frontier(a_archive, f"task_{i}", selected_composite=0.4 + 0.05 * i)
        _write_frontier(b_archive, f"task_{i}", selected_composite=0.5 + 0.05 * i)

    first = await compare_candidates(
        _make_report("cand_a"),
        _make_report("cand_b"),
        a_archive,
        b_archive,
        bootstrap_resamples=200,
    )
    second = await compare_candidates(
        _make_report("cand_a"),
        _make_report("cand_b"),
        a_archive,
        b_archive,
        bootstrap_resamples=200,
    )
    assert first.delta_composite_ci_low == second.delta_composite_ci_low
    assert first.delta_composite_ci_high == second.delta_composite_ci_high
