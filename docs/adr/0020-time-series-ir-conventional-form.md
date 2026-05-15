---
status: proposed
date: 2026-05-15
deciders: [VIGOR architecture team]
consulted: [builder-modality-strategy]
informed: [coordinator]
---

# ADR-0020: Conventional Form For Time-Series IRs

## Context and Problem Statement

VIGOR's `DomainAdapter` contract (ADR-0010) and IR schema versioning
discipline (ADR-0011) treat each adapter's IR body as opaque
`dict[str, Any]` validated by a Pydantic model that the adapter
registers via `vigor_core.registry.register_ir`. The contract makes no
assumptions about the IR's internal structure — every existing adapter
encodes its own shape: photo recipes are stateless, CAD parametrics are
declarative feature graphs, Manim scenes hide animation timing inside a
`python_code: str` field.

This works for the three shipping modalities because none of them have
a first-class time axis. The strategic deep-dive (`docs/strategy/next-modalities.md`)
identifies music notation, raw audio, animation, video timeline, MIDI
composition, and DAW filter-graphs as future modalities that all share
one structural property: their IR has segments / events / tracks
arranged along a time axis (beats, bars, seconds, frames). Without a
shared convention, each adapter will independently re-invent the
representation — and worse, the patch language for time-relative edits
("delay scene 3 by 200ms", "trim track 2 from beat 16 to beat 24") will
fragment.

ADR-0017 admitted pure-MCP plugins as ambient tool sources; the same
ecosystem pressure exists here for time-series. If VIGOR ships music
notation in Phase 9 with one shape, then audio in Phase 10 with a
different shape, the framework will have to reconcile them retroactively.
Better to land a conventional form now, while only one adopting adapter
is being built.

This ADR is **not** a core-schema change. It is an advisory convention
that adapters with time-series IRs SHOULD adopt; adapters without time
axes (photo, CAD, slide) are unaffected.

## Decision Drivers

- **Forward compatibility.** A shared idiom for time-series IRs avoids
  fragmentation across music, audio, animation, video, MIDI, and
  filter-graph adapters when they land.
- **Patch-language uniformity.** `PatchPlan.objectives` for time-series
  edits should follow a parseable shape so that backends generating
  patches across modalities can produce consistent, learnable diffs.
- **Strict-mode preservation.** ADR-0011's
  `ConfigDict(strict=True, extra="forbid")` discipline must be preserved
  per-adapter; a core-schema field would either weaken `extra="forbid"`
  for all adapters or force every adapter to declare a time field it
  doesn't use.
- **Adapter authoring discipline.** ADR-0003 makes adapters a one-stop
  shop for a modality. Conventions documented as ADRs (rather than
  buried in code) are more discoverable for new adapter authors.
- **Patch ownership rule (ADR-0010).** `AgentBackend.propose_patch`
  produces structured patch plans; `DomainAdapter.apply_patch` is the
  deterministic transform. A convention for how time-series patches are
  expressed strengthens the seam between the two.

## Considered Options

- **Option A — Advisory convention, opt-in per adapter.** Document a
  recommended body shape (`tracks`, `events`, `time_position`) and a
  recommended `PatchPlan.objectives` shape (`tracks/<id>:[<start>-<end>]
  <verb>`). No core-schema change. Adapters that adopt the convention
  inherit a shared idiom; adapters that don't are unchanged.
- **Option B — Core-schema extension.** Add optional `time_axis:
  TimeAxis | None` field to `ArtifactIR` itself. Every adapter would
  see the field even if it's None. Forces every IR through a contract
  decision it may not need.
- **Option C — Mixin / base-class convention.** Provide a Pydantic
  mixin (`TimeSeriesIR`) that adapters inherit. Stronger typing, but
  introduces an inheritance hierarchy that contradicts ADR-0011's
  discriminated-union flat-model preference.
- **Option D — Defer until two adapters demand it.** Wait for music
  notation (Phase 9) and one audio adapter (Phase 10+) to ship
  independently, then refactor. Proven path for "premature abstraction"
  avoidance, but the strategic doc explicitly flagged this as a
  fragmentation risk worth pre-empting.

## Decision Outcome

Chosen option: **Option A — advisory convention, opt-in per adapter.**

The convention is published in this ADR and lives in the
`docs/adoption/<modality>.md` briefs for adapters that adopt it. No
changes to `vigor-core` are required.

### Convention: Body Shape

Time-series adapters SHOULD encode their bodies as:

```text
body:
  tracks:
    - id: <track_id>
      kind: <"events" | "segments" | "automation">
      time_unit: <"beat" | "bar" | "second" | "frame">
      events:
        - id: <event_id>
          start: <TimePosition>
          duration: <TimePosition | null>
          payload: <adapter-specific>
```

