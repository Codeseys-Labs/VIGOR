"""Tests that MCPToolBackend.call_tool emits audit events at every boundary."""

from __future__ import annotations

import asyncio
import itertools
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

import pytest
from vigor_core.agent_config import MCPServerSpec
from vigor_core.audit import AuditEvent, InMemoryAuditSink
from vigor_core.util import sha256_text, stable_json
from vigor_mcp.backend import MCPToolBackend


@dataclass
class _FakeContentBlock:
    text: str

    def model_dump(self) -> dict[str, Any]:
        return {"type": "text", "text": self.text}


@dataclass
class _FakeCallResult:
    content: list[_FakeContentBlock] = field(default_factory=list)
    isError: bool = False
    structuredContent: dict[str, Any] | None = None


@dataclass
class _FakeTool:
    name: str
    annotations: dict[str, Any] = field(default_factory=dict)
    description: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "annotations": self.annotations,
        }


@dataclass
class _FakeListResult:
    tools: list[_FakeTool] = field(default_factory=list)


class _Session:
    def __init__(
        self,
        *,
        tools: list[_FakeTool],
        call_result: _FakeCallResult | None = None,
        raise_call: BaseException | None = None,
    ) -> None:
        self._tools = tools
        self._call_result = call_result or _FakeCallResult(content=[_FakeContentBlock(text="ok")])
        self._raise_call = raise_call
        self.call_log: list[tuple[str, dict[str, Any] | None]] = []

    async def list_tools(self) -> _FakeListResult:
        return _FakeListResult(tools=list(self._tools))

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> _FakeCallResult:
        self.call_log.append((name, arguments))
        if self._raise_call is not None:
            raise self._raise_call
        return self._call_result


def _opener(session: _Session) -> Any:
    async def open_(spec: MCPServerSpec, stack: AsyncExitStack) -> _Session:
        return session

    return open_


def _spec(server_id: str = "alpha", *, timeout_s: int = 30) -> MCPServerSpec:
    return MCPServerSpec(
        server_id=server_id,
        transport="stdio",
        command=["irrelevant"],
        timeout_s=timeout_s,
    )


def _deterministic_event_id_factory() -> Any:
    counter = itertools.count(1)
    return lambda: f"evt_{next(counter):03d}"


@pytest.mark.asyncio
async def test_audit_event_emitted_on_success() -> None:
    session = _Session(tools=[_FakeTool(name="echo")])
    sink = InMemoryAuditSink()
    backend = MCPToolBackend(
        [_spec()],
        session_opener=_opener(session),
        audit_sink=sink,
        actor="agent.demo",
        run_id="run_1",
        event_id_factory=_deterministic_event_id_factory(),
    )
    payload = {"x": 1}
    result = await backend.call_tool("mcp.alpha.echo", payload)
    assert result.status == "success"

    events = sink.events()
    assert len(events) == 1
    event = events[0]
    assert event.actor == "agent.demo"
    assert event.run_id == "run_1"
    assert event.tool_id == "mcp.alpha.echo"
    assert event.outcome == "success"
    assert event.payload_sha256 == sha256_text(stable_json(payload))
    assert event.prev_event_sha256 is None
    await backend.aclose()


@pytest.mark.asyncio
async def test_audit_event_emitted_on_unknown_server_denial() -> None:
    sink = InMemoryAuditSink()
    backend = MCPToolBackend(
        [_spec("alpha")],
        session_opener=_opener(_Session(tools=[])),
        audit_sink=sink,
        actor="agent.demo",
        run_id="run_1",
    )
    result = await backend.call_tool("mcp.missing.echo", {})
    assert result.status == "failure"

    events = sink.events()
    assert len(events) == 1
    assert events[0].outcome == "denied"
    assert events[0].tool_id == "mcp.missing.echo"
    await backend.aclose()


