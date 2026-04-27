"""VIGOR Pydantic v2 schemas.

This module defines every runtime object referenced by the architecture docs:
tasks, adapter manifests, editable IRs, compile results, review reports,
adjudication reports, patch plans, export bundles, frontiers, and provenance.

Design rules (see ADR-0011):

* All models inherit from `_VigorBase` which enables strict mode and forbids
  extra fields.
* Persisted top-level records carry `schema_version`, a stable id, and
  `created_at`.
* Field names are snake_case in Python; JSON serialization uses camelCase via
  an alias generator.
* Adapter-specific fields go under `domain` so extensions stay explicit.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from vigor_core.util import utcnow_iso

# ---------------------------------------------------------------------------
# Base classes
# ---------------------------------------------------------------------------


class _VigorBase(BaseModel):
    """Shared Pydantic config for VIGOR schema objects."""

    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        populate_by_name=True,
        alias_generator=to_camel,
        from_attributes=False,
        frozen=False,
    )


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------


class ReferenceArtifact(_VigorBase):
    """Pointer to an input artifact on disk or remote storage."""

    artifact_id: str
    uri: str
    media_type: str | None = None
    sha256: str | None = None


class Constraint(_VigorBase):
    """Declarative constraint applied to a task."""

    id: str
    type: str
    text: str


class Budgets(_VigorBase):
    """Resource budgets the orchestrator should enforce."""

    max_iterations: int = 5
    max_candidates: int = 4
    max_wall_clock_s: int = 1800
    max_cost_usd: float | None = None
    max_tool_retries: int = 2


# ---------------------------------------------------------------------------
# Task specification
# ---------------------------------------------------------------------------


class TaskSpec(_VigorBase):
    schema_version: Literal["vigor.task.v1"] = "vigor.task.v1"
    task_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    goal: str
    modalities: list[str]
    references: list[ReferenceArtifact] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
    target_outputs: list[str] = Field(default_factory=list)
    budgets: Budgets = Field(default_factory=Budgets)
    human_mode: Literal["automatic", "checkpoint", "interactive"] = "automatic"
    domain: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Adapter manifests and tool declarations
# ---------------------------------------------------------------------------


class ToolManifest(_VigorBase):
    tool_id: str
    capability: Literal[
        "compile", "render", "simulate", "inspect", "score", "patch", "export", "observe"
    ]
    mutability: Literal["observer", "mutator"] = "observer"
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    timeout_s: int | None = None
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    description: str | None = None


class AdapterManifest(_VigorBase):
    schema_version: Literal["vigor.adapter_manifest.v1"] = "vigor.adapter_manifest.v1"
    adapter_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    domain: str
    version: str
    supported_ir: list[str]
    tools: list[ToolManifest] = Field(default_factory=list)
    reviewers: list[str] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Editable IR wrapper
# ---------------------------------------------------------------------------


class ArtifactIR(_VigorBase):
    """Opaque wrapper around a domain-specific IR payload.

    Adapters parse the `body` field into their own Pydantic IR models. The
    wrapper preserves hash, lineage, and generator metadata so the runtime can
    version and replay artifacts without knowing the domain schema.
    """

    schema_version: Literal["vigor.artifact_ir.v1"] = "vigor.artifact_ir.v1"
    candidate_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    ir_type: str
    parent_candidate_id: str | None = None
    hypothesis: str | None = None
    body: dict[str, Any] = Field(default_factory=dict)
    body_sha256: str | None = None
    generator: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Compilation / rendering / simulation
# ---------------------------------------------------------------------------


StopReason = Literal[
    "accepted",
    "budget_exhausted",
    "plateau",
    "human_selected",
    "failed",
    "escalated",
]


class ObservableArtifact(_VigorBase):
    """A produced asset that reviewers can inspect."""

    artifact_id: str
    uri: str
    media_type: str
    sha256: str | None = None
    summary: str | None = None


class RuntimeErrorRecord(_VigorBase):
    """Structured runtime error record.

    Renamed from ``RuntimeError`` to avoid shadowing the builtin inside this
    module. The public ``__init__`` exports it as ``VigorRuntimeError``.
    """

    schema_version: Literal["vigor.runtime_error.v1"] = "vigor.runtime_error.v1"
    error_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    type: Literal[
        "schema_validation",
        "compile_error",
        "render_error",
        "tool_timeout",
        "reviewer_error",
        "export_error",
        "budget_exceeded",
        "adapter_contract",
        "generic",
    ] = "generic"
    severity: Literal["high", "medium", "low"] = "medium"
    message: str
    tool_id: str | None = None
    retryable: bool = False
    evidence_uri: str | None = None


class CompileResult(_VigorBase):
    schema_version: Literal["vigor.compile_result.v1"] = "vigor.compile_result.v1"
    compile_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    candidate_id: str
    tool_id: str
    status: Literal["success", "failure", "timeout", "cancelled"]
    inputs: list[ReferenceArtifact] = Field(default_factory=list)
    outputs: list[ObservableArtifact] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[RuntimeErrorRecord] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Review reports
# ---------------------------------------------------------------------------


class Finding(_VigorBase):
    id: str
    severity: Literal["high", "medium", "low", "info"]
    category: str
    artifact_ref: str | None = None
    location: dict[str, Any] = Field(default_factory=dict)
    evidence: str
    rule_or_rubric: str | None = None
    suggestion: str | None = None
    verified_by_tool: bool = False


class ReviewReport(_VigorBase):
    schema_version: Literal["vigor.review_report.v1"] = "vigor.review_report.v1"
    review_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    candidate_id: str
    artifact_id: str | None = None
    reviewer_id: str
    reviewer_type: Literal[
        "objective_metric",
        "learned_scorer",
        "model_critic",
        "tool_inspector",
        "human",
    ]
    summary: str
    scores: dict[str, float] = Field(default_factory=dict)
    thresholds: dict[str, float] = Field(default_factory=dict)
    passed: bool
    confidence: float | None = None
    findings: list[Finding] = Field(default_factory=list)
    recommended_action: Literal["accept", "patch", "branch", "pivot", "escalate", "fail"] = "accept"
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Adjudication
# ---------------------------------------------------------------------------


class AdjudicationReport(_VigorBase):
    schema_version: Literal["vigor.adjudication_report.v1"] = "vigor.adjudication_report.v1"
    adjudication_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    candidate_id: str
    policy_id: str
    hard_gate_passed: bool
    normalized_scores: dict[str, float] = Field(default_factory=dict)
    composite: float | None = None
    reviewer_disagreement: float | None = None
    decision: Literal["accept", "patch", "branch", "pivot", "escalate", "fail"]
    basis: list[str] = Field(default_factory=list)
    selection_reason: str | None = None
    residual_risks: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Patches
# ---------------------------------------------------------------------------


class PatchPlan(_VigorBase):
    schema_version: Literal["vigor.patch_plan.v1"] = "vigor.patch_plan.v1"
    patch_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    source_candidate_id: str
    basis: list[str] = Field(default_factory=list)
    objectives: list[str]
    do_not_change: list[str] = Field(default_factory=list)
    allowed_operations: list[str] = Field(default_factory=list)
    risk_level: Literal["low", "medium", "high"] = "low"
    expected_validation: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------


class ExportEntry(_VigorBase):
    type: str
    uri: str
    media_type: str | None = None
    sha256: str | None = None


class ExportBundle(_VigorBase):
    schema_version: Literal["vigor.export_bundle.v1"] = "vigor.export_bundle.v1"
    export_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    candidate_id: str
    exports: list[ExportEntry] = Field(default_factory=list)
    lossiness: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Frontier
# ---------------------------------------------------------------------------


class FrontierCandidate(_VigorBase):
    candidate_id: str
    status: Literal["selected", "kept", "rejected"] = "kept"
    scores: dict[str, float] = Field(default_factory=dict)
    hard_gate_passed: bool = True
    rank: int | None = None
    selection_reason: str | None = None


class Frontier(_VigorBase):
    schema_version: Literal["vigor.frontier.v1"] = "vigor.frontier.v1"
    frontier_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    run_id: str
    selection_policy: str
    candidates: list[FrontierCandidate] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


class ProvenanceActivity(_VigorBase):
    activity_id: str
    type: Literal["generation", "compile", "review", "adjudication", "patch", "export"]
    agent: str | None = None
    model: str | None = None
    tool_id: str | None = None
    reviewer_id: str | None = None


class ProvenanceRecord(_VigorBase):
    schema_version: Literal["vigor.provenance.v1"] = "vigor.provenance.v1"
    provenance_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    run_id: str
    task_id: str
    selected_candidate_id: str | None = None
    inputs: list[str] = Field(default_factory=list)
    activities: list[ProvenanceActivity] = Field(default_factory=list)
    derived_artifacts: list[str] = Field(default_factory=list)
    stop_reason: StopReason = "accepted"
    residual_risks: list[str] = Field(default_factory=list)
