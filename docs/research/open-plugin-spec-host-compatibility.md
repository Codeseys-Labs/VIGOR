# Open Plugin Spec v1 Host Compatibility

Empirical research into how Open Plugin Specification (OPS) v1 plugins are
consumed by host environments in 2026, and a recommendation for VIGOR adapter
packaging. Feeds the upcoming ADR-0015 decision.

Date of research: 2026-05-14. All citations dated relative to that date. WebFetch and
the GitHub REST API were used to verify each source.

## Executive Summary

The Open Plugin Specification v1.0.0 was published on 2026-04-03 by Vercel
Labs at `vercel-labs/open-plugin-spec` and mandates a vendor-neutral manifest
at `.plugin/plugin.json` plus an optional vendor-prefixed sibling
(`.<tool>-plugin/plugin.json`). At the time of this audit, **zero shipping
hosts honor the vendor-neutral path** and only one (Claude Code) loads the
vendor-prefixed variant. The remaining seven hosts use proprietary,
filename-divergent schemes: `gemini-extension.json`, YAML-in-config-yaml
(Goose), per-skill `mcp.json` plus user `settings.json` (Amp), per-plugin
`manifest.json` or `plugin.yaml` (Hermes), `.cursor/mcp.json`,
`.continue/mcpServers/*.yaml`, decorator-only registration (Strands), and
in-IDE settings (Junie).