@pytest.mark.asyncio
async def test_audit_event_emitted_on_allowlist_block() -> None:
    sink = InMemoryAuditSink()
    spec = MCPServerSpec(
        server_id="alpha",
        transport="stdio",
        command=["x"],
        tool_allowlist=["echo"],
    )
    backend = MCPToolBackend(
        [spec],
        session_opener=_opener(_Session(tools=[_FakeTool(name="echo")])),
        audit_sink=sink,
        actor="agent.demo",
        run_id="run_1",
    )
    result = await backend.call_tool("mcp.alpha.reverse", {})
    assert result.status == "failure"
    events = sink.events()
    assert len(events) == 1
    assert events[0].outcome == "denied"
    assert events[0].tool_id == "mcp.alpha.reverse"
    await backend.aclose()


@pytest.mark.asyncio
async def test_audit_event_emitted_on_mutator_capability_denial() -> None:
    sink = InMemoryAuditSink()
    session = _Session(tools=[_FakeTool(name="write", annotations={"destructiveHint": True})])
    backend = MCPToolBackend(
        [_spec()],
        session_opener=_opener(session),
        audit_sink=sink,
        actor="agent.demo",
        run_id="run_1",
    )
    result = await backend.call_tool("mcp.alpha.write", {"data": "x"})
    assert result.status == "failure"
    assert "requires capability grant" in (result.error or "")

    events = sink.events()
    assert len(events) == 1
    assert events[0].outcome == "denied"
    # The session was NOT invoked.
    assert session.call_log == []
    await backend.aclose()


@pytest.mark.asyncio
async def test_audit_event_emitted_on_timeout() -> None:
    class _SlowSession:
        def __init__(self) -> None:
            self.call_log: list[tuple[str, dict[str, Any] | None]] = []

        async def list_tools(self) -> _FakeListResult:
            return _FakeListResult(tools=[_FakeTool(name="echo")])

        async def call_tool(
            self, name: str, arguments: dict[str, Any] | None = None
        ) -> _FakeCallResult:
            self.call_log.append((name, arguments))
            await asyncio.sleep(2.0)
            return _FakeCallResult()

    sink = InMemoryAuditSink()
    backend = MCPToolBackend(
        [_spec(timeout_s=1)],
        session_opener=_opener(_SlowSession()),  # type: ignore[arg-type]
        audit_sink=sink,
        actor="agent.demo",
        run_id="run_1",
    )
    result = await backend.call_tool("mcp.alpha.echo", {})
    assert result.status == "timeout"
    events = sink.events()
    assert len(events) == 1
    assert events[0].outcome == "timeout"
    await backend.aclose()


@pytest.mark.asyncio
async def test_audit_event_emitted_on_underlying_failure() -> None:
    sink = InMemoryAuditSink()
    session = _Session(
        tools=[_FakeTool(name="echo")],
        raise_call=RuntimeError("boom"),
    )
    backend = MCPToolBackend(
        [_spec()],
        session_opener=_opener(session),
        audit_sink=sink,
        actor="agent.demo",
        run_id="run_1",
    )
    result = await backend.call_tool("mcp.alpha.echo", {})
    assert result.status == "failure"
    events = sink.events()
    assert len(events) == 1
    assert events[0].outcome == "failure"
    await backend.aclose()


@pytest.mark.asyncio
async def test_audit_events_chain_across_calls() -> None:
    sink = InMemoryAuditSink()
    session = _Session(tools=[_FakeTool(name="echo")])
    backend = MCPToolBackend(
        [_spec()],
        session_opener=_opener(session),
        audit_sink=sink,
        actor="agent.demo",
        run_id="run_1",
    )
    await backend.call_tool("mcp.alpha.echo", {"a": 1})
    await backend.call_tool("mcp.alpha.echo", {"a": 2})
    await backend.call_tool("mcp.alpha.echo", {"a": 3})

    events = sink.events()
    assert len(events) == 3
    assert events[0].prev_event_sha256 is None
    assert events[1].prev_event_sha256 == events[0].canonical_hash()
    assert events[2].prev_event_sha256 == events[1].canonical_hash()
    await backend.aclose()


