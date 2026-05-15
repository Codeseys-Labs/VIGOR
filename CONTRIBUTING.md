# Contributing to VIGOR

Thank you for contributing. VIGOR is a generate-compile-review framework; the bar for landing code is kept high because downstream projects depend on stable schemas and contracts.

## Quick Start

```bash
# Clone
git clone https://github.com/Codeseys-Labs/VIGOR.git
cd VIGOR

# Install uv: https://docs.astral.sh/uv/getting-started/installation/

# Install the full workspace in editable mode.
uv sync --all-packages --all-extras

# Run the quality gate.
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest

# Try the end-to-end demo.
uv run vigor demo --goal "Hello VIGOR" --runs-dir runs
```

## Layout

```
packages/
  vigor-core/                          # schemas, interfaces, archive, scoring, frontier
  vigor-runtime/                       # orchestrator, echo backend, CLI, toy adapter
  vigor-backend-strands/               # optional Strands-backed AgentBackend
  vigor-backend-claude-agent-sdk/      # optional Claude Agent SDK-backed AgentBackend
  vigor-adapter-photo/                 # photo editing adapter (MVP)
examples/
  echo-toy-demo/                       # smallest runnable demo
docs/
```

## Quality Gate

Every PR must pass:

1. `uv run ruff check .`
2. `uv run ruff format --check .`
3. `uv run mypy` (strict)
4. `uv run pytest`

## Regenerating Adapter Skills

Each adapter ships a generated `SKILL.md` derived from its registered IR JSON Schema (see ADR-0015). If you change an adapter's IR module, regenerate the skill files and commit them in the same PR:

```bash
uv run python scripts/regen_skills.py
git add packages/*/skills/
```

The `skill-drift` GitHub Actions workflow runs this script on every PR and fails if the regenerated output differs from what was committed. Regenerate locally before pushing to avoid red CI.

## Schema Changes

1. Bump the schema version (see ADR-0011): add a new `Literal[...]` version instead of editing the old one if the change is not fully backward compatible.
2. Provide a migration function.
3. Add round-trip tests in `packages/vigor-core/tests/test_schemas.py`.

## Interface Changes

1. Discuss in an ADR first.
2. Keep `AgentBackend`, `ToolBackend`, and `DomainAdapter` small and async.
3. Never couple domain adapters to specific agent SDKs.

## Commits And PRs

1. Use clear commit messages. Prefer imperative mood ("add photo XMP export").
2. Reference the ADR or doc a change supports.
3. Keep PRs focused. Schema + runtime + adapter + backend changes should usually be separate PRs.

## Dependencies

1. Prefer upper-bounded pins in `pyproject.toml` (`strands-agents>=1.37,<2`).
2. Keep `uv.lock` in sync (`uv lock`).
3. Optional integrations belong behind PEP 621 `optional-dependencies` extras.
