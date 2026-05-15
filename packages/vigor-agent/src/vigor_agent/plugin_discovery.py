"""Open Plugin Spec v1 discovery for `vigor-agent`.

Lets users point an `AgentConfig` adapter at a plugin directory
(``.plugin/plugin.json``) and have the agent register its skills and
declared MCP servers. Implementing this in Phase 7 of the rollout makes
non-Python adapters (e.g. third-party MCP-only plugins) loadable.

The `DomainAdapter` Python contract still gates the loop. A plugin
without a Python factory can carry skills and MCP servers but cannot
drive `compile`/`apply_patch` deterministically — `vigor-agent` will
warn rather than register a partial adapter. v1 only loads plugins
that ALSO supply a Python factory ref via ``plugin_factory.json``
(see :func:`load_plugin_directory`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from vigor_core.agent_config import (
    AdapterSpec,
    FactoryRef,
    assert_factory_ref_allowed,
)
from vigor_core.plugin import OpenPluginManifest


class PluginDiscoveryError(RuntimeError):
    """Raised when an Open Plugin directory is malformed or incompatible."""


@dataclass(slots=True)
class DiscoveredPlugin:
    """Result of inspecting an Open Plugin directory."""

    root: Path
    manifest: OpenPluginManifest
    factory: FactoryRef | None
    skills_dir: Path | None
    mcp_servers_path: Path | None


def load_plugin_directory(path: str | Path) -> DiscoveredPlugin:
    """Inspect a directory containing ``.plugin/plugin.json``.

    Returns the parsed manifest plus resolved on-disk paths for
    optional skills and MCP servers. If the directory also contains
    ``.plugin/vigor.json`` declaring a `FactoryRef`, that's used as
    the Python entry point for the VIGOR loop.
    """

    root = Path(path).resolve()
    manifest_path = root / ".plugin" / "plugin.json"
    if not manifest_path.exists():
        raise PluginDiscoveryError(f"plugin directory {root} is missing .plugin/plugin.json")
    manifest = OpenPluginManifest.model_validate(
        json.loads(manifest_path.read_text(encoding="utf-8"))
    )

    skills_dir = _resolve_optional_path(root, manifest.skills, default="skills")
    mcp_servers_path = _resolve_optional_path(root, manifest.mcp_servers, default=".mcp.json")

    factory: FactoryRef | None = None
    vigor_extra = root / ".plugin" / "vigor.json"
    if vigor_extra.exists():
        payload = json.loads(vigor_extra.read_text(encoding="utf-8"))
        factory = FactoryRef.model_validate(payload)

    resolved_skills = skills_dir if skills_dir and skills_dir.exists() else None
    resolved_mcp = mcp_servers_path if mcp_servers_path and mcp_servers_path.exists() else None
    return DiscoveredPlugin(
        root=root,
        manifest=manifest,
        factory=factory,
        skills_dir=resolved_skills,
        mcp_servers_path=resolved_mcp,
    )


def adapter_spec_from_plugin(
    plugin: DiscoveredPlugin,
    *,
    adapter_id: str,
    modalities: list[str] | None = None,
    domains: list[str] | None = None,
    host_allowed_prefixes: list[str] | tuple[str, ...] | None = None,
) -> AdapterSpec:
    """Build an `AdapterSpec` from a discovered plugin's Python factory.

    Raises if the plugin doesn't include a `FactoryRef` (i.e. has
    skills/MCP only). Such plugins can still be useful as ambient tool
    sources, but they can't drive the VIGOR loop on their own.

    ``host_allowed_prefixes`` is the host's allowlist for plugin-supplied
    namespaces. If supplied, every prefix declared inside the plugin's
    own ``.plugin/vigor.json`` must be contained in (or equal to) one
    of these — preventing a plugin from self-authorising into arbitrary
    namespaces. ``None`` keeps the legacy behavior (no host gate); the
    caller is then responsible for trusting the plugin's declarations.
    """

    if plugin.factory is None:
        raise PluginDiscoveryError(
            f"plugin at {plugin.root} has no .plugin/vigor.json with a Python "
            "FactoryRef; v1 vigor-agent cannot drive the VIGOR loop without one"
        )
    if host_allowed_prefixes is not None:
        try:
            assert_factory_ref_allowed(plugin.factory, host_allowed_prefixes)
        except ValueError as exc:
            raise PluginDiscoveryError(str(exc)) from exc
    return AdapterSpec(
        adapter_id=adapter_id,
        factory=plugin.factory,
        modalities=modalities or [],
        domains=domains or [],
    )


def _resolve_optional_path(
    root: Path,
    field: str | list[str] | dict[str, object] | None,
    *,
    default: str,
) -> Path | None:
    if field is None:
        return root / default
    if isinstance(field, str):
        return (root / field).resolve()
    if isinstance(field, list) and field:
        first = field[0]
        if isinstance(first, str):
            return (root / first).resolve()
    if isinstance(field, dict):
        paths = field.get("paths")
        if isinstance(paths, list) and paths and isinstance(paths[0], str):
            return (root / paths[0]).resolve()
    return None
