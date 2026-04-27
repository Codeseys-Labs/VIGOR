# VIGOR Adoption Plan: Agentic Video Generation And AIECF

Status: **partially shipped**.

The standalone first slice, `vigor-adapter-video-manim`, exists and is tested without requiring Manim in CI via an injectable fake runner. It supports `manim_scene.v1`, writes a scene file, builds a safe list-argument Manim CLI command, predicts/locates the MP4 artifact, reviews basic MP4 existence, and exports the video artifact through the normal VIGOR archive.

Still blocked:

1. `vigor-adapter-video-aiecf`: a compatibility layer for a concrete AIECF repository. Requires repo URL/access/license and pipeline verification.
2. Real Manim E2E in CI: requires Manim installation strategy and system dependencies.
3. VideoScore2 hard scorer: requires GPU/model-serving decision or explicit shadow-mode policy.

## Goal

Adopt VIGOR as the orchestration framework for agentic educational video generation, including systems like AI Education Content Factory.

The target pipeline is:

```text
learning goal -> storyboard/script/scene IR -> compile/render video -> score/review -> refine -> final video + editable recipe
```

## Why AIECF-Style Systems Are A Strong Fit

This plan is written for AIECF-style scene-based educational video systems. The mapping below should be verified against the target repository before implementation. If a specific deployment does not use a listed component, treat the row as an adapter candidate rather than an asserted fact.

| Assumed Existing Pattern | VIGOR Mapping |
| --- | --- |
| LLM storyboard/script/code generation | Generator over editable scene IR |
| Manim rendering | `vigor-adapter-video-manim` compiler/renderer adapter |
| ffmpeg assembly | future compiler/export stage |
| Gemini or VLM critique | reviewer adapter |
| Quality thresholds and refinement | adjudication and patch loop |
| Redis/RQ workers | async compile/review worker backend |
| Scene map-reduce | candidate graph and domain adapter composition |

## Assumptions To Verify For AIECF Integration

| Assumption | Verification Needed |
| --- | --- |
| Scene-based generation exists | Inspect pipeline services and data models |
| Manim or another executable renderer is used | Inspect render worker or compiler service |
| VLM/Gemini critique exists | Inspect review/evaluation services and prompts |
| Redis/RQ or equivalent async workers exist | Inspect infrastructure and worker configuration |
| Final assembly uses ffmpeg or equivalent | Inspect media assembly code |
| Quality gates already affect refinement | Inspect threshold and retry logic |

## Current Standalone Manim Slice

| Capability | Status |
| --- | --- |
| `manim_scene.v1` IR | done |
| Manim CLI command construction | done |
| Fake-runner unit tests | done |
| Basic MP4 reviewer | done |
| Scene source artifact | done |
| Real Manim CI render | blocked on environment |
| Multi-scene/ffmpeg assembly | future |
| VideoScore2 scoring | blocked on GPU/shadow-mode policy |

## Future AIECF Adapter

The future `vigor-adapter-video-aiecf` should wrap a concrete AIECF repo rather than duplicate it. It should:

1. Convert AIECF scene/storyboard objects to VIGOR `TaskSpec` and `ArtifactIR` records.
2. Delegate Manim rendering to the existing AIECF worker where available.
3. Store AIECF outputs in the VIGOR `RunArchive` structure.
4. Run VideoScore2/VLM reviews in shadow mode first.
5. Keep AIECF-specific assumptions out of `vigor-core` and `vigor-runtime`.
