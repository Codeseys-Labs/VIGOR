# VIGOR Compared With Related Systems, Papers, And Agent SDKs

## Purpose

This document compares VIGOR with adjacent systems and answers the implementation question:

> Should VIGOR become a generalized importable module built on something like Strands Agents or the Claude Agent SDK, or should it remain a set of example implementations such as agentic Blender, agentic CAD, and agentic photo editing?

## Short Recommendation

Build VIGOR as an **SDK-agnostic core library with optional orchestration backends and reference domain adapters**.

Do not make VIGOR only a pile of examples. That would lose the main value: shared schemas, provenance, reviewer contracts, scoring policy, frontier selection, and adapter interfaces.

Do not hard-couple VIGOR to one agent SDK either. Strands and the Claude Agent SDK are useful execution substrates, but VIGOR's durable value should live above them as a portable artifact-runtime contract.

Recommended package shape:

```text
vigor-core
  schemas, run archive, adapter interfaces, review reports, scoring, adjudication, frontier logic

vigor-runtime
  default orchestrator, budgets, retries, persistence, CLI/API entrypoints

vigor-backend-strands
  optional Strands implementation of generator/reviewer/tool orchestration

vigor-backend-claude-agent-sdk
  optional Claude Agent SDK implementation for Claude Code-powered workflows

vigor-adapter-photo
  photo edit IR, renderer, reviewers, XMP/GIMP/Photoshop exports

vigor-adapter-video-aiecf
  educational video IR, Manim/ffmpeg compilers, VideoScore2/VLM reviewers

vigor-adapter-cad
  CAD IR, geometry compiler, slicer/simulation reviewers

examples/
  agentic-photo-editing, agentic-video, agentic-cad, agentic-blender
```

## What VIGOR Is And Is Not

| VIGOR Is | VIGOR Is Not |
| --- | --- |
| A generate-compile-review artifact framework | Just another chat-agent wrapper |
| A representation-first runtime | A pixel/video/code-only generator |
| A schema and provenance layer | A replacement for every agent SDK |
| An adapter contract for compilers/renderers/reviewers | A single hardcoded implementation for Blender, CAD, or Lightroom |
| A way to compose objective validators, learned scorers, LLM/VLM critics, and humans | A claim that one scorer or one LLM can judge everything |

## Comparison Matrix

| System | Primary Focus | Core Loop | Durable Artifact | Review Model | What VIGOR Learns | Why VIGOR Is Different |
| --- | --- | --- | --- | --- | --- | --- |
| VIGA | Inverse graphics and visual reconstruction | Generate code, render, verify, revise | Blender/PPTX/scene programs and renders | Generator/Verifier roles with visual inspection | Executable representation plus render-review loop | VIGOR generalizes from graphics to any modality and adds adapter contracts, scoring policy, and provenance across domains |
| Meta-Harness | Optimizing the harness around a fixed model | Propose harness, evaluate on tasks, store traces/scores, iterate | Harness code, execution traces, benchmark scores | Benchmark evaluator | Outer-loop optimization over prompts/tools/memory/review policies | VIGOR applies the idea to artifact-generation harnesses and keeps an inner artifact-refinement loop |
| Claude Design | Interactive design and prototyping | Generate first design, refine via chat/comments/direct edits | Exported design assets and handoff bundle | User feedback and Claude review | First generation is a seed; interaction and handoff matter | VIGOR adds automatic reviewer ensembles, artifact provenance, and modality-neutral adapters |
| Anthropic long-running harness | Better frontend/full-stack generation | Planner/generator/evaluator loops and sprint contracts | Codebase, task files, review findings | Separate evaluator with Playwright-backed inspection | Separate evaluator beats self-review; live artifact review matters | VIGOR makes this a domain-independent runtime pattern, not only app-building harness design |
| VideoScore2 | AI-generated video evaluation | Score video against prompt | Video scores and rationales | Learned video evaluator across visual quality, alignment, physical/common-sense consistency | Use interpretable learned scorers as reviewer plugins | VIGOR is not a scorer; it can host VideoScore2 inside broader adjudication and patch loops |
| TRIBE v2 | Predicting brain response to multimodal stimuli | Encode video/audio/text, predict fMRI response | Predicted brain activity | Neural prediction, not artifact review | Consensus/uncertainty and in-silico experimentation as analogies | VIGOR should not treat TRIBE v2 as an artifact-quality judge without domain validation |
| Strands Agents SDK | Multi-provider agent framework | Model-driven agents, tools, graphs, swarms, A2A | Agent sessions and tool outputs | App-defined | Useful backend for VIGOR orchestration, multi-agent patterns, MCP, observability | VIGOR's IR/review/provenance contracts should stay SDK-independent |
| Claude Agent SDK | Claude Code-powered custom agents | Claude agent queries with tools, MCP, permissions, hooks | Claude Code sessions, diffs, checkpoints, tool traces | App-defined | Useful backend for coding-heavy and Claude-native workflows with strong permissions/control | VIGOR should use it as an optional backend, not the core abstraction |

