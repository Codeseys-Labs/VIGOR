"""Photo adapter tests (recipe schema, renderer, histogram critic, XMP, adapter)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image
from vigor_adapter_photo import (
    HistogramCritic,
    PhotoEditingAdapter,
    PhotoEditRecipeV1,
    PhotoGlobalAdjustments,
    PhotoLocalAdjustment,
    recipe_to_xmp,
)
from vigor_adapter_photo.masks import radial_gradient, save_mask_png
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


def test_renderer_applies_local_mask(tmp_path: Path) -> None:
    input_path = _synth_image(tmp_path / "input.jpg")
    mask_path = tmp_path / "mask.png"
    save_mask_png(radial_gradient(64, 64), mask_path)
    recipe = PhotoEditRecipeV1(
        intent="local lift",
        local_adjustments=[
            PhotoLocalAdjustment(
                target="subject",
                mask_type="radial_gradient",
                mask_uri="mask.png",
                adjustments={"exposure": 0.5},
            )
        ],
    )
    out_path = tmp_path / "preview.jpg"
    baseline = np.asarray(Image.open(input_path).convert("RGB"), dtype=np.float32).mean()
    render_preview(input_path, recipe, out_path, mask_base_dir=tmp_path)
    rendered = np.asarray(Image.open(out_path).convert("RGB"), dtype=np.float32).mean()
    assert out_path.exists()
    assert rendered > baseline


def test_renderer_rejects_absolute_mask_uri(tmp_path: Path) -> None:
    input_path = _synth_image(tmp_path / "input.jpg")
    recipe = PhotoEditRecipeV1(
        intent="bad mask",
        local_adjustments=[
            PhotoLocalAdjustment(
                target="subject",
                mask_type="radial_gradient",
                mask_uri=str(tmp_path / "mask.png"),
                adjustments={"exposure": 0.5},
            )
        ],
    )
    with pytest.raises(ValueError, match="absolute mask"):
        render_preview(input_path, recipe, tmp_path / "preview.jpg", mask_base_dir=tmp_path)


def test_histogram_critic_accepts_balanced_image(tmp_path: Path) -> None:
    path = tmp_path / "gray.jpg"
    Image.new("RGB", (32, 32), color=(128, 128, 128)).save(path, quality=90)
    critic = HistogramCritic()
    report = critic.review(path, "cand_1", "art_1")
    assert report.reviewer_id == "photo.histogram.v1"
    assert report.passed is True
    assert not report.findings


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


def _global(**overrides: Any) -> PhotoGlobalAdjustments:
    data = {
        "exposure": 0.1,
        "contrast": 8,
        "highlights": -20,
        "shadows": 10,
        "whites": 0,
        "blacks": 0,
        "temperature": 4,
        "tint": 0,
        "vibrance": 0,
        "saturation": 0,
        "clarity": 0,
        "dehaze": 0,
        "sharpening": 0,
        "noise_reduction_color": 0,
    }
    data.update(overrides)
    return PhotoGlobalAdjustments.model_validate(data)


def _seed_recipe(_request) -> dict[str, Any]:
    recipe = PhotoEditRecipeV1(
        intent="warm cinematic, natural greens",
        global_adjustments=_global(),
        local_adjustments=[
            PhotoLocalAdjustment(
                target="sky",
                mask_type="sky_heuristic",
                adjustments={"highlights": -10, "temperature": 4},
            ),
            PhotoLocalAdjustment(
                target="foreground",
                mask_type="foreground_gradient",
                adjustments={"shadows": 10},
            ),
        ],
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
        target_outputs=["preview.jpg", "recipe.json", "lightroom.xmp", "masks/*.png"],
    )
    result = await orchestrator.run(task)

    assert result.accepted is True

    final_dir = archive.run_dir("photo_demo") / "final"
    assert (final_dir / "export_bundle.json").exists()
    assert (final_dir / "provenance.json").exists()

    candidate_root = archive.run_dir("photo_demo") / "candidates"
    previews = [
        candidate_dir / "artifacts" / "preview.jpg" for candidate_dir in candidate_root.iterdir()
    ]
    assert any(path.exists() for path in previews)
    assert any(
        list((candidate_dir / "artifacts" / "masks").glob("*.png"))
        for candidate_dir in candidate_root.iterdir()
    )

    bundle_json = json.loads((final_dir / "export_bundle.json").read_text())
    assert result.export_bundle is not None
    entry_types = {e["type"] for e in bundle_json["exports"]}
    assert {"final_artifact", "canonical_ir", "lightroom_xmp", "mask_png"} <= entry_types

    for entry in bundle_json["exports"]:
        uri_path = runs_dir / entry["uri"]
        assert uri_path.exists(), f"missing export file: {entry['uri']}"

    recipe_json = json.loads((final_dir / "exports" / "recipe.json").read_text())
    assert recipe_json["localAdjustments"][0]["maskUri"]
    assert recipe_json["localAdjustments"][0]["maskSha256"]
