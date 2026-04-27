# VIGOR Compared With Related Systems, Papers, And Agent SDKs

## Short Recommendation

Build VIGOR as an **SDK-agnostic core library with optional orchestration backends and reference domain adapters**.

That recommendation is now implemented as a UV monorepo with:

```text
vigor-core
vigor-runtime
vigor-backend-strands
vigor-backend-claude-agent-sdk
vigor-adapter-photo
vigor-adapter-video-manim
vigor-adapter-cad
vigor-harness
examples/
```

## Comparison Matrix

| System | Primary Focus | What VIGOR Learns | Why VIGOR Is Different |
| --- | --- | --- | --- |
| VIGA | Inverse graphics and visual reconstruction | Executable representation plus render-review loop | Generalizes from graphics to any modality and adds adapter contracts, scoring policy, and provenance |
| Meta-Harness | Optimizing the harness around a fixed model | Filesystem history of source, scores, traces | VIGOR has both inner artifact refinement and outer harness evaluation |
| Claude Design | Interactive design/prototyping | First generation is a seed; interaction matters | VIGOR adds automatic reviewer ensembles and modality-neutral adapters |
| Anthropic long-running harness | Better app generation | Separate evaluator + live artifact review | VIGOR makes the pattern domain-independent |
| VideoScore2 | AI-generated video evaluation | Learned scorer as reviewer plugin | VIGOR hosts scorers inside broader adjudication/patch loops |
| TRIBE v2 | Predicting brain response to multimodal stimuli | Multimodal uncertainty analogy | Not treated as an artifact-quality judge without validation |
| Strands Agents SDK | Multi-provider agent framework | Optional backend for model/tool orchestration | VIGOR's IR/review/provenance contracts remain SDK-independent |
| Claude Agent SDK | Claude Code-powered agents | Optional backend for Claude-native workflows | VIGOR keeps canonical archive independent from Claude sessions/checkpoints |

## Current Core Interfaces

```python
class AgentBackend:
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...
    async def review(self, request: ReviewRequest) -> ReviewResult: ...
    async def propose_patch(self, request: PatchProposalRequest) -> PatchProposal: ...
    async def aclose(self) -> None: ...

class ToolBackend:
    async def call_tool(self, tool_id: str, payload: dict) -> ToolResult: ...
    async def list_tools(self) -> list[ToolManifest]: ...

class DomainAdapter:
    async def describe_capabilities(self) -> AdapterManifest: ...
    async def plan_representation(self, task: TaskSpec) -> RepresentationPlan: ...
    async def validate_ir(self, ir: ArtifactIR) -> ValidationReport: ...
    async def compile(self, ir: ArtifactIR, context: RunContext) -> CompileResult: ...
    async def review(
        self, artifact: ObservableArtifact, ir: ArtifactIR, context: RunContext
    ) -> list[ReviewReport]: ...
    async def apply_patch(self, ir: ArtifactIR, patch: PatchPlan) -> ArtifactIR: ...
    async def export(
        self, ir: ArtifactIR, artifact: ObservableArtifact, context: RunContext
    ) -> ExportBundle: ...
```

## Module Versus Examples

| Option | Verdict |
| --- | --- |
| Examples only | Rejected: fragments schemas, scoring, provenance, and review logic |
| Monolithic package | Rejected: dependency sprawl and weak sandboxing |
| SDK-agnostic core + optional backends/adapters | Accepted and implemented |

## Backend Guidance

| Backend | Role |
| --- | --- |
| Strands | First general-purpose backend skeleton; useful for multi-provider and graph/swarm workflows |
| Claude Agent SDK | Optional Claude-native backend skeleton; useful for coding-heavy workflows and permissioned Claude Code sessions |
| Direct/local models | Future backend; must implement `AgentBackend` only |

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
| Claude Agent SDK docs | https://docs.anthropic.com/en/api/agent-sdk/python |
| Strands Agent-to-Agent docs | https://strandsagents.com/docs/user-guide/concepts/multi-agent/agent-to-agent/index.md |
| VideoScore2 paper | https://arxiv.org/abs/2509.22799 |
