"""VIGOR adapter for standalone Manim scenes."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import ClassVar

from pydantic import ValidationError
from vigor_core.interfaces import DomainAdapter, RepresentationPlan, RunContext, ValidationReport
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
from vigor_core.util import safe_relative, sha256_file, utcnow_iso

from vigor_adapter_video_manim.renderer import ManimRenderConfig, Runner, render_manim_scene
from vigor_adapter_video_manim.scene_ir import ManimSceneIRV1


class ManimVideoAdapter(DomainAdapter):
    """Compile generated Manim scene code into MP4 when Manim is available."""

    domain: ClassVar[str] = "video_manim"

    def __init__(
        self,
        *,
        render_config: ManimRenderConfig | None = None,
        runner: Runner | None = None,
    ) -> None:
        self._render_config = render_config or ManimRenderConfig()
        self._runner = runner

    async def describe_capabilities(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="video.manim.v1",
            domain=self.domain,
            version="0.1.0",
            supported_ir=["manim_scene.v1"],
            tools=[
                ToolManifest(
                    tool_id="manim.render.v1",
                    capability="render",
                    mutability="mutator",
                    inputs=["manim_scene.v1"],
                    outputs=["video/mp4", "text/x-python"],
                    timeout_s=self._render_config.timeout_s,
                    description="Render Manim scene code through the Manim CLI.",
                )
            ],
            reviewers=["video.manim.basic.v1"],
            exports=["video/mp4", "scene.py"],
        )

    async def plan_representation(self, task: TaskSpec) -> RepresentationPlan:
        return RepresentationPlan(
            ir_type="manim_scene.v1",
            reviewer_ids=["video.manim.basic.v1"],
            notes="Standalone Manim scene rendered through CLI.",
        )

    async def validate_ir(self, ir: ArtifactIR) -> ValidationReport:
        try:
            ManimSceneIRV1.model_validate(ir.body)
        except ValidationError as exc:
            return ValidationReport(ok=False, errors=[str(exc)])
        return ValidationReport(ok=True)

    def _scene(self, ir: ArtifactIR) -> ManimSceneIRV1:
        return ManimSceneIRV1.model_validate(ir.body)

    async def compile(self, ir: ArtifactIR, context: RunContext) -> CompileResult:
        scene = self._scene(ir)
        run_dir = Path(context.run_dir)
        artifacts_dir = run_dir / "candidates" / ir.candidate_id / "artifacts"
        scene_path = artifacts_dir / "scene.py"
        media_dir = artifacts_dir / "media"
        scene_path.parent.mkdir(parents=True, exist_ok=True)
        scene_path.write_text(scene.python_code, encoding="utf-8")
        try:
            video_path = await asyncio.to_thread(
                render_manim_scene,
                scene_path,
                scene.scene_name,
                media_dir,
                config=self._render_config,
                runner=self._runner,
            )
        except Exception as exc:
            return CompileResult(
                compile_id=f"compile_{ir.candidate_id}",
                candidate_id=ir.candidate_id,
                tool_id="manim.render.v1",
                status="failure",
                errors=[
                    RuntimeErrorRecord(
                        error_id=f"err_manim_{ir.candidate_id}",
                        type="render_error",
                        severity="high",
                        message=str(exc),
                        retryable=False,
                    )
                ],
            )
        video_digest = await asyncio.to_thread(sha256_file, video_path)
        code_digest = await asyncio.to_thread(sha256_file, scene_path)
        return CompileResult(
            compile_id=f"compile_{ir.candidate_id}",
            candidate_id=ir.candidate_id,
            tool_id="manim.render.v1",
            status="success",
            outputs=[
                ObservableArtifact(
                    artifact_id=f"manim_video_{ir.candidate_id}",
                    uri=safe_relative(video_path, run_dir.parent),
                    media_type="video/mp4",
                    sha256=video_digest,
                    summary=scene.title,
                ),
                ObservableArtifact(
                    artifact_id=f"manim_scene_{ir.candidate_id}",
                    uri=safe_relative(scene_path, run_dir.parent),
                    media_type="text/x-python",
                    sha256=code_digest,
                    summary="Manim scene source",
                ),
            ],
            metrics={"scene_name": scene.scene_name, "renderer": "manim_cli"},
        )

    async def review(
        self, artifact: ObservableArtifact, ir: ArtifactIR, context: RunContext
    ) -> list[ReviewReport]:
        _ = context
        passed = artifact.media_type == "video/mp4" and artifact.sha256 is not None
        return [
            ReviewReport(
                review_id=f"rev_manim_basic_{ir.candidate_id}",
                candidate_id=ir.candidate_id,
                artifact_id=artifact.artifact_id,
                reviewer_id="video.manim.basic.v1",
                reviewer_type="objective_metric",
                summary="mp4 artifact exists" if passed else "missing mp4 artifact",
                scores={"quality": 1.0 if passed else 0.0},
                passed=passed,
                recommended_action="accept" if passed else "patch",
            )
        ]

    async def apply_patch(self, ir: ArtifactIR, patch: PatchPlan) -> ArtifactIR:
        scene = self._scene(ir)
        comment = "\n# VIGOR patch objectives:\n" + "\n".join(
            f"# - {objective}" for objective in patch.objectives
        )
        patched = scene.model_copy(update={"python_code": scene.python_code + comment})
        return ArtifactIR(
            candidate_id=f"{ir.candidate_id}_p{uuid.uuid4().hex[:8]}",
            ir_type=ir.ir_type,
            parent_candidate_id=ir.candidate_id,
            hypothesis="appended patch objectives as comments",
            body=patched.model_dump(by_alias=True, mode="json"),
            generator={"source": "video_manim.apply_patch", "timestamp": utcnow_iso()},
        )

    async def export(
        self, ir: ArtifactIR, artifact: ObservableArtifact, context: RunContext
    ) -> ExportBundle:
        _ = context
        return ExportBundle(
            export_id=f"export_{ir.candidate_id}",
            candidate_id=ir.candidate_id,
            exports=[
                ExportEntry(
                    type="final_artifact",
                    uri=artifact.uri,
                    media_type=artifact.media_type,
                    sha256=artifact.sha256,
                )
            ],
        )
