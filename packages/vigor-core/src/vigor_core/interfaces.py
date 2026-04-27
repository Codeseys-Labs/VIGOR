"""Async abstract interfaces for adapters, agent backends, and tool backends.

See ADR-0010. These are the only contracts the orchestrator needs. Adapters
and backends depend on `vigor-core` only.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any, ClassVar

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

# ---------------------------------------------------------------------------
# Runtime context
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RunContext:
    """Runtime context passed into adapter calls."""

    run_id: str
    run_dir: str
    task: TaskSpec
    iteration: int = 0
    extras: dict[str, Any] = field(default_factory=dict)


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


# ---------------------------------------------------------------------------
# Agent backend request/response dataclasses
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class GenerationRequest:
    task: TaskSpec
    plan: RepresentationPlan
    prior_candidates: list[ArtifactIR] = field(default_factory=list)
    system_prompt: str | None = None


@dataclass(slots=True)
class GenerationResult:
    ir: ArtifactIR
    reasoning: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class ReviewRequest:
    ir: ArtifactIR
    artifact: ObservableArtifact
    context: RunContext
    reviewer_id: str


@dataclass(slots=True)
class ReviewResult:
    report: ReviewReport


@dataclass(slots=True)
class PatchProposalRequest:
    ir: ArtifactIR
    reviews: list[ReviewReport]
    context: RunContext


@dataclass(slots=True)
class PatchProposal:
    patch: PatchPlan
    rationale: str | None = None


# ---------------------------------------------------------------------------
# Tool backend result
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ToolResult:
    tool_id: str
    status: str  # "success" | "failure" | "timeout"
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# ---------------------------------------------------------------------------
# Interfaces
# ---------------------------------------------------------------------------


class AgentBackend(abc.ABC):
    """Drives LLM / agent calls for generation, review, and patch proposal.

    Backends never mutate artifact state directly. They propose changes; the
    domain adapter applies them.
    """

    @abc.abstractmethod
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...

    @abc.abstractmethod
    async def review(self, request: ReviewRequest) -> ReviewResult: ...

    @abc.abstractmethod
    async def propose_patch(self, request: PatchProposalRequest) -> PatchProposal: ...

    async def aclose(self) -> None:
        """Optional cleanup hook."""


class ToolBackend(abc.ABC):
    """Exposes typed tool invocation."""

    @abc.abstractmethod
    async def call_tool(self, tool_id: str, payload: dict[str, Any]) -> ToolResult: ...

    @abc.abstractmethod
    async def list_tools(self) -> list[ToolManifest]: ...


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
