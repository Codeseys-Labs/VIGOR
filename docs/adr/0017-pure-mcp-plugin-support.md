---
status: proposed
date: 2026-05-15
deciders: [VIGOR architecture team]
consulted: [builder-mcp-survey, builder-plugin-host-research]
informed: [coordinator]
---

# ADR-0017: Admit Pure-MCP Plugins As Ambient Tool Sources

## Context and Problem Statement

ADR-0014 established `AgentConfig` and the `vigor-agent` package, with
`vigor_agent.plugin_discovery.load_plugin_directory` parsing Open Plugin
Spec (OPS) v1 manifests at `.plugin/plugin.json`. ADR-0015 made VIGOR
adapter packages dual-publish as OPS v1 plugins. The v1 implementation
requires every loadable plugin to ALSO ship a Python `FactoryRef` at
`.plugin/vigor.json` so the iterative loop has deterministic
`compile` / `apply_patch` / review hooks; `adapter_spec_from_plugin`
raises `PluginDiscoveryError` when the FactoryRef is missing.

This intentionally excludes **pure-MCP plugins** — OPS v1 packages that
ship only `skills/` and an `.mcp.json` (or manifest-declared `mcpServers`)
with no Python entry point. Per the empirical research in
`docs/research/open-plugin-spec-host-compatibility.md`, pure-MCP is the
dominant 2026 packaging shape: every surveyed host (Claude Code, Goose,
Sourcegraph Amp, Hermes, Strands, Gemini CLI, Junie, Cursor) accepts MCP
servers as the unit of capability; only one (Claude Code) accepts the
OPS-vendor-prefixed manifest at all; none load Python factories. The
companion `2026-mcp-reviewer-survey.md` reinforces that MCP is the
canonical capability mechanism across hosts and that no public 2026 MCP
server exposes a typed `compile` / `apply_patch` contract.

A user shipping a pure-MCP plugin today must hand-translate its
`mcpServers` block into `AgentConfig.mcp_servers` YAML. The mechanism
works but breaks discoverability: the plugin directory is the natural
unit of distribution, and `vigor-agent` ignores everything in it that
isn't a Python factory.

ADR-0014 deferred this question explicitly. ADR-0017 settles the v2 path.

## Decision Drivers

- **Discoverability.** Pointing `vigor-agent` at an OPS plugin directory
  should yield something useful — not a `PluginDiscoveryError` — when
  the plugin happens to be pure-MCP.
- **Typed-runtime guarantees.** ADR-0014 and ADR-0015 are explicit that
  VIGOR's value-add is the verifiable iterative loop. Generic MCP tool
  calls cannot substitute for `DomainAdapter.compile` / `apply_patch` /
  `reviewers` deterministically — the IR contract (ADR-0011) and review
  semantics (ADR-0004) require typed Python.
- **Security posture.** Plugin discovery is already a supply-chain risk
  surface (VIGOR-8bdf: `.plugin/vigor.json` self-authorises via
  attacker-supplied `allowed_prefixes`). Any extension must not widen
  the attack surface in shapes `AgentConfig.mcp_servers` doesn't already
  cover.
- **Spec instability.** OPS v1 is in active flux — vercel-labs/open-plugin-spec
  PR #3 (open since 2026-05-04) proposes moving the canonical manifest
  to root-level `plugin.json` and adding a required `id` field. Deep
  investment in spec-coupled infrastructure is premature.
- **Ecosystem alignment.** Zero shipping hosts honour the OPS
  vendor-neutral path; pure-MCP is the cross-host de-facto default.
  Ignoring it diverges VIGOR from where the ecosystem is going.

## Considered Options

- **Option A — Admit pure-MCP plugins as ambient tool sources.** Lift
  the `FactoryRef` requirement in `plugin_discovery`. When a plugin has
  no `FactoryRef`, parse its declared `mcpServers` (per OPS §8 forms:
  default `.mcp.json`, manifest path, inline) and merge them onto
  `AgentConfig.mcp_servers` at agent-construction time, gated by a
  host-side allowlist. Skills declared in the manifest surface to the
  backend as today. A clear warning fires at `load_agent_config` time
  stating that the plugin contributes tools only and cannot drive the
  loop.
- **Option B — Generic MCP-driven adapter.** Add a
  `vigor-adapter-mcp-generic` package that consumes a pure-MCP plugin's
  tools as `compile` / `render` / `review` hooks against a convention
  (e.g. tools named `compile`, `render`, `review`). When the convention
  isn't met, fall back to a "review-only" mode. This lets pure-MCP
  plugins drive the loop without Python.
- **Option C — Defer indefinitely.** Keep `plugin_discovery` requiring
  a `FactoryRef`. Pure-MCP plugins remain second-class — usable only
  via manual entry in `AgentConfig.mcp_servers`. Document the policy
  and re-open if the OPS ecosystem matures or VIGOR's adapter contract
  relaxes.

## Decision Outcome

