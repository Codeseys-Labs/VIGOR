"""Typed errors for the VIGOR runtime.

Adapters and backends should raise `VigorError` or a subclass to produce a
structured runtime error record. Uncaught exceptions are converted to
`VigorError` by the orchestrator.
"""

from __future__ import annotations


class VigorError(Exception):
    """Base class for VIGOR structured errors."""

    kind: str = "generic"
    retryable: bool = False

    def __init__(
        self,
        message: str,
        *,
        kind: str | None = None,
        retryable: bool | None = None,
        evidence_uri: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if kind is not None:
            self.kind = kind
        if retryable is not None:
            self.retryable = retryable
        self.evidence_uri = evidence_uri


class SchemaValidationError(VigorError):
    kind = "schema_validation"
    retryable = False


class CompileError(VigorError):
    kind = "compile_error"
    retryable = False


class ToolTimeoutError(VigorError):
    kind = "tool_timeout"
    retryable = True


class ReviewerError(VigorError):
    kind = "reviewer_error"
    retryable = True


class ExportError(VigorError):
    kind = "export_error"
    retryable = False


class BudgetExceededError(VigorError):
    kind = "budget_exceeded"
    retryable = False


class AdapterContractError(VigorError):
    kind = "adapter_contract"
    retryable = False
