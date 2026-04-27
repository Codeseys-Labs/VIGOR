# VIGOR Roadmap

## Roadmap Principles

VIGOR should prove modality-agnostic value by supporting at least two very different modalities through the same runtime before expanding.

Recommended initial pair:

1. Photo editing, because editability and subjective aesthetic review are central.
2. Agentic video generation, because it needs long-horizon multimodal planning, rendering, and scoring.

CAD should follow once the runtime has mature provenance and safety gating.

## Phase 0: Documentation And Architecture

Status: done for documentation baseline and Phase 1 runtime skeleton has shipped

Deliverables:

| Deliverable | Status |
| --- | --- |
| Framework architecture | done |
| Research synthesis | done |
| ADRs | done |
| Adoption plans | done |
| Adapter templates | done |
| Runtime schemas | done |
| Scoring/adjudication policy | done |

Exit criteria:

1. Docs define the core loop, adapter contract, reviewer schema, and provenance model.
2. At least three downstream adoption plans exist.
3. Architecture decisions are captured in ADRs.

## Phase 1: Runtime Skeleton

Status: **shipped.** Lives in `packages/vigor-core/` and `packages/vigor-runtime/`. Exit criteria met: the toy adapter (`vigor_runtime.toy_adapter.ToyTextAdapter`) runs end to end through the eight-stage loop, `RunArchive` persists `task.json`, `adapter_manifest.json`, `candidates/<cid>/{ir,compile_result,adjudication,patch_plan}.json`, `reviews/<rid>.json`, `errors/<eid>.json`, `frontier.json`, and `final/{export_bundle,provenance}.json`. Patch loop applies patches via `DomainAdapter.apply_patch` per ADR-0010.

Deliverables:

| Deliverable | Status |
| --- | --- |
| `TaskSpec` | done (Pydantic v2, strict, camelCase aliases) |
| `ArtifactIR` | done |
| `CompileResult` | done |
| `ReviewReport` | done |
| `AdjudicationReport` | done |
| `RunArchive` (filesystem) | done with path-traversal containment |
| `DomainAdapter` / `AgentBackend` / `ToolBackend` interfaces | done (async, per ADR-0010) |
| `Orchestrator` | done: catches `VigorError` + `Exception` at the boundary, runs reviewers in parallel via `asyncio.gather`, invokes `apply_patch`, writes frontier + provenance |
| `EchoAgentBackend` + toy adapter | done |
| CLI (`vigor demo`, `vigor version`) | done |
| CI (ruff + format + mypy strict + pytest, Python 3.11 & 3.12) | done |

Exit criteria (met):

1. A toy adapter can generate, compile, review, patch, and export. ✓
2. Run archive stores all intermediate state. ✓
3. Loop stops by acceptance or budget. ✓

## Phase 2: Photo Editing MVP

Status: **partial — first slice shipped.** `packages/vigor-adapter-photo/` ships the canonical IR (`PhotoEditRecipeV1`), a pure-Python Pillow/NumPy preview renderer, a `HistogramCritic` (objective), JSON recipe export, and an XMP sidecar (Lightroom PV2012). Masks and VLM aesthetic critic remain deferred.

Deliverables:

| Deliverable | Status |
| --- | --- |
| `photo_edit_recipe.v1` (global adjustments) | done |
| Preview renderer (Pillow + NumPy) | done |
| Basic mask support | deferred |
| Histogram critic | done |
| VLM aesthetic critic | deferred (needs provider + test photos) |
| Lightroom XMP export (ProcessVersion=11.0) | done |

Exit criteria:

1. User can provide a photo and style prompt. ✓ (via `TaskSpec.references[0]`)
2. System outputs preview, recipe, masks, review report, and provenance. ✓ for preview/recipe/report/provenance; masks deferred.
3. At least one automatic patch improves a measured issue. In progress (the hint-based `_apply_objective_hint` demonstrates the loop; structured patches land with the mask slice).

## Phase 3: Agentic Video MVP (deferred)

Status: not started. Deferred pending prerequisites C7 (GPU compute) and C8 (AIECF repo access) from `docs/readiness/implementation-readiness.md`. The video adapter is split into `vigor-adapter-video-manim` (standalone) and `vigor-adapter-video-aiecf` (integration).

Planned deliverables once unblocked:

| Deliverable | Description |
| --- | --- |
| `educational_video.v1` | Storyboard, narration, scene code schema |
| Manim adapter | Compile scene IR to MP4 |
| ffmpeg adapter | Assemble scenes and audio |
| VLM scene critic | Structured pedagogical/visual critique |
| Optional VideoScore2 adapter | Video quality/alignment/consistency scoring |
| Continuity reviewer | Adjacent scene and full-video checks |

Exit criteria:

1. Scene-level loop can render, review, patch, and re-render.
2. Full-video archive includes scene artifacts and final export.
3. Hybrid scoring can store at least two reviewer outputs per video.

## Phase 4: Frontier And Search

Deliverables:

| Deliverable | Description |
| --- | --- |
| Best-of-N generation | Multiple candidate branches |
| Frontier manager | Rank by quality, cost, editability, safety |
| Candidate comparison UI or report | Show why candidate won |
| Non-monotonic selection | Allow selecting non-final iteration |

Exit criteria:

1. Runtime can keep several candidates alive.
2. Final artifact can be selected from any candidate, not only the last.
3. Provenance records selection rule.

## Phase 5: CAD MVP

Deliverables:

| Deliverable | Description |
| --- | --- |
| `cad_parametric.v1` | Parametric feature schema |
| CAD compiler | CadQuery, FreeCAD, or OpenSCAD adapter |
| Geometry validator | Watertightness and validity checks |
| Manufacturability reviewer | Wall thickness, overhangs, slicer report |
| Simulation hook | FEM or simplified load checks |

Exit criteria:

1. Generate editable CAD IR from constraints.
2. Compile to CAD and mesh outputs.
3. Detect and patch one geometry/manufacturing failure.
4. Export validation package.

## Phase 6: Meta-Harness-Style Harness Optimization

Deliverables:

| Deliverable | Description |
| --- | --- |
| Domain benchmark suites | Search, validation, and held-out tasks |
| Harness candidate format | Prompt/adapters/reviewer/memory policy bundle |
| Outer-loop evaluator | Runs benchmark tasks and scores harness variants |
| Frontier tracking | Quality/cost/safety/editability Pareto frontiers |

Exit criteria:

1. VIGOR can compare two harness versions over the same task set.
2. Outer-loop changes are reviewed before promotion.
3. Search, validation, and held-out evaluation roles are separate.

Benchmark split definitions:

| Split | Use |
| --- | --- |
| Search | Used by agents or optimizers to propose harness changes |
| Validation | Used to compare candidate harnesses before promotion |
| Held-out test | Used only for final reporting or release qualification |

## Cross-Cutting Workstreams

| Workstream | Need |
| --- | --- |
| Security | Sandbox tools, isolate renderers, scan secrets, restrict destructive actions |
| Governance | Human approval for safety-critical domains |
| Observability | Trace IDs, metrics, run dashboards, failure reports |
| Storage | Large artifact lifecycle, privacy, retention |
| UI | Candidate comparison, reviewer evidence, inline comments |
| Evaluation | Human preference capture, calibration, benchmark splits |
