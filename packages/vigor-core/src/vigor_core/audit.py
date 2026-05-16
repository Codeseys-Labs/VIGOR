"""Audit event schema and sink contract for VIGOR tool-call boundary records.

`AuditEvent` is an append-only, hash-chained record emitted at every
adapter / backend / `MCPToolBackend.call_tool` boundary. The schema is
forensic-grade: it stores ``payload_sha256`` (not the raw payload), so a
replay can prove a payload existed and what its hash was without
retaining cleartext that may contain PII.

`AuditSink` is the persistence contract; the runtime owns the sink, and
the chain integrity (``prev_event_sha256``) is a sink concern, not a
producer concern. Multiple producers (``MCPToolBackend`` today,
``AgentBackend`` tomorrow) share one chain by sharing one sink.
"""

from __future__ import annotations

import abc
import asyncio
import json
from typing import Literal

from pydantic import Field

from vigor_core.schemas import ID_PATTERN, _VigorBase
from vigor_core.util import sha256_text, stable_json, utcnow_iso

AuditOutcome = Literal["success", "failure", "timeout", "denied"]

# 64 lowercase hex characters — the literal length of a SHA-256 hex digest.
_SHA256_HEX_PATTERN = r"^[0-9a-f]{64}$"


class AuditEvent(_VigorBase):
    """Append-only record of one tool-call boundary crossing.

    Hash chain semantics
    --------------------
    ``prev_event_sha256`` is the canonical hash of the previous event in
    the same chain (typically the same ``run_id``). The first event in a
    chain leaves it ``None``. The chain link is `AuditEvent.canonical_hash`,
    which hashes the ``stable_json`` of the camelCase payload. Tampering
    with any prior event invalidates every subsequent ``prev_event_sha256``.

    PII posture
    -----------
    The schema deliberately omits the raw tool payload. Operators that
    need to forensically replay a tool call store the payload elsewhere
    (typically the run archive, which already has tenant scoping per
    ADR-0029) and reference it via ``payload_sha256``. Secrets in the
    payload are scrubbed by ``pydantic.SecretStr`` at the config
    boundary; the audit event records only the hash.
    """

    schema_version: Literal["vigor.audit_event.v1"] = "vigor.audit_event.v1"
    event_id: str = Field(pattern=ID_PATTERN)
    created_at: str = Field(default_factory=utcnow_iso)
    tenant_id: str | None = Field(default=None, pattern=ID_PATTERN)
    run_id: str = Field(pattern=ID_PATTERN)
    actor: str
    tool_id: str
    payload_sha256: str = Field(pattern=_SHA256_HEX_PATTERN)
    outcome: AuditOutcome = "success"
    prev_event_sha256: str | None = Field(default=None, pattern=_SHA256_HEX_PATTERN)

    def canonical_hash(self) -> str:
        """Return the SHA-256 of this event's canonical (stable, camelCase) JSON."""

        wire = json.loads(self.model_dump_json(by_alias=True))
        return sha256_text(stable_json(wire))


class AuditSink(abc.ABC):
    """Persistence contract for `AuditEvent`s.

    Implementations own the chain: ``emit`` returns a new event with
    ``prev_event_sha256`` wired to the previously emitted event's
    ``canonical_hash``. The first event in a chain returns with
    ``prev_event_sha256=None``.
    """

    @abc.abstractmethod
    async def emit(self, event: AuditEvent) -> AuditEvent:
        """Persist ``event`` and return the chained copy actually stored."""


class NullAuditSink(AuditSink):
    """No-op sink used when audit logging is not configured.

    ``last_event_sha256`` always returns ``None`` because nothing is
    persisted.
    """

    async def emit(self, event: AuditEvent) -> AuditEvent:
        return event

    def last_event_sha256(self) -> str | None:
        return None


class InMemoryAuditSink(AuditSink):
    """In-process sink useful for tests and short-lived deployments.

    The chain lives in a list; concurrent producers serialize through an
    ``asyncio.Lock`` so the chain stays totally-ordered even under
    overlapping ``emit`` calls.
    """

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []
        self._lock = asyncio.Lock()

    async def emit(self, event: AuditEvent) -> AuditEvent:
        async with self._lock:
            prev = self._events[-1].canonical_hash() if self._events else None
            chained = event.model_copy(update={"prev_event_sha256": prev})
            self._events.append(chained)
            return chained

    def events(self) -> list[AuditEvent]:
        return list(self._events)

    def last_event_sha256(self) -> str | None:
        if not self._events:
            return None
        return self._events[-1].canonical_hash()


__all__ = [
    "AuditEvent",
    "AuditOutcome",
    "AuditSink",
    "InMemoryAuditSink",
    "NullAuditSink",
]
