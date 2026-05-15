"""Open Plugin Specification v1 helpers.

The Open Plugin Specification (vercel-labs/open-plugin-spec) defines
``.plugin/plugin.json`` as a cross-vendor manifest declaring a plugin's
skills (SKILL.md format), MCP servers, and other extension types.
VIGOR adapter packages can ship this manifest in addition to their
Python `DomainAdapter` so the same package also works as a plugin in
Claude Code, Hermes, Strands, etc.

Helpers in this module:

- ``OpenPluginManifest``: a Pydantic model for the v1 manifest core.
- ``export_plugin_json``: dump a manifest to JSON bytes.
- ``export_skill_md``: render a SKILL.md for a registered IR schema,
  generated from the JSON Schema so the host-agent skill never drifts
  from the typed VIGOR contract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ConfigDict, Field

from vigor_core.registry import export_json_schema, get_ir_model
from vigor_core.schemas import _VigorBase


class OpenPluginManifest(_VigorBase):
    """Open Plugin Spec v1 manifest core fields.

    Per the spec, only ``name`` is required. Extended component types
    (commands, agents, rules, hooks, lspServers, outputStyles) are
    declared explicitly so they round-trip with their camelCase aliases.

    Open Plugin Spec is a living, multi-vendor spec — vendors add new
    component types between releases. The model overrides
    ``extra="allow"`` so unknown manifest keys are preserved instead
    of rejected, keeping VIGOR forward-compatible with future spec
    revisions without code changes.
    """

    model_config = ConfigDict(
        strict=True,
        extra="allow",
        populate_by_name=True,
        alias_generator=_VigorBase.model_config["alias_generator"],
        from_attributes=False,
        frozen=False,
    )

    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9.\-]*$")
    version: str | None = None
    description: str | None = None
    author: str | dict[str, Any] | None = None
    homepage: str | None = None
    repository: str | dict[str, Any] | None = None
    license: str | None = None
    keywords: list[str] = Field(default_factory=list)
    skills: str | list[str] | dict[str, Any] | None = None
    mcp_servers: str | list[str] | dict[str, Any] | None = None
    commands: str | list[str] | dict[str, Any] | None = None
    agents: str | list[str] | dict[str, Any] | None = None
    rules: str | list[str] | dict[str, Any] | None = None
    hooks: str | list[str] | dict[str, Any] | None = None
    lsp_servers: str | list[str] | dict[str, Any] | None = None
    output_styles: str | list[str] | dict[str, Any] | None = None


def export_plugin_json(manifest: OpenPluginManifest, *, indent: int = 2) -> str:
    """Serialise a manifest to JSON suitable for ``.plugin/plugin.json``."""

    return manifest.model_dump_json(by_alias=True, indent=indent, exclude_none=True)


@dataclass(slots=True)
class SkillTemplate:
    """Inputs for a generated SKILL.md."""

    skill_name: str
    description: str
    ir_schema_version: str
    extra_sections: list[tuple[str, str]] | None = None


def export_skill_md(template: SkillTemplate) -> str:
    """Render a SKILL.md whose body is derived from the registered IR schema.

    The skill body advertises:

    - The IR's ``schema_version`` so a host agent knows which contract to use.
    - The full JSON Schema (pretty-printed) so the agent can validate
      its outputs without reading VIGOR source.
    - A short usage note pointing at `validate_ir`/`compile`/`export`.

    Re-running this in CI and diffing against the committed file is the
    drift guard called for in the rollout plan.
    """

    schema = export_json_schema(template.ir_schema_version)
    schema_pretty = json.dumps(schema, indent=2, sort_keys=True)
    model = get_ir_model(template.ir_schema_version)
    title = template.skill_name
    description = template.description.replace("\n", " ").strip()

    sections: list[str] = []
    sections.append(f"---\nname: {title}\ndescription: {description}\n---\n")
    sections.append(f"# {title}\n")
    sections.append(template.description.strip() + "\n")
    sections.append("## IR contract\n")
    sections.append(
        f"This adapter consumes the `{template.ir_schema_version}` "
        f"intermediate representation, modeled by `{model.__name__}`.\n"
    )
    sections.append("### JSON Schema\n")
    sections.append("```json\n" + schema_pretty + "\n```\n")
    sections.append("## How to use\n")
    sections.append(
        "1. Produce a JSON object that validates against the schema above.\n"
        "2. Hand it to the adapter's `validate_ir` then `compile`; the "
        "deterministic output is what the VIGOR loop reviews and exports.\n"
        "3. Patches must round-trip: `apply_patch` must produce IR that "
        "still validates.\n"
    )
    if template.extra_sections:
        for heading, body in template.extra_sections:
            sections.append(f"## {heading}\n")
            sections.append(body.rstrip() + "\n")
    return "\n".join(sections)
