"""Regenerate every adapter's SKILL.md from its registered IR schema.

Run as ``uv run python scripts/regen_skills.py``. Diffing the result
against the committed files in CI guards against drift between the
typed VIGOR contract and the host-agent skill (see ADR-0015).
"""

from __future__ import annotations

from pathlib import Path

# Importing the IR modules registers their schemas via `register_ir`.
import vigor_adapter_cad.ir  # noqa: F401
import vigor_adapter_photo.recipe  # noqa: F401
import vigor_adapter_video_manim.scene_ir  # noqa: F401
from vigor_core.plugin import SkillTemplate, export_skill_md

REPO_ROOT = Path(__file__).resolve().parent.parent

ADAPTERS: list[tuple[str, str, str, str]] = [
    (
        "vigor-adapter-photo",
        "photo-edit-recipe",
        "photo_edit_recipe.v1",
        "Photo editing recipe IR (global tone/color + heuristic local masks).",
    ),
    (
        "vigor-adapter-cad",
        "cad-parametric",
        "cad_parametric.v1",
        "Parametric CAD IR for OpenSCAD generation (bracket plates with mounting holes and ribs).",
    ),
    (
        "vigor-adapter-video-manim",
        "manim-scene",
        "manim_scene.v1",
        "Manim scene IR carrying scene title, scene class name, Python source, optional duration.",
    ),
]


def main() -> None:
    for pkg, skill_name, ir_version, description in ADAPTERS:
        template = SkillTemplate(
            skill_name=skill_name,
            description=description,
            ir_schema_version=ir_version,
        )
        text = export_skill_md(template)
        path = REPO_ROOT / "packages" / pkg / "skills" / skill_name / "SKILL.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(REPO_ROOT)}")


if __name__ == "__main__":
    main()
