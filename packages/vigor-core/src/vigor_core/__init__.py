"""VIGOR core package.

Public API:

* Schemas for tasks, IRs, compile results, reviews, patches, frontiers, provenance.
* Abstract interfaces for domain adapters, agent backends, and tool backends.
* Run archive implementation (filesystem-backed).
* Scoring normalization and adjudication policy.
* Frontier selection and best-of-N helpers.
"""

from vigor_core.archive import RunArchive
from vigor_core.errors import (
    AdapterContractError,
    BudgetExceededError,
    CompileError,
    ExportError,
    ReviewerError,
    SchemaValidationError,
    ToolTimeoutError,
    VigorError,
)
from vigor_core.interfaces import (
    AgentBackend,
    DomainAdapter,
    GenerationRequest,
    GenerationResult,
    PatchProposal,
    PatchProposalRequest,
    RepresentationPlan,
    ReviewRequest,
    ReviewResult,
    RunContext,
    ToolBackend,
    ToolResult,
    ValidationReport,
)
from vigor_core.schemas import (
    AdapterManifest,
    AdjudicationReport,
    ArtifactIR,
    Budgets,
    CompileResult,
    Constraint,
    ExportBundle,
    ExportEntry,
    Finding,
    Frontier,
    FrontierCandidate,
    ObservableArtifact,
    PatchPlan,
    ProvenanceActivity,
    ProvenanceRecord,
    ReferenceArtifact,
    ReviewReport,
    StopReason,
    TaskSpec,
    ToolManifest,
)
from vigor_core.schemas import (
    RuntimeErrorRecord as VigorRuntimeError,
)
from vigor_core.scoring import (
    AdjudicationInputs,
    ScoringPolicy,
    adjudicate,
    build_frontier,
    normalize_score,
    select_best,
)
from vigor_core.util import (
    safe_relative,
    sha256_bytes,
    sha256_file,
    sha256_text,
    stable_json,
    utcnow_iso,
)

__all__ = [
    "AdapterContractError",
    "AdapterManifest",
    "AdjudicationInputs",
    "AdjudicationReport",
    "AgentBackend",
    "ArtifactIR",
    "BudgetExceededError",
    "Budgets",
    "CompileError",
    "CompileResult",
    "Constraint",
    "DomainAdapter",
    "ExportBundle",
    "ExportEntry",
    "ExportError",
    "Finding",
    "Frontier",
    "FrontierCandidate",
    "GenerationRequest",
    "GenerationResult",
    "ObservableArtifact",
    "PatchPlan",
    "PatchProposal",
    "PatchProposalRequest",
    "ProvenanceActivity",
    "ProvenanceRecord",
    "ReferenceArtifact",
    "RepresentationPlan",
    "ReviewReport",
    "ReviewRequest",
    "ReviewResult",
    "ReviewerError",
    "RunArchive",
    "RunContext",
    "SchemaValidationError",
    "ScoringPolicy",
    "StopReason",
    "TaskSpec",
    "ToolBackend",
    "ToolManifest",
    "ToolResult",
    "ToolTimeoutError",
    "ValidationReport",
    "VigorError",
    "VigorRuntimeError",
    "adjudicate",
    "build_frontier",
    "normalize_score",
    "safe_relative",
    "select_best",
    "sha256_bytes",
    "sha256_file",
    "sha256_text",
    "stable_json",
    "utcnow_iso",
]

__version__ = "0.1.0"
