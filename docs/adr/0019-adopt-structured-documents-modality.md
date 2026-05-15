---
status: proposed
date: 2026-05-15
deciders: [VIGOR architecture team]
consulted: [builder-modality-strategy]
informed: [coordinator]
---

# ADR-0019: Adopt Structured Documents As The Next VIGOR Modality

## Context and Problem Statement

VIGOR currently ships three production modality adapters
(`vigor-adapter-photo`, `vigor-adapter-video-manim`, `vigor-adapter-cad`)
plus a toy adapter, all driving the same generate-compile-review loop
through the modality-agnostic core (ADR-0001..0011). The strategic
deep-dive (parent task VIGOR-c1ab, lead task VIGOR-312b) was asked to
identify the next modality to adopt and architect the contract
extensions, if any, required to support it.

`docs/strategy/next-modalities.md` (this branch) surveys ten candidate
clusters — structured documents, slide decks, music notation, audio
filter-graphs, MIDI composition, code refactor, 3D code-driven,
schematics, game levels, speech — and scores each against the
verifiable-iterative-loop value proposition (symbolic IR, fast
deterministic compile, objective reviewers, non-trivial iteration
delta). Structured documents (LaTeX + Markdown → PDF) score highest
overall (20/20), require no extension to the existing `DomainAdapter`
contract, demand large user populations (arXiv, technical writing,
docs-as-code), and have a mature subprocess-based toolchain
(`latexmk`, `pandoc`) that fits the photo/manim adapter precedent.

This ADR commits VIGOR to building `vigor-adapter-doc` as the Phase 7
deliverable. Slide decks and music notation are surveyed in the
strategic doc as Phase 8 / Phase 9 candidates respectively but are
**not** decided here.

## Decision Drivers

- **Verifiable-iterative-loop fit.** Structured documents satisfy all
  four loop-fit criteria from the strategic doc: symbolic IR (textual
  source), fast deterministic compile (5–30s), objective reviewers
  (overfull boxes, undefined references, unresolved citations from the
  compile log), and non-trivial iteration delta (one compile reports
  citation errors that the next compile fixes — exactly the case where
  one-shot generation cannot succeed).
- **Contract reuse.** No changes to `DomainAdapter`, `ArtifactIR`,
  `CompileResult`, or `ReviewReport` are required. The modality fits
  the existing photo/manim/cad adapter pattern: subprocess-based
  compile, log-parsing reviewers, deterministic patch application.
- **Demonstration value.** A successful `vigor-adapter-doc` proves
  modality-neutrality on a non-graphics domain — the strongest
  available rebuttal to the "VIGOR is graphics-specific" critique.
- **Demand evidence.** arXiv submissions are LaTeX-first; docs sites
  are Markdown-first; pandoc has 50k+ GitHub stars. The "compile
  broke, here's the fix" demo flow is highly legible.
- **Toolchain maturity.** `latexmk`, `pandoc`, `weasyprint`,
  `pdftotext`, `qpdf`, `pdffonts` are stable headless CLIs with
  decades of incumbency.
- **Adoption brief readiness.** `docs/adoption/structured-documents.md`
  enumerates IR shape, compile path, reviewer pack, patch pattern,
  exports, MCP availability, MVP acceptance criteria, and risks.

## Considered Options

- **Option A — Adopt structured documents (`vigor-adapter-doc`) next.**
  Build LaTeX + Markdown → PDF as Phase 7. No contract changes.
- **Option B — Adopt slide decks (`vigor-adapter-slide`) next.**
  Similar fit but slightly lower score (19/20) and exercises the
  multi-artifact-per-candidate path more aggressively. Better validated
  after documents.
- **Option C — Adopt music notation (`vigor-adapter-music-notation`)
  next.** Forces a time-series IR convention immediately. Useful but
  premature; better as Phase 9 once ADR-0020 (conventional time-series
  form) has been exercised.
- **Option D — Adopt code refactor / test-driven generation next.**
  High score but heavily commoditised by Cursor / Claude Code / Aider /
  Codex. VIGOR's frontier-adjudicator differentiation is least visible
  here.
- **Option E — Skip a new modality this phase; harden the existing
  three.** Low strategic value; framework-modality-neutrality claims
  remain unproven.

## Decision Outcome

Chosen option: **Option A — adopt structured documents as the next
modality.** Slides (Option B) commit to Phase 8 conditionally; music
notation (Option C) commits to Phase 9 conditionally on ADR-0020
landing. Code (Option D) is deferred indefinitely.

### Positive Consequences

