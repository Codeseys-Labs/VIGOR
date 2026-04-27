# ADR-0009: Use A Single UV Monorepo With `packages/` And `examples/`

Status: Accepted

Date: 2026-04-26

## Context

The readiness assessment flagged prerequisite C3: monorepo versus polyrepo layout was undecided. ADR-0007 defines VIGOR as a package family rather than a single monolithic package.

UV provides first-class workspace support: a root `pyproject.toml` declares workspace members under `[tool.uv.workspace]`, cross-package dependencies are resolved through `[tool.uv.sources]` with `workspace = true`, and the workspace is installed editable with `uv sync` and locked with `uv.lock`.

## Decision

VIGOR is a single monorepo at `Codeseys-Labs/VIGOR`, organized as a UV workspace.

Current directory layout:

```text
VIGOR/
  LICENSE
  README.md
  pyproject.toml                  # workspace root, virtual package
  uv.lock
  ruff.toml                       # shared lint config
  packages/
    vigor-core/
    vigor-runtime/
    vigor-backend-strands/
    vigor-backend-claude-agent-sdk/
    vigor-adapter-photo/
    vigor-adapter-video-manim/
    vigor-adapter-cad/
    vigor-harness/
  examples/
    echo-toy-demo/
  docs/
  .github/
    workflows/ci.yml
    CODEOWNERS
  work-log.md
```

Rules:

1. The repo root is a virtual UV workspace (`package = false`).
2. Each package owns its own `pyproject.toml`, `src/<import_module>/` layout, and `tests/`. For example, distribution `vigor-core` uses import module `vigor_core`.
3. Cross-package dependencies use `[tool.uv.sources]` with `workspace = true`.
4. All packages share `requires-python = ">=3.11"`.
5. Examples are workspace members so they get editable installs and exercise real packages.
6. `uv.lock` is checked into the repo root.
7. CI runs `uv sync --locked --all-packages --all-extras`, lint, type-check, and tests.

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| Polyrepo | More overhead, harder cross-package refactors. |
| Single package with namespace submodules | Forces users to install every modality dependency. |
| Hatch-only workspace | Works, but UV gives a first-class resolver + lockfile flow for the whole tree. |

## Citations

| Source | URL |
| --- | --- |
| UV workspaces | https://docs.astral.sh/uv/concepts/projects/workspaces/ |
| UV sources | https://docs.astral.sh/uv/concepts/projects/dependencies/#workspace-member |
| PEP 621 | https://packaging.python.org/en/latest/specifications/pyproject-toml/ |
