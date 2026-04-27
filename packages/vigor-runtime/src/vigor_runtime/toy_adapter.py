"""A minimal domain adapter used to exercise the orchestrator loop.

The toy adapter treats the goal as text, writes it verbatim to a file, and
returns a single passing reviewer. It is the smallest end-to-end demo of the
VIGOR generate-compile-review-adjudicate cycle.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

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
    TaskSpec,
    ToolManifest,
)
from vigor_core.util import sha256_text, utcnow_iso


class ToyTextAdapter(DomainAdapter):
    """Toy adapter: the IR is `{"text": "<string>"}`. The compiler writes it."""

    domain: ClassVar[str] = "toy_text"

    async def describe_capabilities(self) -> AdapterManifest:
        return AdapterManifest(
            adapter_id="toy_text.v1",
            domain=self.domain,
            version="0.1.0",
            supported_ir=["toy_text.v1"],
            tools=[
                ToolManifest(
                    tool_id="toy_text.writer",
                    capability="render",
                    mutability="mutator",
                    inputs=["toy_text.v1"],
                    outputs=["text/plain"],
                    description="Write the IR text body to disk.",
                )
            ],
            reviewers=["toy_text.length"],
            exports=["text/plain"],
        )

    async def plan_representation(self, task: TaskSpec) -> RepresentationPlan:
        return RepresentationPlan(
            ir_type="toy_text.v1",
            reviewer_ids=["toy_text.length"],
            notes="toy adapter: echo the goal as text",
        )

    async def validate_ir(self, ir: ArtifactIR) -> ValidationReport:
        if "text" not in ir.body:
            return ValidationReport(ok=False, errors=["missing 'text' field"])
        if not isinstance(ir.body["text"], str):
            return ValidationReport(ok=False, errors=["'text' must be a string"])
        return ValidationReport(ok=True)

    async def compile(self, ir: ArtifactIR, context: RunContext) -> CompileResult:
        text = ir.body.get("text", "")
        run_dir = Path(context.run_dir)
        artifacts_dir = run_dir / "candidates" / ir.candidate_id / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        output_path = artifacts_dir / "output.txt"
        output_path.write_text(text, encoding="utf-8")
        artifact = ObservableArtifact(
            artifact_id=f"toy_text_{ir.candidate_id}",
            uri=str(output_path.relative_to(run_dir.parent)),
            media_type="text/plain",
            sha256=sha256_text(text),
            summary=f"{len(text)} characters",
        )
        return CompileResult(
            compile_id=f"compile_{ir.candidate_id}",
            candidate_id=ir.candidate_id,
            tool_id="toy_text.writer",
            status="success",
            outputs=[artifact],
            metrics={"runtime_ms": 1, "char_count": len(text)},
        )

    async def review(
        self,
        artifact: ObservableArtifact,
        ir: ArtifactIR,
        context: RunContext,
    ) -> list[ReviewReport]:
        text = ir.body.get("text", "")
        length_ok = len(text) > 0
        return [
            ReviewReport(
                review_id=f"rev_len_{ir.candidate_id}",
                candidate_id=ir.candidate_id,
                artifact_id=artifact.artifact_id,
                reviewer_id="toy_text.length",
                reviewer_type="objective_metric",
                summary="length check",
                scores={"quality": 1.0 if length_ok else 0.0},
                thresholds={"quality": 0.1},
                passed=length_ok,
                confidence=1.0,
                recommended_action="accept" if length_ok else "fail",
            )
        ]

    async def apply_patch(self, ir: ArtifactIR, patch: PatchPlan) -> ArtifactIR:
        text = ir.body.get("text", "")
        if "append '!'" in patch.objectives:
            text = f"{text}!"
        return ArtifactIR(
            candidate_id=f"{ir.candidate_id}_patched",
            ir_type=ir.ir_type,
            parent_candidate_id=ir.candidate_id,
            hypothesis="applied patch",
            body={"text": text},
            generator={"source": "toy_adapter.apply_patch", "timestamp": utcnow_iso()},
        )

    async def export(
        self,
        ir: ArtifactIR,
        artifact: ObservableArtifact,
        context: RunContext,
    ) -> ExportBundle:
        _ = context  # toy adapter does not persist extra exports
        return ExportBundle(
            export_id=f"export_{ir.candidate_id}",
            candidate_id=ir.candidate_id,
            exports=[
                ExportEntry(
                    type="final_artifact",
                    uri=artifact.uri,
                    media_type="text/plain",
                    sha256=artifact.sha256,
                ),
                ExportEntry(
                    type="canonical_ir",
                    uri=f"candidates/{ir.candidate_id}/ir.json",
                    media_type="application/json",
                ),
            ],
        )
