# VIGOR

**VIGOR** stands for **Verifiable Iterative Generation Over Representations**.

VIGOR is a proposed modality-agnostic framework for AI systems that generate, compile, review, and refine editable artifacts. It generalizes the central insight behind VIGA: produce an executable or editable representation, materialize that representation through a toolchain, review the observable result, and iterate with evidence.

## Core Thesis

High-reliability AI generation workflows should expose four things:

1. An editable representation, not only a final asset.
2. A compiler, renderer, simulator, or execution engine that materializes the representation.
3. Reviewers that inspect the materialized artifact with objective metrics, model critics, domain validators, and optional human feedback.
4. Provenance that records why the artifact changed, what evidence supported it, and when the loop stopped.

## Documentation Map

| Document | Purpose |
| --- | --- |
| [docs/vigor-framework.md](docs/vigor-framework.md) | Main VIGOR architecture and framework contract |
| [docs/research/vigor-research-synthesis.md](docs/research/vigor-research-synthesis.md) | Research synthesis with citations |
| [docs/comparisons/vigor-vs-systems.md](docs/comparisons/vigor-vs-systems.md) | Comparison against related systems and SDK options |
| [docs/readiness/implementation-readiness.md](docs/readiness/implementation-readiness.md) | Implementation readiness and residual blockers |
| [docs/readiness/current-commit-state.md](docs/readiness/current-commit-state.md) | Commit-state documentation |
| [docs/roadmap.md](docs/roadmap.md) | Current roadmap and phase status |
| [docs/schemas/runtime-schemas.md](docs/schemas/runtime-schemas.md) | Runtime object schemas |
| [docs/scoring-adjudication.md](docs/scoring-adjudication.md) | Scoring and adjudication policy |
| [docs/adoption/aiecf.md](docs/adoption/aiecf.md) | AIECF-style video generation adoption |
| [docs/adoption/agentic-cad.md](docs/adoption/agentic-cad.md) | CAD adoption |
| [docs/adoption/photo-editing.md](docs/adoption/photo-editing.md) | Photo-editing adoption |
| [docs/templates/domain-adapter-spec.md](docs/templates/domain-adapter-spec.md) | Domain adapter template |
| [docs/templates/review-report-schema.md](docs/templates/review-report-schema.md) | Review report schema template |
| [docs/adr](docs/adr) | Architecture Decision Records |

## Packages

```text
packages/
  vigor-core/                        # schemas, interfaces, archive, scoring, frontier
  vigor-runtime/                     # orchestrator, echo backend, CLI, toy adapter
  vigor-agent/                       # configurable agent: AgentConfig + router + CLI
  vigor-mcp/                         # MCP-as-ToolBackend bridge (stdio + http/sse)
  vigor-backend-strands/             # optional Strands-backed AgentBackend
  vigor-backend-claude-agent-sdk/    # optional Claude Agent SDK AgentBackend
  vigor-adapter-photo/               # photo editing adapter with masks + XMP export
  vigor-adapter-video-manim/         # standalone Manim video adapter
  vigor-adapter-cad/                 # OpenSCAD first-slice CAD adapter
  vigor-adapter-doc/                 # structured documents (LaTeX + Markdown -> PDF) [skeleton]
  vigor-harness/                     # Meta-Harness-style evaluator
examples/
  echo-toy-demo/                     # smallest runnable demo
  agent-demo/                        # one configurable agent across photo + video + CAD
```

## Generalized agent

`vigor-agent` lets you ship one configurable VIGOR agent that pulls in any
combination of adapters and MCP servers from a YAML/JSON config. See
`docs/adr/0014-generalized-agent-config.md` for the schema rationale.

```bash
uv run vigor-agent run --config agent.yaml task.json
```

A run that was interrupted mid-iteration leaves an
`iteration_checkpoint.json` next to the per-candidate JSONs. Resume the
run from its most recent iteration boundary (no work between iterations
is re-done):

```bash
uv run vigor-agent resume --config agent.yaml <run_id>
```

See `docs/adr/0036-iteration-checkpoint-resume.md` for the rationale.
Resume starts a fresh wall-clock and cost counter; tighten the
`Budgets.max_cost_usd` / `max_wall_clock_s` on the archived task before
resuming if you require an end-to-end ceiling.

A runnable end-to-end example lives in `examples/agent-demo/` — one
agent.yaml declares all three first-slice adapters (photo, video-manim,
cad), an echo backend, and one MCP server, and the same CLI dispatches
each modality through `routing.strategy: modality_match`:

```bash
uv run vigor-agent run --config examples/agent-demo/agent.yaml \
  examples/agent-demo/tasks/photo.json
uv run vigor-agent run --config examples/agent-demo/agent.yaml \
  examples/agent-demo/tasks/video.json
uv run vigor-agent run --config examples/agent-demo/agent.yaml \
  examples/agent-demo/tasks/cad.json
```

Adapters are also published as **Open Plugin Spec v1** packages (each
ships `.plugin/plugin.json` + a generated `SKILL.md`) so the same
package drops into Claude Code, Hermes, Strands, Goose, and other
plugin hosts. See `docs/adr/0015-open-plugin-spec-compatibility.md`.

## Getting Started

VIGOR is a Python 3.11+ UV workspace.

```bash
git clone https://github.com/Codeseys-Labs/VIGOR.git
cd VIGOR
uv sync --all-packages --all-extras

# Run the end-to-end toy adapter demo.
uv run vigor demo --goal "Hello VIGOR" --runs-dir runs --task-id demo_0001

# Full quality gate.
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

## Current Shipped Slices

| Area | Status |
| --- | --- |
| Runtime skeleton | shipped |
| Patch loop | shipped |
| Sequential best-of-N | shipped |
| Parallel best-of-N | shipped: opt-in via `Budgets.parallel_candidates` (ADR-0034) |
| Iteration checkpoint + opt-in resume | shipped: `Orchestrator.resume(run_id)` / `vigor-agent resume <run_id>` (ADR-0036) |
| Photo adapter | shipped: globals, heuristic masks, local rendering, histogram critic, JSON/XMP/mask exports |
| Video adapter | shipped: standalone Manim adapter with fake-runner tests; real Manim optional |
| CAD adapter | shipped: OpenSCAD source generation + pure-Python validators |
| Harness evaluator | shipped: candidate/split/report schemas and evaluator over `TaskSpec` splits |

## External Blockers

| Item | Required Input |
| --- | --- |
| AIECF integration | concrete repo access/license/pipeline verification |
| VideoScore2 hard scorer | GPU/model-serving decision |
| VLM aesthetic critic | provider credentials and licensed test corpus |
| CAD mesh/FEM | CAD kernel/solver/material/load-case corpus |

See `CONTRIBUTING.md` and `SECURITY.md` for governance and vulnerability disclosure.
