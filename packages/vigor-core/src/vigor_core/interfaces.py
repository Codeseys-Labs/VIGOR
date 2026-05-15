"""Async abstract interfaces for adapters, agent backends, and tool backends.

See ADR-0010. These are the only contracts the orchestrator needs. Adapters
and backends depend on `vigor-core` only.
"""

from __future__ import annotations

import abc
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from vigor_core.schemas import (
    AdapterManifest,
    ArtifactIR,
    CompileResult,
    ExportBundle,
    ObservableArtifact,
    PatchPlan,
    ReviewReport,
    TaskSpec,
    ToolManifest,
)


@dataclass(slots=True)
class RunContext:
    """Runtime context passed into adapter calls.

    ``tools`` is an optional ambient ``ToolBackend`` (typically an MCP
    bridge) made available to adapters that want to call out to MCP
    servers configured at the agent level. Adapters that don't need it
    can ignore the field; existing adapters continue to work unchanged.

    ``tool_capabilities`` is the set of tool ids this run is authorized
    to invoke as a mutator (ADR-0016 §3.2). Observer tools are always
    callable. Mutator tools require their ``tool_id`` to be present in
    this frozenset; the orchestrator (or a later policy layer) is
    responsible for issuing capabilities. Default is empty, i.e.
    default-deny for every mutator.
    """

    run_id: str
    run_dir: str
    task: TaskSpec
    iteration: int = 0
    extras: dict[str, Any] = field(default_factory=dict)
    tools: ToolBackend | None = None
    tool_capabilities: frozenset[str] = field(default_factory=frozenset)


@dataclass(slots=True)
class RepresentationPlan:
    """Adapter-declared plan for producing an IR."""

    ir_type: str
    prompt_template: str | None = None
    reviewer_ids: list[str] = field(default_factory=list)
    notes: str | None = None


@dataclass(slots=True)
class ValidationReport:
    """Result of `DomainAdapter.validate_ir`."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GenerationRequest:
    """Request sent from runtime to an agent backend to generate candidate IR."""

    task: TaskSpec
    plan: RepresentationPlan
    prior_candidates: list[ArtifactIR] = field(default_factory=list)
    system_prompt: str | None = None


@dataclass(slots=True)
class GenerationResult:
    """Agent backend response containing candidate IR and optional trace data."""

    ir: ArtifactIR
    reasoning: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ReviewRequest:
    """Request sent to an agent backend to critique a compiled artifact."""

    ir: ArtifactIR
    artifact: ObservableArtifact
    context: RunContext
    reviewer_id: str


@dataclass(slots=True)
class ReviewResult:
    """Agent backend review response."""

    report: ReviewReport


@dataclass(slots=True)
class PatchProposalRequest:
    """Request sent to a backend to convert review evidence into a patch plan."""

    ir: ArtifactIR
    reviews: list[ReviewReport]
    context: RunContext


@dataclass(slots=True)
class PatchProposal:
    """Backend-proposed patch plan plus optional rationale."""

    patch: PatchPlan
    rationale: str | None = None


@dataclass(slots=True)
class ToolResult:
    """Result from a tool backend call."""

    tool_id: str
    status: Literal["success", "failure", "timeout"]
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


class AgentBackend(abc.ABC):
    """Drives LLM / agent calls for generation, review, and patch proposal."""

    @abc.abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...

    @abc.abstractmethod
    async def review(self, request: ReviewRequest) -> ReviewResult: ...

    @abc.abstractmethod
    async def propose_patch(self, request: PatchProposalRequest) -> PatchProposal: ...

    async def aclose(self) -> None:
        """Optional cleanup hook."""


class ToolBackend(abc.ABC):
    """Exposes typed tool invocation.

    ``call_tool`` accepts an optional ``capabilities`` frozenset of
    tool ids the caller is authorized to invoke as mutators
    (ADR-0016 §3.2). Backends that surface mutator tools (currently
    `MCPToolBackend`) reject mutator calls whose ``tool_id`` is not
    present in ``capabilities``. ``None`` is treated identically to an
    empty frozenset (fail-closed).
    """

    @abc.abstractmethod
    async def call_tool(
        self,
        tool_id: str,
        payload: dict[str, Any],
        *,
        capabilities: frozenset[str] | None = None,
    ) -> ToolResult: ...

    @abc.abstractmethod
    async def list_tools(self) -> list[ToolManifest]: ...

    async def aclose(self) -> None:
        """Optional cleanup hook.

        MCP-backed tools open subprocesses or sockets; the orchestrator
        invokes ``aclose`` in its ``finally`` block so leaked sessions
        cannot outlive a run. In-process / stateless tool backends can
        leave the default no-op implementation.
        """


class DomainAdapter(abc.ABC):
    """Owns a modality: its IR, compiler, reviewers, and exports."""

    domain: ClassVar[str] = ""

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
        self,
        ir: ArtifactIR,
        artifact: ObservableArtifact,
        context: RunContext,
    ) -> ExportBundle: ...


SeedIRFactory = Callable[[GenerationRequest], dict[str, Any]]
