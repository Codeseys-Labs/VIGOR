# VIGOR Adoption Plan: Agentic CAD

Status: **first slice shipped** as `vigor-adapter-cad`.

The shipped slice intentionally avoids heavyweight CAD kernels in default CI. It uses a constrained `cad_parametric.v1` IR, generates deterministic OpenSCAD source, and runs pure-Python validators for dimensions, wall thickness, hole margins, bounding box limits, and basic FDM manufacturing warnings.

Mesh/STL/STEP/FEM workflows are future phases that require a CAD kernel/solver decision and a material/load-case corpus.

## Goal

Adopt VIGOR for CAD workflows that generate editable parametric models, validate physical and manufacturing constraints, simulate performance, and iterate toward a design goal.

The target pipeline is:

```text
design intent -> parametric CAD IR -> OpenSCAD source -> validation/review -> patch parameters -> export evidence package
```

## Shipped First Slice

| Capability | Status |
| --- | --- |
| `cad_parametric.v1` | done |
| OpenSCAD source generation | done |
| Pure-Python validators | done |
| Structured findings | done |
| VIGOR run archive/export bundle | done |
| STL/STEP mesh compile | future |
| CAD kernel validation | future |
| FEM simulation | future |

## CAD IR

The shipped v1 IR supports a narrow `bracket_plate` part with parameters such as width, height, thickness, hole diameter, hole margin, rib count, and rib thickness. Narrow scope is intentional: it keeps CI lightweight and makes validators deterministic.

## Compiler And Reviewer Stack

### Current Tools

| Tool | Purpose |
| --- | --- |
| OpenSCAD source generator | Produce editable `.scad` text from validated IR |
| Parameter validator | Dimensions, wall thickness, hole margins, bbox estimates |
| Manufacturing sanity reviewer | FDM minimum hole warning and feature-size checks |

### Future Tools

| Tool | Purpose |
| --- | --- |
| OpenSCAD CLI | Optional `.stl`/`.csg` compile and bounding-box summary |
| CadQuery | STEP/STL export and richer parametric geometry |
| FreeCAD | Native CAD feature tree and assembly workflows |
| FEM simulator | Stress/displacement review for load-bearing designs |

## Safety Policy

CAD VIGOR must distinguish prototypes from load-bearing or safety-critical parts.

| Classification | Policy |
| --- | --- |
| Decorative/non-functional | Automated loop can finalize with report |
| Consumer functional | Require manufacturability and constraint checks |
| Load-bearing | Require simulation and human engineer approval |
| Safety-critical | Require certified engineering workflow outside VIGOR |

VIGOR should not claim certification. It can produce evidence packages for qualified review.

## Required Engineering Metadata For Later Mesh/FEM Phases

| Metadata | Why It Matters |
| --- | --- |
| Material | Strength, stiffness, thermal behavior, print settings |
| Load cases | Forces, moments, direction, duration, dynamic vs static load |
| Boundary conditions | Fixed faces, fasteners, contact surfaces, constraints |
| Tolerances | Fit, clearance, manufacturing process limits |
| Manufacturing process | FDM, SLA, CNC, sheet metal, injection molding |
| Safety factor | Required margin for intended use |
| Solver settings | Mesh density, solver type, convergence, simplifications |

## Implementation Phases

| Phase | Status | Output |
| --- | --- | --- |
| Phase 1: OpenSCAD first slice | done | `.scad` source + pure-Python validation report |
| Phase 2: Optional OpenSCAD CLI | future | `.stl`/`.csg` compile and CLI diagnostics |
| Phase 3: CadQuery/FreeCAD backend | future | STEP/STL/native CAD exports |
| Phase 4: Simulation review | future | stress/displacement report and safety factor checks |

## Acceptance Criteria For Current Slice

1. Generate editable CAD IR from constraints. ✓
2. Compile to editable OpenSCAD source. ✓
3. Detect invalid candidates with structured findings. ✓
4. Export OpenSCAD artifact and validation metadata. ✓
