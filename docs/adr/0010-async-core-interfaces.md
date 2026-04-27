# ADR-0010: Async Core Interfaces For Adapters, Backends, And Patches

Status: Accepted

Date: 2026-04-26

## Context

The readiness assessment flagged conflicts K1 and K5: `DomainAdapter` had different signatures across `docs/vigor-framework.md`, `docs/comparisons/vigor-vs-systems.md`, and ADR-0007. Patch ownership was also ambiguous because both `DomainAdapter` and `AgentBackend` had a `patch` method with different intent.

VIGOR domains include long-running compilers (Manim, rawpy, CAD kernels, slicers, simulators), network reviewers (VLM critics, Strands agents, Claude Agent SDK), and tool calls that fan out. An async-first interface makes concurrency natural without forcing thread pools throughout the runtime.

## Decision

VIGOR adopts async-first core interfaces. One authoritative signature set is pinned in this ADR. Schema objects are Pydantic v2 models.

### `DomainAdapter`

Adapters own the IR, the compiler, and the deterministic patch application.

```python
class DomainAdapter(abc.ABC):
    domain: ClassVar[str]

    @abc.abstractmethod
    async def describe_capabilities(self) -> AdapterManifest: ...

    @abc.abstractmethod
    async def plan_representation(self, task: TaskSpec) -> RepresentationPlan: ...

    @abc.abstractmethod
    async def validate_ir(self, ir: ArtifactIR) -> ValidationReport: ...

    @abc.abstractmethod
    async def compile(self, ir: ArtifactIR, context: RunContext) -> CompileResult: ...

    @abc.abstractmethod
    async def review(
        self, artifact: ObservableArtifact, ir: ArtifactIR, context: RunContext
    ) -> list[ReviewReport]: ...

    @abc.abstractmethod
    async def apply_patch(self, ir: ArtifactIR, patch: PatchPlan) -> ArtifactIR: ...

    @abc.abstractmethod
    async def export(
        self, ir: ArtifactIR, artifact: ObservableArtifact
    ) -> ExportBundle: ...
```

### `AgentBackend`

Backends drive LLM or agent calls. They may propose patches as diffs on the IR, but they do not apply patches to IR themselves.

```python
class AgentBackend(abc.ABC):
    @abc.abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...

    @abc.abstractmethod
    async def review(self, request: ReviewRequest) -> ReviewResult: ...

    @abc.abstractmethod
    async def propose_patch(self, request: PatchProposalRequest) -> PatchProposal: ...
```

### `ToolBackend`

Tool backends expose typed compute. They never hold long-term artifact state.

```python
class ToolBackend(abc.ABC):
    @abc.abstractmethod
    async def call_tool(self, tool_id: str, payload: dict) -> ToolResult: ...

    @abc.abstractmethod
    async def list_tools(self) -> list[ToolManifest]: ...
```

### Patch Ownership Rule

1. `AgentBackend.propose_patch` returns a structured `PatchPlan` built from review evidence.
2. `DomainAdapter.apply_patch` is the deterministic transform that turns an IR plus a `PatchPlan` into a new IR.

This is the only place in VIGOR where LLM outputs cross into authoritative artifact state, and it always goes through validation (`validate_ir`) before the new IR is compiled again.

### Mutability And Capability Rules

1. Tools declare `mutability: Literal["observer", "mutator"]` in `ToolManifest`.
2. Observers may run without special permission.
3. Mutators require explicit capability grants from the orchestrator.
4. Domain adapters must not import backend packages; backends must not import adapters. Both depend only on `vigor-core`.

### Error Handling

1. All methods raise `VigorError` or a subclass on structured failure.
2. Runtime catches and records `VigorError` as a `RuntimeError` record in the run archive.
3. Uncaught exceptions become structured errors at the orchestrator boundary.

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| Sync-everywhere | Forces thread pools and blocks streaming reviewers. |
| Async outer interface with sync inner methods | Works, but makes reviewer fan-out awkward. |
| Put `apply_patch` on the backend | LLMs should propose, not mutate artifacts directly. |
| Let the adapter call the backend | Couples adapters to agent runtimes. |

## Consequences

Positive:

1. Core interface is unambiguous and small.
2. Async fan-out works naturally for reviewer ensembles and best-of-N.
3. LLM output is always validated before it becomes IR.
4. Backends and adapters evolve independently.

Negative:

1. All call sites must be async-aware.
2. Sync users need a thin sync wrapper or `asyncio.run` bridge.
3. Patch semantics must be documented so adapters do not smuggle LLM calls into `apply_patch`.

## Implementation Notes

1. `vigor-core` provides the abstract base classes and Pydantic models.
2. `vigor-runtime` provides an async orchestrator that uses them.
3. Adapters that cannot be async (for example blocking subprocess calls) should offload to `asyncio.to_thread`.

## Citations

| Source | URL |
| --- | --- |
| Pydantic v2 strict mode | https://docs.pydantic.dev/latest/concepts/strict_mode/ |
| Pydantic v2 discriminated unions | https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions |
| Python `asyncio.to_thread` | https://docs.python.org/3/library/asyncio-task.html#running-in-threads |
| VIGOR runtime schemas | `../schemas/runtime-schemas.md` |
| VIGOR scoring and adjudication | `../scoring-adjudication.md` |
