"""Subprocess renderer for Manim scenes.

Generated Manim scene files are Python code. The default real subprocess path
therefore refuses execution unless explicitly opted in via
``allow_unsafe_execution=True`` or a caller injects a sandboxed/fake runner.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import Protocol, cast


class Runner(Protocol):
    def __call__(
        self,
        cmd: list[str],
        *,
        cwd: str,
        text: bool,
        capture_output: bool,
        timeout: int,
        check: bool,
        env: dict[str, str],
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(slots=True)
class ManimRenderConfig:
    manim_exe: str | None = None
    quality_flag: str = "-ql"
    timeout_s: int = 120
    format: str = "mp4"
    allow_unsafe_execution: bool = False


_QUALITY_DIRS = {
    "-ql": "480p15",
    "-qm": "720p30",
    "-qh": "1080p60",
    "-qp": "1440p60",
    "-qk": "2160p60",
}


def expected_output_path(
    scene_file: Path,
    scene_name: str,
    media_dir: Path,
    quality_flag: str = "-ql",
) -> Path:
    quality_dir = _QUALITY_DIRS.get(quality_flag, "480p15")
    return media_dir / "videos" / scene_file.stem / quality_dir / f"{scene_name}.mp4"


def build_command(
    scene_file: Path,
    scene_name: str,
    media_dir: Path,
    config: ManimRenderConfig,
) -> list[str]:
    executable = config.manim_exe or which("manim")
    if executable is None:
        raise RuntimeError("Manim executable not found on PATH")
    return [
        executable,
        "--media_dir",
        str(media_dir),
        "--format",
        config.format,
        config.quality_flag,
        "--progress_bar",
        "none",
        str(scene_file),
        scene_name,
    ]


def render_manim_scene(
    scene_file: Path,
    scene_name: str,
    media_dir: Path,
    *,
    config: ManimRenderConfig | None = None,
    runner: Runner | None = None,
) -> Path:
    cfg = config or ManimRenderConfig()
    if runner is None and not cfg.allow_unsafe_execution:
        raise RuntimeError(
            "Manim renders execute untrusted Python scene code. Provide a sandboxed "
            "runner or set allow_unsafe_execution=True explicitly."
        )
    command_runner: Runner = runner if runner is not None else cast(Runner, subprocess.run)
    cmd = build_command(scene_file, scene_name, media_dir, cfg)
    result = command_runner(
        cmd,
        cwd=str(scene_file.parent),
        text=True,
        capture_output=True,
        timeout=cfg.timeout_s,
        check=False,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONUNBUFFERED": "1"},
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Manim failed with exit code {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    output = expected_output_path(scene_file, scene_name, media_dir, cfg.quality_flag)
    if output.exists():
        return output
    matches = sorted((media_dir / "videos" / scene_file.stem).glob(f"**/{scene_name}.mp4"))
    if matches:
        return matches[0]
    raise RuntimeError(f"Manim reported success but output not found under: {media_dir}")
