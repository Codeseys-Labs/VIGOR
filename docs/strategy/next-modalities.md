# VIGOR Next-Modality Strategy

Status: **Proposed**
Date: 2026-05-15
Parent task: VIGOR-312b (strategic deep-dive lead)
Author: builder-modality-strategy

## Executive Summary

VIGOR currently ships three modality adapters (`photo`, `video-manim`, `cad`)
plus a toy adapter, all driving the same generate-compile-review loop through
the modality-agnostic core (ADR-0001..0011). To prove the framework's claim
of modality-neutrality and to capture the next tranche of user value, VIGOR
should adopt — in this order:

1. **Structured documents** (LaTeX / Markdown → PDF) — `vigor-adapter-doc`
2. **Slide decks** (Marp / python-pptx) — `vigor-adapter-slide`
3. **Music notation** (LilyPond / MusicXML) — `vigor-adapter-music-notation`

Picks 1 and 2 require **no extension** to the DomainAdapter contract: their
IRs are static, their compilers are deterministic and fast, and their review
surfaces are dominated by objective metrics (overflow, citation resolution,
contrast, structural balance). They are the highest-leverage adoptions for
the verifiable-iterative-loop value proposition.

Pick 3 is a deliberate stretch: it forces VIGOR to confront a **time-series
IR** convention (events along a beat axis) without yet requiring waveform
reasoning. ADR-0020 captures the conventional form for time-series IRs so
that subsequent waveform-audio, animation, and DAW-graph adapters land on a
shared idiom.

The remaining clusters (raw audio, code, 3D, schematics, game levels) are
surveyed in §5 and rejected for first-position adoption — each for a
different reason that is documented rather than hand-waved.

## 1. Question 1 — Which Modalities Are Valuable But Uncovered?

The candidate space, broken into clusters:

| Cluster | Sub-modality | Representative IR | Compile path |
| --- | --- | --- | --- |
| Documents | LaTeX papers | `.tex` source + bib | `pdflatex` / `latexmk` |
| Documents | Markdown → PDF | Pandoc Markdown + frontmatter | `pandoc` / `weasyprint` |
| Documents | Structural diagrams | Mermaid / Graphviz / TikZ | `mmdc` / `dot` / `pdflatex` |
| Slides | Marp decks | Marp Markdown | `marp-cli` |
| Slides | python-pptx decks | declarative deck JSON → PPTX | `python-pptx` |
| Slides | RevealJS / Slidev | declarative deck JSON → HTML | static site build |
| Music notation | LilyPond | `.ly` source | `lilypond` → PDF + MIDI + WAV |
| Music notation | MusicXML | XML score | MuseScore / verovio |
| Audio | DAW filter-graph | ffmpeg filter graph | `ffmpeg` |
| Audio | MIDI composition | MIDI events + plugin chain | FluidSynth / Surge |
| Audio | Speech (TTS) | text + voice id | XTTS / Piper / cloud TTS |
| Code | Refactor / test-driven | unified diff / file ops | `pytest` / `ruff` / `mypy` |
| Code | Synth (function-level) | source files | language toolchain |
| 3D | Blender Python | `.blend` build script | `blender --python` |
| 3D | three.js / Babylon.js | scene-graph JSON + JS | headless GL render |
| 3D | USD / glTF | declarative graph | `usdview` / glTF validator |
| Schematics | KiCad | `.kicad_sch` + symbols | `kicad-cli` ERC / DRC |
| Schematics | Verilog / VHDL HDL | RTL source | iverilog / verilator |
| Game levels | Tiled / Godot scene | scene tree JSON | engine load + sim |
| Game levels | Doom WAD | level lump | dsda-doom playthrough |
| Hybrid | UI design | HTML/CSS/React + tokens | bundler + visual diff |

Coverage gaps are real: every cluster above is currently untouched by
VIGOR's adapter portfolio.

## 2. Question 2 — Highest Leverage For The Iterative Loop

The framework's distinct value over one-shot generation is the
**generate → compile → review → patch → re-compile** cycle. Modalities
benefit most when:

