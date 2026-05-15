"""Runnable demo: one configurable VIGOR agent across photo + video + CAD.

Exposes safe-by-default factories so the adapters can be wired in via
``AgentConfig`` without enabling subprocess execution. The Manim
adapter is the only one that needs special handling: it refuses to
execute scene code in-process unless a ``Runner`` is injected, so we
inject a deterministic fake that synthesizes an MP4 placeholder.
"""

from __future__ import annotations

from agent_demo.factories import (
    make_cad_adapter,
    make_demo_echo_backend,
    make_manim_adapter,
    make_photo_adapter,
)

__all__ = [
    "make_cad_adapter",
    "make_demo_echo_backend",
    "make_manim_adapter",
    "make_photo_adapter",
]
