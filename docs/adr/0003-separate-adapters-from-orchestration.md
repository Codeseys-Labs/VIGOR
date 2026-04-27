# ADR-0003: Separate Domain Adapters From The Orchestration Runtime

Status: Accepted

Date: 2026-04-26

## Context

VIGOR must support many modalities with different execution environments. Video generation may use Manim, Blender, ffmpeg, or browser renderers. CAD may use OpenSCAD, FreeCAD, CAD kernels, slicers, and FEM simulators. Photo editing may use rawpy/OpenCV, Lightroom XMP, Photoshop UXP, GIMP/GEGL, or LUT exports.

If VIGOR hardcodes these tools into the orchestrator, the runtime will become brittle and domain-specific.

VIGA demonstrates a useful separation through tool servers and distinct generator/verifier capabilities.

## Decision

VIGOR will separate the modality-agnostic orchestrator from domain adapters.

The orchestrator owns:

1. Loop policy.
2. Budget enforcement.
3. Candidate and frontier management.
4. Reviewer aggregation.
5. Provenance storage.
6. Human interaction mode.

Domain adapters own:

1. IR schema.
2. Tool manifests.
3. Compiler/render/simulation functions.
4. Domain reviewers and metrics.
5. Export logic.
6. Domain-specific patch generation.

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| One monolithic VIGOR engine | Too coupled to early domains and hard to extend. |
| Independent domain systems only | Does not create a universal framework or shared provenance/review model. |
| Tool-only abstraction without domain adapter | Too low-level; the orchestrator needs semantic domain contracts. |

## Consequences

Positive:

1. New modalities can be added without rewriting the runtime.
2. Adapters can evolve independently.
3. Tool environments can be isolated for security and dependency management.

Negative:

1. Adapter authoring requires discipline and templates.
2. Cross-domain tasks need composition logic.
3. Adapter compatibility must be validated before a run starts.

## Citations

| Source | URL |
| --- | --- |
| VIGA architecture doc | https://raw.githubusercontent.com/Fugtemypt123/VIGA/main/docs/architecture.md |
| VIGA repository | https://github.com/Fugtemypt123/VIGA |
| Anthropic tool-interface guidance | https://www.anthropic.com/engineering/building-effective-agents |
