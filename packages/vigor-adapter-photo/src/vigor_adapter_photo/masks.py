"""Mask generation utilities for the photo adapter.

Masks are float arrays in [0, 1] internally and 8-bit grayscale PNGs on disk.
They are heuristic and deterministic; they are not semantic segmentation.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np
from PIL import Image, ImageFilter

_SKY_LOWER_CUTOFF = 0.85
_SKY_LOWER_WEIGHT = 0.25


def smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    denom = max(edge1 - edge0, 1e-6)
    t = np.clip((x - edge0) / denom, 0.0, 1.0)
    return cast(np.ndarray, t * t * (3.0 - 2.0 * t))


def vertical_gradient(height: int, width: int, *, top: bool = True) -> np.ndarray:
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    mask = np.clip((0.65 - y) / 0.45, 0.0, 1.0) if top else np.clip((y - 0.35) / 0.55, 0.0, 1.0)
    return np.repeat(mask, width, axis=1)


def radial_gradient(
    height: int,
    width: int,
    *,
    center: tuple[float, float] = (0.5, 0.48),
    radius: tuple[float, float] = (0.34, 0.42),
    falloff: float = 1.8,
) -> np.ndarray:
    yy, xx = np.mgrid[0:height, 0:width]
    cx, cy = center[0] * width, center[1] * height
    rx, ry = max(radius[0] * width, 1.0), max(radius[1] * height, 1.0)
    d = ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2
    return cast(np.ndarray, np.clip(1.0 - d, 0.0, 1.0).astype(np.float32) ** falloff)


def sky_heuristic(arr: np.ndarray) -> np.ndarray:
    height, width = arr.shape[:2]
    r = arr[..., 0]
    g = arr[..., 1]
    b = arr[..., 2]
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    blue_excess = b - np.maximum(r, g)
    cyan_blue = b + 0.5 * g - 0.75 * r
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    pos = np.repeat(np.clip((0.75 - y) / 0.75, 0.0, 1.0), width, axis=1)
    bright = smoothstep(0.35, 0.85, luma)
    blue = smoothstep(0.02, 0.18, blue_excess)
    cyan = smoothstep(0.10, 0.45, cyan_blue)

    gray = Image.fromarray((luma * 255).astype(np.uint8), mode="L")
    blur = np.asarray(gray.filter(ImageFilter.GaussianBlur(radius=3)), dtype=np.float32) / 255.0
    texture = np.abs(luma - blur)
    low_texture = 1.0 - smoothstep(0.015, 0.08, texture)

    mask = pos * np.maximum(blue, cyan) * bright * low_texture
    mask[y[:, 0] > _SKY_LOWER_CUTOFF, :] *= _SKY_LOWER_WEIGHT
    return feather(mask.astype(np.float32), 12)


def foreground_gradient(arr: np.ndarray, sky: np.ndarray | None = None) -> np.ndarray:
    height, width = arr.shape[:2]
    lower = vertical_gradient(height, width, top=False)
    if sky is not None:
        lower *= 1.0 - sky
    luma = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    dark = 1.0 - smoothstep(0.25, 0.70, luma)
    return feather(lower * (0.5 + 0.5 * dark), 24)


def subject_radial(arr: np.ndarray, sky: np.ndarray | None = None) -> np.ndarray:
    height, width = arr.shape[:2]
    radial = radial_gradient(height, width)
    sat = np.max(arr, axis=2) - np.min(arr, axis=2)
    luma = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    blur = (
        np.asarray(
            Image.fromarray((luma * 255).astype(np.uint8), mode="L").filter(
                ImageFilter.GaussianBlur(radius=3)
            ),
            dtype=np.float32,
        )
        / 255.0
    )
    contrast = np.abs(luma - blur)
    mask = radial
    if sky is not None:
        mask *= 1.0 - sky
    mask *= 0.6 + 0.4 * smoothstep(0.05, 0.30, sat)
    mask *= 0.7 + 0.3 * smoothstep(0.02, 0.12, contrast)
    return feather(mask.astype(np.float32), 18)


def feather(mask: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return cast(np.ndarray, np.clip(mask, 0.0, 1.0))
    mask_u8 = (np.clip(mask, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    blurred = Image.fromarray(mask_u8, mode="L").filter(ImageFilter.GaussianBlur(radius=radius))
    return cast(np.ndarray, np.asarray(blurred, dtype=np.float32) / 255.0)


def save_mask_png(mask: np.ndarray, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    mask_u8 = (np.clip(mask, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    Image.fromarray(mask_u8, mode="L").save(path, format="PNG")
    return str(path)


def load_mask_png(path: Path, shape: tuple[int, int]) -> np.ndarray:
    mask = Image.open(path).convert("L")
    if mask.size != (shape[1], shape[0]):
        mask = mask.resize((shape[1], shape[0]), resample=Image.Resampling.BILINEAR)
    return cast(np.ndarray, np.asarray(mask, dtype=np.float32) / 255.0)


def generate_named_mask(
    arr: np.ndarray, mask_type: str, *, sky: np.ndarray | None = None
) -> np.ndarray:
    height, width = arr.shape[:2]
    if mask_type in {"sky_heuristic", "semantic_or_gradient_mask"}:
        return sky_heuristic(arr)
    if mask_type in {"foreground_gradient", "linear_gradient"}:
        return foreground_gradient(arr, sky=sky)
    if mask_type in {"subject_radial", "radial_gradient", "object_mask"}:
        return subject_radial(arr, sky=sky)
    return np.zeros((height, width), dtype=np.float32)
