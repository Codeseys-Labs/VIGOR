"""VIGOR CAD adapter using deterministic OpenSCAD source generation."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import ClassVar

from pydantic import ValidationError
from vigor_core.archive import RunArchive
from vigor_core.interfaces import DomainAdapter, RepresentationPlan, RunContext, ValidationReport
from vigor_core.schemas import (
    AdapterManifest,
    ArtifactIR,
    CompileResult,
    ExportBundle,
    ExportEntry,
    Finding,
    ObservableArtifact,
    PatchPlan,
    ReviewReport,
    TaskSpec,
    ToolManifest,
)
from vigor_core.util import safe_relative, sha256_file, sha256_text, utcnow_iso

from vigor_adapter_cad.ir import CadParametricIRV1
from vigor_adapter_cad.openscad import render_openscad
from vigor_adapter_cad.validators import validate_cad


class CadOpenScadAdapter(DomainAdapter):
    domain: ClassVar[str] = "cad_openscad"

    async def describe_capabilities(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="cad.openscad.v1",
            domain=self.domain,
            version="0.1.0",
            supported_ir=["cad_parametric.v1"],
            tools=[
                ToolManifest(
                    tool_id="cad.openscad.generate.v1",
                    capability="compile",
                    mutability="mutator",
                    inputs=["cad_parametric.v1"],
                    outputs=["text/x-openscad", "cad.validation.v1"],
                    description="Generate deterministic OpenSCAD text and pure-Python validation.",
                )
            ],
            reviewers=["cad.validation.v1"],
            exports=["model.scad", "cad_validation.json"],
        )

    async def plan_representation(self, task: TaskSpec) -> RepresentationPlan:
        return RepresentationPlan(
            ir_type="cad_parametric.v1",
            reviewer_ids=["cad.validation.v1"],
            notes="First-slice CAD: generate editable OpenSCAD source, no mesh kernel required.",
        )

    async def validate_ir(self, ir: ArtifactIR) -> ValidationReport:
        try:
            CadParametricIRV1.model_validate(ir.body)
        except ValidationError as exc:
            return ValidationReport(ok=False, errors=[str(exc)])
        return ValidationReport(ok=True)

    def _cad(self, ir: ArtifactIR) -> CadParametricIRV1:
        return CadParametricIRV1.model_validate(ir.body)

    async def compile(self, ir: ArtifactIR, context: RunContext) -> CompileResult:
        model = self._cad(ir)
        validation = validate_cad(model)
        run_dir = Path(context.run_dir)
        artifacts_dir = run_dir / "candidates" / ir.candidate_id / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        scad_path = artifacts_dir / "model.scad"
        scad_path.write_text(render_openscad(model), encoding="utf-8")
        artifact = ObservableArtifact(
            artifact_id=f"cad_scad_{ir.candidate_id}",
            uri=safe_relative(scad_path, run_dir.parent),
            media_type="text/x-openscad",
            sha256=sha256_file(scad_path),
            summary=model.intent,
        )
        return CompileResult(
            compile_id=f"compile_{ir.candidate_id}",
            candidate_id=ir.candidate_id,
            tool_id="cad.openscad.generate.v1",
            status="success",
            outputs=[artifact],
            metrics={
                "validation_ok": validation.ok,
                "validation_errors": validation.errors,
                "bbox_mm": validation.bbox_mm,
                "warnings": validation.warnings,
            },
        )

    async def review(
        self, artifact: ObservableArtifact, ir: ArtifactIR, context: RunContext
    ) -> list[ReviewReport]:
        _ = context
        validation = validate_cad(self._cad(ir))
        findings = [
            Finding(
                id=f"cad_error_{idx}",
                severity="high",
                category="cad_validation",
                evidence=error,
                suggestion="adjust CAD parameters to satisfy constraints",
                verified_by_tool=True,
            )
            for idx, error in enumerate(validation.errors)
        ]
        return [
            ReviewReport(
                review_id=f"rev_cad_{ir.candidate_id}",
                candidate_id=ir.candidate_id,
                artifact_id=artifact.artifact_id,
                reviewer_id="cad.validation.v1",
                reviewer_type="objective_metric",
                summary="CAD parameters valid" if validation.ok else "; ".join(validation.errors),
                scores={"quality": 1.0 if validation.ok else 0.0},
                passed=validation.ok,
                findings=findings,
                recommended_action="accept" if validation.ok else "patch",
                metadata={"bbox_mm": validation.bbox_mm, "warnings": validation.warnings},
            )
        ]

    async def apply_patch(self, ir: ArtifactIR, patch: PatchPlan) -> ArtifactIR:
        model = self._cad(ir)
        params = model.parameters.model_copy()
        for objective in patch.objectives:
            lower = objective.lower()
            if "thickness" in lower or "wall" in lower:
                params.thickness_mm = max(
                    params.thickness_mm + 1.0, model.constraints.min_wall_thickness_mm
                )
                params.rib_thickness_mm = max(
                    params.rib_thickness_mm + 1.0,
                    model.constraints.min_wall_thickness_mm,
                )
            if "hole margin" in lower or "edge" in lower:
                params.hole_margin_mm += 1.0
            if "bbox" in lower or "bounds" in lower:
                params.width_mm = min(params.width_mm, model.constraints.max_bbox_mm[0])
                params.height_mm = min(params.height_mm, model.constraints.max_bbox_mm[1])
        patched = model.model_copy(update={"parameters": params})
        return ArtifactIR(
            candidate_id=f"{ir.candidate_id}_p{uuid.uuid4().hex[:8]}",
            ir_type=ir.ir_type,
            parent_candidate_id=ir.candidate_id,
            hypothesis="CAD parameters patched",
            body=patched.model_dump(by_alias=True, mode="json"),
            generator={"source": "cad.apply_patch", "timestamp": utcnow_iso()},
        )

    async def export(
        self, ir: ArtifactIR, artifact: ObservableArtifact, context: RunContext
    ) -> ExportBundle:
        validation = validate_cad(self._cad(ir))
        run_dir = Path(context.run_dir)
        archive = RunArchive(run_dir.parent)
        validation_rel = f"{run_dir.name}/final/exports/cad_validation.json"
        validation_json = json.dumps(
            {
                "ok": validation.ok,
                "errors": validation.errors,
                "warnings": validation.warnings,
                "bboxMm": validation.bbox_mm,
            },
            indent=2,
        )
        archive.write_raw(validation_rel, validation_json)
        return ExportBundle(
            export_id=f"export_{ir.candidate_id}",
            candidate_id=ir.candidate_id,
            exports=[
                ExportEntry(
                    type="openscad_source",
                    uri=artifact.uri,
                    media_type="text/x-openscad",
                    sha256=artifact.sha256,
                ),
                ExportEntry(
                    type="cad_validation",
                    uri=validation_rel,
                    media_type="application/json",
                    sha256=sha256_text(validation_json),
                ),
            ],
        )