`TimePosition` is a tuple-shaped object: `{value: float, unit: str}`,
with `unit` constrained to `Literal["beat", "bar", "second", "frame",
"sample", "tick"]`. Adapters MAY add modality-specific fields under
`payload`.

### Convention: Patch Objectives

Time-series adapters SHOULD parse `PatchPlan.objectives` entries
matching:

```text
tracks/<track_id>:[<start>-<end>] <verb>
```

Where:
- `<track_id>` matches a `track.id` in the IR body.
- `<start>` and `<end>` are `TimePosition` literal forms (e.g. `4b`
  for beat 4, `2.5s` for 2.5 seconds, `f30` for frame 30).
- `<verb>` is one of `delete`, `trim`, `extend`, `transpose`,
  `replace`, `quantize`, plus any adapter-specific verbs documented
  in the adoption brief.

Adapters that don't use the convention parse `objectives` however they
wish; the runtime makes no claims about the shape.

### Convention: Multi-Artifact Compile Output

Time-series adapters often produce paired outputs (LilyPond emits PDF
+ MIDI + WAV). The convention is:

- Emit the **primary** artifact (visual / human-facing) as the first
  `CompileResult.outputs` entry.
- Emit secondary artifacts (MIDI, WAV, telemetry) as subsequent
  entries.
- Set `CompileResult.metrics["primary_artifact_id"]` to the primary
  artifact id so reviewers and exporters that need a single canonical
  output can find it deterministically.

### Positive Consequences

- Future audio / animation / DAW-graph adapters land on a shared idiom
  without core-schema churn.
- Cross-modality backend training (one backend that proposes patches
  across multiple time-series modalities) becomes feasible because the
  patch language is uniform.
- Reviewers that compute time-aware metrics (e.g. "events per beat",
  "automation curve smoothness") can be written generically.
- Strict-mode discipline (ADR-0011) is preserved.

### Negative Consequences

- Convention is advisory — adapters can ignore it. If Phase 9 music
  notation ignores the convention, the convention has zero practical
  effect.
- The ADR cannot enforce convention adherence at the type level; review
  pressure is the only enforcement mechanism.
- Future ADR may need to harden the convention into a typed mixin
  (Option C) or a core-schema field (Option B) once enough adopting
  adapters exist; that ADR would supersede this one.

## Validation

This ADR is satisfied when:

- The adoption brief for the first time-series adapter (music notation,
  Phase 9) explicitly references this ADR and adopts both the body and
  patch conventions.
- A second time-series adapter ships and either adopts the convention
  or files an ADR explaining why a different shape is needed.

The ADR is **not** invalidated by adapters that have no time axis
(photo, CAD, slide, document). They are simply out of scope.

## Pros and Cons of the Options

### Option A — Advisory convention
- Good: zero core-schema impact; preserves strict-mode posture.
- Good: documentable, learnable, reviewable in adapter PRs.
- Good: lets the convention evolve as more adapters land.
- Bad: not type-enforced; adoption is a discipline question.

### Option B — Core-schema extension
- Good: type-enforced, discoverable.
- Bad: forces every adapter (including photo/CAD) to acknowledge a
  field they don't need.
- Bad: weakens `extra="forbid"` posture or expands the core schema
  surface unnecessarily.
- Bad: harder to evolve once published.

### Option C — Mixin / base-class convention
- Good: type-enforced for adopting adapters.
- Bad: introduces inheritance hierarchy contrary to ADR-0011's
  preference for flat discriminated-union shapes.
- Bad: harder to compose with adapter-specific fields.

### Option D — Defer until two adapters demand it
- Good: avoids premature abstraction.
- Bad: post-hoc refactor across two shipping adapters is more disruptive
  than landing a convention now while only one is being built.
- Bad: cross-modality backend training is harder if the patch language
  fragments.

## Implementation Notes

- This ADR ships with no code changes.
- The Phase 9 music-notation adoption brief
  (`docs/adoption/music-notation.md`, future) will cite this ADR and
  show the LilyPond IR adopting the convention.
- A `vigor-core` documentation update (separate Seeds task) may add a
  short pointer to this ADR from the IR-registry docstrings, so adapter
  authors discover the convention naturally.
- This ADR may be superseded if a future ADR upgrades the convention to
  a typed mixin or core-schema extension.

## More Information

- Companion ADR (modality-roadmap commitment): ADR-0019.
- Strategic deep-dive: `docs/strategy/next-modalities.md` §3 (G1, G4)
  and §6.

## Citations

| Source | URL |
| --- | --- |
| ADR-0010 (async core interfaces) | `0010-async-core-interfaces.md` |
| ADR-0011 (IR schema versioning) | `0011-ir-schema-versioning.md` |
| ADR-0017 (pure-MCP plugins) | `0017-pure-mcp-plugin-support.md` |
| LilyPond | https://lilypond.org/doc/ |
| MusicXML | https://www.w3.org/2021/06/musicxml40/ |
