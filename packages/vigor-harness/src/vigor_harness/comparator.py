"""Archive-anchored pairwise comparison of two harness eval reports.

ADR-0031 §2 specifies the comparator: it does not re-run candidates. Given
two ``HarnessEvalReport`` instances and the paths to their archives, it
reads the per-task ``frontier.json`` from each archive and emits a
``HarnessComparison`` artifact. Fails closed via ``ComparisonInputError``
on missing archives or split mismatch.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

from vigor_core.errors import VigorError

from vigor_harness.models import HarnessComparison, HarnessEvalReport


class ComparisonInputError(VigorError):
    """Comparator inputs are missing, malformed, or do not match.

    Raised when an archive directory is absent, a split_id mismatch is
    detected, or the manifest_sha256 (when present on both reports) does
    not match. Per ADR-0031 the comparator is fail-closed: callers must
    fix the inputs rather than receive a partial comparison.
    """

    kind = "comparison_input"
    retryable = False


@dataclass(slots=True, frozen=True)
class _PerTaskOutcome:
    """Per-task signal extracted from a single archive's frontier.json."""

    accepted: bool
    composite: float | None


def _frontier_path(archive_root: Path, task_id: str) -> Path:
    return archive_root / task_id / "frontier.json"


def _read_outcome(archive_root: Path, task_id: str) -> _PerTaskOutcome | None:
    path = _frontier_path(archive_root, task_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", []) if isinstance(payload, dict) else []
    selected = next(
        (c for c in candidates if isinstance(c, dict) and c.get("status") == "selected"),
        None,
    )
    if selected is None:
        return _PerTaskOutcome(accepted=False, composite=None)
    scores = selected.get("scores") or {}
    raw_composite = scores.get("composite") if isinstance(scores, dict) else None
    composite = float(raw_composite) if isinstance(raw_composite, int | float) else None
    return _PerTaskOutcome(accepted=True, composite=composite)


def _list_task_ids(archive_root: Path) -> set[str]:
    if not archive_root.exists():
        return set()
    return {p.name for p in archive_root.iterdir() if p.is_dir() and (p / "frontier.json").exists()}


def _percentile(sorted_values: list[float], q: float) -> float:
    if not sorted_values:
        raise ValueError("cannot compute percentile of empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = q * (len(sorted_values) - 1)
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return sorted_values[lo]
    frac = idx - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def _paired_bootstrap_ci(
    deltas: list[float],
    *,
    resamples: int,
    rng: random.Random,
) -> tuple[float, float]:
    """Two-sided 95% CI for the mean of a paired-difference sample."""

    n = len(deltas)
    if n == 0:
        raise ValueError("paired bootstrap requires at least one paired observation")
    if resamples <= 0:
        raise ValueError("bootstrap_resamples must be positive")
    means: list[float] = []
    for _ in range(resamples):
        total = 0.0
        for _i in range(n):
            total += deltas[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    return _percentile(means, 0.025), _percentile(means, 0.975)


def _mcnemar_exact_p(b: int, c: int) -> float | None:
    """Two-sided exact binomial p-value on discordant accept-rate pairs.

    Returns ``None`` when there are no discordant pairs (b + c == 0); in
    that case the test is undefined and the CI on accept-rate change is
    vacuously {0}.
    """

    n = b + c
    if n == 0:
        return None
    k = min(b, c)
    cumulative = 0.0
    for i in range(k + 1):
        cumulative += math.comb(n, i) * (0.5**n)
    return min(1.0, 2.0 * cumulative)


def _seeded_rng(a_id: str, b_id: str, split_id: str) -> random.Random:
    """Deterministic RNG so reruns over the same archives reproduce.

    Python's builtin ``hash`` is salted per-interpreter via
    ``PYTHONHASHSEED``, so it cannot anchor a cross-process-stable seed.
    We use a SHA-256 digest of the comparison-identifying tuple and take
    the first 8 bytes as a 64-bit seed.
    """

    payload = f"vigor.harness_comparison.v1|{a_id}|{b_id}|{split_id}".encode()
    digest = hashlib.sha256(payload).digest()
    seed = int.from_bytes(digest[:8], "big")
    return random.Random(seed)


def _coerce_manifest_sha(report: HarnessEvalReport) -> str | None:
    """Forward-compat hook for the v2 manifest_sha256 field (ADR-0031 §2 step 1).

    The current ``HarnessEvalReport`` schema (v1) does not declare
    ``manifest_sha256``; ``ConfigDict(extra="forbid")`` would reject it
    on parse, so a v1 report cannot smuggle a value through
    ``model_extra``. When the v2 schema lands the field is populated by
    construction and ``getattr`` will return it; until then this returns
    ``None`` and the equality check is skipped.
    """

    return getattr(report, "manifest_sha256", None)


@dataclass(slots=True)
class _PairwiseTallies:
    wins: int = 0
    losses: int = 0
    ties: int = 0
    discordant_b_only: int = 0  # A accepted, B rejected
    discordant_c_only: int = 0  # A rejected, B accepted
    deltas: list[float] = field(default_factory=list)
    regressed_task_ids: list[str] = field(default_factory=list)


def _classify_pair(
    task_id: str,
    outcome_a: _PerTaskOutcome,
    outcome_b: _PerTaskOutcome,
    tallies: _PairwiseTallies,
) -> None:
    if outcome_a.accepted and not outcome_b.accepted:
        tallies.discordant_b_only += 1
    elif not outcome_a.accepted and outcome_b.accepted:
        tallies.discordant_c_only += 1

    a_score = outcome_a.composite if outcome_a.accepted else None
    b_score = outcome_b.composite if outcome_b.accepted else None

    if a_score is not None and b_score is not None:
        delta = b_score - a_score
        tallies.deltas.append(delta)
        if delta > 0:
            tallies.wins += 1
        elif delta < 0:
            tallies.losses += 1
            tallies.regressed_task_ids.append(task_id)
        else:
            tallies.ties += 1
        return
    if a_score is None and b_score is None:
        tallies.ties += 1
        return
    if a_score is None:
        tallies.wins += 1
        return
    tallies.losses += 1
    tallies.regressed_task_ids.append(task_id)


def _validate_inputs(
    a: HarnessEvalReport,
    b: HarnessEvalReport,
    a_archive: Path,
    b_archive: Path,
) -> list[str]:
    if a.split_id != b.split_id:
        raise ComparisonInputError(
            f"split_id mismatch: a={a.split_id!r} b={b.split_id!r}",
            evidence_uri=f"{a.candidate_id}::{b.candidate_id}",
        )
    a_manifest = _coerce_manifest_sha(a)
    b_manifest = _coerce_manifest_sha(b)
    if a_manifest is not None and b_manifest is not None and a_manifest != b_manifest:
        raise ComparisonInputError(
            f"manifest_sha256 mismatch: a={a_manifest!r} b={b_manifest!r}",
            evidence_uri=f"{a.candidate_id}::{b.candidate_id}",
        )
    if not a_archive.exists():
        raise ComparisonInputError(
            f"archive for candidate {a.candidate_id!r} is missing: {a_archive}",
            evidence_uri=str(a_archive),
        )
    if not b_archive.exists():
        raise ComparisonInputError(
            f"archive for candidate {b.candidate_id!r} is missing: {b_archive}",
            evidence_uri=str(b_archive),
        )
    common_tasks = sorted(_list_task_ids(a_archive) & _list_task_ids(b_archive))
    if not common_tasks:
        raise ComparisonInputError(
            (
                f"no per-task frontier.json found in common between archives "
                f"{a_archive} and {b_archive}"
            ),
            evidence_uri=str(a_archive),
        )
    return common_tasks


async def compare_candidates(
    a: HarnessEvalReport,
    b: HarnessEvalReport,
    a_archive: Path,
    b_archive: Path,
    *,
    bootstrap_resamples: int = 1000,
) -> HarnessComparison:
    """Compare two harness eval reports against their per-task archives.

    Per-task signals are read from ``<archive>/<task_id>/frontier.json``.
    A "selected" frontier candidate counts as accepted; its composite
    score (if present) seeds the paired-difference sample. Tasks present
    in only one archive are dropped from the paired analysis but the
    discordance is reflected in the report's ``n_paired_tasks`` field.
    """

    common_tasks = _validate_inputs(a, b, a_archive, b_archive)

    tallies = _PairwiseTallies()
    for task_id in common_tasks:
        outcome_a = _read_outcome(a_archive, task_id)
        outcome_b = _read_outcome(b_archive, task_id)
        # Both archives listed the task (membership filtered above), so neither is None.
        assert outcome_a is not None and outcome_b is not None
        _classify_pair(task_id, outcome_a, outcome_b, tallies)

    delta_composite: float | None = None
    delta_composite_ci_low: float | None = None
    delta_composite_ci_high: float | None = None
    if tallies.deltas:
        delta_composite = sum(tallies.deltas) / len(tallies.deltas)
        rng = _seeded_rng(a.candidate_id, b.candidate_id, a.split_id)
        delta_composite_ci_low, delta_composite_ci_high = _paired_bootstrap_ci(
            tallies.deltas, resamples=bootstrap_resamples, rng=rng
        )

    mcnemar_p = _mcnemar_exact_p(tallies.discordant_b_only, tallies.discordant_c_only)

    return HarnessComparison(
        comparison_id=f"cmp_{a.candidate_id}_vs_{b.candidate_id}",
        a_candidate_id=a.candidate_id,
        b_candidate_id=b.candidate_id,
        split_id=a.split_id,
        n_paired_tasks=len(common_tasks),
        wins=tallies.wins,
        losses=tallies.losses,
        ties=tallies.ties,
        delta_composite=delta_composite,
        delta_composite_ci_low=delta_composite_ci_low,
        delta_composite_ci_high=delta_composite_ci_high,
        mcnemar_p=mcnemar_p,
        regressed_task_ids=tallies.regressed_task_ids,
    )
