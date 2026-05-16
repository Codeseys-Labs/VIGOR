"""Meta-Harness-style evaluation utilities for VIGOR."""

from vigor_harness.comparator import ComparisonInputError, compare_candidates
from vigor_harness.evaluator import HarnessEvaluationResult, evaluate_candidate
from vigor_harness.models import (
    HarnessCandidate,
    HarnessComparison,
    HarnessEvalReport,
    SplitManifest,
)

__all__ = [
    "ComparisonInputError",
    "HarnessCandidate",
    "HarnessComparison",
    "HarnessEvalReport",
    "HarnessEvaluationResult",
    "SplitManifest",
    "compare_candidates",
    "evaluate_candidate",
]
__version__ = "0.1.0"
