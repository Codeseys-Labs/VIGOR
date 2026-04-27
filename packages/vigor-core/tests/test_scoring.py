"""Scoring normalization, adjudication, and frontier tests."""

from __future__ import annotations

import pytest
from vigor_core.schemas import ReviewReport
from vigor_core.scoring import (
    AdjudicationInputs,
    ScoringPolicy,
    adjudicate,
    build_frontier,
    normalize_score,
    select_best,
)


def test_normalize_score_scales() -> None:
    assert normalize_score(0.5, "0_1") == 0.5
    assert normalize_score(3, "1_5") == 0.5
    assert normalize_score(5, "0_10") == 0.5
    assert normalize_score(50, "0_100") == 0.5
    assert normalize_score(1, "pass_fail") == 1.0
    assert normalize_score(0, "pass_fail") == 0.0


def test_normalize_score_clamps() -> None:
    assert normalize_score(-10, "0_1") == 0.0
    assert normalize_score(1.5, "0_1") == 1.0


def test_normalize_score_unknown_scale() -> None:
    with pytest.raises(ValueError):
        normalize_score(1.0, "bogus")


def _review(
    reviewer_id: str,
    scores: dict[str, float],
    *,
    passed: bool = True,
    action: str = "accept",
    candidate: str = "cand_1",
) -> ReviewReport:
    return ReviewReport.model_validate(
        {
            "review_id": f"rev_{reviewer_id}",
            "candidate_id": candidate,
            "reviewer_id": reviewer_id,
            "reviewer_type": "objective_metric",
            "summary": "synthetic",
            "scores": scores,
            "passed": passed,
            "recommended_action": action,
        }
    )


def test_adjudicate_accept_path() -> None:
    policy = ScoringPolicy(
        policy_id="p",
        hard_gates=["render_success"],
        weights={"quality": 0.5, "alignment": 0.5},
        minimums={"quality": 0.5, "alignment": 0.5},
    )
    inputs = AdjudicationInputs(
        candidate_id="cand_1",
        reviews=[
            _review("a", {"quality": 0.8, "alignment": 0.7}),
            _review("b", {"quality": 0.7, "alignment": 0.7}),
        ],
        hard_gate_signals={"render_success": True},
    )
    report = adjudicate(inputs, policy, "adj_1")
    assert report.decision == "accept"
    assert report.hard_gate_passed is True
    assert report.composite is not None
    assert report.composite > 0.5


def test_adjudicate_blocks_on_hard_gate_failure() -> None:
    policy = ScoringPolicy(policy_id="p", hard_gates=["render_success"])
    inputs = AdjudicationInputs(
        candidate_id="cand_1",
        reviews=[_review("a", {"quality": 0.9})],
        hard_gate_signals={"render_success": False},
    )
    report = adjudicate(inputs, policy, "adj_2")
    assert report.decision == "fail"
    assert report.hard_gate_passed is False


def test_adjudicate_patches_on_min_failure() -> None:
    policy = ScoringPolicy(policy_id="p", minimums={"quality": 0.8})
    inputs = AdjudicationInputs(
        candidate_id="cand_1",
        reviews=[_review("a", {"quality": 0.5})],
        hard_gate_signals={},
    )
    report = adjudicate(inputs, policy, "adj_3")
    assert report.decision == "patch"


def test_adjudicate_patches_on_mixed_failed_review() -> None:
    policy = ScoringPolicy(policy_id="p")
    inputs = AdjudicationInputs(
        candidate_id="cand_1",
        reviews=[
            _review("good", {"quality": 1.0}, passed=True, action="accept"),
            _review("bad", {"quality": 1.0}, passed=False, action="patch"),
        ],
        hard_gate_signals={},
    )
    report = adjudicate(inputs, policy, "adj_mixed")
    assert report.decision == "patch"


def test_adjudicate_branches_on_disagreement() -> None:
    policy = ScoringPolicy(policy_id="p", disagreement_threshold=0.1)
    inputs = AdjudicationInputs(
        candidate_id="cand_1",
        reviews=[
            _review("a", {"quality": 0.9}),
            _review("b", {"quality": 0.2}),
        ],
        hard_gate_signals={},
    )
    report = adjudicate(inputs, policy, "adj_4")
    assert report.decision == "branch"
    assert report.reviewer_disagreement is not None
    assert report.reviewer_disagreement > 0.1


def test_adjudicate_escalates_on_reviewer_request() -> None:
    policy = ScoringPolicy(policy_id="p")
    inputs = AdjudicationInputs(
        candidate_id="cand_1",
        reviews=[_review("a", {"quality": 0.9}, action="escalate")],
        hard_gate_signals={},
    )
    report = adjudicate(inputs, policy, "adj_5")
    assert report.decision == "escalate"


def test_frontier_selects_best_accepted_candidate() -> None:
    policy = ScoringPolicy(policy_id="p", weights={"quality": 1.0})
    inputs_a = AdjudicationInputs(
        candidate_id="cand_a",
        reviews=[_review("a", {"quality": 0.6}, candidate="cand_a")],
        hard_gate_signals={},
    )
    inputs_b = AdjudicationInputs(
        candidate_id="cand_b",
        reviews=[_review("b", {"quality": 0.8}, candidate="cand_b")],
        hard_gate_signals={},
    )
    adj_a = adjudicate(inputs_a, policy, "adj_a")
    adj_b = adjudicate(inputs_b, policy, "adj_b")

    frontier = build_frontier("run_1", "frontier_1", [adj_a, adj_b], policy)
    best = select_best(frontier)
    assert best is not None
    assert best.candidate_id == "cand_b"
    assert best.rank == 1


def test_frontier_does_not_select_patch_candidate_with_high_score() -> None:
    policy = ScoringPolicy(policy_id="p", weights={"quality": 1.0})
    patch_adj = adjudicate(
        AdjudicationInputs(
            candidate_id="needs_patch",
            reviews=[
                _review(
                    "needs_patch",
                    {"quality": 1.0},
                    candidate="needs_patch",
                    passed=False,
                    action="patch",
                )
            ],
            hard_gate_signals={},
        ),
        policy,
        "adj_patch",
    )
    accept_adj = adjudicate(
        AdjudicationInputs(
            candidate_id="accepted",
            reviews=[_review("accepted", {"quality": 0.2}, candidate="accepted")],
            hard_gate_signals={},
        ),
        policy,
        "adj_accept",
    )
    frontier = build_frontier("run_1", "frontier_1", [patch_adj, accept_adj], policy)
    best = select_best(frontier)
    assert best is not None
    assert best.candidate_id == "accepted"
