# ADR-0009: Use A Single UV Monorepo With `packages/` And `examples/`

Status: Accepted

Date: 2026-04-26

## Context

The readiness assessment flagged prerequisite C3: monorepo versus polyrepo layout was undecided. ADR-0007 lists `vigor-core`, `vigor-runtime`, two backends, three adapters, and an `examples/` tree as sibling paths but does not specify repo layout.

UV (Astral) provides first-class workspace support: a root `pyproject.toml` declares workspace members under `[tool.uv.workspace]`, cross-package dependencies are resolved through `[tool.uv.sources]` with `workspace = true`, and the entire workspace is installed editable with one `uv sync` and locked with one `uv.lock`.

## Decision

VIGOR is a single monorepo at `Codeseys-Labs/VIGOR`, organized as a UV workspace.

Directory layout:

```text
VIGOR/
  LICENSE
  README.md
  pyproject.toml                  # workspace root, virtual package
  uv.lock
  ruff.toml                       # shared lint config
  packages/
    vigor-core/
      pyproject.toml
      src/vigor_core/
      tests/
    vigor-runtime/
    vigor-backend-strands/
    vigor-backend-claude-agent-sdk/
    vigor-adapter-photo/
  examples/
    echo-toy-demo/
  docs/
  .github/
    workflows/ci.yml
  work-log.md
```

Rules:

1. The repo root is a virtual UV workspace that depends on every workspace member for dev install.
2. Each package owns its own `pyproject.toml`, `src/<dist_name>/` layout, and `tests/`.
3. Cross-package dependencies use `[tool.uv.sources]` with `workspace = true`.
4. All packages share `requires-python = ">=3.11"` and Pydantic v2 as a dependency.
5. Examples are workspace members so they get editable installs and can exercise real adapters.
6. `uv.lock` is checked into the repo root.
7. CI runs `uv sync --all-packages` then lint and tests.

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| Polyrepo (one GitHub repo per package) | More overhead, harder cross-package refactors, and VIGOR is at the "define shared contracts" stage where a single history is valuable. |
| Single package with namespace submodules | Forces every downstream user to install all dependencies (Manim, rawpy, ML scorers) even for a small adapter. |
| Monorepo with Hatch workspaces only | Works, but UV also covers dependency resolution and lockfile discipline for the whole tree with less ceremony. |
| Monorepo with Poetry workspaces | Poetry does not yet have native workspace semantics equivalent to UV. |

## Consequences

Positive:

1. Single source of truth, single CI pipeline, single lockfile.
2. Cross-package refactors land atomically.
3. Editable installs everywhere out of the box.
4. Downstream adopters can depend on each package independently from PyPI later.

Negative:

1. Growing the repo too large eventually hurts CI time; plan to shard CI jobs by package when needed.
2. One shared lockfile means one package's dependency bump affects everyone; that is usually a feature, not a bug.
3. Cloning the repo pulls every package. Documentation should make it clear which package a user needs.

## Implementation Notes

The root `pyproject.toml` minimum shape:

```toml
[project]
name = "vigor"
version = "0.0.0"
requires-python = ">=3.11"
description = "Verifiable Iterative Generation Over Representations"

[tool.uv]
package = false
default-groups = ["dev"]

[tool.uv.workspace]
members = ["packages/*", "examples/*"]
```

Each workspace member declares cross-package deps like this:

```toml
[project]
name = "vigor-runtime"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["pydantic>=2.8", "typer>=0.12", "vigor-core"]

[tool.uv.sources]
vigor-core = { workspace = true }
```

## Citations

| Source | URL |
| --- | --- |
| UV workspaces | https://docs.astral.sh/uv/concepts/projects/workspaces/ |
| UV sources (workspace) | https://docs.astral.sh/uv/concepts/projects/dependencies/#workspace-member |
| UV project config | https://docs.astral.sh/uv/concepts/projects/config/ |
| PEP 621 project metadata | https://packaging.python.org/en/latest/specifications/pyproject-toml/ |