Because OPS v1 has effectively zero adoption today and an unmerged but
publicly-circulating PR (vercel-labs/open-plugin-spec#3, opened 2026-05-04)
proposes moving the manifest to root-level `plugin.json` and adding a
required `id` field, ratifying VIGOR's adapter packaging on the
vendor-neutral path is premature. The recommendation in §"Recommendation for
VIGOR" is to **dual-publish**: keep `.plugin/plugin.json` as the source of
truth and emit vendor-specific manifests (currently Claude Code,
Gemini CLI, and Hermes) from the same generator, gated behind a per-target
build step.

| Dimension | Finding |
| --- | --- |
| Hosts attempted | 8 of 8 — all evaluated. Hermes mapped to `NousResearch/hermes-agent`. |
| Hosts confirmed loading OPS v1 vendor-neutral path (`.plugin/plugin.json`) | 0 |
| Hosts honoring OPS v1 vendor-prefixed precedence (`.claude-plugin/plugin.json`) | 1 (Claude Code) |
| Hosts using independent, non-OPS manifest schemes | 7 |
| OPS v1 changes since 2026-05-01 | One open PR (#3) proposing a breaking manifest-path move and a new required `id` field. No merged changes. |

## Hosts to investigate (priority order)

The spec listed 8 hosts: Claude Code, Block Goose, Sourcegraph Amp, Hermes,
Goose, Strands, Gemini CLI, JetBrains Junie. **Block Goose collapses into
Goose** — see §"Goose / Block Goose disambiguation" below — so the eighth
slot is filled with **Cursor**, the largest-deployed agentic-host in 2026
that is not otherwise covered.

### Per-host load-status matrix

| # | Host | OPS v1 manifest support | Citation |
| --- | --- | --- | --- |
| 1 | Claude Code | Vendor-prefixed only — `.claude-plugin/plugin.json` | https://code.claude.com/docs/en/plugins |
| 2 | Goose (Block + AAIF) | None — global `~/.config/goose/config.yaml` registry | https://block.github.io/goose/docs/getting-started/using-extensions; https://github.com/block/goose/blob/main/crates/goose/src/config/extensions.rs |
| 3 | Sourcegraph Amp | None — `.amp/plugins/*.ts` + per-skill `mcp.json` | https://ampcode.com/manual |
| 4 | Hermes Agent (NousResearch) | None — per-plugin `manifest.json` or `plugin.yaml` | https://github.com/NousResearch/hermes-agent/tree/main/plugins |
| 5 | Strands Agents (AWS) | None — Python decorator registration only | https://github.com/strands-agents/sdk-python |
| 6 | Gemini CLI (Google) | None — `gemini-extension.json` | https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/reference.md |
| 7 | JetBrains Junie | None — IDE settings UI; no on-disk manifest | https://www.jetbrains.com/help/ai-assistant/mcp.html |
| 8 | Cursor *(substituted for Block Goose)* | None — `.cursor/mcp.json` only; no plugin manifest | https://cursor.com/docs/context/mcp |

### MCP declaration matrix

| Host | MCP declaration location | Cite |
| --- | --- | --- |
| Claude Code | `.mcp.json` at plugin root (loaded only when plugin is enabled) | https://code.claude.com/docs/en/plugins ("Plugin structure overview" table) |
| Goose | YAML map under `extensions:` key inside `~/.config/goose/config.yaml`; each entry has `cmd`, `args`, `type: stdio`, `enabled` | https://block.github.io/goose/docs/getting-started/using-extensions |
| Sourcegraph Amp | Per-skill `mcp.json` inside `.agents/skills/<name>/mcp.json`, OR `amp.mcpServers` key in `~/.config/amp/settings.json` | https://ampcode.com/manual |
| Hermes Agent | Per-plugin `plugin.yaml` (`provides_*` fields) plus repo-level `mcp_serve.py` and `model_tools.py` for runtime registration | https://github.com/NousResearch/hermes-agent/blob/main/plugins/web/exa/plugin.yaml; https://github.com/NousResearch/hermes-agent/blob/main/mcp_serve.py |
| Strands Agents | Programmatic — `MCPClient(lambda: stdio_client(StdioServerParameters(...)))` registered in Python at agent construction | https://github.com/strands-agents/sdk-python |
| Gemini CLI | `mcpServers` map inside `gemini-extension.json` at extension root, supports `${extensionPath}` placeholders; `~/.gemini/settings.json` overrides | https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/reference.md |
| JetBrains Junie / AI Assistant | IDE Settings UI under `Settings | Tools | AI Assistant | Model Context Protocol`; inline JSON; can import from Claude Desktop config | https://www.jetbrains.com/help/ai-assistant/mcp.html |
| Cursor | `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global); programmatic `vscode.cursor.mcp.registerServer()` | https://cursor.com/docs/context/mcp |

### Vendor manifest path matrix

| Host | Manifest filename(s) | Path conventions | Cite |
| --- | --- | --- | --- |
| Claude Code | `plugin.json` | `<plugin-root>/.claude-plugin/plugin.json`; component dirs (`skills/`, `commands/`, `agents/`, `hooks/`) live at the plugin root *not* inside `.claude-plugin/` | https://code.claude.com/docs/en/plugins |
| Goose | none | extension entries are inline in `~/.config/goose/config.yaml`; loader keys off `extensions` map; no per-extension manifest scan | https://github.com/block/goose/blob/main/crates/goose/src/config/extensions.rs |
| Sourcegraph Amp | none for plugins; `SKILL.md` for skills | `.amp/plugins/*.ts` (project), `~/.config/amp/plugins/*.ts` (user); skills under `.agents/skills/<name>/SKILL.md` | https://ampcode.com/manual |
| Hermes Agent | `manifest.json` (frontend dashboard plugins), `plugin.yaml` (backend kind plugins) | `<repo>/plugins/<plugin-name>/...` — no fixed metadata directory; loader inspects `kind` + provider declarations | https://github.com/NousResearch/hermes-agent/blob/main/plugins/example-dashboard/dashboard/manifest.json; https://github.com/NousResearch/hermes-agent/blob/main/plugins/web/exa/plugin.yaml |
| Strands Agents | none | tools registered programmatically; optional `./tools/` directory scan via `load_tools_from_directory=True`; no manifest filename | https://github.com/strands-agents/sdk-python |
| Gemini CLI | `gemini-extension.json` | `~/.gemini/extensions/<name>/gemini-extension.json`; `name` field MUST equal directory name | https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/reference.md |
| JetBrains Junie | none on disk | configuration is in IDE settings; only artifact in the public repo is `registry-{nightly,experimental,eap}.json` for installer use | https://github.com/JetBrains/junie |
| Cursor | none | only `mcp.json` (no plugin manifest concept beyond MCP integrations and Marketplace metadata) | https://cursor.com/docs/context/mcp |

## OPS v1 spec snapshot

### Source

`vercel-labs/open-plugin-spec`, single-file spec in `README.md`, default branch `main`. Repository created 2026-04-03; last merged commit `cd5f34e7` on 2026-04-03 ("Apply Gemini team feedback and final Oracle verification"). 23 stargazers as of 2026-05-14.

Cite: `gh api repos/vercel-labs/open-plugin-spec` returned `{"created_at":"2026-04-03T02:21:18Z","default_branch":"main","pushed_at":"2026-05-04T17:14:19Z","stargazers_count":23}`.

### Required manifest path

§4.1.2 of the spec: *"A plugin MUST include a manifest at `.plugin/plugin.json`."*

§5 (per WebFetch of the README) explicitly permits a vendor-prefixed override of the form `.<tool-name>-plugin/plugin.json`, which a matching host *MAY* prefer over the vendor-neutral path when both exist.

### Required fields

Only `name` is REQUIRED in the manifest body. All other top-level fields (`version`, `description`, `author`, `homepage`, `repository`, `license`, `keywords`, `skills`, `mcpServers`, `commands`, `agents`, `rules`, `hooks`, `lspServers`, `outputStyles`) are OPTIONAL. `name` is constrained to 1–64 characters, lowercase alphanumeric plus hyphens and periods, no consecutive hyphens, must start/end alphanumerically.

### MCP declaration syntax

Per §8 of the spec, three permitted forms:

1. **Default discovery** — host reads `.mcp.json` at plugin root when no manifest override exists.
2. **Manifest path** — `"mcpServers": "./config/mcp.json"` pointing to a JSON file containing a top-level `mcpServers` object.
3. **Inline config** — `"mcpServers": { "mcpServers": { "<name>": { "command": "...", "args": [...] } } }` (note the doubled key).

`command`, `args`, `env`, and `cwd` MUST support `${PLUGIN_ROOT}` placeholder expansion (§10).

### Standard layout (§4.2)

```text
my-plugin/
├── .plugin/
│   └── plugin.json
├── commands/
├── agents/
├── skills/
├── output-styles/
├── rules/
├── hooks/
│   └── hooks.json
├── .mcp.json
├── .lsp.json
├── scripts/
├── assets/
├── LICENSE
└── CHANGELOG.md
```

### Host conformance (§12)

A host claiming OPS v1 conformance MUST scan for `.plugin/plugin.json` and MAY additionally honor a vendor-prefixed sibling. No shipping host except Claude Code currently meets even the relaxed reading of §12.

## OPS v1 changelog scan since 2026-05-01

The repo has no merged commits between 2026-05-01 and 2026-05-14 — only the
two foundational commits dated 2026-04-03 (`c01f3921`, `cd5f34e7`) on `main`.
There are no git tags and no releases.

There is **one open pull request** that materially changes the spec, opened
2026-05-04:

- **PR #3** — `[codex] Update README for governance and manifest direction`
  (head: `codex/gav-readme-governance-suggestions`, base: `main`, +124/−70). Diff
  (verified via `gh api repos/vercel-labs/open-plugin-spec/pulls/3/files`):

  - Moves the canonical manifest from `.plugin/plugin.json` to root-level
    `plugin.json`. The Quick Start example, §1, §4, §5, and §12 are all
    rewritten.
  - Adds a new REQUIRED top-level `id` field with URL-style provenance
    (e.g. `"id": "https://github.com/example/hello-plugin/tree/main"`).
  - Replaces "vendor-prefixed manifest precedence" with "namespaced top-level
    extension fields" (host-specific keys like `x-claude-code: { ... }` instead
    of separate manifest files).
  - Adds §1.1 ("Governance model") proposing a steering committee modeled on
    the Open Responses governance structure.

This PR is **unmerged** as of 2026-05-14 23:17:02 UTC (last update). It has not
been ratified — but its existence means the canonical manifest path is in
active flux and any decision VIGOR makes today should treat the path as
non-final.

The PR was opened by an automated codex agent ("[codex]" prefix), not by the
spec maintainers, which suggests it represents one stakeholder's proposal and
not consensus. No spec maintainer has commented or approved as of access date.

## Per-host detail

### 1. Claude Code (Anthropic)

#### Source Summary

Anthropic's Claude Code documents a plugin model at
https://code.claude.com/docs/en/plugins (redirected from
docs.anthropic.com/en/docs/claude-code/plugins on 2026-05-14). The CLI also exposes
`claude --plugin-dir <path>` for local testing and `claude --plugin-url
<url>` for archive testing.

#### Loading Behavior

Claude Code requires a manifest at `.claude-plugin/plugin.json`. From the docs
(verbatim): *"The manifest file at `.claude-plugin/plugin.json` defines your
plugin's identity: its name, description, and version."* This is the
vendor-prefixed variant the OPS spec permits in §5 — i.e. Claude Code is
**OPS-precedence-compatible** but does not appear to scan
`.plugin/plugin.json` as a fallback. The docs do not name OPS, do not link to
the Vercel Labs spec, and do not claim conformance.

#### MCP Story

`.mcp.json` at the plugin root. From the docs: *"`.mcp.json` | Plugin root |
MCP server configurations"*. This matches OPS §8 default discovery exactly.

#### Vendor Manifest Path

`<plugin-root>/.claude-plugin/plugin.json`. Component directories (`skills/`,
`commands/`, `agents/`, `hooks/hooks.json`, `.lsp.json`, `monitors/`,
`bin/`, `settings.json`) live at the plugin root, NOT inside
`.claude-plugin/`. The docs flag misplacement as a "Common mistake."

#### Citations

- https://code.claude.com/docs/en/plugins (accessed 2026-05-14)
- https://github.com/anthropics/claude-code (CHANGELOG.md grep for "Open Plugin", "OPS", ".plugin/plugin.json" — zero matches as of `main` on 2026-05-14)
- https://code.claude.com/docs/en/plugins-reference (referenced but not separately fetched; manifest schema reference)

### 2. Goose (Block / AAIF)

#### Source Summary

Goose was originally `block/goose` (Block, formerly Square). The README in the
upstream repo states: *"This project has moved from `block/goose` to the
[Agentic AI Foundation (AAIF)](https://aaif.io/) at the Linux Foundation."* The
canonical source remains accessible at `block/goose` and that is what is
cited here.

#### Loading Behavior

Goose does NOT scan for any per-plugin manifest file. Extensions are entries
in a global YAML config at `~/.config/goose/config.yaml`. The Rust loader at
`crates/goose/src/config/extensions.rs` keys off the constant
`EXTENSIONS_CONFIG_KEY = "extensions"` and deserializes the map into
`IndexMap<String, ExtensionEntry>`.

A separate plugin-discovery module exists at `crates/goose/src/plugins/discovery.rs`
that walks `<project>/.agents/plugins/<name>/` and `~/.agents/plugins/<name>/`,
treating any subdirectory as a plugin candidate without scanning a manifest
filename. The test fixture creates `hooks/hooks.json` rather than any
`plugin.json`.

#### MCP Story

YAML map under `extensions:` in `~/.config/goose/config.yaml`. Each entry has
`cmd`, `args`, `env`, `enabled`, `type` (stdio / sse / streamable-http). MCP
servers are first-class extensions in Goose's model — there is no separate
"plugin manifest that contains MCP" indirection.

#### Vendor Manifest Path

None. The closest analog is the `extensions:` map key in
`~/.config/goose/config.yaml`. There is no on-disk per-plugin manifest. This
makes Goose **fundamentally incompatible** with OPS v1 §4.1.2 absent a
shim translating OPS plugins into config entries at install time.

#### Citations

- https://block.github.io/goose/docs/getting-started/using-extensions (accessed 2026-05-14)
- https://github.com/block/goose/blob/main/crates/goose/src/config/extensions.rs
- https://github.com/block/goose/blob/main/crates/goose/src/plugins/discovery.rs
- https://github.com/block/goose README — "moved to AAIF" disambiguation note

### 3. Sourcegraph Amp

#### Source Summary

Sourcegraph Amp is documented at https://ampcode.com/manual.

#### Loading Behavior

No manifest concept for plugins. Plugins are individual TypeScript files
loaded from:

- `.amp/plugins/*.ts` (project)
- `~/.config/amp/plugins/*.ts` (user, macOS/Linux)
- `%USERPROFILE%\.config\amp\plugins\*.ts` (Windows)

Skills, separately, follow a `SKILL.md`-with-frontmatter convention in directories
under `.agents/skills/<name>/`, `.claude/skills/<name>/`,
`~/.config/agents/skills/`, `~/.config/amp/skills/`, or `~/.claude/skills/`.
Notably Amp deliberately consumes `.claude/skills/` — a sign that vendor
cross-loading is happening today even without a shared spec.

#### MCP Story

Two declaration sites:

1. Per-skill `mcp.json` inside the skill directory (e.g. `.agents/skills/<name>/mcp.json`).
2. Top-level `amp.mcpServers` key in `~/.config/amp/settings.json` or
   `.amp/settings.json`.

#### Vendor Manifest Path

None. Amp has no plugin manifest. Skills use `SKILL.md` frontmatter with
`name` and `description` required.

#### Citations

- https://ampcode.com/manual (accessed 2026-05-14) — sections "Plugins" and "Skills"

### 4. Hermes Agent (NousResearch)

#### Source Summary

The "Hermes" name in 2026 is heavily overloaded (Facebook's JS engine, an IBC
relayer, a JS-bytecode reverse-engineering tool, JetBrains' transactional
mailer, etc.). The agentic-host project that fits the spec's intent is
`NousResearch/hermes-agent` ("The agent that grows with you"; 150,865
stars; default branch `main`; last pushed 2026-05-15T06:44:09Z). The
disambiguation matters because the same query also surfaces an unrelated
`Xiaofei-it/HermesEventBus` (Android IPC).

#### Loading Behavior

Hermes uses **two coexisting manifest schemes** in the same monorepo, keyed
by plugin kind:

- **Frontend dashboard plugins** declare `manifest.json` at
  `plugins/<plugin-name>/<dashboard-name>/manifest.json`. Verified content
  from `plugins/example-dashboard/dashboard/manifest.json`:

  ```json
  {
    "name": "example",
    "label": "Example",
    "description": "Example dashboard plugin — used by test suite for auth coverage",
    "icon": "Sparkles",
    "version": "1.0.0",
    "tab": { "path": "/example", "position": "after:skills" },
    "slots": [],
    "entry": "dist/index.js",
    "api": "plugin_api.py"
  }
  ```

- **Backend / provider plugins** declare `plugin.yaml` at
  `plugins/<area>/<plugin-name>/plugin.yaml`. Verified content from
  `plugins/web/exa/plugin.yaml`:

  ```yaml
  name: web-exa
  version: 1.0.0
  description: "Exa web search and content extraction. Requires EXA_API_KEY..."
  author: NousResearch
  kind: backend
  provides_web_providers:
    - exa
  ```

Neither path matches OPS §4.1.2.

#### MCP Story

Hermes ships its own MCP server (`mcp_serve.py` at the repo root) rather than
declaring external MCP servers per-plugin. The README links to
`docs/user-guide/features/mcp` (404 at the docs URL, no source-tree match).
Plugin-level MCP declaration is via `provides_*` fields in `plugin.yaml`, not
a portable `mcpServers` map.

#### Vendor Manifest Path

`plugins/<plugin>/manifest.json` (frontend) OR `plugins/<area>/<plugin>/plugin.yaml`
(backend). No metadata directory — no `.plugin/`, no `.hermes-plugin/`.

#### Citations

- https://github.com/NousResearch/hermes-agent (root README)
- https://github.com/NousResearch/hermes-agent/blob/main/plugins/example-dashboard/dashboard/manifest.json (verified via `gh api`)
- https://github.com/NousResearch/hermes-agent/blob/main/plugins/web/exa/plugin.yaml (verified via `gh api`)

### 5. Goose / Block Goose disambiguation

The two names refer to the **same project**. Block Goose was the original
home (`block/goose` on GitHub) and the project announced a move to the
Linux Foundation's Agentic AI Foundation (AAIF) under the `aaif-goose/goose`
namespace. Block-era branding still ships in active marketing
(block.github.io/goose/...). Treating them as two distinct hosts would
double-count.

The replacement eighth host is **Cursor** — see §6 (was reserved) → §8
remap. Cursor was selected because it is the largest agentic IDE host not
otherwise covered, has clear public docs on its extension model, and is
materially different from the rest in that its plugin story is "MCP only,
no manifest."

(Citation for the move: README excerpt at
https://github.com/block/goose dated within 2026-05.)

### 6. Strands Agents (AWS)

#### Source Summary

The repo `strands-agents/sdk-python` (and `sdk-typescript`) is AWS's Strands
Agents framework, integrated with Amazon Bedrock by default.

#### Loading Behavior

No manifest, no on-disk plugin format. Tools are registered via the `@tool`
Python decorator, and the framework optionally watches a `./tools/` directory
when `load_tools_from_directory=True`. The OPS package model (§4) does not
map cleanly onto a decorator-only registration.

#### MCP Story

Programmatic. `MCPClient(lambda: stdio_client(StdioServerParameters(command="uvx",
args=[...])))` is constructed in Python; tools come from
`list_tools_sync()`; the resulting tool list is passed directly to the
`Agent` constructor.

#### Vendor Manifest Path

None.

#### Citations

- https://github.com/strands-agents/sdk-python (accessed 2026-05-14)
- https://github.com/strands-agents (org-level repo listing — `sdk-python`, `sdk-typescript`, `tools`, `samples`, `docs`, `mcp-server`, `evals`, `agent-sop`, `agent-builder`, `devtools`, `.github`)

### 7. Gemini CLI (Google)

#### Source Summary

Gemini CLI is Google's open-source agentic CLI, configured per repo with
`GEMINI.md` and per user with `~/.gemini/settings.json`. Extension docs live in
the repo at `docs/extensions/{index,reference,writing-extensions,best-practices,releasing}.md`.

#### Loading Behavior

Manifest filename is `gemini-extension.json` at the extension root; the
extension itself lives at `~/.gemini/extensions/<name>/`. The `name` field
MUST match the directory name. Required: `name`, `version`. Optional:
`description`, `mcpServers`, `contextFileName`, `settings`.

#### MCP Story

`mcpServers` map inside `gemini-extension.json`, with `command`, `args`, `cwd`,
and the path placeholders `${extensionPath}`, `${workspacePath}`, `${/}`. Note
this is a **different placeholder vocabulary** than OPS's `${PLUGIN_ROOT}`. A
server defined at the user level in `~/.gemini/settings.json` overrides an
extension-defined server with the same name. The `trust` option is not
supported in extension-defined MCP servers.

#### Vendor Manifest Path

`~/.gemini/extensions/<name>/gemini-extension.json`. No alternate paths
documented. Open Plugin Spec is not mentioned anywhere in
`docs/extensions/`.

#### Citations

- https://github.com/google-gemini/gemini-cli (root README)
- https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/reference.md
- https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/writing-extensions.md
- https://github.com/google-gemini/gemini-cli/tree/main/docs/extensions (file listing)

### 8. JetBrains Junie

#### Source Summary

The public Junie repo is `JetBrains/junie` and contains only installer
scripts and registry JSON files for IDE distribution. The product
documentation lives at `https://junie.jetbrains.com/docs/` (dormant content
on the date of access — only landing-page text returned).

#### Loading Behavior

Junie is an IDE-resident agent rather than a CLI host with on-disk plugins.
The MCP configuration UI is shared with JetBrains AI Assistant and lives
under `Settings | Tools | AI Assistant | Model Context Protocol (MCP)`.
There is no plugin manifest; there is no on-disk per-plugin directory layout
documented. The repository's only configuration JSON is `registry-{nightly,experimental,eap}.json` for the installer pipeline — not plugin manifests.

Starting with JetBrains 2025.2, IDEs ship a built-in MCP **server** (so external
clients can connect to the IDE), configured at `Settings | Tools | MCP Server`.

#### MCP Story

Inline JSON typed into the IDE settings dialog:

```json
{ "mcpServers": { "yourServerName": { "command": "...", "args": [] } } }
```

Junie can also import existing Claude Desktop MCP configurations.

#### Vendor Manifest Path

None on disk. Configuration is IDE-state.

#### Citations

- https://github.com/JetBrains/junie (root listing — install scripts only)
- https://www.jetbrains.com/help/ai-assistant/mcp.html
- https://junie.jetbrains.com/docs/ (landing page only on access date)

### 9. Cursor *(eighth-slot substitute)*

#### Source Summary

Per the spec instructions: when two of the originally-listed names collapse
to the same project (Goose / Block Goose), one additional host should be
substituted. Cursor was selected for size and for representing the
"MCP-only, no plugin manifest" archetype.

#### Loading Behavior

No plugin manifest format. Cursor's only on-disk extensibility surface is
MCP server registration. The "Cursor Marketplace" markets one-click MCP
installs but is ultimately a registry over MCP, not a plugin spec.

#### MCP Story

`.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global). A programmatic
extension API (`vscode.cursor.mcp.registerServer()`) exists for dynamic
registration in enterprise pipelines.

#### Vendor Manifest Path

None.

#### Citations

- https://cursor.com/docs/context/mcp (accessed 2026-05-14, redirected from `docs.cursor.com`)
- https://cursor.com/docs (root docs listing)

## Recommendation for VIGOR

**This research is the empirical input for ADR-0015. ADR-0015 has not yet been
written; the recommendation here is a synthesis, not a prior decision.**

### Recommendation

VIGOR adapters SHOULD ship `.plugin/plugin.json` as the primary manifest AND
emit vendor-specific manifests for the three hosts where doing so is
materially valuable (Claude Code, Gemini CLI, Hermes Agent). This is
"dual-publish" — one source of truth in `.plugin/plugin.json`, a
build-step generator that emits `.claude-plugin/plugin.json`,
`gemini-extension.json`, and `plugin.yaml`/`manifest.json` (Hermes) to
matching paths.

The remaining four hosts (Goose, Strands, Junie, Cursor) cannot be served by
any static manifest — they require runtime registration (Goose via config
edit, Strands via decorator, Junie via IDE settings, Cursor via MCP). For
those, ship a thin **install-time helper** (e.g. `vigor adapter install
--host goose`) that translates the canonical manifest into the host's
runtime registration.

Sourcegraph Amp deserves a special note: it consumes `.claude/skills/`
directly. VIGOR adapters that ship skill content should emit a
`.claude/skills/<skill-name>/SKILL.md` symlink or copy as a side effect of
the Claude Code build step — Amp will pick it up for free, and that's the
cheapest cross-host win available today.

### Why not "ship only `.plugin/plugin.json`"

Because zero hosts honor it. Every confirmed-loading adapter today depends
on a vendor-specific path. Shipping only the OPS-canonical manifest means
shipping a manifest no shipping host reads. ADR-0003's "stable adapter
contract" requires that adapters work on the hosts that exist, not the
hosts the spec hopes will exist.

### Why not "ship only vendor-specific paths"

Because OPS v1 is the only candidate for a future shared standard. Skipping
the canonical path makes VIGOR a free-rider on whatever standard does emerge,
and creates a migration cliff if/when hosts adopt OPS conformance. The cost
of also writing `.plugin/plugin.json` is one additional file per adapter.

### Why dual-publish, not vendor-only

`.plugin/plugin.json` is the source of truth that the vendor-specific
generators read from. A future host that adopts OPS will load the canonical
manifest immediately. A future host that diverges will be served by adding
a new generator target without changing adapter source.

### Caveats and risks

1. **OPS v1 manifest path is in flux.** PR #3 (open since 2026-05-04) proposes
   moving the canonical path from `.plugin/plugin.json` to root-level
   `plugin.json` and adding a required `id` field. ADR-0015 should specify
   the OPS revision VIGOR pins to (today: `vercel-labs/open-plugin-spec@cd5f34e7`)
   and re-evaluate when PR #3 either merges or is rejected.
2. **No host conformance test exists.** Even Claude Code does not claim OPS
   conformance — its `.claude-plugin/plugin.json` is structurally compatible
   but not advertised as such. The "dual-publish" recommendation should
   include a CI test that loads each emitted manifest with the corresponding
   host's actual loader (or its docs-described schema), not just a
   schema-validation pass.
3. **The Hermes manifest split** (frontend `manifest.json` vs backend
   `plugin.yaml`) means the generator for Hermes must select the right output
   based on adapter kind. This is the most expensive integration; consider
   whether VIGOR has a Hermes use case before investing.
4. **Goose and Strands cannot be served by static files.** A "config-edit"
   helper for Goose risks corrupting user config; prefer printing the
   required YAML snippet and instructing the user to merge it manually,
   unless an `--in-place` flag is explicit.
5. **Sourcegraph Amp's `.claude/skills/` consumption is informal.** The Amp
   manual lists it as a precedence path; nothing prevents that from being
   removed in a future release. Treat it as a "free win today, not a
   contract."

## Key Sources

| Source | URL | Date Accessed |
| --- | --- | --- |
| OPS v1 spec (canonical) | https://github.com/vercel-labs/open-plugin-spec | 2026-05-14 |
| OPS v1 README — main | https://raw.githubusercontent.com/vercel-labs/open-plugin-spec/main/README.md | 2026-05-14 |
| OPS v1 commits | `gh api repos/vercel-labs/open-plugin-spec/commits` | 2026-05-14 |
| OPS v1 PR #3 (manifest-path move) | https://github.com/vercel-labs/open-plugin-spec/pull/3 | 2026-05-14 |
| Claude Code plugins guide | https://code.claude.com/docs/en/plugins | 2026-05-14 |
| Claude Code repo (CHANGELOG grep) | https://github.com/anthropics/claude-code | 2026-05-14 |
| Goose extensions guide | https://block.github.io/goose/docs/getting-started/using-extensions | 2026-05-14 |
| Goose extensions loader | https://github.com/block/goose/blob/main/crates/goose/src/config/extensions.rs | 2026-05-14 |
| Goose plugin discovery | https://github.com/block/goose/blob/main/crates/goose/src/plugins/discovery.rs | 2026-05-14 |
| Sourcegraph Amp manual | https://ampcode.com/manual | 2026-05-14 |
| Hermes Agent repo | https://github.com/NousResearch/hermes-agent | 2026-05-14 |
| Hermes example dashboard manifest | https://github.com/NousResearch/hermes-agent/blob/main/plugins/example-dashboard/dashboard/manifest.json | 2026-05-14 |
| Hermes web/exa plugin.yaml | https://github.com/NousResearch/hermes-agent/blob/main/plugins/web/exa/plugin.yaml | 2026-05-14 |
| Strands Agents Python SDK | https://github.com/strands-agents/sdk-python | 2026-05-14 |
| Strands org-level repo listing | https://github.com/strands-agents | 2026-05-14 |
| Gemini CLI extensions reference | https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/reference.md | 2026-05-14 |
| Gemini CLI extensions index | https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/index.md | 2026-05-14 |
| Gemini CLI extension authoring guide | https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/writing-extensions.md | 2026-05-14 |
| JetBrains Junie repo | https://github.com/JetBrains/junie | 2026-05-14 |
| JetBrains AI Assistant MCP docs | https://www.jetbrains.com/help/ai-assistant/mcp.html | 2026-05-14 |
| Cursor MCP docs | https://cursor.com/docs/context/mcp | 2026-05-14 |
| Cursor docs root | https://cursor.com/docs | 2026-05-14 |

## Scope notes

- VIGOR cannot test-load OPS plugins inside this worktree — there is no
  plugin runtime installed. All evidence is documentation- or
  source-code-based, per the spec's methodology guidance.
- Where source-code paths were cited, they were verified via the GitHub REST
  API (`gh api repos/<org>/<repo>/contents/<path>` and
  `gh api repos/<org>/<repo>/contents/<path> --jq '.content' | base64 -d`).
- One observation worth recording for ADR-0015 deliberation: every host
  surveyed agrees on **one** thing — MCP servers are the canonical way to
  add capabilities. The disagreement is entirely in *how* MCP servers are
  declared (file format, file location, registration mechanism). A VIGOR
  adapter could plausibly skip plugin-spec compliance and ship as a
  pure-MCP server with a thin per-host install helper. This would be a more
  radical alternative to "dual-publish" and is left as a question for
  ADR-0015 rather than a recommendation here.
