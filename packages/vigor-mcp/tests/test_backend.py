"""Unit tests for MCPToolBackend with a stub session opener."""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

import pytest
from vigor_core.agent_config import MCPServerSpec
from vigor_mcp.backend import MCPBackendError, MCPToolBackend


@dataclass
class _FakeTool:
    name: str
    description: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description}


@dataclass
class _FakeListResult:
    tools: list[_FakeTool] = field(default_factory=list)


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


class _FakeSession:
    def __init__(self) -> None:
        self.list_calls = 0
        self.call_log: list[tuple[str, dict[str, Any] | None]] = []

    async def list_tools(self) -> _FakeListResult:
        self.list_calls += 1
        return _FakeListResult(tools=[_FakeTool(name="echo"), _FakeTool(name="reverse")])

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> _FakeCallResult:
        self.call_log.append((name, arguments))
        if name == "echo":
            return _FakeCallResult(
                content=[_FakeContentBlock(text=str(arguments))],
                structuredContent={"echo": arguments},
            )
        if name == "boom":
            return _FakeCallResult(
                content=[_FakeContentBlock(text="something broke")],
                isError=True,
            )
        return _FakeCallResult(content=[_FakeContentBlock(text="?")])


class _OpenerFactory:
    def __init__(self) -> None:
        self.sessions: dict[str, _FakeSession] = {}
        self.opened: list[str] = []

    async def __call__(self, spec: MCPServerSpec, stack: AsyncExitStack) -> _FakeSession:
        self.opened.append(spec.server_id)
        session = self.sessions.setdefault(spec.server_id, _FakeSession())
        return session


def _stdio_spec(server_id: str = "fake") -> MCPServerSpec:
    return MCPServerSpec(
        server_id=server_id,
        transport="stdio",
        command=["irrelevant"],
    )


@pytest.mark.asyncio
async def test_list_tools_namespaces_by_server_id() -> None:
    opener = _OpenerFactory()
    backend = MCPToolBackend([_stdio_spec("alpha")], session_opener=opener)
    tools = await backend.list_tools()
    assert {t.tool_id for t in tools} == {"mcp.alpha.echo", "mcp.alpha.reverse"}
    await backend.aclose()


@pytest.mark.asyncio
async def test_call_tool_routes_to_named_server() -> None:
    opener = _OpenerFactory()
    backend = MCPToolBackend([_stdio_spec("alpha"), _stdio_spec("beta")], session_opener=opener)
    result = await backend.call_tool("mcp.beta.echo", {"x": 1})
    assert result.status == "success"
    assert opener.opened == ["beta"]
    assert opener.sessions["beta"].call_log == [("echo", {"x": 1})]
    await backend.aclose()


@pytest.mark.asyncio
async def test_call_tool_unknown_server_returns_failure() -> None:
    backend = MCPToolBackend([_stdio_spec("alpha")], session_opener=_OpenerFactory())
    result = await backend.call_tool("mcp.missing.echo", {})
    assert result.status == "failure"
    assert "missing" in (result.error or "")
    await backend.aclose()


@pytest.mark.asyncio
async def test_call_tool_invalid_tool_id_raises() -> None:
    backend = MCPToolBackend([_stdio_spec("alpha")], session_opener=_OpenerFactory())
    with pytest.raises(MCPBackendError):
        await backend.call_tool("not.an.mcp.tool", {})
    await backend.aclose()


@pytest.mark.asyncio
async def test_call_tool_propagates_is_error() -> None:
    opener = _OpenerFactory()
    backend = MCPToolBackend([_stdio_spec("alpha")], session_opener=opener)
    result = await backend.call_tool("mcp.alpha.boom", {})
    assert result.status == "failure"
    assert "something broke" in (result.error or "")
    await backend.aclose()


@pytest.mark.asyncio
async def test_tool_allowlist_blocks_disallowed_tools() -> None:
    opener = _OpenerFactory()
    spec = MCPServerSpec(
        server_id="alpha",
        transport="stdio",
        command=["x"],
        tool_allowlist=["echo"],
    )
    backend = MCPToolBackend([spec], session_opener=opener)
    tools = await backend.list_tools()
    assert {t.tool_id for t in tools} == {"mcp.alpha.echo"}

    blocked = await backend.call_tool("mcp.alpha.reverse", {})
    assert blocked.status == "failure"
    assert "blocked by allowlist" in (blocked.error or "")
    await backend.aclose()


@pytest.mark.asyncio
async def test_session_opened_only_once_per_server() -> None:
    opener = _OpenerFactory()
    backend = MCPToolBackend([_stdio_spec("alpha")], session_opener=opener)
    await backend.list_tools()
    await backend.call_tool("mcp.alpha.echo", {"a": 1})
    await backend.call_tool("mcp.alpha.echo", {"a": 2})
    assert opener.opened.count("alpha") == 1
    await backend.aclose()
