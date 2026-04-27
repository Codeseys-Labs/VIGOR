# VIGOR

**VIGOR** stands for **Verifiable Iterative Generation Over Representations**.

VIGOR is a proposed modality-agnostic framework for AI systems that generate, compile, review, and refine editable artifacts. It generalizes the central insight behind VIGA: do not ask a model to produce a final opaque output in one pass. Ask it to produce an executable or editable representation, materialize that representation through a toolchain, review the observable result, and iterate with evidence.

VIGA applies this pattern to inverse graphics: generated Blender or PowerPoint programs are rendered, visually verified, and revised. VIGOR extends the same generate-compile-review loop across video generation, CAD, photo editing, code, documents, audio, robotics, data workflows, simulations, and mixed multimodal artifacts.

## Core Thesis

High-reliability AI generation workflows should expose four things:

1. An editable representation, not only a final asset.
2. A compiler, renderer, simulator, or execution engine that materializes the representation.
3. Reviewers that inspect the materialized artifact with objective metrics, model critics, domain validators, and optional human feedback.
4. Provenance that records why the artifact changed, what evidence supported it, and when the loop stopped.

The target shape is:

```text
goal + references + constraints
  -> representation planner
  -> generator
  -> editable intermediate representation
  -> compiler / renderer / simulator
  -> observable artifact
  -> reviewer ensemble
  -> patch plan
  -> next candidate or final artifact
```

## Why VIGOR Exists

One-shot generation is often impressive but brittle. It fails when outputs must satisfy spatial, aesthetic, physical, semantic, safety, or engineering constraints. A single prompt can produce a plausible image, video, CAD model, UI, or code patch, but it usually cannot guarantee that the output is editable, reproducible, verifiable, and aligned with downstream tooling.

VIGOR treats generation as an evidence-driven optimization loop over artifacts.

## Documentation Map

| Document | Purpose |
| --- | --- |
| [docs/vigor-framework.md](docs/vigor-framework.md) | Main VIGOR architecture and framework contract |
| [docs/research/vigor-research-synthesis.md](docs/research/vigor-research-synthesis.md) | Research synthesis with citations for VIGA, Meta-Harness, TRIBE v2, Claude Design, and agent patterns |
| [docs/comparisons/vigor-vs-systems.md](docs/comparisons/vigor-vs-systems.md) | Comparison of VIGOR against related systems, papers, SDKs, and implementation options |
| [docs/readiness/implementation-readiness.md](docs/readiness/implementation-readiness.md) | Readiness assessment for implementing VIGOR recommendations |
| [docs/roadmap.md](docs/roadmap.md) | Phased implementation and validation roadmap |
| [docs/schemas/runtime-schemas.md](docs/schemas/runtime-schemas.md) | Runtime object schemas for tasks, IRs, compile results, patches, frontiers, exports, and provenance |
| [docs/scoring-adjudication.md](docs/scoring-adjudication.md) | Score normalization, reviewer weighting, hard gates, disagreement handling, and calibration |
| [docs/adoption/aiecf.md](docs/adoption/aiecf.md) | Adoption plan for AI Education Content Factory style video generation |
| [docs/adoption/agentic-cad.md](docs/adoption/agentic-cad.md) | Adoption plan for agentic CAD and simulation workflows |
| [docs/adoption/photo-editing.md](docs/adoption/photo-editing.md) | Adoption plan for agentic photo editing and editor adapters |
| [docs/templates/domain-adapter-spec.md](docs/templates/domain-adapter-spec.md) | Template for adding a new modality/domain adapter |
| [docs/templates/review-report-schema.md](docs/templates/review-report-schema.md) | Standard reviewer and score-report schema |
| [docs/adr](docs/adr) | Architecture Decision Records |

## ADRs

| ADR | Decision |
| --- | --- |
| [ADR-0001](docs/adr/0001-adopt-vigor-loop.md) | Adopt generate-compile-review as the core framework loop |
| [ADR-0002](docs/adr/0002-use-editable-intermediate-representations.md) | Use editable intermediate representations as first-class outputs |
| [ADR-0003](docs/adr/0003-separate-adapters-from-orchestration.md) | Separate domain adapters from the orchestration runtime |
| [ADR-0004](docs/adr/0004-reviewer-ensemble-and-adjudicator.md) | Use reviewer ensembles plus an adjudicator instead of self-review |
| [ADR-0005](docs/adr/0005-trajectory-memory-and-provenance.md) | Store trajectory memory and artifact provenance as core state |
| [ADR-0006](docs/adr/0006-meta-harness-inspired-outer-loop.md) | Add a Meta-Harness-inspired outer loop for harness optimization |
| [ADR-0007](docs/adr/0007-sdk-agnostic-core-with-optional-agent-backends.md) | Build VIGOR as an SDK-agnostic core with optional Strands/Claude Agent SDK backends |

## Initial Target Domains

The first implementation focus should stay on photo editing, AIECF-style video generation, and CAD. Other rows are future examples used to keep the framework contract honest.

| Domain | Editable Representation | Compiler / Renderer | Reviewers |
| --- | --- | --- | --- |
| Agentic video generation | Storyboard, script, scene graph, Manim/Blender/HTML code | Manim, Blender, ffmpeg, browser renderers | VideoScore2, VLM critique, continuity checks, accessibility/readability checks |
| CAD | Parametric CAD graph, OpenSCAD/FreeCAD script, feature tree | CAD kernel, mesh exporter, slicer, FEM simulator | Geometry validity, constraints, manufacturability, simulation, cost/material metrics |
| Photo editing | XMP-like recipe, mask graph, layer stack, LUT | rawpy/OpenCV, Lightroom XMP, Photoshop UXP, GIMP/GEGL | Aesthetic critic, histogram/clipping metrics, skin/identity preservation, artifact detection |
| UI/design | HTML/CSS/React, Figma-like scene graph, design tokens | Browser, Playwright, screenshot renderer | Visual design rubric, accessibility, interaction tests, responsive layout checks |
| Code | Patch plan, source diffs, generated files | Compiler, test runner, container, deploy preview | Tests, type checks, security scans, code review agents |

## Name

VIGOR is intentionally close to VIGA:

```text
VIGA  = Vision-as-Inverse-Graphics Agent
VIGOR = Verifiable Iterative Generation Over Representations
```

VIGA is a powerful instance. VIGOR is the generalized framework.

## Getting Started

VIGOR is a Python 3.11+ UV workspace. Install [uv](https://docs.astral.sh/uv/) and then:

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

Monorepo layout:

```
packages/
  vigor-core/                        # schemas, interfaces, archive, scoring, frontier
  vigor-runtime/                     # orchestrator, echo backend, CLI, toy adapter
  vigor-backend-strands/             # optional Strands-backed AgentBackend
  vigor-backend-claude-agent-sdk/    # optional Claude Agent SDK AgentBackend
  vigor-adapter-photo/               # photo editing adapter (MVP)
examples/
  echo-toy-demo/                     # smallest runnable demo
```

See `CONTRIBUTING.md` and `SECURITY.md` for governance and vulnerability disclosure.
