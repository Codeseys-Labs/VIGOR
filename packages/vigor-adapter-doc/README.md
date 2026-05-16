# vigor-adapter-doc

VIGOR domain adapter for structured documents (LaTeX + Markdown -> PDF).

This package is the Phase 7 deliverable committed by ADR-0019. The
generate-compile-review loop is exercised by:

1. Generating `latex_document.v1` or `markdown_document.v1` IR.
2. Compiling via `latexmk` or `pandoc` subprocesses (sandboxed per
   ADR-0029).
3. Reviewing the compile log + PDF for overfull boxes, undefined
   references, unresolved citations, missing fonts, and hyperref
   errors.
4. Applying deterministic patches that re-run compile-then-review until
   the budget is exhausted or the run accepts.

## Status

**Skeleton.** This commit lands the package layout, workspace
registration, plugin manifest, and quality-gate plumbing. The IR
modules, adapter class, compile path, reviewers, `apply_patch`, and
export bundle are tracked under follow-up Seeds tasks rooted at
`VIGOR-c916`:

- `VIGOR-5f0b` — `latex_document.v1` + `markdown_document.v1` IR
  schemas (Pydantic v2 strict, registered via
  `vigor_core.registry.register_ir`).
- Subsequent children — compile path, reviewer pack, patch shapes,
  export bundle, `vigor-runtime` integration test, real-toolchain
  test gated on `LATEX_AVAILABLE`.

## References

- `docs/adoption/structured-documents.md` — canonical implementation
  brief.
- `docs/adr/0019-adopt-structured-documents-modality.md` — decision
  record.
- `docs/strategy/next-modalities.md` — strategic deep-dive.