@pytest.mark.asyncio
async def test_audit_event_payload_sha256_independent_of_dict_order() -> None:
    sink = InMemoryAuditSink()
    backend = MCPToolBackend(
        [_spec()],
        session_opener=_opener(_Session(tools=[_FakeTool(name="echo")])),
        audit_sink=sink,
        actor="agent.demo",
        run_id="run_1",
    )
    await backend.call_tool("mcp.alpha.echo", {"a": 1, "b": 2})
    await backend.call_tool("mcp.alpha.echo", {"b": 2, "a": 1})
    events = sink.events()
    assert events[0].payload_sha256 == events[1].payload_sha256
    await backend.aclose()


@pytest.mark.asyncio
async def test_audit_event_carries_tenant_id_when_configured() -> None:
    sink = InMemoryAuditSink()
    backend = MCPToolBackend(
        [_spec()],
        session_opener=_opener(_Session(tools=[_FakeTool(name="echo")])),
        audit_sink=sink,
        actor="agent.demo",
        run_id="run_1",
        tenant_id="tenant_a",
    )
    await backend.call_tool("mcp.alpha.echo", {})
    events = sink.events()
    assert events[0].tenant_id == "tenant_a"
    await backend.aclose()


@pytest.mark.asyncio
async def test_no_audit_when_no_sink_configured() -> None:
    """Backwards compatibility: existing callers don't see audit behavior change."""

    backend = MCPToolBackend(
        [_spec()],
        session_opener=_opener(_Session(tools=[_FakeTool(name="echo")])),
    )
    # Must work without actor/run_id/sink.
    result = await backend.call_tool("mcp.alpha.echo", {})
    assert result.status == "success"
    await backend.aclose()


@pytest.mark.asyncio
async def test_audit_event_collapsed_across_retries() -> None:
    """Retries (VIGOR-2585) emit ONE audit event per logical call_tool, not per attempt.

    The sink-owned hash chain (mx-0eae76) treats each emit() as a logical
    call boundary; per-attempt audit would corrupt the chain semantics
    that test_audit_events_chain_across_calls relies on.
    """

    class _RetryThenSucceed:
        def __init__(self) -> None:
            self.call_log: list[tuple[str, dict[str, Any] | None]] = []

        async def list_tools(self) -> _FakeListResult:
            return _FakeListResult(tools=[_FakeTool(name="echo")])

        async def call_tool(
            self, name: str, arguments: dict[str, Any] | None = None
        ) -> _FakeCallResult:
            self.call_log.append((name, arguments))
            if len(self.call_log) < 3:
                raise RuntimeError("transient")
            return _FakeCallResult(content=[_FakeContentBlock(text="ok")])

    sink = InMemoryAuditSink()
    session = _RetryThenSucceed()

    async def _no_sleep(_delay: float) -> None:
        return None

    backend = MCPToolBackend(
        [_spec()],
        session_opener=_opener(session),  # type: ignore[arg-type]
        audit_sink=sink,
        actor="agent.demo",
        run_id="run_1",
        max_tool_retries=3,
        retry_base_delay_s=0.0,
        sleep=_no_sleep,
    )
    result = await backend.call_tool("mcp.alpha.echo", {"x": 1})
    assert result.status == "success"
    assert len(session.call_log) == 3

    events = sink.events()
    # Exactly one audit event for the logical call (final outcome).
    assert len(events) == 1
    assert events[0].outcome == "success"
    await backend.aclose()


@pytest.mark.asyncio
async def test_audit_sink_failure_propagates_fail_closed() -> None:
    """A sink that raises must abort the call — audit gap is a security failure."""

    class _BrokenSink(InMemoryAuditSink):
        async def emit(self, event: AuditEvent) -> AuditEvent:
            raise RuntimeError("disk full")

    backend = MCPToolBackend(
        [_spec()],
        session_opener=_opener(_Session(tools=[_FakeTool(name="echo")])),
        audit_sink=_BrokenSink(),
        actor="agent.demo",
        run_id="run_1",
    )
    with pytest.raises(RuntimeError, match="disk full"):
        await backend.call_tool("mcp.alpha.echo", {})
    await backend.aclose()
