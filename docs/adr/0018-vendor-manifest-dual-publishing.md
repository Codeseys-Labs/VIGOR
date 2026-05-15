---
status: proposed
date: 2026-05-15
deciders: [VIGOR architecture team]
consulted: [builder-plugin-host-research]
informed: [coordinator]
refines: ADR-0015
---

# ADR-0018: Dual-Publish Vendor Manifests From The Adapter Generator For Open-Plugin-Spec Host Compatibility

## Context and Problem Statement

ADR-0015 made VIGOR adapter packages dual-publish as Python `DomainAdapter`
implementations AND Open Plugin Spec (OPS) v1 plugins, with
`.plugin/plugin.json` declared as the source-of-truth manifest. The
"Alternatives Considered" table of ADR-0015 explicitly *deferred*
shipping `.claude-plugin/plugin.json` (and other vendor-prefixed paths)
on the rationale that *"the Open Plugin spec explicitly allows hosts to
also recognise vendor paths, so we can add them later without breaking
changes."*

The empirical host-compatibility research carried out for this branch
contradicts the premise of that deferral. Per
`docs/research/open-plugin-spec-host-compatibility.md` (dated 2026-05-14,
8 of 8 hosts evaluated):

- **Zero shipping hosts** honour the OPS vendor-neutral path
  (`.plugin/plugin.json`).
- **Exactly one host** (Claude Code) honours the OPS vendor-prefixed
  variant (`.claude-plugin/plugin.json`).
- **Seven hosts** (Goose, Sourcegraph Amp, Hermes, Strands, Gemini CLI,
  JetBrains Junie, Cursor) use proprietary, filename-divergent schemes
  with no OPS support: `gemini-extension.json`, YAML-in-config-yaml,
  per-skill `mcp.json`, per-plugin `manifest.json`/`plugin.yaml`,
  decorator-only registration, in-IDE settings.
- The OPS spec itself is in active flux:
  vercel-labs/open-plugin-spec PR #3 (open since 2026-05-04) proposes
  moving the canonical manifest to root-level `plugin.json` and adding
  a required `id` field. Unmerged as of 2026-05-14, no spec-maintainer
  approval.

ADR-0015's "defer vendor paths" decision means VIGOR adapters today ship
a manifest that **no shipping host reads**. The package layout cost of
adding a generator step is small; the cost of shipping invisible
manifests until OPS adoption catches up is that VIGOR adapters cannot
be discovered by any host except via SKILL.md side-channels and
`vigor-agent`'s own loader. ADR-0017 (proposed alongside this ADR)
admits pure-MCP plugins as ambient tool sources — that change is also
predicated on OPS manifests being meaningfully consumed somewhere.

This ADR amends ADR-0015's deferral. It does not supersede ADR-0015 in
full: SKILL.md generation, the registry-driven IR pattern, and the
"adapter Python package + OPS plugin in one ship" decision all stand.
Only the single row "Defer `.claude-plugin/plugin.json` and other
vendor paths" is revised.

The pure-MCP plugin question (consuming third-party OPS plugins that
ship only `mcpServers`) is **out of scope for this ADR** — it was
settled by ADR-0017.

## Decision Drivers

- **Discoverability now, not when OPS adoption catches up.** Adapters
  must be loadable by the hosts that exist in 2026, not the hosts the
  spec hopes will exist in 2027.
- **Single source of truth.** Vendor manifests must derive from one
  canonical declaration so they can never drift from each other or
  from the SKILL.md generated alongside them.
- **No churn in adapter Python source.** ADR-0015's promise that
  adapters keep working unchanged must continue to hold.
- **Spec instability.** OPS v1's manifest path is in flux (PR #3).
  VIGOR cannot stake its host-compatibility story on
  `.plugin/plugin.json` alone, and cannot pre-emptively migrate to
  PR #3's layout before the PR merges either.
- **CI-enforceable freshness.** The same drift guard ADR-0015 added
  for SKILL.md (regenerate + diff) must extend to vendor manifests so
  out-of-band edits to one target cannot diverge from the canonical
  manifest.
- **Bounded vendor scope.** Add only the targets where dual-publish
  yields measurable host compatibility. The four hosts that require
  runtime registration (Goose, Strands, Junie, Cursor) cannot be served
  by any static manifest and remain out of scope here — they need the
  install-time helper noted in the research recommendation, not a
  vendor manifest target.

## Considered Options

- **Option A — Keep single canonical manifest (current ADR-0015 state).**
  Ship only `.plugin/plugin.json`. Wait for OPS conformance to roll out
  across hosts.