Chosen option: **Option A — Admit pure-MCP plugins as ambient tool
sources**, because it closes the discoverability gap with a small,
contained change while preserving every typed-runtime guarantee that
ADR-0014 and ADR-0015 depend on. Pure-MCP plugins become first-class
citizens of the *tool* surface (where they always belonged), without
being granted authority over the iterative loop (which their schema is
not equipped to provide).

Option B is rejected because no public 2026 MCP server exposes the
typed `compile` / `apply_patch` / review contract VIGOR's loop requires
(see `docs/research/2026-mcp-reviewer-survey.md` — every reviewer-shaped
MCP server today has a domain-specific tool surface like
`run_fem_analysis`, `score_video`, `audit_design`); a generic adapter
against a convention nobody else uses would be an interface the
ecosystem cannot author against. Option C is rejected because pure-MCP
is the dominant 2026 packaging shape; forcing every user to hand-translate
manifests into YAML is busywork with no upside vs. Option A.

### Consequences

- **Positive**: pure-MCP plugins drop into a `vigor-agent` config
  without manual `mcp_servers` translation, matching the rest of the
  2026 host ecosystem (Claude Code, Goose, Gemini CLI, Cursor) where
  MCP servers are the unit of capability.
- **Positive**: `vigor-adapter-*` packages remain the only path to drive
  the loop, preserving ADR-0014's typed-runtime guarantees and the
  loop semantics ADR-0001 / ADR-0002 / ADR-0003 are built on.
- **Positive**: the change is additive — gated behind the absence of a
  `FactoryRef`, so existing dual-published adapters and existing
  `AgentConfig.mcp_servers` users are unaffected.
- **Negative** (REQUIRED): the host now has two registration paths for
  MCP servers — manifest-discovered and `AgentConfig.mcp_servers`-declared.
  Operators must reason about both for allowlist and audit posture;
  tooling that answers "what tools is this agent exposed to" must
  inspect both.
- **Negative**: a user who points `vigor-agent` at a pure-MCP plugin
  directory may silently assume it will drive the loop and be confused
  when the warning is buried in logs. UX guard required: surface the
  no-loop-driver state at config-load time, not at first-task time.
- **Negative**: extends the supply-chain attack surface that VIGOR-8bdf
  already identified for `FactoryRef.allowed_prefixes`. Pure-MCP plugins
  are MCP-server publishers; the host-side allowlist for MCP-server
  identities (e.g. `AgentConfig.plugin_allowed_mcp_servers`) becomes a
  hard prerequisite before this ADR can move from `proposed` to
  `accepted`.
- **Neutral**: skills declared in `.plugin/plugin.json` are already
  authored by adapter authors via `vigor_core.plugin.export_skill_md`;
  pure-MCP plugin skills are surfaced to the backend identically and
  require no new pathway.
- **Neutral**: this ADR does not change OPS v1 conformance behaviour.
  VIGOR continues to dual-publish per ADR-0015; the change here is
  only in what VIGOR consumes from third-party OPS plugins.

## Pros and Cons of the Options

### Option A — Admit pure-MCP plugins as ambient tool sources

- Good, because the change is bounded — roughly 30–80 LOC in
  `plugin_discovery.py` plus a registration hook in
  `AgentOrchestrator` / `AdapterRegistry.from_config`. No new package,
  no new abstraction, no IR-shape coercion.
- Good, because it composes cleanly with the existing
  `AgentConfig.mcp_servers` path — the same allowlist policy applies
  and the same `vigor-mcp.MCPToolBackend` consumes the merged result.
- Good, because it matches 2026 host behaviour: every shipping host
  treats MCP as the unit of plugin capability per
  `docs/research/open-plugin-spec-host-compatibility.md` §"Per-host detail".
- Good, because loop semantics are unchanged; the failure mode for
  "user expected loop driver" is a clearly-loggable warning at config
  load, not silent breakage at run time.
- Bad, because operators must reason about two registration paths for
  the same kind of resource. Auditing "what MCP tools does this agent
  see" requires inspecting both manifest-discovered and config-declared
  servers.
- Bad, because the no-loop-driver warning is easy to miss in agent logs;
  UX must surface this at config-load (mitigation, not avoidance).
- Bad, because it expands the supply-chain attack surface in the same
  shape as VIGOR-8bdf — host-side allowlist for MCP-server identities
  becomes a hard prerequisite for promotion to `accepted`.

### Option B — Generic MCP-driven adapter

- Good, because in the limit it lets non-Python authors ship
  loop-driving plugins, which would broaden VIGOR's contributor pool
  considerably.
- Good, because it stakes out a convention (typed `compile` / `render` /
  `review` MCP tools) that other hosts could in principle adopt — VIGOR
  could lead a typed-MCP adapter standard.
- Bad, because no public 2026 MCP server implements that convention.
  Per `docs/research/2026-mcp-reviewer-survey.md`, every reviewer-shaped
  MCP server today has a domain-specific tool surface (`run_fem_analysis`,
  `score_video`, `audit_design`); the typed `compile` / `apply_patch`
  contract VIGOR's loop requires is not a thing the MCP world produces.
