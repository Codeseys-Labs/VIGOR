"""Filesystem-backed run archive."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from vigor_core.errors import SchemaValidationError
from vigor_core.schemas import (
    AdapterManifest,
    AdjudicationReport,
    ArtifactIR,
    CompileResult,
    ExportBundle,
    Frontier,
    PatchPlan,
    ProvenanceRecord,
    ReviewReport,
    RuntimeErrorRecord,
    TaskSpec,
)

T = TypeVar("T", bound=BaseModel)


def _dump(model: BaseModel) -> str:
    return model.model_dump_json(by_alias=True, indent=2)


def _load(path: Path, cls: type[T]) -> T:
    try:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise SchemaValidationError(
            f"failed to parse {cls.__name__} at {path}: {exc}",
            evidence_uri=str(path),
        ) from exc


class RunArchive:
    """Persist every record the orchestrator produces."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def run_dir(self, run_id: str) -> Path:
        return self._safe_target(run_id)

    def candidate_dir(self, run_id: str, candidate_id: str) -> Path:
        return self._safe_target(f"{run_id}/candidates/{candidate_id}")

    def reviews_dir(self, run_id: str, candidate_id: str) -> Path:
        return self._safe_target(f"{run_id}/candidates/{candidate_id}/reviews")

    def artifacts_dir(self, run_id: str, candidate_id: str) -> Path:
        return self._safe_target(f"{run_id}/candidates/{candidate_id}/artifacts")

    def write_task(self, task: TaskSpec) -> Path:
        run_dir = self.run_dir(task.task_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "task.json"
        path.write_text(_dump(task), encoding="utf-8")
        return path

    def read_task(self, run_id: str) -> TaskSpec:
        return _load(self.run_dir(run_id) / "task.json", TaskSpec)

    def write_manifest(self, run_id: str, manifest: AdapterManifest) -> Path:
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "adapter_manifest.json"
        path.write_text(_dump(manifest), encoding="utf-8")
        return path

    def write_ir(self, run_id: str, ir: ArtifactIR) -> Path:
        cand = self.candidate_dir(run_id, ir.candidate_id)
        cand.mkdir(parents=True, exist_ok=True)
        path = cand / "ir.json"
        path.write_text(_dump(ir), encoding="utf-8")
        return path

    def read_ir(self, run_id: str, candidate_id: str) -> ArtifactIR:
        return _load(self.candidate_dir(run_id, candidate_id) / "ir.json", ArtifactIR)

    def write_compile_result(self, run_id: str, result: CompileResult) -> Path:
        cand = self.candidate_dir(run_id, result.candidate_id)
        cand.mkdir(parents=True, exist_ok=True)
        path = cand / "compile_result.json"
        path.write_text(_dump(result), encoding="utf-8")
        return path

    def write_review(self, run_id: str, review: ReviewReport) -> Path:
        reviews = self.reviews_dir(run_id, review.candidate_id)
        reviews.mkdir(parents=True, exist_ok=True)
        path = self._safe_target(
            f"{run_id}/candidates/{review.candidate_id}/reviews/{review.review_id}.json"
        )
        path.write_text(_dump(review), encoding="utf-8")
        return path

    def list_reviews(self, run_id: str, candidate_id: str) -> list[ReviewReport]:
        reviews = self.reviews_dir(run_id, candidate_id)
        if not reviews.exists():
            return []
        return [_load(path, ReviewReport) for path in sorted(reviews.glob("*.json"))]

    def write_adjudication(self, run_id: str, report: AdjudicationReport) -> Path:
        cand = self.candidate_dir(run_id, report.candidate_id)
        cand.mkdir(parents=True, exist_ok=True)
        path = cand / "adjudication.json"
        path.write_text(_dump(report), encoding="utf-8")
        return path

    def write_patch(self, run_id: str, patch: PatchPlan) -> Path:
        cand = self.candidate_dir(run_id, patch.source_candidate_id)
        cand.mkdir(parents=True, exist_ok=True)
        path = cand / "patch_plan.json"
        path.write_text(_dump(patch), encoding="utf-8")
        return path

    def write_frontier(self, run_id: str, frontier: Frontier) -> Path:
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "frontier.json"
        path.write_text(_dump(frontier), encoding="utf-8")
        return path

    def write_final(
        self,
        run_id: str,
        export_bundle: ExportBundle,
        provenance: ProvenanceRecord,
    ) -> tuple[Path, Path]:
        final_dir = self._safe_target(f"{run_id}/final")
        final_dir.mkdir(parents=True, exist_ok=True)
        export_path = final_dir / "export_bundle.json"
        export_path.write_text(_dump(export_bundle), encoding="utf-8")
        prov_path = final_dir / "provenance.json"
        prov_path.write_text(_dump(provenance), encoding="utf-8")
        return export_path, prov_path

    def list_candidates(self, run_id: str) -> list[str]:
        cands = self.run_dir(run_id) / "candidates"
        if not cands.exists():
            return []
        return sorted(p.name for p in cands.iterdir() if p.is_dir())

    def write_raw(self, relative_path: str, data: str | bytes) -> Path:
        target = self._safe_target(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            target.write_bytes(data)
        else:
            target.write_text(data, encoding="utf-8")
        return target

    def write_json(self, relative_path: str, obj: Any) -> Path:
        return self.write_raw(relative_path, json.dumps(obj, indent=2, default=str))

    def write_error(self, run_id: str, error: RuntimeErrorRecord) -> Path:
        errors_dir = self._safe_target(f"{run_id}/errors")
        errors_dir.mkdir(parents=True, exist_ok=True)
        path = self._safe_target(f"{run_id}/errors/{error.error_id}.json")
        path.write_text(_dump(error), encoding="utf-8")
        return path

    def _safe_target(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ValueError(f"relative_path must not be absolute: {relative_path!r}")
        root_resolved = self.root.resolve()
        target = (self.root / candidate).resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError(f"relative_path escapes archive root: {relative_path!r}") from exc
        return target
