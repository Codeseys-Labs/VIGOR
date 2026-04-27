"""Meta-Harness-style evaluation utilities for VIGOR."""

from vigor_harness.evaluator import HarnessEvaluationResult, evaluate_candidate
from vigor_harness.models import HarnessCandidate, HarnessEvalReport, SplitManifest

__all__ = [
    "HarnessCandidate",
    "HarnessEvalReport",
    "HarnessEvaluationResult",
    "SplitManifest",
    "evaluate_candidate",
]
__version__ = "0.1.0"
