"""Pure-Python CAD validators."""

from __future__ import annotations

from dataclasses import dataclass, field

from vigor_adapter_cad.ir import CadParametricIRV1

_MIN_FDM_HOLE_DIAMETER_MM = 3.0
_SUPPORTED_HOLE_COUNTS = {0, 1, 2, 4}


@dataclass(slots=True)
class CadValidation:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    bbox_mm: tuple[float, float, float] = (0.0, 0.0, 0.0)


def validate_cad(ir: CadParametricIRV1) -> CadValidation:
    p = ir.parameters
    c = ir.constraints
    errors: list[str] = []
    warnings: list[str] = []
    bbox = (p.width_mm, p.height_mm, p.thickness_mm * (2 if p.rib_count else 1))

    hole_count = next(
        (feature.count for feature in ir.features if feature.type == "mounting_holes"),
        4,
    )
    hole_count = 4 if hole_count is None else hole_count
    if hole_count not in _SUPPORTED_HOLE_COUNTS:
        errors.append(
            f"unsupported mounting hole count {hole_count}; use one of {_SUPPORTED_HOLE_COUNTS}"
        )
    if p.thickness_mm < c.min_wall_thickness_mm:
        errors.append(f"thickness {p.thickness_mm}mm below minimum {c.min_wall_thickness_mm}mm")
    if p.rib_count > 0 and p.rib_thickness_mm < c.min_wall_thickness_mm:
        errors.append(
            f"rib thickness {p.rib_thickness_mm}mm below minimum {c.min_wall_thickness_mm}mm"
        )
    if any(value > maximum for value, maximum in zip(bbox, c.max_bbox_mm, strict=True)):
        errors.append(f"bbox {bbox} exceeds max {c.max_bbox_mm}")
    min_edge_distance = p.hole_diameter_mm / 2.0 + c.min_wall_thickness_mm
    if hole_count > 0 and p.hole_margin_mm < min_edge_distance:
        errors.append(
            f"hole margin {p.hole_margin_mm}mm below safe edge distance {min_edge_distance}mm"
        )
    if hole_count > 0 and (
        2 * p.hole_margin_mm >= p.width_mm or 2 * p.hole_margin_mm >= p.height_mm
    ):
        errors.append("hole margins do not fit inside part bounds")
    if c.manufacturing == "fdm" and p.hole_diameter_mm < _MIN_FDM_HOLE_DIAMETER_MM:
        warnings.append("FDM holes below 3mm may print undersized")
    return CadValidation(ok=not errors, errors=errors, warnings=warnings, bbox_mm=bbox)
