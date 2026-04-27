"""Standalone Manim video adapter."""

from vigor_adapter_video_manim.adapter import ManimVideoAdapter
from vigor_adapter_video_manim.renderer import (
    ManimRenderConfig,
    expected_output_path,
    render_manim_scene,
)
from vigor_adapter_video_manim.scene_ir import ManimSceneIRV1

__all__ = [
    "ManimRenderConfig",
    "ManimSceneIRV1",
    "ManimVideoAdapter",
    "expected_output_path",
    "render_manim_scene",
]
__version__ = "0.1.0"
