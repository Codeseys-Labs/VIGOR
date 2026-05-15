# Adoption Brief: Structured Documents (`vigor-adapter-doc`)

Status: **Proposed**
Date: 2026-05-15
Parent strategic doc: `docs/strategy/next-modalities.md` (recommended pick #1)
Related ADR: ADR-0019 (proposed)

## Modality Definition

Single-source structured document compilation. Two IR variants ship in v1:

- `latex_document.v1` — LaTeX source + bibliography references + frontmatter.
- `markdown_document.v1` — Pandoc-flavor Markdown + frontmatter (YAML).

Both compile to PDF as the canonical observable artifact. Optional
side-products: HTML, EPUB, normalized BibTeX `.bib`.

## Why This Modality, And Why First

VIGOR's value-prop is the iterative loop: generate → compile → review →
patch → re-compile. Structured documents map onto that loop almost
perfectly:

- **L1 (symbolic IR).** LaTeX/Markdown are textual; patches are line
  diffs.
- **L2 (fast deterministic compile).** `latexmk -pdf` and `pandoc -o
  out.pdf` complete in 5–30s for typical papers.
- **L3 (objective reviewers).** Overfull boxes, undefined references,
  unresolved citations, missing fonts, hyperref errors are all
  measurable from the compile log + PDF inspection. No model-critic
  required for the first pass.
- **L4 (iteration changes outcome).** A second compile fixes the
  citations the first compile reported missing — a textbook example of
  what one-shot generation cannot do well.

It is also a modality VIGOR can demo against use cases the
photo/video/CAD adapters cannot serve: research papers, technical
reports, legal/policy briefs, docs sites.

## IR Shape

### `latex_document.v1`

Pydantic v2 model registered through `vigor_core.registry.register_ir`
per ADR-0011. Strict mode + camelCase aliases per VIGOR house style.

Fields:

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | `Literal["latex_document.v1"]` | Pinned per ADR-0011 |
| `kind` | `Literal["latex_document"]` | Discriminator |
| `intent` | `str` | Free-text natural-language intent |
| `document_class` | `Literal["article", "report", "book", "beamer", "ieeeconf"]` | Default `"article"` |
| `preamble` | `str` | `\usepackage{...}` block |
| `body` | `str` | Everything between `\begin{document}` and `\end{document}` |
| `bibliography` | `list[BibEntry]` | BibTeX entries |
| `frontmatter` | `DocumentFrontmatter` | Title, author, abstract, keywords |
| `constraints` | `list[str]` | E.g. `"max-pages: 8"`, `"must-cite: smith2024"` |

### `markdown_document.v1`

Same shape minus the LaTeX-specific fields, plus:

| Field | Type | Notes |
| --- | --- | --- |
| `pandoc_format` | `Literal["markdown", "commonmark_x", "gfm"]` | Default `"markdown"` |

Both share `BibEntry` and `DocumentFrontmatter`. Both register via
`register_ir`.

## Compile Path

### LaTeX
The adapter writes `main.tex` + `refs.bib` into the per-candidate
artifacts directory, then invokes `latexmk` via the Python
`asyncio.create_subprocess` argv-based API (no shell):

```text
argv: ["latexmk", "-pdf", "-interaction=nonstopmode", "-halt-on-error",
       "-output-directory", <artifacts_dir>, <src_path>]
env:  sandboxed (PATH, HOME, LANG, optionally LATEXMKRC) per ADR-0029
timeout_s: from DocCompileConfig (default 60)
```

### Markdown
```text
argv: ["pandoc", <src_path>, "-o", <pdf_path>,
       "--pdf-engine", <weasyprint|xelatex>,
       "--citeproc", "--bibliography", <bib_path>,
       <frontmatter args>]
```

### Determinism + safety
- Subprocess timeout from `DocCompileConfig`.
- Subprocess env follows ADR-0029 default-drop posture (only `PATH`,
  `HOME`, `LANG`, `LATEXMKRC` if present).
- `latexmk -interaction=nonstopmode -halt-on-error` to avoid prompts.
- Capture `main.log`, parse for `! ` errors, `LaTeX Warning: ...`,
  `Reference \w+ on page \d+ undefined`, `Citation \w+ on page \d+
  undefined`, `Overfull \\hbox`, `Underfull \\hbox`, missing-font
  warnings.

## Review Surface

Reviewer pack (`vigor-adapter-doc` ships):

| Reviewer | Type | What it checks |
| --- | --- | --- |
| `doc.compile_status.v1` | objective_metric | `latexmk` exit code 0; log clean of `! ` errors |
| `doc.references.v1` | tool_inspector | log scan for `Reference \w+ undefined` |
| `doc.citations.v1` | tool_inspector | log scan for `Citation \w+ undefined`; cross-check `\cite{}` keys against `.bib` |
| `doc.overfull.v1` | objective_metric | count of `Overfull \\hbox` warnings exceeding threshold |
| `doc.fonts_embedded.v1` | tool_inspector | `pdffonts main.pdf` or `qpdf --json` to verify fonts embedded |
| `doc.page_budget.v1` | objective_metric | `len(pages) <= constraints["max-pages"]` |
| `doc.constraints.v1` | tool_inspector | per-`Constraint` text matching against rendered text (`pdftotext`) |
| `doc.prose.v1` (optional) | model_critic | LLM critic for clarity / grammar; opt-in, low weight |

Reviewer pack lives at
`packages/vigor-adapter-doc/src/vigor_adapter_doc/reviewers.py`.

## Patch Pattern

LaTeX/Markdown patches are line-level edits over `body` and `preamble`.
`apply_patch` parses `PatchPlan.objectives` for free-text directives:

| Objective shape | Action |
| --- | --- |
| `add-package: <name>` | Append `\usepackage{<name>}` to preamble |
| `add-citation: <key>` | Append `\cite{<key>}` at insertion marker |
| `fix-overfull: <line>` | Insert `\sloppy` block around the line |
| `trim-section: <ref>` | Truncate text under `\section{<ref>}` to fit |
| `<freeform>` | Backend-proposed full rewrite of the section |

Backend-proposed `PatchProposal.patch` carries the full new IR body for
the freeform case; structural directives are applied deterministically.

## Export

`ExportBundle.exports` carries:

- `final_artifact` → `main.pdf`
- `source` → `main.tex` (or `main.md`)
- `bibliography` → `refs.bib`
- `compile_log` → `main.log` (lossiness warning: stripped of timing
  info, otherwise verbatim)
- Optional `html` / `epub` siblings via opt-in `pandoc` re-runs.

Lossiness entries:
- "PDF font subsetting may drop unused glyphs" → noted on PDF export.
- "Markdown → PDF round-trip is lossy on raw-html blocks" → noted on
  Markdown variant.

## MCP Server Availability (As Of 2026-05)

| MCP server | Quality | Notes |
| --- | --- | --- |
| `pandoc-mcp` (community) | functional | Wraps `pandoc` CLI; useful for review-only flows; not used for compile in v1 |
| `latex-mcp` (third-party) | uneven | Not relied on in v1; direct subprocess preferred |
| `bibtex-mcp` (third-party) | minimal | Optional for normalising `.bib` |

The adapter does **not** require any MCP server. Pure-MCP plugins
(ADR-0017) may surface review-helper tools (e.g. style-check, citation
lookup) as ambient tools for the model-critic reviewer.

## Real-World Demand Evidence

- **arXiv submissions** are LaTeX-first. Researchers regularly iterate
  on overfull/citation/page-budget errors today by hand.
- **GitBook / MkDocs / docs sites** are Markdown-first. Doc-as-code
  pipelines exist but lack iterative quality-gate-driven authoring.
- **Pandoc** has 50k+ GitHub stars; LaTeX has unbounded incumbency.
- VIGOR's frontier-adjudicator differentiation is highly visible:
  "compile broke twice, third candidate succeeded with all constraints
  met" is a clear demo flow.

## MVP Scope (Phase 7 Acceptance)

- [ ] Package skeleton `packages/vigor-adapter-doc/` with `pyproject.toml`,
      src layout, `py.typed`, CI inclusion.
- [ ] `latex_document.v1` and `markdown_document.v1` IR models registered
      via `register_ir`.
- [ ] `compile` for LaTeX (latexmk) and Markdown (pandoc) with
      sandboxed subprocess env per ADR-0029.
- [ ] Compile-log parser surfacing references/citations/overfull
      warnings into `CompileResult.warnings` and `RuntimeErrorRecord`s.
- [ ] Reviewer pack as listed above (model-critic optional).
- [ ] `apply_patch` deterministic for the listed objective shapes;
      freeform proposals validated through `validate_ir`.
- [ ] `export` writes PDF + source + `.bib` + log.
- [ ] Adapter end-to-end test through `vigor-runtime` with a fake
      runner (no real `latexmk` in CI; mirror the Manim adapter's
      injectable-runner pattern).
- [ ] Real-toolchain integration test marked `@pytest.mark.optional`,
      gated on `LATEX_AVAILABLE` env var.
- [ ] Skill manifest under `packages/vigor-adapter-doc/skills/` per
      `vigor-adapter-photo` precedent.

## Risks

| Risk | Mitigation |
| --- | --- |
| Toolchain version drift | Capture `latexmk --version` and `pandoc --version` in `CompileResult.metrics` |
| Bibliography backend split (BibTeX vs biber) | v1 supports BibTeX only; biber added as opt-in via config |
| `pdflatex` infinite loop on bad input | `-halt-on-error -interaction=nonstopmode` + subprocess timeout |
| Real-toolchain CI cost | Direct subprocess in CI is unsafe; CI uses fake runner only |
| Locale / Unicode issues | Force `LANG=C.UTF-8` in sandboxed env |

## Out Of Scope (V1)

- Word/.docx output (pandoc supports it; defer to v2).
- Live preview / continuous compile.
- Bibliography-from-DOI auto-fill (third-party tool, future seed).
- Inline figure generation from prompts (orthogonal modality).
