"""Adapter / backend factories for the agent-demo example.

Each factory is referenced by ``examples/agent-demo/agent.yaml`` via a
``FactoryRef`` whose ``allowed_prefixes`` list this package's namespace.
That keeps the demo within the same allowlist gate the production agent
uses without sneaking the adapters into ``vigor_runtime``.

The Manim renderer normally shells out to the ``manim`` CLI, which is
not available in the demo / CI environment. We inject a fake
``Runner`` that writes a placeholder MP4 to the path the adapter
expects, so the *adapter* code path runs unchanged but no untrusted
Python is ever executed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from vigor_adapter_cad.adapter import CadOpenScadAdapter
from vigor_adapter_photo.adapter import PhotoEditingAdapter
from vigor_adapter_video_manim.adapter import ManimVideoAdapter
from vigor_adapter_video_manim.renderer import (
    ManimRenderConfig,
    Runner,
    expected_output_path,
)
from vigor_core.interfaces import GenerationRequest
from vigor_runtime.backends import EchoAgentBackend


def make_photo_adapter() -> PhotoEditingAdapter:
    """No-arg photo adapter factory used by ``agent.yaml``."""

    return PhotoEditingAdapter()


def make_cad_adapter() -> CadOpenScadAdapter:
    """No-arg CAD adapter factory used by ``agent.yaml``."""

    return CadOpenScadAdapter()


def _fake_manim_runner() -> Runner:
    """Returns a ``Runner`` that emulates a successful Manim render.

    Manim's CLI writes the output to a quality-suffixed directory under
    ``--media_dir``. The fake reproduces that path so the adapter's
    post-render lookup succeeds without launching any subprocess.
    """

    def runner(
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
        # cmd shape (build_command): exe, --media_dir, MEDIA, --format, FMT,
        # QUALITY_FLAG, --progress_bar, none, SCENE_FILE, SCENE_NAME
        scene_file = Path(cmd[-2])
        scene_name = cmd[-1]
        quality_flag = cmd[5]
        out = expected_output_path(scene_file, scene_name, media_dir, quality_flag)
        out.parent.mkdir(parents=True, exist_ok=True)
        # 32-byte placeholder big enough to digest cleanly.
        out.write_bytes(b"\x00FAKE_MP4_PLACEHOLDER_FOR_DEMO\x00\x00\x00")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    return runner


def make_manim_adapter() -> ManimVideoAdapter:
    """Manim adapter wired to a deterministic fake runner.

    Refuses to delegate to the real Manim CLI: that path needs
    ``allow_unsafe_execution=True``, which we deliberately leave off so
    the demo works on any machine with no Manim install.
    """

    return ManimVideoAdapter(
        render_config=ManimRenderConfig(
            manim_exe="/usr/bin/env",  # placeholder; the fake runner ignores it
            allow_unsafe_execution=False,
        ),
        runner=_fake_manim_runner(),
    )


def _seed_ir_for_modality(request: GenerationRequest) -> dict[str, object]:
    """Produce a per-modality seed IR the echo backend can return.

    The echo backend is deterministic: we look at the adapter-declared
    ``ir_type`` in the ``RepresentationPlan`` and synthesize a matching
    minimal IR body. That's enough to drive each adapter's
    compile/review path end-to-end with no real LLM calls.
    """

    ir_type = request.plan.ir_type
    goal = request.task.goal
    if ir_type == "photo_edit_recipe.v1":
        return {
            "schemaVersion": "photo_edit_recipe.v1",
            "kind": "photo_edit_recipe",
            "intent": goal or "demo recipe",
        }
    if ir_type == "manim_scene.v1":
        return {
            "schemaVersion": "manim_scene.v1",
            "kind": "manim_scene",
            "title": goal or "Demo Scene",
            "sceneName": "DemoScene",
            "pythonCode": (
                "from manim import Scene\n\n"
                "class DemoScene(Scene):\n"
                "    def construct(self):\n"
                "        pass\n"
            ),
        }
    if ir_type == "cad_parametric.v1":
        return {
            "schemaVersion": "cad_parametric.v1",
            "kind": "cad_parametric",
            "units": "mm",
            "intent": goal or "demo bracket",
            "partType": "bracket_plate",
        }
    return {"text": goal}


def make_demo_echo_backend() -> EchoAgentBackend:
    """Echo backend configured to seed each modality's IR shape."""

    return EchoAgentBackend(seed_ir_factory=_seed_ir_for_modality)