- **(L1) The IR is symbolic / textual** so patches are well-defined diffs.
- **(L2) Compile is fast and deterministic** so candidate fan-out is cheap.
- **(L3) Reviewers can be objective** so the adjudicator (ADR-0004) can
  converge without unbounded LLM-as-judge variance.
- **(L4) Iteration changes the artifact non-trivially** — i.e. the second
  pass is meaningfully different from the first, so multi-iteration runs
  pay off.

Scoring each cluster against L1–L4 (1 = bad, 5 = ideal):

| Cluster | L1 | L2 | L3 | L4 | Score |
| --- | --- | --- | --- | --- | --- |
| Structured documents (LaTeX/MD) | 5 | 5 | 5 | 5 | **20** |
| Slide decks (Marp/pptx) | 5 | 5 | 4 | 5 | **19** |
| Music notation (LilyPond) | 5 | 5 | 3 | 4 | **17** |
| 3D code-driven (Blender/three.js) | 5 | 3 | 3 | 5 | **16** |
| Schematics (KiCad) | 4 | 4 | 5 | 3 | **16** |
| Code refactor / test-driven | 5 | 4 | 5 | 4 | **18** *(but commodified)* |
| Audio filter-graph (ffmpeg) | 4 | 4 | 3 | 4 | **15** |
| MIDI composition | 4 | 4 | 2 | 4 | **14** |
| UI design (HTML/CSS) | 5 | 3 | 3 | 4 | **15** |
| Game levels | 4 | 2 | 2 | 5 | **13** |
| Speech (TTS) | 1 | 5 | 4 | 1 | **11** *(IR ≈ prompt)* |

The top three by raw score are documents, code, and slides. **Code is
excluded from the first pick** despite its high score because the modality
is heavily commoditised by Cursor / Claude Code / Aider / Codex, and
VIGOR's frontier-adjudicator differentiation is least visible there
(the de facto reviewer is `pytest`, which every coding agent already
runs). VIGOR adoption of code-as-modality should follow proven uptake on
documents and slides; it is captured as a future Seeds task, not a Phase
7 target.

## 3. Question 3 — Where The DomainAdapter Contract Does Not Yet Generalize

Reading the contract (`packages/vigor-core/src/vigor_core/interfaces.py`,
`schemas.py`) reveals five implicit assumptions that the existing three
adapters either satisfy or quietly side-step:

### G1. IR is static structure (no first-class time axis)
`ArtifactIR.body: dict[str, Any]` is opaque. The Manim adapter encodes
animation timing inside `python_code: str`; CAD has no time axis; photo
recipes are stateless. A future audio / animation / DAW-graph IR needs
explicit time semantics (events at beats, segments at seconds, tracks
parallel in time). **Today this works only because no adapter has tested
it.**

### G2. Compile is single-pass and deterministic
`compile(ir, context) -> CompileResult` returns one terminal result.
There is no contract for:
- Iterative simulation that converges over time (FEM, fluid, training loops).
- Streaming compile (long renders that emit progress).
- Interactive evaluation (game-engine playthroughs, REPL-driven repl).

