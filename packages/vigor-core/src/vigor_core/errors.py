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


class ArchiveLockedError(VigorError):
    """Another process holds the advisory lock on this archive directory.

    See ADR-0035: VIGOR-the-library is single-node by contract. The
    `RunArchive` constructor acquires `<archive_dir>/.archive.lock` exclusively
    and refuses to open if a peer process already holds it.
    """

    kind = "archive_locked"
    retryable = False


class ArchiveBusyError(VigorError):
    """Two ``Orchestrator.run`` / ``Orchestrator.resume`` calls overlap on
    the same archive root *within the same process*.

    Distinct from :class:`ArchiveLockedError`:

    - ``ArchiveLockedError`` — a *different process* holds the OS advisory
      lock on ``<archive>/.archive.lock`` (ADR-0035 / mx-7ce41e).
    - ``ArchiveBusyError`` — the same process already has an in-flight
      orchestrator run on this archive (ADR-0035 §Negative #1 / VIGOR-c2ec).

    Sibling, not subclass: ``except ArchiveLockedError`` MUST NOT swallow a
    busy error, because retry strategies for the two are different (busy
    requires the caller to fix their code; locked may resolve when the peer
    process exits). The guard lives at ``Orchestrator.run`` /
    ``Orchestrator.resume``, not at ``RunArchive.__init__``: adapter
    ``export()`` paths legitimately construct transient ``RunArchive``
    instances under the same OS lock (mx-514b28) and must continue to work
    during an active run.
    """

    kind = "archive_busy"
    retryable = False


class NoCheckpointError(VigorError):
    """No iteration checkpoint exists for the requested ``run_id``.

    See ADR-0036: ``Orchestrator.resume(run_id)`` requires an
    ``iteration_checkpoint.json`` written by a prior partial run. If the
    archive directory has no checkpoint (run never started, or crashed
    before its first iteration boundary), resume cannot proceed and this
    error is raised.
    """

    kind = "no_checkpoint"
    retryable = False
