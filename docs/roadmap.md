# VIGOR Roadmap

## Roadmap Principles

VIGOR should prove universality by supporting at least two very different modalities through the same runtime before expanding.

Recommended initial pair:

1. Photo editing, because editability and subjective aesthetic review are central.
2. Agentic video generation, because it needs long-horizon multimodal planning, rendering, and scoring.

CAD should follow once the runtime has mature provenance and safety gating.

## Phase 0: Documentation And Architecture

Status: in progress

Deliverables:

| Deliverable | Status |
| --- | --- |
| Framework architecture | done |
| Research synthesis | done |
| ADRs | done |
| Adoption plans | done |
| Adapter templates | done |

Exit criteria:

1. Docs define the core loop, adapter contract, reviewer schema, and provenance model.
2. At least three downstream adoption plans exist.
3. Architecture decisions are captured in ADRs.

## Phase 1: Runtime Skeleton

Deliverables:

| Deliverable | Description |
| --- | --- |
| `TaskSpec` | Goal, references, constraints, target outputs |
| `ArtifactIR` | Versioned editable representation wrapper |
| `CompileResult` | Compiler/render/sim result schema |
| `ReviewReport` | Standard review report schema |
| `AdjudicationReport` | Decision and patch-objective schema |
| `RunArchive` | Filesystem or database-backed trajectory store |
| `DomainAdapter` interface | Adapter contract |

Exit criteria:

1. A toy adapter can generate, compile, review, patch, and export.
2. Run archive stores all intermediate state.
3. Loop stops by acceptance or budget.

## Phase 2: Photo Editing MVP

Deliverables:

| Deliverable | Description |
| --- | --- |
| `photo_edit_recipe.v1` | Global/local adjustment schema |
| Preview renderer | JPEG input to edited preview |
| Basic mask support | Sky/subject/foreground masks |
| Histogram critic | Clipping and tonal checks |
| VLM aesthetic critic | Structured critique |
| XMP export | Lightroom-style sidecar or preset |

Exit criteria:

1. User can provide a photo and style prompt.
2. System outputs preview, recipe, masks, review report, and provenance.
3. At least one automatic patch improves a measured issue.

## Phase 3: Agentic Video MVP

Deliverables:

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
| Domain benchmark suites | Search and held-out tasks |
| Harness candidate format | Prompt/adapters/reviewer/memory policy bundle |
| Outer-loop evaluator | Runs benchmark tasks and scores harness variants |
| Frontier tracking | Quality/cost/safety/editability Pareto frontiers |

Exit criteria:

1. VIGOR can compare two harness versions over the same task set.
2. Outer-loop changes are reviewed before promotion.
3. Held-out evaluation is separate from search.

## Cross-Cutting Workstreams

| Workstream | Need |
| --- | --- |
| Security | Sandbox tools, isolate renderers, scan secrets, restrict destructive actions |
| Governance | Human approval for safety-critical domains |
| Observability | Trace IDs, metrics, run dashboards, failure reports |
| Storage | Large artifact lifecycle, privacy, retention |
| UI | Candidate comparison, reviewer evidence, inline comments |
| Evaluation | Human preference capture, calibration, benchmark splits |