- Bad, because the adapter would have to coerce free-text or per-server
  JSON into `ReviewReport`, `ArtifactIR`, and `Patch` shapes; coercion
  errors are precisely the silent-failure mode ADR-0011 was written to
  prevent.
- Bad, because a "generic" adapter that fails to drive the loop
  deterministically violates the value-add ADR-0014 and ADR-0015 are
  explicit about preserving.
- Bad, because it would be a new package with its own CI, type schema,
  security posture, and test suite — disproportionate cost for a
  use-case nobody has demonstrated demand for.

### Option C — Defer indefinitely

- Good, because zero work, zero new attack surface, zero ambiguity
  about loop-driver authority.
- Good, because if OPS v1 stabilises (PR #3 resolves) and a typed-MCP
  convention emerges, ADR-0017 can be superseded with full information.
- Bad, because pure-MCP plugins are the dominant 2026 packaging shape
  (every host except Claude Code) and ignoring them diverges VIGOR
  from its ecosystem.
- Bad, because the workaround — hand-translating a plugin's `mcpServers`
  block into `AgentConfig.mcp_servers` YAML — is busywork the user
  shouldn't need to do.
- Bad, because it presents a discoverability cliff at the boundary
  between OPS plugins and VIGOR adapters that the rest of the 2026
  ecosystem doesn't have.

## More Information

### Implementation sketch (informational, not part of the decision)

`plugin_discovery.adapter_spec_from_plugin` no longer raises when
`plugin.factory is None`. A sibling helper
`mcp_servers_from_plugin(plugin) -> list[MCPServerSpec]` parses the
plugin's manifest-declared `mcpServers` (per OPS §8 forms: default
`.mcp.json` discovery, manifest path, inline config). `AgentOrchestrator`
or `AdapterRegistry.from_config` merges those into the existing
`cfg.mcp_servers` list under a host-side
`plugin_allowed_mcp_servers` allowlist (see follow-ups below). The
user-visible warning fires once at `load_agent_config` time, not per-run,
and includes the plugin root path so the operator can locate the
manifest.

`${PLUGIN_ROOT}` placeholders in MCP `command` / `args` / `env` / `cwd`
fields (per OPS §10) resolve to the discovered `DiscoveredPlugin.root`.

### Follow-ups required before this ADR moves from `proposed` to `accepted`

1. **VIGOR-8bdf** — resolve the supply-chain self-authorisation bug for
   `FactoryRef.allowed_prefixes`. The same allowlist discipline is the
   blueprint for MCP-server identity allowlisting under this ADR;
   merging Option A before VIGOR-8bdf lands would widen the attack
   surface that bug describes.
2. **MCP-server identity allowlist** — decide where it lives. Natural
   shape is `AgentConfig.plugin_allowed_mcp_servers` (host-side, mirrors
   `plugin_allowed_prefixes`). Likely a small extension to whatever
   ADR or PR resolves VIGOR-8bdf, not a separate ADR.
3. **UX surface** — confirm the "pure-MCP plugin, no loop driver"
   warning fires at config-load time, not on first task dispatch.
   Run-time surprises here are worse than load-time strictness.

### Re-evaluation triggers

- OPS v1 PR #3 merges, changing the canonical manifest path or adding
  a required `id` field. The `plugin_discovery` code path changes
  regardless; revisit then. (`docs/research/open-plugin-spec-host-compatibility.md`
  §"OPS v1 changelog scan since 2026-05-01".)
- A typed-MCP convention emerges in the ecosystem (i.e. MCP servers
  start exposing `compile` / `apply_patch` / `review` shapes
  out-of-the-box). Revisit Option B with concrete implementations.
- VIGOR's adapter contract relaxes (e.g. a non-deterministic loop
  variant ships). Revisit Option B under looser constraints.

### Citations

| Source | URL / Path |
| --- | --- |
| ADR-0014 (deferring this question) | docs/adr/0014-generalized-agent-config.md |
| ADR-0015 (OPS v1 dual-publish) | docs/adr/0015-open-plugin-spec-compatibility.md |
| ADR-0011 (IR schema versioning) | docs/adr/0011-ir-schema-versioning.md |
| ADR-0004 (reviewer ensemble) | docs/adr/0004-reviewer-ensemble-and-adjudicator.md |
| ADR-0003 (adapters separated from orchestration) | docs/adr/0003-separate-adapters-from-orchestration.md |
| OPS v1 host compatibility research | docs/research/open-plugin-spec-host-compatibility.md |
| 2026 MCP reviewer survey | docs/research/2026-mcp-reviewer-survey.md |
| Open Plugin Specification v1.0.0 | https://github.com/vercel-labs/open-plugin-spec |
| OPS v1 PR #3 (manifest-path move proposal) | https://github.com/vercel-labs/open-plugin-spec/pull/3 |
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk |
| Seeds: VIGOR-ca0f (this ADR's task) | sd show VIGOR-ca0f |
| Seeds: VIGOR-8bdf (plugin self-authorisation) | sd show VIGOR-8bdf |
