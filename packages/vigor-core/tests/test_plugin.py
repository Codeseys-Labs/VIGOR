"""Tests for the Open Plugin Spec helpers."""

from __future__ import annotations

import json
from typing import Literal

import pytest
from pydantic import BaseModel, Field, ValidationError
from vigor_core.plugin import (
    OpenPluginManifest,
    SkillTemplate,
    export_plugin_json,
    export_skill_md,
)
from vigor_core.registry import register_ir


class _DemoIRV1(BaseModel):
    schema_version: Literal["demo.ir.v1"] = "demo.ir.v1"
    title: str = Field(min_length=1)
    payload: dict[str, str] = Field(default_factory=dict)


# Register once at import time so subsequent tests see the model.
register_ir(_DemoIRV1)


def test_manifest_minimal_only_requires_name() -> None:
    manifest = OpenPluginManifest(name="vigor-adapter-demo")
    assert manifest.name == "vigor-adapter-demo"


def test_manifest_rejects_invalid_name() -> None:
    with pytest.raises(ValidationError):
        OpenPluginManifest(name="UPPERCASE")
    with pytest.raises(ValidationError):
        OpenPluginManifest(name="")


def test_manifest_export_uses_camelcase_paths() -> None:
    manifest = OpenPluginManifest(
        name="vigor-adapter-demo",
        version="0.1.0",
        skills="./skills/",
        mcp_servers="./.mcp.json",
    )
    payload = json.loads(export_plugin_json(manifest))
    assert payload["name"] == "vigor-adapter-demo"
    assert payload["skills"] == "./skills/"
    assert payload["mcpServers"] == "./.mcp.json"
    assert "description" not in payload  # exclude_none


def test_export_skill_md_includes_schema_version_and_json_schema() -> None:
    template = SkillTemplate(
        skill_name="demo-ir",
        description="Demonstration IR for the plugin export helper.",
        ir_schema_version="demo.ir.v1",
    )
    text = export_skill_md(template)
    assert text.startswith("---\n")
    assert "name: demo-ir" in text
    assert "demo.ir.v1" in text
    assert '"title": "_DemoIRV1"' in text or '"_DemoIRV1"' in text
    assert "## How to use" in text


def test_export_skill_md_appends_extra_sections() -> None:
    template = SkillTemplate(
        skill_name="demo-ir",
        description="d",
        ir_schema_version="demo.ir.v1",
        extra_sections=[("Reviewers", "Use the histogram critic.")],
    )
    text = export_skill_md(template)
    assert "## Reviewers" in text
    assert "histogram critic" in text


def test_export_skill_md_unknown_schema_raises() -> None:
    template = SkillTemplate(
        skill_name="x",
        description="x",
        ir_schema_version="not.registered.v1",
    )
    with pytest.raises(KeyError):
        export_skill_md(template)


def test_manifest_allows_unknown_keys_for_forward_compat() -> None:
    """Open Plugin Spec evolves; unknown keys should be preserved, not rejected."""

    payload = {
        "name": "vigor-adapter-demo",
        "version": "0.1.0",
        "futureCustomKey": {"some": "value"},
        "anotherUnknown": ["a", "b"],
    }
    manifest = OpenPluginManifest.model_validate(payload)
    assert manifest.name == "vigor-adapter-demo"
    # Pydantic exposes unknown keys via model_extra
    assert manifest.model_extra is not None
    assert manifest.model_extra.get("futureCustomKey") == {"some": "value"}
    assert manifest.model_extra.get("anotherUnknown") == ["a", "b"]
