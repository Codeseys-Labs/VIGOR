# Adoption Brief: Slide Decks (`vigor-adapter-slide`)

Status: **Proposed**
Date: 2026-05-15
Parent strategic doc: `docs/strategy/next-modalities.md` (recommended pick #2)
Related ADR: ADR-0019 (Phase 7 commits to documents first; slides land in Phase 8)

## Modality Definition

Slide-deck generation with two IR variants:

- `marp_deck.v1` — Marp Markdown source: YAML frontmatter (theme, size,
  paginate), then `---`-delimited slides, each with markdown body.
- `pptx_deck.v1` — Declarative deck JSON consumed by `python-pptx` for
  cases where richer layout / shape control is needed and pure-text
  Marp authoring is too constrained.

Compile produces multiple observable artifacts per candidate:
- Single PDF (deck.pdf)
- Per-slide PNGs (slide-1.png, slide-2.png, ...)
- Optionally `.pptx` if the request specifies it.

## Why This Modality, And Why Second

Slides combine the editable-IR and fast-compile properties of documents
with a rich enough review surface (per-slide overflow, contrast, image
aspect, structural balance) that the iterative loop is genuinely
valuable. Demand is enormous (every consultant, every internal-comms
team, python-pptx has 5M+ monthly PyPI downloads).

It is **second** rather than first because:

1. The document adapter shares 60–70% of its toolchain (Markdown →
   render → PDF). Building slides after documents reuses code and
   conventions.
2. Slide review surfaces include per-slide PNG inspection, which
   exercises the runtime's "multiple artifacts per candidate" path
   more aggressively than documents do. Better to validate that path
   on a modality whose review failure mode is "obvious overflow"
   rather than on a brand-new modality with brand-new tooling.
3. Slide decks are the natural multi-artifact-per-candidate test case
   for a future `review_bundle` extension if it lands (see
   `docs/strategy/next-modalities.md` §8).

## IR Shape

### `marp_deck.v1`

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | `Literal["marp_deck.v1"]` | |
| `kind` | `Literal["marp_deck"]` | |
| `intent` | `str` | |
| `theme` | `Literal["default", "gaia", "uncover"] \| str` | Default `"default"` |
| `size` | `Literal["16:9", "4:3"]` | Default `"16:9"` |
| `paginate` | `bool` | Default `True` |
| `frontmatter_extra` | `dict[str, str]` | Theme overrides |
| `slides` | `list[MarpSlide]` | |
| `constraints` | `list[str]` | E.g. `"max-bullets-per-slide: 7"` |

`MarpSlide`:

| Field | Type | Notes |
| --- | --- | --- |
| `id` | `str` (`ID_PATTERN`) | |
| `layout` | `Literal["default", "title", "two-column", "image-left", "image-right", "code"]` | |
| `body` | `str` | Raw Marp markdown for this slide |
| `notes` | `str \| None` | Speaker notes |
| `background_image` | `str \| None` | Local path or URL |

### `pptx_deck.v1`

Declarative shape graph: a list of `Slide` records each containing
`shapes: list[Shape]` where `Shape` is a discriminated union of
`TextBoxShape`, `ImageShape`, `TableShape`, `ChartShape`. Each shape
carries `left/top/width/height` in EMUs.

## Compile Path

### Marp
Argv-based subprocess invocation (no shell):

```text
argv: ["marp", <deck_path>,
       "-o", <pdf_path>,
       "--allow-local-files",
       "--theme", <theme_path or theme_name>,
       "--image", "png",
       "--image-dir", <images_dir>]
env:  sandboxed per ADR-0029
timeout_s: from SlideCompileConfig (default 30)
```

### python-pptx
In-process; no subprocess. The adapter constructs a `Presentation`
from the IR, applies layouts, persists `.pptx`, then renders to PDF
via LibreOffice headless:

```text
argv: ["soffice", "--headless", "--convert-to", "pdf",
       "--outdir", <out_dir>, <pptx_path>]
```

## Review Surface

| Reviewer | Type | Checks |
| --- | --- | --- |
| `slide.compile_status.v1` | objective_metric | Marp / soffice exit 0 |
| `slide.overflow.v1` | tool_inspector | Per-slide PNG: detect text touching slide edges (CV-based or layout heuristic) |
| `slide.contrast.v1` | objective_metric | WCAG 2.2 AA contrast ratio for text-on-background pairs (axe-core if available, fallback heuristic) |
| `slide.font_min.v1` | objective_metric | Body text >= 18pt, title text >= 28pt |
| `slide.bullet_density.v1` | objective_metric | <= constraint-defined bullets/slide |
| `slide.aspect_consistency.v1` | objective_metric | Image aspect ratios within tolerance per layout |
| `slide.asset_resolution.v1` | tool_inspector | Image paths resolve, sizes >= layout-required minimum |
| `slide.narrative.v1` (optional) | model_critic | LLM critic for slide-to-slide narrative flow |

The runtime calls `review` per `ObservableArtifact`; the adapter emits
the deck PDF as one artifact and per-slide PNGs as additional
artifacts. Reviewers receive whichever artifact matches their
`media_type` preference. A future `review_bundle` facility would let
reviewers consume the whole set; out of scope for v1.

## Patch Pattern

Slide patches are slide-level edits, not deck-level rewrites:

| Objective shape | Action |
| --- | --- |
| `slide:<id> reduce-bullets: <n>` | Trim `body` to <=n bullets |
| `slide:<id> change-layout: <layout>` | Update `MarpSlide.layout` and reflow |
| `slide:<id> increase-contrast` | Switch theme color tokens |
| `slide:<id> add-image: <prompt>` | Insert image placeholder, defer to image-gen subadapter |
| `deck reflow: <max-slides>` | Merge sparse slides until count <= max |

`apply_patch` is deterministic for the listed shapes. Freeform
backend-proposed patches re-validate via `validate_ir`.

## Export

| Export | Always | Notes |
| --- | --- | --- |
| `final_artifact` (PDF) | yes | Canonical deck artifact |
| `slides_png` (PNGs) | yes | Per-slide rendering, used by reviewers |
| `source` (Marp md) | yes | The IR source |
| `pptx` | opt-in | python-pptx export when `target=pptx` requested |
| `notes` | opt-in | Per-slide speaker notes as separate text file |

## MCP Server Availability

| MCP server | Quality | Notes |
| --- | --- | --- |
| `marp-mcp` | functional | Wraps `marp-cli`; usable in review-only mode |
| `pptx-mcp` | functional | Wraps `python-pptx`; can build slides from prompts |
| `pdf-mcp` (generic) | functional | Useful for PDF inspection in reviewers |

Pure-MCP plugins (ADR-0017) for slide style-checking can surface as
ambient model-critic helpers.

## Real-World Demand Evidence

- **python-pptx**: 5M+ monthly PyPI downloads.
- **Marp**: 14k+ GitHub stars, broad use in technical talks.
- **Enterprise**: every B2B SaaS vendor produces sales decks; legal
  and policy teams produce internal decks; researchers produce
  conference slides.
- VIGOR demo opportunity: "make me a 12-slide deck on X under WCAG-AA
  contrast with no overflow" exercises the loop visibly.

## MVP Scope (Phase 8 Acceptance)

- [ ] Package skeleton `packages/vigor-adapter-slide/`.
- [ ] `marp_deck.v1` IR registered.
- [ ] Marp compile path with sandboxed subprocess.
- [ ] Reviewer pack: compile_status, overflow, contrast, font_min,
      bullet_density, aspect_consistency, asset_resolution.
- [ ] `apply_patch` deterministic for the listed objective shapes.
- [ ] Export: PDF + per-slide PNGs + source.
- [ ] Adapter integration test through `vigor-runtime` with fake runner.
- [ ] Real-toolchain integration test gated on `MARP_AVAILABLE`.

## Phase 8.1 (follow-up)

- [ ] `pptx_deck.v1` IR + python-pptx compile path.
- [ ] LibreOffice-headless PDF renderer for the pptx variant.
- [ ] `review_bundle` extension prototype if cross-artifact reviewers
      become necessary.

## Risks

| Risk | Mitigation |
| --- | --- |
| Marp theme drift | Pin Marp version in adapter pyproject extras; capture version in metrics |
| Per-slide PNG dimensions vary by theme | Reviewers normalise to fixed virtual canvas |
| Aesthetic review subjectivity | Treat narrative reviewer as low-weight optional; hard reviewers are objective |
| Image asset trust | Image URLs subject to ADR-0029 sandboxing; local-file-only by default |

## Out Of Scope (V1)

- Animation / transitions (Marp supports limited; not reviewed).
- Live presenter mode.
- Voice narration (orthogonal modality, see audio cluster).
- Brand-template enforcement (corporate theming) — future enterprise ADR.