- VIGOR proves modality-neutrality on a non-graphics modality.
- No contract churn; existing adapters and runtime are unchanged.
- Demo flows expand to cover technical writing and docs-as-code.
- Toolchain reuse (subprocess wrapper, log parsing) sets a template
  for slides and beyond.
- Pure-MCP plugin path (ADR-0017) exercised opportunistically for
  review-helper tools (`pandoc-mcp`, `latex-mcp`).

### Negative Consequences

- LaTeX toolchain version drift introduces reproducibility risk;
  mitigated by capturing toolchain versions in `CompileResult.metrics`.
- BibTeX vs biber choice: v1 supports BibTeX only; biber is opt-in.
- Real-toolchain CI is impractical (large install footprint); CI uses
  fake-runner pattern from `vigor-adapter-video-manim`.
- `vigor-adapter-doc` becomes the fourth Python package the team
  maintains; documentation, skill manifests, integration tests must be
  ported.

## Validation

The ADR is satisfied when:

- `packages/vigor-adapter-doc/` exists with a passing CI build.
- `latex_document.v1` and `markdown_document.v1` are registered via
  `vigor_core.registry.register_ir`.
- An end-to-end `vigor-runtime` integration test compiles a sample
  LaTeX document, runs the reviewer pack, and produces an
  `ExportBundle` with PDF + source + bibliography + log.
- The Seeds backlog items filed under VIGOR-312b children are closed.

## Pros and Cons of the Options

### Option A — Structured documents
- Good: highest loop-fit score (20/20), no contract change, large
  demand, mature toolchain, demonstrative.
- Good: BibTeX/citation review is a clear and visible iteration story.
- Bad: LaTeX has long-tail toolchain drift; BibTeX vs biber split.
- Bad: real-toolchain CI is heavy (mitigated by fake runners).

### Option B — Slide decks
- Good: high loop-fit score (19/20), large demand, fast compile.
- Good: exercises multi-artifact-per-candidate review path.
- Bad: aesthetic review surface is partly subjective.
- Bad: better validated after the document toolchain is in place,
  since 60–70% is reusable.

### Option C — Music notation
- Good: forces time-series IR convention, opens door to audio /
  animation.
- Bad: smaller user base; defer until ADR-0020 has been adopted.

### Option D — Code refactor / test-driven
- Good: high loop-fit score (18/20), pytest is a free objective
  reviewer.
- Bad: heavily commoditised by existing coding agents; VIGOR's
  differentiation is least visible here.

### Option E — Skip new modality
- Good: zero new maintenance burden.
- Bad: framework-neutrality claims remain unproven; strategic deep-dive
  produced no actionable output.

## Implementation Notes

The adoption brief at `docs/adoption/structured-documents.md` is the
canonical implementation reference. Seeds backlog filed under VIGOR-312b
includes:

- Adapter package skeleton + CI inclusion.
- IR schema (LaTeX + Markdown variants) + registry registration.
- Compile path (latexmk and pandoc subprocess wrappers, sandboxed env
  per ADR-0029).
- Compile-log parser surfacing references/citations/overfull warnings.
- Reviewer pack as enumerated in the adoption brief.
- Deterministic `apply_patch` for the listed objective shapes.
- Export bundle (PDF + source + .bib + log).
- Adapter integration test through `vigor-runtime` (fake runner).
- Real-toolchain test gated on `LATEX_AVAILABLE`.
- Skill manifest under `packages/vigor-adapter-doc/skills/`.

## More Information

- Strategic deep-dive summary: `docs/strategy/next-modalities.md`.
- Adoption brief: `docs/adoption/structured-documents.md`.
- Companion ADR (time-series IR convention, advisory): ADR-0020.
- Parent task: VIGOR-312b (children file Seeds backlog for Phase 7).

## Citations

| Source | URL |
| --- | --- |
| ADR-0001 (VIGOR loop) | `0001-adopt-vigor-loop.md` |
| ADR-0002 (editable IRs) | `0002-use-editable-intermediate-representations.md` |
| ADR-0003 (adapter separation) | `0003-separate-adapters-from-orchestration.md` |
| ADR-0010 (async core interfaces) | `0010-async-core-interfaces.md` |
| ADR-0011 (IR schema versioning) | `0011-ir-schema-versioning.md` |
| ADR-0017 (pure-MCP plugins) | `0017-pure-mcp-plugin-support.md` |
| ADR-0029 (subprocess env hardening) | `0029-multi-tenant-subprocess-env-hardening.md` |
| latexmk | https://mg.readthedocs.io/latexmk.html |
| pandoc | https://pandoc.org/ |
| weasyprint | https://weasyprint.org/ |
