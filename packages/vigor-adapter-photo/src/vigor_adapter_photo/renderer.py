"""Pure-Python photo renderer used for VIGOR previews.

The renderer applies global adjustments, then blends local adjusted variants
through optional grayscale PNG masks. It is deterministic and intentionally
approximate; it is a preview renderer, not a Lightroom-compatible raw engine.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from PIL import Image

from vigor_adapter_photo.masks import load_mask_png

if TYPE_CHECKING:
    from vigor_adapter_photo.recipe import PhotoEditRecipeV1, PhotoGlobalAdjustments


def _load(image_path: Path) -> Image.Image:
    return Image.open(image_path).convert("RGB")


def _apply_adjustments(arr: np.ndarray, adjustments: dict[str, Any]) -> np.ndarray:
    exposure = float(adjustments.get("exposure", 0.0))
    contrast = int(adjustments.get("contrast", 0))
    highlights = int(adjustments.get("highlights", 0))
    shadows = int(adjustments.get("shadows", 0))
    saturation = int(adjustments.get("saturation", 0))
    vibrance = int(adjustments.get("vibrance", 0))
    temperature = int(adjustments.get("temperature", 0))

    out = np.clip(arr * (2.0**exposure), 0.0, 1.0)
    if contrast != 0:
        c = 1.0 + contrast / 100.0
        out = np.clip((out - 0.5) * c + 0.5, 0.0, 1.0)
    if highlights != 0:
        mask = np.clip((out - 0.5) * 2.0, 0.0, 1.0)
        out = np.clip(out + (highlights / 200.0) * mask, 0.0, 1.0)
    if shadows != 0:
        mask = np.clip((0.5 - out) * 2.0, 0.0, 1.0)
        out = np.clip(out + (shadows / 200.0) * mask, 0.0, 1.0)
    if saturation != 0 or vibrance != 0:
        luma = (0.2126 * out[..., 0] + 0.7152 * out[..., 1] + 0.0722 * out[..., 2])[..., None]
        factor = 1.0 + (saturation + vibrance * 0.7) / 100.0
        out = np.clip(luma + (out - luma) * factor, 0.0, 1.0)
    if temperature != 0:
        t = temperature / 200.0
        out[..., 0] = np.clip(out[..., 0] + t, 0.0, 1.0)
        out[..., 2] = np.clip(out[..., 2] - t, 0.0, 1.0)
    return cast(np.ndarray, out)


def _global_to_dict(adj: PhotoGlobalAdjustments) -> dict[str, Any]:
    return {
        "exposure": adj.exposure,
        "contrast": adj.contrast,
        "highlights": adj.highlights,
        "shadows": adj.shadows,
        "saturation": adj.saturation,
        "vibrance": adj.vibrance,
        "temperature": adj.temperature,
    }


def _resolve_mask_uri(mask_uri: str, mask_base_dir: Path | None) -> Path:
    path = Path(mask_uri)
    if path.is_absolute():
        raise ValueError(f"absolute mask URIs are not accepted: {mask_uri}")
    if mask_base_dir is None:
        if ".." in path.parts:
            raise ValueError(f"mask URI escapes base directory: {mask_uri}")
        return path
    base = mask_base_dir.resolve()
    resolved = (base / path).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"mask URI escapes base directory: {mask_uri}") from exc
    return resolved


def render_preview(
    image_path: Path,
    recipe: PhotoEditRecipeV1,
    output_path: Path,
    *,
    mask_base_dir: Path | None = None,
) -> Image.Image:
    """Render a preview JPEG from an sRGB input and a recipe."""

    img = _load(image_path)
    arr = np.asarray(img, dtype=np.float32) / 255.0
    arr = _apply_adjustments(arr, _global_to_dict(recipe.global_adjustments))

    for local in recipe.local_adjustments:
        if local.mask_uri is None:
            continue
        mask_path = _resolve_mask_uri(local.mask_uri, mask_base_dir)
        if not mask_path.exists():
            raise FileNotFoundError(f"local adjustment mask not found: {local.mask_uri}")
        mask = load_mask_png(mask_path, arr.shape[:2])
        if local.invert:
            mask = 1.0 - mask
        adjusted = _apply_adjustments(arr.copy(), local.adjustments)
        alpha = mask[..., None]
        arr = np.clip(arr * (1.0 - alpha) + adjusted * alpha, 0.0, 1.0)

    out = (arr * 255.0 + 0.5).astype(np.uint8)
    rendered = Image.fromarray(out, mode="RGB")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rendered.save(output_path, format="JPEG", quality=92)
    return rendered
