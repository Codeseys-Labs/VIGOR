"""Tests for Open Plugin Spec v1 discovery in vigor-agent."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from vigor_agent.plugin_discovery import (
    PluginDiscoveryError,
    adapter_spec_from_plugin,
    load_plugin_directory,
)


def _write_plugin(
    root: Path,
    *,
    manifest: dict[str, object],
    factory: dict[str, object] | None = None,
    skills_subdir: str | None = "skills/photo-edit-recipe",
) -> None:
    plugin_dir = root / ".plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    if factory is not None:
        (plugin_dir / "vigor.json").write_text(json.dumps(factory), encoding="utf-8")
    if skills_subdir is not None:
        skills_path = root / skills_subdir
        skills_path.mkdir(parents=True, exist_ok=True)
        (skills_path / "SKILL.md").write_text("# skill", encoding="utf-8")


def test_load_plugin_directory_resolves_paths(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        manifest={
            "name": "vigor-adapter-demo",
            "version": "0.1.0",
            "skills": "./skills/",
        },
    )
    plugin = load_plugin_directory(tmp_path)
    assert plugin.manifest.name == "vigor-adapter-demo"
    assert plugin.skills_dir is not None
    assert plugin.skills_dir.exists()
    assert plugin.factory is None


def test_load_plugin_directory_picks_up_vigor_factory(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        manifest={"name": "vigor-adapter-demo"},
        factory={
            "factory": "vigor_runtime.toy_adapter:ToyTextAdapter",
            "allowedPrefixes": ["vigor_runtime"],
        },
    )
    plugin = load_plugin_directory(tmp_path)
    assert plugin.factory is not None
    assert plugin.factory.factory == "vigor_runtime.toy_adapter:ToyTextAdapter"


def test_load_plugin_directory_missing_manifest_raises(tmp_path: Path) -> None:
    with pytest.raises(PluginDiscoveryError, match="missing"):
        load_plugin_directory(tmp_path)


def test_adapter_spec_from_plugin_requires_factory(tmp_path: Path) -> None:
    _write_plugin(tmp_path, manifest={"name": "vigor-adapter-demo"})
    plugin = load_plugin_directory(tmp_path)
    with pytest.raises(PluginDiscoveryError, match=r"vigor\.json"):
        adapter_spec_from_plugin(plugin, adapter_id="adapter_demo")


def test_adapter_spec_from_plugin_carries_modalities(tmp_path: Path) -> None:
    _write_plugin(
        tmp_path,
        manifest={"name": "vigor-adapter-demo"},
        factory={
            "factory": "vigor_runtime.toy_adapter:ToyTextAdapter",
            "allowedPrefixes": ["vigor_runtime"],
        },
    )
    plugin = load_plugin_directory(tmp_path)
    spec = adapter_spec_from_plugin(
        plugin,
        adapter_id="adapter_demo",
        modalities=["toy_text"],
    )
    assert spec.adapter_id == "adapter_demo"
    assert spec.modalities == ["toy_text"]
    assert spec.factory.factory == "vigor_runtime.toy_adapter:ToyTextAdapter"


def test_real_photo_adapter_plugin_directory(tmp_path: Path) -> None:
    """The shipped photo adapter package itself should be a discoverable plugin."""

    repo_root = Path(__file__).resolve().parents[3]
    photo_pkg = repo_root / "packages" / "vigor-adapter-photo"
    if not (photo_pkg / ".plugin" / "plugin.json").exists():
        pytest.skip("photo adapter not present in this checkout")
    plugin = load_plugin_directory(photo_pkg)
    assert plugin.manifest.name == "vigor-adapter-photo"
    assert plugin.skills_dir is not None
    assert (plugin.skills_dir / "photo-edit-recipe" / "SKILL.md").exists()
    assert plugin.factory is not None
    assert plugin.factory.factory == "vigor_adapter_photo.adapter:PhotoEditingAdapter"
