"""Reviewer implementations for the photo adapter.

The histogram critic is a deterministic objective reviewer:

* Computes fraction of clipped highlights and crushed blacks.
* Computes mean luminance, contrast (RMS around mean), and saturation proxy.
* Returns a structured `ReviewReport` with per-dimension scores and a
  summary suitable for the adjudicator.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image
from vigor_core.schemas import Finding, ReviewReport
from vigor_core.util import utcnow_iso

# Luminance thresholds treated as clipped (highlights) or crushed (shadows).
_HIGHLIGHT_CLIP_LUMA = 0.995
_SHADOW_CRUSH_LUMA = 0.005
_PERCENT = 100


@dataclass(slots=True)
class HistogramSummary:
    mean_luminance: float
    rms_contrast: float
    clipped_highlights_fraction: float
    crushed_blacks_fraction: float
    saturation_proxy: float


def analyze(image_path: Path) -> HistogramSummary:
    arr = np.asarray(Image.open(image_path).convert("RGB"), dtype=np.float32) / 255.0
    luma = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    mean_luminance = float(luma.mean())
    rms_contrast = float(np.sqrt(((luma - mean_luminance) ** 2).mean()))
    clipped_highlights = float((luma >= _HIGHLIGHT_CLIP_LUMA).mean())
    crushed_blacks = float((luma <= _SHADOW_CRUSH_LUMA).mean())
    chroma = float(arr.std(axis=-1).mean())
    return HistogramSummary(
        mean_luminance=mean_luminance,
        rms_contrast=rms_contrast,
        clipped_highlights_fraction=clipped_highlights,
        crushed_blacks_fraction=crushed_blacks,
        saturation_proxy=chroma,
    )


class HistogramCritic:
    """Objective critic with configurable thresholds."""

    reviewer_id = "photo.histogram.v1"

    def __init__(
        self,
        *,
        highlights_tolerance: float = 0.02,
        blacks_tolerance: float = 0.02,
        target_contrast: float = 0.18,
    ) -> None:
        self.highlights_tolerance = highlights_tolerance
        self.blacks_tolerance = blacks_tolerance
        self.target_contrast = target_contrast

    def review(self, image_path: Path, candidate_id: str, artifact_id: str) -> ReviewReport:
        summary = analyze(image_path)
        findings: list[Finding] = []

        if summary.clipped_highlights_fraction > self.highlights_tolerance:
            findings.append(
                Finding(
                    id="highlights_clip",
                    severity="medium",
                    category="tonality",
                    evidence=(
                        f"{summary.clipped_highlights_fraction * _PERCENT:.2f}% of pixels "
                        f"are at or above {_HIGHLIGHT_CLIP_LUMA} luminance"
                    ),
                    rule_or_rubric="protect highlights unless intent says otherwise",
                    suggestion="lower global highlights or whites",
                    verified_by_tool=True,
                )
            )
        if summary.crushed_blacks_fraction > self.blacks_tolerance:
            findings.append(
                Finding(
                    id="blacks_crush",
                    severity="medium",
                    category="tonality",
                    evidence=(
                        f"{summary.crushed_blacks_fraction * _PERCENT:.2f}% of pixels "
                        f"are at or below {_SHADOW_CRUSH_LUMA} luminance"
                    ),
                    rule_or_rubric="protect shadows unless style asks for crushed blacks",
                    suggestion="lift global shadows or blacks",
                    verified_by_tool=True,
                )
            )

        # Score dimensions are all 0..1, higher is better.
        highlight_safety = max(
            0.0,
            1.0 - summary.clipped_highlights_fraction / max(self.highlights_tolerance, 1e-6),
        )
        shadow_safety = max(
            0.0,
            1.0 - summary.crushed_blacks_fraction / max(self.blacks_tolerance, 1e-6),
        )
        contrast_score = max(
            0.0,
            1.0 - abs(summary.rms_contrast - self.target_contrast) / self.target_contrast,
        )
        overall = min(highlight_safety, shadow_safety, contrast_score)
        passed = not findings

        return ReviewReport(
            review_id=f"rev_histogram_{candidate_id}",
            created_at=utcnow_iso(),
            candidate_id=candidate_id,
            artifact_id=artifact_id,
            reviewer_id=self.reviewer_id,
            reviewer_type="objective_metric",
            summary=(
                f"luma={summary.mean_luminance:.2f} "
                f"contrast={summary.rms_contrast:.2f} "
                f"clip={summary.clipped_highlights_fraction * _PERCENT:.2f}% "
                f"crush={summary.crushed_blacks_fraction * _PERCENT:.2f}%"
            ),
            scores={
                "quality": overall,
                "highlight_safety": highlight_safety,
                "shadow_safety": shadow_safety,
                "contrast": contrast_score,
            },
            thresholds={"quality": 0.5},
            passed=passed,
            confidence=0.9,
            findings=findings,
            recommended_action="accept" if passed else "patch",
            metadata={
                "mean_luminance": summary.mean_luminance,
                "rms_contrast": summary.rms_contrast,
                "clipped_highlights_fraction": summary.clipped_highlights_fraction,
                "crushed_blacks_fraction": summary.crushed_blacks_fraction,
            },
        )
