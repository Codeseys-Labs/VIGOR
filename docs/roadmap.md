# VIGOR Roadmap

## Roadmap Principles

VIGOR proves modality-agnostic value by running distinct adapters through the same runtime. The current codebase now exercises text/toy, photo editing, standalone Manim video, first-slice CAD, and harness evaluation through shared VIGOR contracts.

## Phase 0: Documentation And Architecture

Status: **done**.

Deliverables shipped: framework architecture, research synthesis, comparison document, readiness assessment, ADRs 0001-0011, adoption plans, runtime schemas, scoring/adjudication policy, templates, and commit-state documentation.

## Phase 1: Runtime Skeleton

Status: **done**.

| Deliverable | Status |
| --- | --- |
| `vigor-core` Pydantic schemas | done |
| Async `DomainAdapter`, `AgentBackend`, `ToolBackend` interfaces | done |
| `RunArchive` filesystem persistence with path containment | done |
| Scoring, adjudication, and frontier selection | done |
| `vigor-runtime` orchestrator | done |
| Patch loop (`propose_patch` + `apply_patch`) | done |
| Best-of-N from `Budgets.max_candidates` | done |
| Echo backend + toy adapter | done |
| CLI (`vigor demo`, `vigor version`) | done |
| CI and quality gate | done |

## Phase 2: Photo Editing MVP

Status: **done for deterministic MVP**.

| Deliverable | Status |
| --- | --- |
| `photo_edit_recipe.v1` | done |
| Global adjustments | done |
| Local adjustment metadata | done |
| Basic masks | done: sky heuristic, foreground gradient, subject/radial gradient |
| Preview renderer | done: Pillow + NumPy, globals + local mask blending |
| Histogram critic | done |
| XMP export | done: Lightroom/ACR PV2012 global settings |
| Mask PNG export | done |
| VLM aesthetic critic | optional future enhancement; backend model reviewer path exists |

## Phase 3: Agentic Video MVP

Status: **done for standalone Manim first slice; AIECF integration remains externally blocked**.

| Deliverable | Status |
| --- | --- |
| `manim_scene.v1` | done |
| Standalone Manim adapter | done (`vigor-adapter-video-manim`) |
| CLI command construction | done |
| Test strategy without Manim in CI | done: injectable fake runner |
| Basic MP4 artifact reviewer | done |
| Real Manim subprocess guard | done: requires sandboxed runner or explicit unsafe opt-in |
| AIECF wrapper | blocked pending concrete AIECF repo access and license |
| VideoScore2 hard reviewer | blocked pending GPU or accepted shadow-mode path |

## Phase 4: Frontier And Search

Status: **done for sequential best-of-N**.

| Deliverable | Status |
| --- | --- |
| Best-of-N generation | done: runtime evaluates `Budgets.max_candidates` candidates |
| Frontier manager | done |
| Non-monotonic selection | done: final selected candidate can be non-first |
| Parallel candidate scheduling | future performance optimization |

## Phase 5: CAD MVP

Status: **done for OpenSCAD first slice**.

| Deliverable | Status |
| --- | --- |
| `cad_parametric.v1` | done |
| CAD compiler | done: deterministic OpenSCAD source generation |
| Geometry/manufacturing validator | done: dimensions, wall thickness, hole margin, bbox, FDM warning |
| Export validation package | done: `.scad` artifact + `cad_validation.json` |
| Mesh/STL compilation | optional future enhancement requiring OpenSCAD/CadQuery/FreeCAD |
| FEM/simulation | deferred to safety-critical later phase |

## Phase 6: Meta-Harness-Style Harness Optimization

Status: **done for minimal evaluator; proposer/optimizer deferred**.

| Deliverable | Status |
| --- | --- |
| Harness candidate schema | done |
| Split manifest schema | done |
| Candidate evaluator | done: runs existing VIGOR orchestrator over JSON `TaskSpec` files referenced by split manifests |
| Aggregate report | done |
| Promotion gates | documented, not automated |
| Self-proposing code optimizer | future enhancement |

## Remaining External Blockers

| Item | Status | Required Input |
| --- | --- | --- |
| `vigor-adapter-video-aiecf` | blocked | concrete AIECF repo URL/access/license and pipeline verification |
| VideoScore2 as hard scorer | blocked | GPU/model-serving decision |
| VLM aesthetic critic | optional | provider credentials, model choice, licensed test photo corpus |
| CAD mesh/FEM validation | deferred | CAD kernel choice, solver choice, material/load-case test corpus |

## Current Quality Gate

Required before every commit:

1. `uv run ruff check .`
2. `uv run ruff format --check .`
3. `uv run mypy`
4. `uv run pytest`
5. `uv run vigor demo --goal "Final verification" --runs-dir runs --task-id final_verify`
