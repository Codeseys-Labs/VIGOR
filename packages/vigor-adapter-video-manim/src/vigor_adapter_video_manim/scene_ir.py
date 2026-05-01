"""Manim scene IR."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from vigor_core.registry import register_ir


class ManimSceneIRV1(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        populate_by_name=True,
        alias_generator=to_camel,
    )

    schema_version: Literal["manim_scene.v1"] = "manim_scene.v1"
    kind: Literal["manim_scene"] = "manim_scene"
    title: str
    scene_name: str = Field("VigorScene", pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    python_code: str
    prompt: str | None = None
    duration_s: float | None = Field(default=None, gt=0)


register_ir(ManimSceneIRV1)