## Strands As A VIGOR Backend

Strands is a strong candidate for a first general-purpose backend because its docs describe:

| Capability | Relevance To VIGOR |
| --- | --- |
| Python and TypeScript SDKs | VIGOR can support backend services and browser/interactive tools |
| Multiple model providers | Reduces lock-in for generator/reviewer agents |
| Custom tools with schemas | Maps well to compiler/reviewer/inspector tools |
| MCP integration | Lets VIGOR adapters expose tools through a standard protocol |
| Graph workflows | Useful for deterministic generate-compile-review DAGs |
| Swarm patterns | Useful for dynamic reviewer/generator handoffs |
| Session persistence | Useful for long-running artifact loops |
| OpenTelemetry | Useful for provenance and observability |
| A2A protocol support | Useful if VIGOR adapters become remote agents |

Best fit:

1. VIGOR reference runtime.
2. Multi-provider deployments.
3. Cross-domain demos.
4. Graph-based workflows where generation, compilation, review, and adjudication are explicit nodes.

Risk:

1. VIGOR could accidentally inherit Strands concepts as core concepts.
2. Dynamic Swarm behavior can obscure deterministic provenance unless constrained.
3. Some downstream projects may not want a Strands dependency.

Mitigation:

Use `vigor-backend-strands` as an optional backend that implements VIGOR's `AgentBackend` and `ToolBackend` interfaces.

## Claude Agent SDK As A VIGOR Backend

Claude Agent SDK is a strong candidate for Claude-native and coding-heavy workflows. Anthropic's docs describe custom agents powered by Claude Code's tools and capabilities, with control over orchestration, tool access, and permissions. The docs also describe MCP integration, allowed/disallowed tools, subagents, hooks, checkpointing, cost/usage tracking, OpenTelemetry, and deployment guidance.

Best fit:

1. Agentic code generation adapters.
2. Harness optimization where candidate harnesses are code changes.
3. AIECF or CAD repo work where file edits, shell commands, and permission controls matter.
4. Reviewers that need to inspect and patch codebases.

Risk:

1. It is Claude-centric.
2. It may be overkill for small non-code artifact loops.
3. It can blur VIGOR with Claude Code-specific concepts like sessions, permission modes, and checkpoints.

Mitigation:

Use `vigor-backend-claude-agent-sdk` as an optional backend. Keep VIGOR's canonical run archive independent from Claude's session transcript or checkpoints.

## Module Versus Examples

### Option A: Examples Only

```text
agentic-blender/
agentic-cad/
agentic-photo-editing/
agentic-video/
```

Pros:

1. Fastest to prototype.
2. Each domain can move independently.
3. No framework over-design early.

Cons:

1. Duplicates schemas, review policies, memory, and provenance.
2. Makes VIGOR a branding pattern rather than an adoptable runtime.
3. Harder to compare candidates across domains.
4. Harder to build Meta-Harness-style outer-loop optimization.
5. Every downstream project re-solves scoring and artifact storage.

Use examples-only only for short-lived experiments.

### Option B: One Monolithic Framework

```text
vigor/
  everything: agents, tools, CAD, photo, video, UI, scoring
```

Pros:

1. Simple import story.
2. Shared implementation from day one.
3. Easier demos.

Cons:

1. Hard dependency sprawl across Blender, CAD, raw image tools, browser tools, video tools, and model SDKs.
2. Forces all users to inherit all modality assumptions.
3. Harder to sandbox risky tools.
4. Likely to become brittle.

Avoid this.

### Option C: SDK-Agnostic Core Plus Optional Backends And Adapters

```text
vigor-core
vigor-runtime
vigor-backend-strands
vigor-backend-claude-agent-sdk
vigor-adapter-photo
vigor-adapter-video-aiecf
vigor-adapter-cad
examples/*
```

Pros:

1. Preserves shared VIGOR concepts.
2. Avoids SDK lock-in.
3. Lets downstream projects import only what they need.
4. Supports both reusable library and example implementations.
5. Enables benchmark and harness optimization across adapters.

Cons:

1. Requires disciplined interfaces.
2. More initial packaging work.
3. Backends must be kept feature-compatible enough for common workflows.

