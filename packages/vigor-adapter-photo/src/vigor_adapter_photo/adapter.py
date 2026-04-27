"""VIGOR domain adapter for photo editing.

The adapter accepts an IR whose body is a `PhotoEditRecipeV1`. It renders a
preview using the pure-Python renderer, runs the histogram critic, and can
export JSON and XMP sidecars.

The generator (agent backend) is expected to produce the recipe body. For
deterministic runs without an LLM, use `EchoAgentBackend` with a seed factory
that returns `PhotoEditRecipeV1(...).model_dump(by_alias=True)`.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import ClassVar

from pydantic import ValidationError
from vigor_core.archive import RunArchive
from vigor_core.interfaces import (
    DomainAdapter,
    RepresentationPlan,
    RunContext,
    ValidationReport,
)
from vigor_core.schemas import (
    AdapterManifest,
    ArtifactIR,
    CompileResult,
    ExportBundle,
    ExportEntry,
    ObservableArtifact,
    PatchPlan,
    ReviewReport,
    RuntimeErrorRecord,
    TaskSpec,
    ToolManifest,
)
from vigor_core.util import safe_relative, sha256_file, sha256_text, utcnow_iso

from vigor_adapter_photo.recipe import PhotoEditRecipeV1, PhotoGlobalAdjustments
from vigor_adapter_photo.renderer import render_preview
from vigor_adapter_photo.reviewers import HistogramCritic
from vigor_adapter_photo.xmp import recipe_to_xmp


class PhotoEditingAdapter(DomainAdapter):
    """Photo editing adapter (global adjustments only for MVP)."""

    domain: ClassVar[str] = "photo_editing"

    def __init__(self, critic: HistogramCritic | None = None) -> None:
        self._critic = critic or HistogramCritic()

    async def describe_capabilities(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="photo.editing.v1",
            domain=self.domain,
            version="0.1.0",
            supported_ir=["photo_edit_recipe.v1"],
            tools=[
                ToolManifest(
                    tool_id="photo.renderer.v1",
                    capability="render",
                    mutability="mutator",
                    inputs=["photo_edit_recipe.v1", "image/jpeg"],
                    outputs=["image/jpeg", "metrics.histogram.v1"],
                    description="Pure-Python Pillow/NumPy preview renderer.",
                ),
                ToolManifest(
                    tool_id="photo.histogram.v1",
                    capability="score",
                    mutability="observer",
                    outputs=["vigor.review_report.v1"],
                    description="Clipping / crush / contrast critic.",
                ),
            ],
            reviewers=["photo.histogram.v1"],
            exports=["recipe.json", "lightroom.xmp", "image/jpeg"],
        )

    async def plan_representation(self, task: TaskSpec) -> RepresentationPlan:
        return RepresentationPlan(
            ir_type="photo_edit_recipe.v1",
            reviewer_ids=["photo.histogram.v1"],
            notes="Global tone/color adjustments. Masks deferred to v1.",
        )

    async def validate_ir(self, ir: ArtifactIR) -> ValidationReport:
        try:
            PhotoEditRecipeV1.model_validate(ir.body)
        except ValidationError as exc:
            return ValidationReport(ok=False, errors=[str(exc)])
        return ValidationReport(ok=True)

    def _recipe(self, ir: ArtifactIR) -> PhotoEditRecipeV1:
        return PhotoEditRecipeV1.model_validate(ir.body)

    async def compile(self, ir: ArtifactIR, context: RunContext) -> CompileResult:
        recipe = self._recipe(ir)
        input_uri = context.task.references[0].uri if context.task.references else None
        if input_uri is None:
            return CompileResult(
                compile_id=f"compile_{ir.candidate_id}",
                candidate_id=ir.candidate_id,
                tool_id="photo.renderer.v1",
                status="failure",
                errors=[
                    RuntimeErrorRecord(
                        error_id=f"err_compile_{ir.candidate_id}",
                        type="adapter_contract",
                        severity="high",
                        message=(
                            "no input reference supplied; photo adapter requires "
                            "TaskSpec.references[0].uri"
                        ),
                        retryable=False,
                    )
                ],
            )
        input_path = Path(input_uri)
        run_dir = Path(context.run_dir)
        cand_dir = run_dir / "candidates" / ir.candidate_id
        artifacts_dir = cand_dir / "artifacts"
        preview_path = artifacts_dir / "preview.jpg"
        # Run blocking Pillow/NumPy in a thread so the orchestrator stays async.
        await asyncio.to_thread(render_preview, input_path, recipe, preview_path)
        digest = await asyncio.to_thread(sha256_file, preview_path)
        preview_artifact = ObservableArtifact(
            artifact_id=f"photo_preview_{ir.candidate_id}",
            uri=safe_relative(preview_path, run_dir.parent),
            media_type="image/jpeg",
            sha256=digest,
            summary=f"recipe: {recipe.intent}",
        )
        return CompileResult(
            compile_id=f"compile_{ir.candidate_id}",
            candidate_id=ir.candidate_id,
            tool_id="photo.renderer.v1",
            status="success",
            outputs=[preview_artifact],
            metrics={"renderer": "pillow_numpy"},
        )

    async def review(
        self,
        artifact: ObservableArtifact,
        ir: ArtifactIR,
        context: RunContext,
    ) -> list[ReviewReport]:
        preview_path = self._resolve_artifact_path(context, artifact)
        report = await asyncio.to_thread(
            self._critic.review, preview_path, ir.candidate_id, artifact.artifact_id
        )
        return [report]

    async def apply_patch(self, ir: ArtifactIR, patch: PatchPlan) -> ArtifactIR:
        recipe = self._recipe(ir)
        new_adj = recipe.global_adjustments.model_copy()
        for objective in patch.objectives:
            _apply_objective_hint(new_adj, objective)
        new_recipe = recipe.model_copy(update={"global_adjustments": new_adj})
        suffix = uuid.uuid4().hex[:8]
        return ArtifactIR(
            candidate_id=f"{ir.candidate_id}_p{suffix}",
            ir_type=ir.ir_type,
            parent_candidate_id=ir.candidate_id,
            hypothesis="applied patch objectives",
            body=new_recipe.model_dump(by_alias=True, mode="json"),
            generator={"source": "photo_adapter.apply_patch", "timestamp": utcnow_iso()},
        )

    async def export(
        self,
        ir: ArtifactIR,
        artifact: ObservableArtifact,
        context: RunContext,
    ) -> ExportBundle:
        recipe = self._recipe(ir)
        xmp = recipe_to_xmp(recipe)
        recipe_bytes = json.dumps(recipe.model_dump(by_alias=True, mode="json"), indent=2)
        # Persist XMP + canonical IR under <run_id>/final/exports/ inside the
        # archive root. ``context.run_dir`` is always absolute; its parent is
        # the archive root.
        run_dir = Path(context.run_dir)
        archive_root = run_dir.parent
        archive = RunArchive(archive_root)
        xmp_rel = f"{run_dir.name}/final/exports/lightroom.xmp"
        recipe_rel = f"{run_dir.name}/final/exports/recipe.json"
        archive.write_raw(xmp_rel, xmp)
        archive.write_raw(recipe_rel, recipe_bytes)
        xmp_entry = ExportEntry(
            type="lightroom_xmp",
            uri=xmp_rel,
            media_type="application/xml",
            sha256=sha256_text(xmp),
        )
        recipe_entry = ExportEntry(
            type="canonical_ir",
            uri=recipe_rel,
            media_type="application/json",
            sha256=sha256_text(recipe_bytes),
        )
        preview_entry = ExportEntry(
            type="final_artifact",
            uri=artifact.uri,
            media_type="image/jpeg",
            sha256=artifact.sha256,
        )
        return ExportBundle(
            export_id=f"export_{ir.candidate_id}",
            candidate_id=ir.candidate_id,
            exports=[preview_entry, recipe_entry, xmp_entry],
            lossiness=[
                {
                    "export_type": "lightroom_xmp",
                    "note": (
                        "MVP XMP carries global tone/color only. Masks and local "
                        "adjustments are written as external references when added."
                    ),
                }
            ],
        )

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _resolve_artifact_path(self, context: RunContext, artifact: ObservableArtifact) -> Path:
        """Resolve an artifact URI safely inside the run archive.

        Rejects absolute paths and any path that escapes the archive root via
        ``..`` segments.
        """

        run_dir = Path(context.run_dir)
        archive_root = run_dir.parent.resolve()
        uri = Path(artifact.uri)
        if uri.is_absolute():
            raise ValueError(
                f"absolute artifact URIs are not accepted by photo adapter: {artifact.uri}"
            )
        for candidate in (archive_root / uri, run_dir / uri):
            resolved = candidate.resolve()
            try:
                resolved.relative_to(archive_root)
            except ValueError as exc:
                raise ValueError(f"artifact uri escapes archive root: {artifact.uri}") from exc
            if resolved.exists():
                return resolved
        raise FileNotFoundError(f"artifact not found: {artifact.uri}")


def _apply_objective_hint(adj: PhotoGlobalAdjustments, objective: str) -> None:
    """Tiny deterministic hint-to-slider mapper for demos.

    Real agentic patching should return structured slider deltas through
    `AgentBackend.propose_patch`. This helper keeps the demo runnable.
    """

    lower = objective.lower()
    if "clip" in lower and "highlight" in lower:
        adj.highlights = max(-100, adj.highlights - 10)
        adj.whites = max(-100, adj.whites - 5)
    if "crush" in lower and "black" in lower:
        adj.shadows = min(100, adj.shadows + 10)
        adj.blacks = min(100, adj.blacks + 5)
    if "warm" in lower:
        adj.temperature = min(100, adj.temperature + 5)
    if "cool" in lower:
        adj.temperature = max(-100, adj.temperature - 5)
    if "contrast" in lower and "more" in lower:
        adj.contrast = min(100, adj.contrast + 10)
    if "contrast" in lower and "less" in lower:
        adj.contrast = max(-100, adj.contrast - 10)
