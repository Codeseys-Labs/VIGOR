"""Photo adapter tests (recipe schema, renderer, histogram critic, XMP, adapter)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image
from vigor_adapter_photo import (
    HistogramCritic,
    PhotoEditingAdapter,
    PhotoEditRecipeV1,
    PhotoGlobalAdjustments,
    recipe_to_xmp,
)
from vigor_adapter_photo.renderer import render_preview
from vigor_core.archive import RunArchive
from vigor_core.schemas import ReferenceArtifact, TaskSpec
from vigor_runtime.backends import EchoAgentBackend
from vigor_runtime.orchestrator import Orchestrator


def _synth_image(path: Path, shape: tuple[int, int] = (64, 64)) -> Path:
    rng = np.random.default_rng(42)
    arr = (rng.random((*shape, 3)) * 255).astype(np.uint8)
    Image.fromarray(arr, mode="RGB").save(path, format="JPEG", quality=90)
    return path


def test_recipe_roundtrip() -> None:
    recipe = PhotoEditRecipeV1(
        intent="warm cinematic",
        global_adjustments=PhotoGlobalAdjustments(
            exposure=-0.1,
            contrast=18,
            highlights=-35,
            shadows=12,
            temperature=8,
            vibrance=-5,
            clarity=-8,
        ),
    )
    data = recipe.model_dump(by_alias=True, mode="json")
    rebuilt = PhotoEditRecipeV1.model_validate(data)
    assert rebuilt == recipe


def test_renderer_produces_jpeg(tmp_path: Path) -> None:
    input_path = _synth_image(tmp_path / "input.jpg")
    recipe = PhotoEditRecipeV1(intent="bright")
    out_path = tmp_path / "preview.jpg"
    img = render_preview(input_path, recipe, out_path)
    assert out_path.exists()
    assert img.size == (64, 64)


def test_histogram_critic_accepts_balanced_image(tmp_path: Path) -> None:
    input_path = _synth_image(tmp_path / "input.jpg")
    critic = HistogramCritic()
    report = critic.review(input_path, "cand_1", "art_1")
    assert report.reviewer_id == "photo.histogram.v1"
    assert 0.0 <= report.scores["quality"] <= 1.0


def test_histogram_critic_flags_clipped(tmp_path: Path) -> None:
    all_white = Image.new("RGB", (32, 32), color=(255, 255, 255))
    path = tmp_path / "white.jpg"
    all_white.save(path, quality=90)
    critic = HistogramCritic(highlights_tolerance=0.01)
    report = critic.review(path, "cand_white", "art_white")
    assert report.passed is False
    assert any(f.id == "highlights_clip" for f in report.findings)


def test_xmp_contains_process_version_and_required_attrs() -> None:
    recipe = PhotoEditRecipeV1(
        intent="warm cinematic",
        global_adjustments=PhotoGlobalAdjustments(
            exposure=0.35, contrast=15, highlights=-40, shadows=25, temperature=8
        ),
    )
    xmp = recipe_to_xmp(recipe)
    assert 'crs:ProcessVersion="11.0"' in xmp
    assert 'crs:HasSettings="True"' in xmp
    assert 'crs:WhiteBalance="Custom"' in xmp
    assert 'crs:Exposure2012="+0.35"' in xmp
    assert "ToneCurvePV2012" in xmp


def _seed_recipe(_request):
    recipe = PhotoEditRecipeV1(
        intent="warm cinematic, natural greens",
        global_adjustments=PhotoGlobalAdjustments(
            exposure=0.1,
            contrast=8,
            highlights=-20,
            shadows=10,
            whites=0,
            blacks=0,
            temperature=4,
            tint=0,
            vibrance=0,
            saturation=0,
            clarity=0,
            dehaze=0,
            sharpening=0,
            noise_reduction_color=0,
        ),
    )
    return recipe.model_dump(by_alias=True, mode="json")


@pytest.mark.asyncio
async def test_photo_adapter_end_to_end(tmp_path: Path) -> None:
    input_path = _synth_image(tmp_path / "input.jpg")
    runs_dir = tmp_path / "runs"
    archive = RunArchive(runs_dir)
    adapter = PhotoEditingAdapter()
    backend = EchoAgentBackend(seed_ir_factory=_seed_recipe)
    orchestrator = Orchestrator(adapter=adapter, backend=backend, archive=archive)

    task = TaskSpec(
        task_id="photo_demo",
        goal="Warm cinematic edit, protect highlights",
        modalities=["image", "photo_edit_recipe"],
        references=[
            ReferenceArtifact(
                artifact_id="input_001",
                uri=str(input_path),
                media_type="image/jpeg",
            )
        ],
        target_outputs=["preview.jpg", "recipe.json", "lightroom.xmp"],
    )
    result = await orchestrator.run(task)

    assert result.accepted is True

    final_dir = archive.run_dir("photo_demo") / "final"
    assert (final_dir / "export_bundle.json").exists()
    assert (final_dir / "provenance.json").exists()

    candidate_root = archive.run_dir("photo_demo") / "candidates"
    assert any(
        (candidate_dir / "artifacts" / "preview.jpg").exists()
        for candidate_dir in candidate_root.iterdir()
    )

    # Export bundle must reference files that actually exist on disk.
    bundle_json = json.loads((final_dir / "export_bundle.json").read_text())
    assert result.export_bundle is not None
    entry_types = {e["type"] for e in bundle_json["exports"]}
    assert {"final_artifact", "canonical_ir", "lightroom_xmp"} <= entry_types

    for entry in bundle_json["exports"]:
        # All referenced export URIs are relative to the archive root.
        uri_path = runs_dir / entry["uri"]
        assert uri_path.exists(), f"missing export file: {entry['uri']}"
