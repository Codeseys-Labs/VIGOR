# ADR-0015: Open Plugin Spec v1 Compatibility for VIGOR Adapters

Status: Accepted

Date: 2026-05-01

## Context

A cross-vendor plugin standard has emerged in 2026: **Open Plugin
Specification v1.0.0** (vercel-labs/open-plugin-spec) declares
``.plugin/plugin.json`` as a manifest carrying skills (Anthropic's
SKILL.md format) and MCP servers as required components, plus optional
commands, agents, rules, hooks, LSP servers, and output styles.
Anthropic's Agent Skills format is itself becoming a de facto standard
adopted by 32+ tools (Gemini CLI, JetBrains Junie, Sourcegraph Amp,
Block Goose, Mistral, Spring AI, etc.).

A natural question is whether VIGOR should pivot — replace its bespoke
`DomainAdapter` contract with plugins and run on a host agent (Claude
Agent SDK, Strands, Hermes, PI). It should not. Plugins extend an
interactive chat/coding agent with declarative tools and skills; VIGOR
adapters own a typed runtime contract (IR schema, deterministic
compile, validators, exports, patch ops) that the orchestrator drives
in a closed iterative loop. Replacing adapters with plugins would lose
the verifiable loop, which is VIGOR's value-add.

But the package layout cost of dual-publishing is small.

## Decision

VIGOR adapter packages are simultaneously published as Python packages
implementing `DomainAdapter` AND Open Plugin Spec v1 plugins.

Each adapter package now ships:

1. ``.plugin/plugin.json`` — Open Plugin Spec v1 manifest declaring
   the adapter's name, version, and skill paths.
2. ``skills/<skill-name>/SKILL.md`` — host-agent skill generated from
   the adapter's registered IR JSON Schema via
   ``vigor_core.plugin.export_skill_md``.
3. (Future) ``.mcp.json`` — MCP server config exposing the adapter's
   compile/render/review/export tools so non-Python hosts can drive
   them. Deferred to a follow-up; the manifest field is left unset
   in v1.

`vigor-core` adds `vigor_core.plugin` with:

- `OpenPluginManifest` — Pydantic model for the v1 manifest core.
- `export_plugin_json` — serialise the manifest to JSON bytes.
- `export_skill_md` — render SKILL.md from a registered IR schema.

`scripts/regen_skills.py` regenerates every adapter's SKILL.md from
its `register_ir` JSON Schema; a CI diff guards against drift between
the typed VIGOR contract and the host-agent skill.

Each adapter's IR module now calls `register_ir(...)` at import time
(matching the registry pattern from ADR-0011) so the JSON Schema is
discoverable without importing the adapter class.

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| Pivot VIGOR to Claude Agent SDK + plugins (no orchestrator) | Loses verifiable iterative loop; couples VIGOR to one vendor's runtime; effectively retires the project's value-add. |
| Use Anthropic's `.claude-plugin/plugin.json` only | Locks adapters to Claude Code; rejects cross-vendor distribution. |
| Ship both `.plugin/` and `.claude-plugin/` manifests | Defer; the Open Plugin spec explicitly allows hosts to also recognise vendor paths, so we can add them later without breaking changes. |
| Hand-write SKILL.md per adapter | Drifts from the typed IR schema; no enforcement. Generating from the registry keeps the contract authoritative. |
| Encode adapter compile/render as Open Plugin "hooks" | Hooks are intended for event-driven side effects, not the deterministic compile/validate/export contract VIGOR depends on. |

## Consequences

Positive:

1. The same VIGOR adapter package now drops cleanly into Claude Code,
   Hermes, Strands, Goose, Gemini CLI, etc. as a discoverable plugin.
2. SKILL.md is generated from the typed IR schema, so host-agent
   instructions cannot drift from the contract.
3. No changes to the orchestrator, the loop, or existing adapter
   Python code — adapters keep working unchanged.

Negative:

1. Adapters now have an additional publication surface (the manifest
   and skills directory) that maintainers must regenerate when IR
   schemas change. The CI diff guard makes this a forcing function,
   not a maintenance burden.
2. v1 doesn't yet ship `.mcp.json`; non-Python plugin hosts can read
   the SKILL.md but can't yet invoke compile/render. Follow-up work
   adds that surface.

## Citations

| Source | URL |
| --- | --- |
| Open Plugin Specification v1.0.0 | https://github.com/vercel-labs/open-plugin-spec |
| Anthropic Agent Skills | https://docs.claude.com/en/docs/agent-sdk/agent-skills |
| Claude Code plugins | https://code.claude.com/docs/en/plugins-reference |
| ADR-0003 | docs/adr/0003-separate-adapters-from-orchestration.md |
| ADR-0007 | docs/adr/0007-sdk-agnostic-core-with-optional-agent-backends.md |
| ADR-0011 | docs/adr/0011-ir-schema-versioning.md |
| ADR-0014 | docs/adr/0014-generalized-agent-config.md |
