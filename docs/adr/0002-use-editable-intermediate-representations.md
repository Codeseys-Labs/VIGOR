# ADR-0002: Use Editable Intermediate Representations As First-Class Outputs

Status: Accepted

Date: 2026-04-26

## Context

Many generative systems produce attractive final assets that are difficult to edit. A diffusion output may look good but does not preserve layer intent. A rendered video may be visually acceptable but does not expose the storyboard, timeline, code, or masks. A CAD mesh may be valid but not parametric or maintainable.

VIGA's key advantage is that it generates executable programs, not just pixels. A generalized VIGOR framework should preserve that benefit.

## Decision

VIGOR will treat editable intermediate representations as primary artifacts.

Final rendered assets are outputs, but the IR is the durable source of truth.

Examples:

| Domain | IR |
| --- | --- |
| Photo editing | XMP-like recipe, mask graph, adjustment layer graph, LUT |
| Video generation | Storyboard JSON, scene graph, timeline, Manim/Blender/HTML code |
| CAD | Parametric feature tree, FreeCAD/OpenSCAD script, constraint graph |
| UI design | HTML/CSS/React, design tokens, component graph |
| Audio | DAW graph, plugin chain, ffmpeg filter graph |
| Robotics | Behavior tree, trajectory plan, task-and-motion plan |
| Code | Patch plan, diffs, source files, tests |

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| Pixel/audio/video final output only | Not sufficiently editable, reproducible, or inspectable. |
| Prompt-only storage | Cannot reproduce all tool/environment effects. |
| Domain-native files only | Useful but not portable enough for cross-domain orchestration. |

## Consequences

Positive:

1. Users can inspect and adjust generated work.
2. Downstream adapters can export to multiple tools.
3. Reviewers can critique both representation and rendered output.
4. Provenance can be expressed as IR diffs.

Negative:

1. IR schemas need versioning.
2. Some domains require lossy compilation from IR to native editor formats.
3. The framework must distinguish canonical IR from adapter-specific exports.

## Citations

| Source | URL |
| --- | --- |
| VIGA paper | https://arxiv.org/abs/2601.11109 |
| VIGA architecture doc | https://raw.githubusercontent.com/Fugtemypt123/VIGA/main/docs/architecture.md |
| Claude Design export and handoff patterns | https://www.anthropic.com/news/claude-design-anthropic-labs |
