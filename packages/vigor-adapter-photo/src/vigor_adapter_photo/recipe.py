"""Pydantic schemas for the photo editing IR.

Ranges are chosen to match Lightroom/Camera Raw conventions so XMP export is a
straightforward field rename. The MVP persists global adjustments and a
reduced set of local-adjustment metadata; the renderer currently uses only
globals.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _PhotoBase(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        populate_by_name=True,
        alias_generator=to_camel,
    )


class PhotoGlobalAdjustments(_PhotoBase):
    exposure: float = Field(0.0, ge=-5.0, le=5.0)
    contrast: int = Field(0, ge=-100, le=100)
    highlights: int = Field(0, ge=-100, le=100)
    shadows: int = Field(0, ge=-100, le=100)
    whites: int = Field(0, ge=-100, le=100)
    blacks: int = Field(0, ge=-100, le=100)
    temperature: int = Field(0, ge=-100, le=100)
    tint: int = Field(0, ge=-150, le=150)
    vibrance: int = Field(0, ge=-100, le=100)
    saturation: int = Field(0, ge=-100, le=100)
    clarity: int = Field(0, ge=-100, le=100)
    dehaze: int = Field(0, ge=-100, le=100)
    sharpening: int = Field(0, ge=0, le=150)
    noise_reduction_color: int = Field(0, ge=0, le=100)


class PhotoLocalAdjustment(_PhotoBase):
    target: str
    mask_type: Literal[
        "semantic_or_gradient_mask",
        "object_mask",
        "linear_gradient",
        "radial_gradient",
    ]
    adjustments: dict[str, Any] = Field(default_factory=dict)


def _default_global() -> PhotoGlobalAdjustments:
    return PhotoGlobalAdjustments(
        exposure=0.0,
        contrast=0,
        highlights=0,
        shadows=0,
        whites=0,
        blacks=0,
        temperature=0,
        tint=0,
        vibrance=0,
        saturation=0,
        clarity=0,
        dehaze=0,
        sharpening=0,
        noise_reduction_color=0,
    )


class PhotoEditRecipeV1(_PhotoBase):
    schema_version: Literal["photo_edit_recipe.v1"] = "photo_edit_recipe.v1"
    kind: Literal["photo_edit_recipe"] = "photo_edit_recipe"
    intent: str
    global_adjustments: PhotoGlobalAdjustments = Field(default_factory=_default_global)
    local_adjustments: list[PhotoLocalAdjustment] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
