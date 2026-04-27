"""VIGOR photo editing adapter."""

from vigor_adapter_photo.adapter import PhotoEditingAdapter
from vigor_adapter_photo.masks import (
    foreground_gradient,
    generate_named_mask,
    load_mask_png,
    radial_gradient,
    save_mask_png,
    sky_heuristic,
    subject_radial,
    vertical_gradient,
)
from vigor_adapter_photo.recipe import (
    PhotoEditRecipeV1,
    PhotoGlobalAdjustments,
    PhotoLocalAdjustment,
)
from vigor_adapter_photo.reviewers import HistogramCritic, HistogramSummary
from vigor_adapter_photo.xmp import recipe_to_xmp

__all__ = [
    "HistogramCritic",
    "HistogramSummary",
    "PhotoEditRecipeV1",
    "PhotoEditingAdapter",
    "PhotoGlobalAdjustments",
    "PhotoLocalAdjustment",
    "foreground_gradient",
    "generate_named_mask",
    "load_mask_png",
    "radial_gradient",
    "recipe_to_xmp",
    "save_mask_png",
    "sky_heuristic",
    "subject_radial",
    "vertical_gradient",
]
__version__ = "0.1.0"
