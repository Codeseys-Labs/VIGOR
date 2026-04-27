"""Pure-Python photo renderer used for VIGOR previews.

This renderer is deliberately minimal. It applies exposure, contrast,
highlights, shadows, saturation, and temperature to an sRGB image using
Pillow + NumPy. It does not claim to match Lightroom output exactly; its
purpose is to produce a fast, deterministic preview the histogram critic can
evaluate.

For RAW input, callers can install the `raw` extra (rawpy) and convert to
an sRGB JPEG/PIL image before invoking `render_preview`.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image

if TYPE_CHECKING:
    from vigor_adapter_photo.recipe import PhotoEditRecipeV1


def _load(image_path: Path) -> Image.Image:
    return Image.open(image_path).convert("RGB")


def render_preview(image_path: Path, recipe: PhotoEditRecipeV1, output_path: Path) -> Image.Image:
    """Render a preview JPEG from an sRGB input and a recipe."""

    img = _load(image_path)
    arr = np.asarray(img, dtype=np.float32) / 255.0
    adj = recipe.global_adjustments

    # Exposure: add EV stops (2^ev in linear), approximated in sRGB for speed.
    arr = np.clip(arr * (2.0**adj.exposure), 0.0, 1.0)

    # Contrast: push around 0.5.
    if adj.contrast != 0:
        c = 1.0 + adj.contrast / 100.0
        arr = np.clip((arr - 0.5) * c + 0.5, 0.0, 1.0)

    # Highlights / shadows via piecewise tone shift.
    if adj.highlights != 0:
        mask = np.clip((arr - 0.5) * 2.0, 0.0, 1.0)
        arr = np.clip(arr + (adj.highlights / 200.0) * mask, 0.0, 1.0)
    if adj.shadows != 0:
        mask = np.clip((0.5 - arr) * 2.0, 0.0, 1.0)
        arr = np.clip(arr + (adj.shadows / 200.0) * mask, 0.0, 1.0)

    # Saturation and vibrance: simple HSV-like shift in RGB space.
    if adj.saturation != 0 or adj.vibrance != 0:
        luma = (0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2])[..., None]
        factor = 1.0 + (adj.saturation + adj.vibrance * 0.7) / 100.0
        arr = np.clip(luma + (arr - luma) * factor, 0.0, 1.0)

    # Temperature: shift blue/red channels inversely.
    if adj.temperature != 0:
        t = adj.temperature / 200.0
        arr[..., 0] = np.clip(arr[..., 0] + t, 0.0, 1.0)
        arr[..., 2] = np.clip(arr[..., 2] - t, 0.0, 1.0)

    out = (arr * 255.0 + 0.5).astype(np.uint8)
    rendered = Image.fromarray(out, mode="RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered.save(output_path, format="JPEG", quality=92)
    return rendered