- **Option B — Dual-publish from a shared template generator.** Keep
  `.plugin/plugin.json` as source-of-truth. Add a generator step that
  emits `.claude-plugin/plugin.json` (Claude Code), `gemini-extension.json`
  (Gemini CLI), and `plugin.yaml` (Hermes backend) per-adapter from one
  template. Reuse the existing `scripts/regen_skills.py` orchestration
  with a new `regen_vendor_manifests` companion (or extend the same
  script). Add a CI diff guard.
- **Option C — Pivot to a single vendor path** (e.g. only
  `.claude-plugin/plugin.json`). Drop OPS conformance ambitions.
- **Option D — Wait for vercel-labs/open-plugin-spec PR #3 to merge,**
  then adopt whatever manifest path / `id` field the merged version
  prescribes; do not ship any vendor manifest until then.

## Decision Outcome

Chosen option: **Option B — Dual-publish from a shared template generator**,
because it closes the empirical "zero hosts read VIGOR's manifest"
gap immediately for the three hosts where a static manifest can solve
it, while preserving `.plugin/plugin.json` as the declarative source of
truth so a future host adopting OPS conformance loads VIGOR adapters
without code changes.

Option A is rejected because *"hosts will adopt OPS later"* was the
premise of ADR-0015's deferral, and the research falsifies it: OPS v1
has been published for six weeks with one open PR proposing breaking
changes and zero merged adoption beyond Claude Code's vendor-prefixed
variant. Continuing to ship only `.plugin/plugin.json` is shipping a
manifest no one reads.

Option C is rejected because it forecloses the future where a shared
spec emerges. Pivoting to `.claude-plugin/plugin.json`-only locks
VIGOR to one vendor's lifecycle and gives up the cross-vendor
distribution that motivated ADR-0015 in the first place. The cost of
*also* writing `.plugin/plugin.json` is one additional file per
adapter — vanishingly cheap relative to the lock-in.

Option D is rejected because PR #3 is unmerged, has no spec-maintainer
approval, and would re-shape OPS in a backwards-incompatible way (root
`plugin.json` + required `id`). Coupling VIGOR's host-compatibility
rollout to its merge timeline cedes a decision the project should
make for itself. ADR-0018 is explicit that the OPS revision VIGOR
pins to today is `vercel-labs/open-plugin-spec@cd5f34e7` and re-evaluates
on PR #3 resolution (see "Re-evaluation triggers" below).

### Consequences

- **Positive**: each VIGOR adapter package becomes loadable by Claude
  Code (via `.claude-plugin/plugin.json`), Gemini CLI (via
  `gemini-extension.json` placed at the publish-time install path),
  and Hermes (via `plugin.yaml` for backend-kind plugins) without any
  per-host hand-authoring. The manifest no host reads (`.plugin/plugin.json`)
  remains in place as the OPS conformance hook.
- **Positive**: vendor manifests cannot drift from the canonical
  manifest because they regenerate from the same template each CI run;
  the same diff guard pattern that protects SKILL.md (ADR-0015)
  protects the manifests.
- **Positive**: composes cleanly with ADR-0017. Pure-MCP plugins
  consumed by `vigor-agent` continue to read `.plugin/plugin.json`'s
  `mcpServers`; vendor manifests are an emit-only concern. The two
  ADRs' code paths do not overlap.
- **Positive**: extending the generator to a new target (e.g. when
  Cursor or Junie ship a static plugin manifest) is additive — a new
  function plus a new emit path, no change to the source manifest.
- **Negative** (REQUIRED): every adapter now ships **four** manifest
  surfaces (`.plugin/plugin.json` + three vendor copies) instead of
  one. CI must regenerate-and-diff all four; release tarballs are
  larger; out-of-band edits to any one of the four are now a rejectable
  drift signal. The maintenance forcing function from ADR-0015 widens
  proportionally.
- **Negative**: the generator is now coupled to three vendor schemas
  (Claude Code, Gemini CLI, Hermes) whose evolution VIGOR does not
  control. A breaking change in any one of them requires generator
  patching even if the canonical OPS manifest is unaffected. A pinned
  schema-revision matrix (in `scripts/` or `docs/`) must be maintained
  to track which vendor revision each generator target produces.
- **Negative**: Hermes' two-manifest split (frontend `manifest.json`
  vs backend `plugin.yaml`) means the Hermes generator target is
  conditional on adapter kind. Today every VIGOR adapter is
  backend-kind, so this collapses to `plugin.yaml`-only — but the
  generator API must accept a kind hint to remain extensible without
  rewriting later.
