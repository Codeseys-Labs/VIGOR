"""Scoring normalization, adjudication policy, and frontier selection."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from vigor_core.schemas import (
    AdjudicationReport,
    Decision,
    Frontier,
    FrontierCandidate,
    ReviewReport,
)
from vigor_core.util import utcnow_iso


def normalize_score(value: float, scale: str) -> float:
    """Normalize a reviewer-reported score into the VIGOR 0..1 range."""

    if scale == "0_1":
        result = value
    elif scale == "1_5":
        result = (value - 1.0) / 4.0
    elif scale == "0_10":
        result = value / 10.0
    elif scale == "0_100":
        result = value / 100.0
    elif scale == "pass_fail":
        result = 1.0 if value else 0.0
    else:
        raise ValueError(f"unknown scale: {scale}")
    return max(0.0, min(1.0, result))


@dataclass(slots=True)
class ScoringPolicy:
    """Declarative scoring policy for a run."""

    policy_id: str
    hard_gates: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)
    minimums: dict[str, float] = field(default_factory=dict)
    disagreement_threshold: float = 0.20
    respect_review_passed: bool = True


@dataclass(slots=True)
class AdjudicationInputs:
    candidate_id: str
    reviews: list[ReviewReport]
    hard_gate_signals: dict[str, bool]


_MIN_REVIEWERS_FOR_DISAGREEMENT = 2
_REFINEMENT_PRIORITY: tuple[Decision, ...] = ("pivot", "branch", "patch")


def _aggregate_scores(reviews: list[ReviewReport]) -> tuple[dict[str, float], float]:
    buckets: dict[str, list[float]] = {}
    for review in reviews:
        for dim, value in review.scores.items():
            buckets.setdefault(dim, []).append(float(value))
    means = {dim: sum(values) / len(values) for dim, values in buckets.items() if values}
    disagreements = [
        max(values) - min(values)
        for values in buckets.values()
        if len(values) >= _MIN_REVIEWERS_FOR_DISAGREEMENT
    ]
    return means, max(disagreements) if disagreements else 0.0


def _composite(scores: dict[str, float], weights: dict[str, float]) -> float | None:
    if not weights:
        return None
    total = sum(weights.values())
    if total == 0:
        return None
    return sum(weight * scores.get(dim, 0.0) for dim, weight in weights.items()) / total


def _minimums_ok(scores: dict[str, float], minimums: dict[str, float]) -> list[str]:
    return [dim for dim, floor in minimums.items() if scores.get(dim, 0.0) < floor]


def _requested_refinement(reviews: list[ReviewReport]) -> Decision | None:
    actions = {review.recommended_action for review in reviews}
    for action in _REFINEMENT_PRIORITY:
        if action in actions:
            return action
    if any(not review.passed for review in reviews):
        return "patch"
    return None


def adjudicate(
    inputs: AdjudicationInputs,
    policy: ScoringPolicy,
    adjudication_id: str,
) -> AdjudicationReport:
    """Merge reviews into a decision using the policy."""

    hard_failures = [
        gate for gate in policy.hard_gates if not inputs.hard_gate_signals.get(gate, False)
    ]
    hard_gate_passed = not hard_failures
    normalized, disagreement = _aggregate_scores(inputs.reviews)
    composite = _composite(normalized, policy.weights)
    min_failures = _minimums_ok(normalized, policy.minimums)
    refinement = _requested_refinement(inputs.reviews) if policy.respect_review_passed else None

    decision: Decision
    reason: str

    if not hard_gate_passed:
        decision = "fail"
        reason = f"hard gate failure: {', '.join(hard_failures)}"
    elif any(r.recommended_action == "escalate" for r in inputs.reviews):
        decision = "escalate"
        reason = "at least one reviewer requested escalation"
    elif any(r.recommended_action == "fail" for r in inputs.reviews):
        decision = "fail"
        reason = "at least one reviewer requested failure"
    elif min_failures:
        decision = "patch"
        reason = f"score below minimum for: {', '.join(min_failures)}"
    elif refinement is not None:
        decision = refinement
        reason = f"reviewer requested {refinement} or reported failed status"
    elif disagreement > policy.disagreement_threshold:
        decision = "branch"
        reason = f"reviewer disagreement {disagreement:.2f} above threshold"
    else:
        decision = "accept"
        reason = (
            f"passes gates and minimums; composite={composite:.2f}"
            if composite is not None
            else "passes gates and minimums"
        )

    return AdjudicationReport(
        adjudication_id=adjudication_id,
        created_at=utcnow_iso(),
        candidate_id=inputs.candidate_id,
        policy_id=policy.policy_id,
        hard_gate_passed=hard_gate_passed,
        normalized_scores=normalized,
        composite=composite,
        reviewer_disagreement=disagreement,
        decision=decision,
        basis=[r.review_id for r in inputs.reviews],
        selection_reason=reason,
        residual_risks=min_failures,
    )


def build_frontier(
    run_id: str,
    frontier_id: str,
    adjudications: Iterable[AdjudicationReport],
    policy: ScoringPolicy,
) -> Frontier:
    """Rank candidates. Only accepted candidates are selectable."""

    scored: list[FrontierCandidate] = []
    for adj in adjudications:
        selectable = adj.hard_gate_passed and adj.decision == "accept"
        rejected = adj.decision in {"fail", "escalate"} or not adj.hard_gate_passed
        scored.append(
            FrontierCandidate(
                candidate_id=adj.candidate_id,
                status="kept" if not rejected else "rejected",
                decision=adj.decision,
                scores=dict(adj.normalized_scores)
                | ({"composite": adj.composite} if adj.composite is not None else {}),
                hard_gate_passed=adj.hard_gate_passed,
                rank=None,
                selection_reason=adj.selection_reason,
            )
        )
        if not selectable:
            scored[-1].scores.setdefault("composite", 0.0)

    def sort_key(candidate: FrontierCandidate) -> tuple[int, float]:
        selectable = candidate.decision == "accept" and candidate.hard_gate_passed
        return (0 if selectable else 1, -candidate.scores.get("composite", 0.0))

    scored.sort(key=sort_key)
    for idx, candidate in enumerate(scored):
        candidate.rank = idx + 1
        if idx == 0 and candidate.decision == "accept" and candidate.hard_gate_passed:
            candidate.status = "selected"
            candidate.selection_reason = "top-ranked accepted candidate passing hard gates"

    return Frontier(
        frontier_id=frontier_id,
        run_id=run_id,
        selection_policy=policy.policy_id,
        candidates=scored,
    )


def select_best(frontier: Frontier) -> FrontierCandidate | None:
    for candidate in frontier.candidates:
        if candidate.status == "selected":
            return candidate
    return None
