"""Tests for the standalone Manim adapter."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError
from vigor_adapter_video_manim import ManimRenderConfig, ManimSceneIRV1, ManimVideoAdapter
from vigor_adapter_video_manim.renderer import render_manim_scene
from vigor_core.archive import RunArchive
from vigor_core.schemas import Budgets, TaskSpec
from vigor_runtime.backends import EchoAgentBackend
from vigor_runtime.orchestrator import Orchestrator


def _fake_runner_success(
    cmd: list[str],
    *,
    cwd: str,
    text: bool,
    capture_output: bool,
    timeout: int,
    check: bool,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    media_dir = Path(cmd[cmd.index("--media_dir") + 1])
    scene_file = Path(cmd[-2])
    scene_name = cmd[-1]
    quality = "720p30" if "-qm" in cmd else "480p15"
    output = media_dir / "videos" / scene_file.stem / quality / f"{scene_name}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"fake mp4")
    return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")


def test_renderer_builds_expected_output(tmp_path: Path) -> None:
    scene_file = tmp_path / "scene.py"
    scene_file.write_text("from manim import *\n", encoding="utf-8")
    media_dir = tmp_path / "media"
    output = render_manim_scene(
        scene_file,
        "VigorScene",
        media_dir,
        config=ManimRenderConfig(manim_exe="manim"),
        runner=_fake_runner_success,
    )
    assert output.exists()
    assert output == media_dir / "videos" / "scene" / "480p15" / "VigorScene.mp4"


def test_renderer_finds_non_default_quality_output(tmp_path: Path) -> None:
    scene_file = tmp_path / "scene.py"
    scene_file.write_text("from manim import *\n", encoding="utf-8")
    media_dir = tmp_path / "media"
    output = render_manim_scene(
        scene_file,
        "VigorScene",
        media_dir,
        config=ManimRenderConfig(manim_exe="manim", quality_flag="-qm"),
        runner=_fake_runner_success,
    )
    assert output == media_dir / "videos" / "scene" / "720p30" / "VigorScene.mp4"


def test_real_runner_requires_explicit_unsafe_opt_in(tmp_path: Path) -> None:
    scene_file = tmp_path / "scene.py"
    scene_file.write_text("from manim import *\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="untrusted Python"):
        render_manim_scene(
            scene_file,
            "VigorScene",
            tmp_path / "media",
            config=ManimRenderConfig(manim_exe="manim"),
        )


def _seed_scene(_request):
    scene = ManimSceneIRV1(
        title="Demo",
        scene_name="VigorScene",
        prompt="show hello",
        python_code=(
            "from manim import *\n\n"
            "class VigorScene(Scene):\n"
            "    def construct(self):\n"
            "        self.add(Text('Hello VIGOR'))\n"
        ),
    )
    return scene.model_dump(by_alias=True, mode="json")


@pytest.mark.asyncio
async def test_manim_adapter_end_to_end_with_fake_runner(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    adapter = ManimVideoAdapter(
        render_config=ManimRenderConfig(manim_exe="manim"),
        runner=_fake_runner_success,
    )
    backend = EchoAgentBackend(seed_ir_factory=_seed_scene)
    orchestrator = Orchestrator(adapter=adapter, backend=backend, archive=archive)
    task = TaskSpec(
        task_id="video_demo",
        goal="make a Manim hello scene",
        modalities=["video", "manim_scene"],
        budgets=Budgets(max_iterations=1, max_candidates=1),
    )
    result = await orchestrator.run(task)
    assert result.accepted is True
    assert (archive.run_dir("video_demo") / "final" / "export_bundle.json").exists()
    assert (archive.run_dir("video_demo") / "candidates").exists()


def test_invalid_scene_name_rejected() -> None:
    with pytest.raises(ValidationError):
        ManimSceneIRV1(title="bad", scene_name="123bad", python_code="")