- **Negative**: vendor manifest fields outside the OPS core (e.g.
  Gemini CLI's `${extensionPath}` placeholder vocabulary, Hermes'
  `provides_*` keys) require explicit per-target translation in the
  generator. There is no generic "OPS → vendor" projection; the
  generator carries vendor knowledge.
- **Neutral**: the four hosts requiring runtime registration (Goose,
  Strands, Junie, Cursor) remain unaddressed by this ADR. They are
  served by a separate install-time helper (recommended in the
  research, not yet decided in an ADR). Dual-publish does not preclude
  that path.
- **Neutral**: pinning to `vercel-labs/open-plugin-spec@cd5f34e7` is
  explicit. PR #3's resolution will trigger a generator revision, not
  a re-decision of dual-publishing as a strategy.

## Pros and Cons of the Options

### Option A — Keep single canonical manifest

- Good, because zero generator code, zero new file artifacts, zero
  vendor coupling.
- Good, because if OPS conformance arrives unmodified, VIGOR is already
  conformant with no migration.
- Bad, because the manifest VIGOR ships today is read by zero shipping
  hosts; ADR-0015's "discoverable plugin" promise is empirically
  unrealised.
- Bad, because the deferral's stated rationale ("hosts will adopt
  OPS-prefix paths later") is falsified by the host-compatibility
  research.
- Bad, because Claude Code is the largest agentic-host distribution
  channel today and `.claude-plugin/plugin.json` is the only manifest
  it reads — refusing to emit it forfeits that channel.

### Option B — Dual-publish from a shared template generator

- Good, because every confirmed-loading host either reads the canonical
  OPS path (theoretical, zero hosts today) or reads its vendor-specific
  path (Claude Code, Gemini CLI, Hermes — all served by this option).
- Good, because the source manifest stays vendor-neutral; vendor
  manifests are derived artifacts the maintainer never hand-edits.
- Good, because CI drift guards (regenerate + diff) extend a pattern
  the project already uses for SKILL.md, so the operational discipline
  is familiar.
- Good, because additive: a new vendor target is a new generator
  function, not a manifest-source rewrite.
- Bad, because the generator embeds vendor schemas VIGOR does not own.
  Vendor breaking changes require generator patches; a pinned matrix
  of "which vendor schema revision we target" must be maintained.
- Bad, because the file count per adapter goes from 1 to 4, widening
  the surface CI checks and out-of-band-edit drift detection apply to.
- Bad, because Hermes' frontend/backend split forces a kind-aware
  emit, raising the generator's interface complexity.

### Option C — Pivot to a single vendor path

- Good, because instantly solves the "discoverable in Claude Code"
  problem with one manifest file and no generator.
- Good, because removes the OPS-spec-instability risk entirely — if
  PR #3 lands or OPS forks, VIGOR is unaffected.
- Bad, because abandons the cross-vendor distribution thesis that
  motivated ADR-0015. Adapters become Claude-Code-only, contradicting
  ADR-0007's SDK-agnostic posture.
- Bad, because the cost of also keeping `.plugin/plugin.json` is one
  file per adapter — there is no real saving from omitting it.
- Bad, because forecloses VIGOR's ability to ride a future shared
  spec without a migration cliff.

### Option D — Wait for OPS PR #3

- Good, because if PR #3 merges with consensus, VIGOR adopts a stable
  spec rather than a fork-prone moving target.
- Good, because zero work today; the decision is deferred cleanly to
  the spec's resolution.