The CAD validator already silently elides this for FEM ("deferred to
safety-critical later phase" per `roadmap.md` §Phase 5).

### G3. Review consumes one ObservableArtifact at a time
`review(artifact, ir, context) -> list[ReviewReport]` takes one artifact.
Multi-modal artifacts (slide deck = PDF + thumbnails; LilyPond =
PDF + MIDI + WAV; UI = HTML + screenshot + accessibility tree) require
the adapter to either pick a "primary" artifact or emit multiple
`ObservableArtifact`s and rely on the runtime to call `review` per
artifact. The runtime currently calls `review` once per compile output,
which is workable but means cross-artifact reviewers (e.g. "does the
narrated audio match the slide?") cannot be expressed at the contract
level.

### G4. Patch is body-level, not behaviour-level
`apply_patch(ir, patch) -> ArtifactIR` produces a new IR; `PatchPlan`
declares `objectives` and `allowed_operations` as free-text strings. For
time-series IRs, useful patches are temporal — "delay scene 3 by 200ms",
"trim track 2 from beat 16 to beat 24". The contract supports this in
principle (the adapter parses `objectives` however it wants) but offers
no convention, and ad-hoc parsing across adapters fragments the patch
language.

### G5. RunContext.iteration is a wall-clock counter
`RunContext.iteration: int = 0` is a generation iteration, not a
media-time position. This is not a bug, but a future
animation/audio/video adapter needs to be careful not to conflate
"iteration of the generate-review loop" with "position along the
artifact's internal time axis."

**Implication.** Picks 1 and 2 (documents, slides) require **no**
contract change — they fit G1–G5 cleanly. Pick 3 (music notation)
brushes against G1 and G4 enough that ADR-0020 should land alongside
the music-notation adapter to fix a conventional form for time-series
IRs before audio waveforms or animation arrive and lock in incompatible
idioms.

## 4. Question 4 — Per-Modality Detail

### 4a. Structured documents (recommended #1)

| Aspect | Detail |
| --- | --- |
| Existing tools | `pdflatex` / `latexmk`, `pandoc`, `weasyprint`, `mmdc` (mermaid), Graphviz, TikZ. All headless, all subprocess-friendly. |
| IR shape | Discriminated union: `latex_document.v1` (tex source + bib refs + frontmatter) or `markdown_document.v1` (pandoc-flavor markdown + frontmatter). Both are textual, diffable. |
| Compile path | `latexmk -pdf` or `pandoc -o out.pdf`. Deterministic given the same source + same toolchain version. Hot path is ~5–30s for typical papers. |
| Review surface | Objective: page count, missing references (`Reference \| undefined`), unresolved citations, overfull boxes, broken hyperref links, fonts-not-embedded, accessibility tag presence for tagged PDF. Optional model-critic for prose. |
| MCP availability | `pandoc-mcp`, `latex-mcp` exist in the wild as of 2026; quality varies. The pure-MCP path (ADR-0017) lets VIGOR consume them as ambient tools. |
| Demand evidence | Researchers, technical writers, ops/policy authors. ChatGPT/Claude already produce LaTeX, but no system iterates on overflow/citation errors automatically. Strong "wow" demo: "compile broke, here's the fixed candidate." |
| Risk | Bibliography handling is fiddly (BibTeX vs biber); pdflatex is single-pass and emits warnings rather than errors for many real bugs. Adapter must parse the `.log` carefully. |

See `docs/adoption/structured-documents.md` for the full adoption brief.

### 4b. Slide decks (recommended #2)

| Aspect | Detail |
| --- | --- |
| Existing tools | `marp-cli` (Markdown → PDF + PNG), `python-pptx` (declarative → PPTX), RevealJS, Slidev. All scriptable, all headless. |
| IR shape | `marp_deck.v1`: frontmatter + per-slide markdown + theme. Companion `pptx_deck.v1` for python-pptx if richer layout control is needed downstream. |
| Compile path | `marp deck.md -o deck.pdf --images png` for thumbnails, or `python-pptx` for `.pptx`. Both <5s typical. |
| Review surface | Objective: per-slide overflow detection (text exceeds slide bounds), WCAG contrast on text/background pairs, font size minimums, image aspect mismatch, asset path resolution, structural balance (≤7 bullets/slide convention). Model-critic for narrative flow. |
| MCP availability | `marp-mcp` exists; `pptx-mcp` exists. Coverage is reasonable for slides specifically. |
| Demand evidence | Enterprise demand is enormous: every consultant, sales engineer, internal-comms team. python-pptx has 5M+ monthly PyPI downloads; Marp has wide GitHub adoption. |
| Risk | Visual-correctness review is partly subjective. Mitigated by emphasising structural reviewers and treating aesthetics as an optional model-critic with low weight. |

See `docs/adoption/slide-decks.md` for the full adoption brief.

### 4c. Music notation (recommended #3)

| Aspect | Detail |
| --- | --- |
| Existing tools | `lilypond` (`.ly` → PDF + MIDI), `verovio` (MusicXML → SVG), `music21` (Python music-theory toolkit), MuseScore CLI. |
| IR shape | `lilypond_score.v1`: source + tempo + voice declarations. Time axis is symbolic (beats / bars), not seconds. |
| Compile path | `lilypond -o out score.ly` produces PDF + MIDI; FluidSynth converts MIDI → WAV for audition. |
| Review surface | Pitch range checks, voice-leading rules (parallel fifths, voice crossing), beat-grid validity, MIDI duration vs requested length. Audio reviewer is optional (loudness, key estimation via librosa). |
| MCP availability | Limited. `music21` exposed as MCP is a known third-party project but quality varies. Most adoption value comes from the LilyPond CLI directly, not via MCP. |
| Demand evidence | Smaller market than docs/slides but extremely passionate user base (composition students, music engravers, transcribers). |
| Risk | Time-axis IR is the first VIGOR adapter to genuinely have one. ADR-0020 mitigates by establishing the convention before the adapter ships. |

### 4d. Surveyed-but-rejected for first position

- **Code refactor / test-driven** — high contract fit, but commoditised
  by existing coding agents. VIGOR's frontier-adjudicator advantage is
  least legible in a domain whose dominant reviewer (`pytest`) is
  pass/fail. **Status: future-phase candidate, not first-position.**
- **Audio filter-graph (ffmpeg)** — solid score (15) but the review
  surface is dominated by perceptual metrics (loudness, spectral
  balance) where the model-critic path is currently weakest. Wait
  until the time-series convention from #3 has been exercised.
- **3D code-driven (Blender/three.js)** — VIGA-adjacent territory and a
  natural fit, but compile is slow (10–60s for non-trivial Blender) and
  reviewers are heavily perceptual. Better as Phase 8 once the GPU /
  shadow-mode reviewer path (currently blocked, per `roadmap.md`) is
  unblocked.
- **Schematics (KiCad)** — excellent contract fit and objective DRC/ERC
  reviewers, but the user base is small. Worth keeping as a "halo"
  adopter that demonstrates VIGOR's seriousness for engineering
  workflows. Phase 9 candidate.
- **Game levels** — review surface is fundamentally subjective
  (gameplay-quality requires playtesting). Not a fit until VIGOR has a
  story for human-in-the-loop reviewers at scale.
- **Speech (TTS)** — IR is essentially the prompt. Iteration value is
  minimal; one-shot generation already works. Skip.

## 5. Question 5 — Recommended Adopt Order

### Phase 7 (next): Structured documents — `vigor-adapter-doc`
Highest fit, no contract changes, strong demand, ecosystem tools mature.
Demonstrates VIGOR on a non-graphics modality. ADR-0019 records this
choice. Seeds backlog filed under VIGOR-312b children.

### Phase 8: Slide decks — `vigor-adapter-slide`
Reuses 80% of the document toolchain (Markdown → render → PNG/PDF
review). Validates the framework on a multi-artifact-per-candidate
shape (PDF + per-slide PNGs).

### Phase 9: Music notation — `vigor-adapter-music-notation`
Forces the time-series-IR convention (ADR-0020) into the framework.
Audio waveform / DAW-graph / animation adapters land downstream of
this and inherit the convention.

### Deferred (no commitment)
Code, raw audio, 3D, schematics, game levels — surveyed in §5, each
deferred for documented reasons. Revisit after Phase 9.

## 6. Contract Generalisation

Picks 1 and 2 require zero changes to the contract. Pick 3 motivates
**ADR-0020** ("Conventional Form For Time-Series IRs"), which:

- Defines an opt-in body convention: `body.tracks: list[Track]`,
  `Track.events: list[Event]`, `Event.start: TimePosition`,
  `TimePosition.unit: Literal["beat", "bar", "second", "frame"]`.
- Defines an opt-in patch convention: `PatchPlan.objectives` entries
  may use the form `tracks/<track_id>:[<start>-<end>] <verb>` (free
  text within the body, but parseable by adapters that adopt it).
- Does not alter the abstract `DomainAdapter` interface. Adapters
  that don't need time-series semantics (every existing one) are
  unaffected.

ADR-0020 is **conventional**, not enforced — `ConfigDict(strict=True,
extra="forbid")` per ADR-0011 is preserved at the body level by each
adapter's own Pydantic IR model. No core schema change is required.

## 7. Backlog (For Phase 7)

The first-modality backlog is filed against the Seeds tracker. The
package skeleton is `vigor-adapter-doc` under `packages/`. Parent seed
**VIGOR-c916** ("Adopt structured-documents modality (Phase 7 lead)").

| Seed | Title | Depends on |
| --- | --- | --- |
| VIGOR-17e8 | `vigor-adapter-doc` package skeleton | — |
| VIGOR-5f0b | doc IR schemas (`latex_document.v1` + `markdown_document.v1`) | VIGOR-17e8 |
| VIGOR-d361 | doc compile path (latexmk + pandoc subprocess wrappers) | VIGOR-5f0b |
| VIGOR-60d7 | doc compile-log parser + reviewer pack | VIGOR-d361 |
| VIGOR-95dd | doc `apply_patch` deterministic transforms | VIGOR-5f0b |
| VIGOR-3d43 | doc export bundle (PDF + source + `.bib` + log) | VIGOR-d361 |
| VIGOR-348e | end-to-end integration test through `vigor-runtime` | VIGOR-d361, VIGOR-60d7, VIGOR-95dd |

Each seed has its acceptance criteria in its description; see `sd show
<seed-id>` for the full text. Parent linkage will be re-asserted via
`sd sync`.

## 8. Open Questions / Risks

- **Toolchain pinning.** LaTeX distributions vary widely (TeX Live vs
  MiKTeX, year-to-year package updates). Adapter must capture toolchain
  version in `CompileResult.metrics` for provenance reproducibility.
- **MCP fragmentation.** Pure-MCP plugins (ADR-0017) for documents are
  uneven in quality. Adoption brief defaults to direct subprocess
  invocation; MCP path is opt-in.
- **Multi-artifact review.** Slide decks emit multiple
  `ObservableArtifact`s per candidate. The runtime currently calls
  `review` per artifact, which is fine, but reviewers that compare
  artifacts (PDF vs per-slide PNG) need a "review-bundle" facility.
  This may motivate a future `review_bundle` extension; out of scope
  for the first picks, captured here for future ADR.
- **Time-series convention adoption pressure.** ADR-0020 is opt-in. If
  audio/animation adapters land before the convention is exercised on
  music notation, they may diverge. Mitigation: make ADR-0020 advisory
  and revisit after Phase 9.

## 9. Acceptance Against VIGOR-312b

Per the task acceptance criteria:

- Strategic summary committed: **this document.**
- Per-modality adoption briefs for top 1–2 picks:
  `docs/adoption/structured-documents.md`,
  `docs/adoption/slide-decks.md`.
- ADR drafts in MADR 3.0:
  `docs/adr/0019-adopt-structured-documents-modality.md`,
  `docs/adr/0020-time-series-ir-conventional-form.md`.
- Seeds backlog: filed in this branch's `sd sync`; titles/acceptance
  enumerated in §7.

## Citations

| Source | URL |
| --- | --- |
| ADR-0001 (VIGOR loop) | `docs/adr/0001-adopt-vigor-loop.md` |
| ADR-0002 (editable IRs) | `docs/adr/0002-use-editable-intermediate-representations.md` |
| ADR-0003 (adapter separation) | `docs/adr/0003-separate-adapters-from-orchestration.md` |
| ADR-0010 (async core interfaces) | `docs/adr/0010-async-core-interfaces.md` |
| ADR-0011 (IR schema versioning) | `docs/adr/0011-ir-schema-versioning.md` |
| ADR-0017 (pure-MCP plugins) | `docs/adr/0017-pure-mcp-plugin-support.md` |
| Roadmap | `docs/roadmap.md` |
| LilyPond | https://lilypond.org/doc/ |
| Marp | https://marp.app/ |
| Pandoc | https://pandoc.org/ |
| python-pptx | https://python-pptx.readthedocs.io/ |
| latexmk | https://mg.readthedocs.io/latexmk.html |