This is the recommended approach.

## Proposed Core Interfaces

```python
class AgentBackend:
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...
    async def review(self, request: ReviewRequest) -> ReviewResult: ...
    async def patch(self, request: PatchRequest) -> PatchResult: ...

class ToolBackend:
    async def call_tool(self, tool_id: str, payload: dict) -> ToolResult: ...
    def list_tools(self) -> list[ToolManifest]: ...

class DomainAdapter:
    def describe_capabilities(self) -> AdapterManifest: ...
    def validate_ir(self, ir: ArtifactIR) -> ValidationReport: ...
    async def compile(self, ir: ArtifactIR, context: RunContext) -> CompileResult: ...
    async def review(self, artifact: ObservableArtifact, context: RunContext) -> list[ReviewReport]: ...
    async def export(self, ir: ArtifactIR, artifact: ObservableArtifact) -> ExportBundle: ...
```

The core runtime should not know whether the backend uses Strands, Claude Agent SDK, direct model APIs, local models, or a custom service.

## Import Story

Example downstream usage should look like this:

```python
from vigor import VigorRuntime, TaskSpec
from vigor_backend_strands import StrandsBackend
from vigor_adapter_photo import PhotoEditingAdapter

runtime = VigorRuntime(
    backend=StrandsBackend(),
    adapters=[PhotoEditingAdapter()],
    archive_dir="runs"
)

result = await runtime.run(TaskSpec(
    goal="Warm cinematic edit, natural greens, protect highlights",
    references=["input.raw"],
    modalities=["image", "photo_edit_recipe"],
    target_outputs=["preview.jpg", "recipe.json", "lightroom.xmp"]
))
```

The same runtime should also support Claude Agent SDK:

```python
from vigor import VigorRuntime
from vigor_backend_claude_agent_sdk import ClaudeAgentBackend
from vigor_adapter_video_aiecf import EducationalVideoAdapter

runtime = VigorRuntime(
    backend=ClaudeAgentBackend(permission_mode="acceptEdits"),
    adapters=[EducationalVideoAdapter()],
    archive_dir="runs"
)
```

## Decision Guidance

| Question | Recommendation |
| --- | --- |
| Should VIGOR be importable as a module? | Yes. Otherwise adoption will fragment. |
| Should VIGOR be built directly on Strands? | Use Strands as the first general backend, not as the core abstraction. |
| Should VIGOR be built directly on Claude Agent SDK? | Use it as a Claude-native backend for coding-heavy workflows, not as the core abstraction. |
| Should domain projects remain as examples? | Yes, but as reference adapters and example apps backed by shared core packages. |
| Should VIGOR define its own agent protocol? | Define the minimal backend interface needed for generation/review/patch/tool calls; do not reimplement a full agent SDK. |
| Should VIGOR use MCP? | Yes for tool adapters where possible, because it helps isolate domain tools from the runtime. |

## Recommended Next ADR

Adopt the following decision:

> VIGOR will be packaged as an SDK-agnostic core library plus optional agent-runtime backends and domain adapters. Strands should be the first reference general backend; Claude Agent SDK should be a first-class optional backend for Claude-native/coding-heavy workflows; downstream projects should be examples and adapter packages rather than independent one-off implementations.

## Sources

| Source | URL |
| --- | --- |
| VIGA repository | https://github.com/Fugtemypt123/VIGA |
| VIGA paper | https://arxiv.org/abs/2601.11109 |
| Meta-Harness paper | https://arxiv.org/abs/2603.28052 |
| Meta-Harness repository | https://github.com/stanford-iris-lab/meta-harness |
| Claude Design announcement | https://www.anthropic.com/news/claude-design-anthropic-labs |
| Anthropic long-running harness article | https://www.anthropic.com/engineering/harness-design-long-running-apps |
| Anthropic Building Effective Agents | https://www.anthropic.com/engineering/building-effective-agents |
| Claude Code overview / Agent SDK docs | https://docs.anthropic.com/en/docs/claude-code |
| Claude Agent SDK MCP docs | https://console.anthropic.com/docs/en/agent-sdk/mcp |
| Strands Agent-to-Agent docs | https://strandsagents.com/docs/user-guide/concepts/multi-agent/agent-to-agent/index.md |
| Strands TypeScript SDK announcement | https://strandsagents.com/blog/strands-agents-typescript-sdk/index.md |
| VideoScore2 paper | https://arxiv.org/abs/2509.22799 |
| TRIBE v2 repository | https://github.com/facebookresearch/tribev2 |