- Bad, because PR #3 is unmerged, has no spec-maintainer approval, and
  was opened by an automated agent (per the research §"OPS v1 changelog
  scan"). It may never merge, or merge in a different shape.
- Bad, because waiting indefinitely means continuing to ship a manifest
  no host reads — Option A's pathology with a different rationale.
- Bad, because PR #3's proposed root-level `plugin.json` + required
  `id` field is itself a breaking change that VIGOR would have to absorb;
  pre-committing to it before merge is worse than dual-publishing now
  and re-evaluating on resolution.

## More Information

### Generator design (informational, not part of the decision)

The generator extends the existing `scripts/regen_skills.py`
orchestration. Two natural shapes:

1. **Single script, multi-target.** Rename `scripts/regen_skills.py` to
   `scripts/regen_plugin_artifacts.py` (or keep the name and broaden
   its scope) so one entrypoint regenerates SKILL.md plus all vendor
   manifests for every adapter. Preferred — fewer entrypoints, fewer
   CI hooks.
2. **Companion script.** Add `scripts/regen_vendor_manifests.py`
   alongside `regen_skills.py`. Acceptable if the script grows complex
   enough that splitting clarifies it. Not the default.

Either shape is acceptable; the implementing builder picks based on
the scope of the change at the time. The decision below is on the
contract, not the file layout.

**Inputs.** A single per-adapter declaration the generator reads:

```python
@dataclass
class AdapterPluginSpec:
    package: str                # "vigor-adapter-photo"
    plugin_name: str            # "vigor-adapter-photo"
    version: str                # "0.2.0"
    description: str            # short, single-line
    homepage: str | None = None
    license: str | None = None
    keywords: list[str] = ()
    skill_dir: str = "./skills/"     # relative to plugin root
    mcp_servers: dict | str | None = None  # OPS §8 forms
    hermes_kind: Literal["backend", "frontend"] = "backend"
    # extension hooks for future targets:
    extra: dict[str, Any] | None = None
```

This object is the canonical declaration. Today's `ADAPTERS` list in
`scripts/regen_skills.py` is the obvious place for it. The
`AdapterPluginSpec` rolls up to the existing `OpenPluginManifest`
Pydantic model in `vigor_core.plugin` for OPS emission, and to
per-vendor projections for the rest.

**Emit targets.**

| Target | Output path (relative to adapter root) | Format | Notes |
| --- | --- | --- | --- |
| OPS v1 (canonical) | `.plugin/plugin.json` | JSON | Existing. Source of truth. Generated by `vigor_core.plugin.export_plugin_json`. |
| Claude Code | `.claude-plugin/plugin.json` | JSON | Mirrors OPS field semantics; component dirs (`skills/`, `commands/`, etc.) live at adapter root, NOT inside `.claude-plugin/` (per Claude Code "common mistake" warning in the research). |
| Gemini CLI | `gemini-extension.json` (at adapter root) | JSON | Required: `name` (must equal directory name), `version`. Optional: `description`, `mcpServers`, `contextFileName`, `settings`. `${extensionPath}` placeholder, NOT `${PLUGIN_ROOT}`. |
| Hermes backend | `plugin.yaml` (at adapter root) | YAML | Required: `name`, `version`, `kind: backend`, `provides_*` (defaults to `provides_tools`). VIGOR adapters today are all backend-kind. |

The `.plugin/vigor.json` FactoryRef sidecar (introduced for ADR-0014's
Python entry point) is **out of scope** for this ADR. It is a
VIGOR-internal contract and not part of any vendor's loader; the
generator does not regenerate it.

**Per-target field projection.** The generator owns explicit
mappings — there is no generic "OPS → vendor" projection because the
schemas diverge meaningfully. Sketch:

```python
def emit_claude_code(spec: AdapterPluginSpec) -> bytes:
    """Mirrors OPS core. Same field names, different path."""

def emit_gemini_cli(spec: AdapterPluginSpec) -> bytes:
    """Translate OPS mcpServers (which use ${PLUGIN_ROOT}) to Gemini CLI
    mcpServers (which use ${extensionPath}). Drop OPS-only fields."""

def emit_hermes_backend(spec: AdapterPluginSpec) -> bytes:
    """Emit YAML with kind=backend. Translate skills declaration to
    provides_tools. Drop OPS-only fields."""
```

**Drift guard.** A CI step runs `uv run python scripts/regen_skills.py`
(or whatever single entrypoint emerges) and fails if `git diff` reports
any change under `packages/*/.plugin/`, `packages/*/.claude-plugin/`,
`packages/*/gemini-extension.json`, or `packages/*/plugin.yaml`. The
existing SKILL.md drift guard expands to cover these paths.

**Pinned schema-revision matrix.** Maintain a small markdown table at
`docs/plugin-manifest-targets.md` (or in the generator script's
docstring — implementer's call) listing the upstream revision of each
target schema:

| Target | Pinned revision | Source |
| --- | --- | --- |
| OPS v1 | `vercel-labs/open-plugin-spec@cd5f34e7` (2026-04-03) | `.plugin/plugin.json` |
| Claude Code | docs revision dated 2026-05-14 | code.claude.com/docs/en/plugins-reference |
| Gemini CLI | `google-gemini/gemini-cli@docs/extensions/reference.md` HEAD as of 2026-05-14 | gemini-extension.json |
| Hermes | `NousResearch/hermes-agent` HEAD as of 2026-05-14 | plugin.yaml |

This list is the trigger for re-evaluation: when an upstream revision
moves, regenerate, diff, and decide whether the change is breaking.

### Out of scope

- **Pure-MCP plugin consumption.** Settled by ADR-0017. This ADR is
  about emitting manifests, not consuming them.
- **Goose / Strands / Junie / Cursor.** No static manifest serves
  these. The research recommends a `vigor adapter install --host <name>`
  helper as a separate workstream; that decision is not made here.
- **Sourcegraph Amp `.claude/skills/` mirroring.** Identified as a
  "free win" in the research (Amp consumes Claude Code's skill path
  directly). Whether to symlink, copy, or leave alone is a tactical
  packaging detail, not an architectural decision; resolve in a follow-up
  issue.
- **Migration of ADR-0015's status.** ADR-0015 is `accepted`. This ADR
  *amends* a single row of its Alternatives table (the deferral of
  vendor paths) but does not invalidate its other decisions
  (SKILL.md generation, registry-driven IR, dual-publication as a
  Python+plugin package). When this ADR moves from `proposed` to
  `accepted`, ADR-0015's Alternatives table row "Ship both `.plugin/`
  and `.claude-plugin/` manifests" gains a footnote pointing to ADR-0018;
  ADR-0015's `Status` line stays `Accepted`.

### Follow-ups required before this ADR moves from `proposed` to `accepted`

1. **Generator implementation.** Land `scripts/regen_skills.py`
   (or successor) emitting all four targets for the three current
   adapters (`vigor-adapter-photo`, `vigor-adapter-cad`,
   `vigor-adapter-video-manim`). Tracked in a follow-up Seeds issue.
2. **CI drift guard expansion.** Extend the existing SKILL.md diff
   gate to cover the new manifest paths.
3. **Per-target schema validation.** A test that loads each emitted
   manifest with the corresponding host's documented schema (or actual
   loader where available — Claude Code via `claude --plugin-dir`,
   Gemini CLI via its docs schema). Static schema validation is the
   minimum bar.
4. **Pinned revision matrix.** Commit `docs/plugin-manifest-targets.md`
   (or the in-script equivalent) so the upstream revisions VIGOR
   targets are auditable.

### Re-evaluation triggers

- **OPS PR #3 resolves.** If merged, the canonical manifest moves to
  root-level `plugin.json` with a required `id` field. The generator's
  OPS target updates; the dual-publish strategy is unaffected. If
  rejected, no action.
- **A surveyed host adopts OPS conformance.** If e.g. Goose or Cursor
  begins reading `.plugin/plugin.json`, the corresponding vendor target
  may become redundant. Drop it from the generator.
- **A new vendor target becomes worthwhile.** If Junie, Cursor, or
  another host ships a static plugin-manifest format, add a generator
  target. The dual-publish core stays.
- **Vendor schema break.** If Claude Code, Gemini CLI, or Hermes ship
  a backwards-incompatible manifest revision, the generator's per-target
  function updates; the source manifest is unaffected.

### Citations

| Source | URL / Path |
| --- | --- |
| ADR-0015 (single-manifest decision this ADR amends) | docs/adr/0015-open-plugin-spec-compatibility.md |
| ADR-0017 (pure-MCP plugin consumption — sibling ADR) | docs/adr/0017-pure-mcp-plugin-support.md |
| ADR-0014 (generalized agent config / FactoryRef) | docs/adr/0014-generalized-agent-config.md |
| ADR-0011 (IR schema versioning, registry pattern) | docs/adr/0011-ir-schema-versioning.md |
| ADR-0007 (SDK-agnostic core posture) | docs/adr/0007-sdk-agnostic-core-with-optional-agent-backends.md |
| OPS v1 host compatibility research | docs/research/open-plugin-spec-host-compatibility.md |
| Open Plugin Specification v1.0.0 | https://github.com/vercel-labs/open-plugin-spec |
| OPS v1 PR #3 (manifest-path-move proposal) | https://github.com/vercel-labs/open-plugin-spec/pull/3 |
| Claude Code plugin manifest reference | https://code.claude.com/docs/en/plugins-reference |
| Gemini CLI extensions reference | https://github.com/google-gemini/gemini-cli/blob/main/docs/extensions/reference.md |
| Hermes Agent backend plugin example | https://github.com/NousResearch/hermes-agent/blob/main/plugins/web/exa/plugin.yaml |
| Existing skill regeneration script | scripts/regen_skills.py |
| Existing OPS manifest helpers | packages/vigor-core/src/vigor_core/plugin.py |
| Seeds: VIGOR-6c15 (this ADR's task) | sd show VIGOR-6c15 |
