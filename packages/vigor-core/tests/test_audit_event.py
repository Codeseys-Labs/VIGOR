"""Tests for vigor.audit_event.v1 schema and InMemoryAuditSink chain."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from vigor_core.audit import AuditEvent, AuditOutcome, AuditSink, InMemoryAuditSink, NullAuditSink
from vigor_core.util import sha256_text, stable_json


def _roundtrip(model: AuditEvent) -> None:
    data = model.model_dump(by_alias=True, mode="json")
    rebuilt = AuditEvent.model_validate(data)
    assert rebuilt.model_dump(by_alias=True, mode="json") == data


def test_audit_event_minimum_fields_roundtrip() -> None:
    event = AuditEvent(
        event_id="evt_001",
        run_id="run_1",
        actor="agent.demo",
        tool_id="mcp.alpha.echo",
        payload_sha256=sha256_text("hello"),
    )
    _roundtrip(event)
    assert event.schema_version == "vigor.audit_event.v1"
    assert event.tenant_id is None
    assert event.prev_event_sha256 is None
    assert event.outcome == "success"


def test_audit_event_camelcase_aliases_on_wire() -> None:
    event = AuditEvent(
        event_id="evt_002",
        run_id="run_1",
        actor="agent.demo",
        tool_id="mcp.alpha.echo",
        payload_sha256=sha256_text("hi"),
    )
    payload = event.model_dump(by_alias=True, mode="json")
    assert "eventId" in payload
    assert "payloadSha256" in payload
    assert "tenantId" in payload
    assert "prevEventSha256" in payload


def test_audit_event_strict_mode_rejects_extra() -> None:
    with pytest.raises(ValidationError):
        AuditEvent.model_validate(
            {
                "eventId": "evt",
                "runId": "r",
                "actor": "a",
                "toolId": "mcp.x.y",
                "payloadSha256": sha256_text(""),
                "unknown": True,
            }
        )


def test_audit_event_outcome_literal() -> None:
    outcomes: tuple[AuditOutcome, ...] = ("success", "failure", "timeout", "denied")
    for outcome in outcomes:
        event = AuditEvent(
            event_id=f"evt_{outcome}",
            run_id="r",
            actor="a",
            tool_id="mcp.x.y",
            payload_sha256=sha256_text(""),
            outcome=outcome,
        )
        assert event.outcome == outcome


def test_audit_event_rejects_invalid_outcome() -> None:
    with pytest.raises(ValidationError):
        AuditEvent.model_validate(
            {
                "eventId": "evt",
                "runId": "r",
                "actor": "a",
                "toolId": "mcp.x.y",
                "payloadSha256": sha256_text(""),
                "outcome": "explode",
            }
        )


def test_audit_event_id_pattern_enforced() -> None:
    # event_id must match ID_PATTERN (no spaces, etc.)
    with pytest.raises(ValidationError):
        AuditEvent(
            event_id="bad id with spaces",
            run_id="r",
            actor="a",
            tool_id="mcp.x.y",
            payload_sha256=sha256_text(""),
        )


def test_audit_event_tenant_id_optional_validates_pattern() -> None:
    # When set, must obey ID_PATTERN
    with pytest.raises(ValidationError):
        AuditEvent(
            event_id="evt",
            run_id="r",
            tenant_id="bad tenant",
            actor="a",
            tool_id="mcp.x.y",
            payload_sha256=sha256_text(""),
        )


def test_audit_event_payload_sha256_hex_only() -> None:
    # payload_sha256 must be 64 hex chars (sha256 hex digest length).
    with pytest.raises(ValidationError):
        AuditEvent(
            event_id="evt",
            run_id="r",
            actor="a",
            tool_id="mcp.x.y",
            payload_sha256="not-a-real-hash",
        )


def test_audit_event_canonical_hash_is_stable_over_field_order() -> None:
    event = AuditEvent(
        event_id="evt_A",
        run_id="run_1",
        tenant_id="tenant_a",
        actor="agent.demo",
        tool_id="mcp.alpha.echo",
        payload_sha256=sha256_text("hello"),
        outcome="success",
    )
    h1 = event.canonical_hash()
    # Re-instantiating from the dump must yield the same hash.
    rebuilt = AuditEvent.model_validate(event.model_dump(by_alias=True, mode="json"))
    h2 = rebuilt.canonical_hash()
    assert h1 == h2
    # And it must be stable over JSON round-trip.
    h3 = AuditEvent.model_validate_json(event.model_dump_json(by_alias=True)).canonical_hash()
    assert h1 == h3


def test_audit_event_canonical_hash_excludes_no_fields() -> None:
    """canonical_hash includes every field (the hash is the chain link itself)."""

    base = AuditEvent(
        event_id="evt_A",
        run_id="run_1",
        actor="a",
        tool_id="mcp.x.y",
        payload_sha256=sha256_text("p"),
    )
    # Changing any field should change the hash.
    different_payload = base.model_copy(update={"payload_sha256": sha256_text("q")})
    assert base.canonical_hash() != different_payload.canonical_hash()


@pytest.mark.asyncio
async def test_null_audit_sink_is_a_noop() -> None:
    sink = NullAuditSink()
    # emit must be a no-op and must not raise.
    await sink.emit(
        AuditEvent(
            event_id="evt",
            run_id="r",
            actor="a",
            tool_id="mcp.x.y",
            payload_sha256=sha256_text(""),
        )
    )
    # last_event remains None.
    assert sink.last_event_sha256() is None


@pytest.mark.asyncio
async def test_inmemory_sink_chains_events() -> None:
    sink = InMemoryAuditSink()
    e1 = AuditEvent(
        event_id="evt_1",
        run_id="r",
        actor="a",
        tool_id="mcp.x.y",
        payload_sha256=sha256_text("p1"),
    )
    e2 = AuditEvent(
        event_id="evt_2",
        run_id="r",
        actor="a",
        tool_id="mcp.x.y",
        payload_sha256=sha256_text("p2"),
    )
    e1_chained = await sink.emit(e1)
    e2_chained = await sink.emit(e2)

    assert e1_chained.prev_event_sha256 is None
    assert e2_chained.prev_event_sha256 == e1_chained.canonical_hash()
    assert sink.last_event_sha256() == e2_chained.canonical_hash()
    assert [e.event_id for e in sink.events()] == ["evt_1", "evt_2"]


@pytest.mark.asyncio
async def test_inmemory_sink_emit_does_not_mutate_input() -> None:
    """emit returns a new event with prev_event_sha256 wired; the input is unchanged."""

    sink = InMemoryAuditSink()
    e1 = AuditEvent(
        event_id="evt_1",
        run_id="r",
        actor="a",
        tool_id="mcp.x.y",
        payload_sha256=sha256_text("p1"),
    )
    original_prev = e1.prev_event_sha256
    chained = await sink.emit(e1)
    # The caller's reference is untouched.
    assert e1.prev_event_sha256 is original_prev is None
    # The chained copy carries the correct prev (still None for first event).
    assert chained.prev_event_sha256 is None


@pytest.mark.asyncio
async def test_inmemory_sink_chain_survives_roundtrip() -> None:
    """A sink-emitted event must remain JSON-roundtrippable to canonicalize the chain."""

    sink = InMemoryAuditSink()
    e1 = await sink.emit(
        AuditEvent(
            event_id="evt_1",
            run_id="r",
            actor="a",
            tool_id="mcp.x.y",
            payload_sha256=sha256_text("p1"),
        )
    )
    payload = e1.model_dump(by_alias=True, mode="json")
    rebuilt = AuditEvent.model_validate(payload)
    assert rebuilt.canonical_hash() == e1.canonical_hash()
    # And the canonical hash matches the documented stable_json projection.
    expected = sha256_text(stable_json(json.loads(rebuilt.model_dump_json(by_alias=True))))
    assert rebuilt.canonical_hash() == expected


def test_audit_sink_abc_requires_emit() -> None:
    """AuditSink is an abstract base class with `emit` abstract."""

    assert AuditSink.__abstractmethods__ == frozenset({"emit"})
