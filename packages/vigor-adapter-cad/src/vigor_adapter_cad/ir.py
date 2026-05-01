"""Parametric CAD IR for first-slice OpenSCAD generation."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from vigor_core.registry import register_ir


class _CadBase(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        populate_by_name=True,
        alias_generator=to_camel,
    )


class CadParameters(_CadBase):
    width_mm: float = Field(100.0, gt=0)
    height_mm: float = Field(60.0, gt=0)
    thickness_mm: float = Field(5.0, gt=0)
    hole_diameter_mm: float = Field(4.5, gt=0)
    hole_margin_mm: float = Field(10.0, ge=0)
    rib_count: int = Field(2, ge=0, le=8)
    rib_thickness_mm: float = Field(4.0, gt=0)


class CadConstraints(_CadBase):
    max_bbox_mm: list[float] = Field(
        default_factory=lambda: [120.0, 80.0, 40.0], min_length=3, max_length=3
    )
    min_wall_thickness_mm: float = Field(3.0, gt=0)
    manufacturing: Literal["fdm", "sla", "cnc", "unknown"] = "fdm"


class CadFeature(_CadBase):
    type: Literal["base_plate", "mounting_holes", "ribs"]
    count: int | None = Field(default=None, ge=0)


def _default_parameters() -> CadParameters:
    return CadParameters(
        width_mm=100.0,
        height_mm=60.0,
        thickness_mm=5.0,
        hole_diameter_mm=4.5,
        hole_margin_mm=10.0,
        rib_count=2,
        rib_thickness_mm=4.0,
    )


def _default_constraints() -> CadConstraints:
    return CadConstraints(
        max_bbox_mm=[120.0, 80.0, 40.0],
        min_wall_thickness_mm=3.0,
        manufacturing="fdm",
    )


def _default_features() -> list[CadFeature]:
    return [
        CadFeature(type="base_plate"),
        CadFeature(type="mounting_holes", count=4),
        CadFeature(type="ribs"),
    ]


class CadParametricIRV1(_CadBase):
    schema_version: Literal["cad_parametric.v1"] = "cad_parametric.v1"
    kind: Literal["cad_parametric"] = "cad_parametric"
    units: Literal["mm"] = "mm"
    intent: str
    part_type: Literal["bracket_plate"] = "bracket_plate"
    parameters: CadParameters = Field(default_factory=_default_parameters)
    constraints: CadConstraints = Field(default_factory=_default_constraints)
    features: list[CadFeature] = Field(default_factory=_default_features)


register_ir(CadParametricIRV1)
