"""End-to-end integration tests for ``MCPToolBackend`` against a real MCP server.

Most ``vigor-mcp`` tests stub ``SessionOpener`` to keep them fast and
hermetic. This module flips that polarity: it spawns the lightweight
reference server in ``tests/_fixtures/echo_mcp_server.py`` as a real
subprocess and drives it through the production stdio transport
(``vigor_mcp.transports.sdk.open_session``).

The test is gated two ways:

1. Module-level ``pytest.importorskip("mcp")`` -- if the official
   Python MCP SDK is not installed, the whole module is skipped.
2. ``@pytest.mark.requires_mcp`` -- declared on every test, so a CI
   matrix that excludes the marker (``pytest -m "not requires_mcp"``)
   skips these tests cleanly without false failures.

To run only the integration suite::

    uv run pytest packages/vigor-mcp/tests/test_integration_real.py -m requires_mcp

To run everything except integration::

    uv run pytest -m "not requires_mcp"
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Skip the entire module if the optional ``mcp`` SDK is missing -- the
# stdio transport in ``vigor_mcp.transports.sdk`` imports it lazily and
# the test cannot drive a real subprocess server without it.
pytest.importorskip("mcp")

from vigor_core.agent_config import MCPServerSpec
from vigor_mcp.backend import MCPToolBackend

_FIXTURE_SERVER = Path(__file__).parent / "_fixtures" / "echo_mcp_server.py"


def _spec(
    server_id: str = "ref",
    *,
    timeout_s: int = 10,
    tool_allowlist: list[str] | None = None,
) -> MCPServerSpec:
    """Build a stdio ``MCPServerSpec`` that runs the in-tree fixture server."""

    return MCPServerSpec(
        server_id=server_id,
        transport="stdio",
        command=[sys.executable, str(_FIXTURE_SERVER)],
        timeout_s=timeout_s,
        tool_allowlist=tool_allowlist,
    )


pytestmark = pytest.mark.requires_mcp


async def test_list_tools_against_real_server() -> None:
    """``list_tools`` should round-trip through subprocess + stdio + initialize."""

    backend = MCPToolBackend([_spec("ref")])
    try:
        tools = await backend.list_tools()
    finally:
        await backend.aclose()

    tool_ids = {t.tool_id for t in tools}
    assert {"mcp.ref.echo", "mcp.ref.add", "mcp.ref.slow", "mcp.ref.boom"} <= tool_ids


async def test_call_tool_round_trips_arguments_and_result() -> None:
    """A real ``call_tool`` returns a success ``ToolResult`` with content blocks."""

    backend = MCPToolBackend([_spec("ref")])
    try:
        result = await backend.call_tool("mcp.ref.echo", {"message": "hello"})
    finally:
        await backend.aclose()

    assert result.status == "success"
    assert result.tool_id == "mcp.ref.echo"
    # FastMCP wraps return values as text content blocks.
    content = (result.output or {}).get("content") or []
    assert any("hello" in (block.get("text") or "") for block in content), result.output


async def test_call_tool_with_structured_arguments() -> None:
    """Confirm structured int args survive serialization through the SDK."""

    backend = MCPToolBackend([_spec("ref")])
    try:
        result = await backend.call_tool("mcp.ref.add", {"a": 7, "b": 35})
    finally:
        await backend.aclose()

    assert result.status == "success"
    content = (result.output or {}).get("content") or []
    text_blocks = [block.get("text") for block in content if block.get("text")]
    # "42" should appear in either the text content or any structured field.
    assert any("42" in (text or "") for text in text_blocks) or "42" in str(result.output)


async def test_tool_allowlist_blocks_real_server_tools() -> None:
    """Allowlist short-circuits before the JSON-RPC call_tool reaches the server."""

    backend = MCPToolBackend([_spec("ref", tool_allowlist=["echo"])])
    try:
        tools = await backend.list_tools()
        listed = {t.tool_id for t in tools}
        assert listed == {"mcp.ref.echo"}, listed

        blocked = await backend.call_tool("mcp.ref.add", {"a": 1, "b": 2})
        assert blocked.status == "failure"
        assert "blocked by allowlist" in (blocked.error or "")
    finally:
        await backend.aclose()


async def test_call_tool_timeout_against_slow_real_server() -> None:
    """A spec with ``timeout_s=1`` must short-circuit a 5s server-side sleep."""

    backend = MCPToolBackend([_spec("ref", timeout_s=1)])
    try:
        result = await backend.call_tool("mcp.ref.slow", {"seconds": 5.0})
    finally:
        await backend.aclose()

    assert result.status == "timeout", result
    assert result.error is not None and "timed out" in result.error


async def test_real_server_isError_propagates_as_failure() -> None:
    """A server-side raise should arrive as ``ToolResult(status='failure')``."""

    backend = MCPToolBackend([_spec("ref")])
    try:
        result = await backend.call_tool("mcp.ref.boom", {"reason": "kaboom"})
    finally:
        await backend.aclose()

    assert result.status == "failure", result
    assert result.error is not None
    err = result.error
    assert "kaboom" in err or "fixture failure" in err or "boom" in err.lower()


async def test_aclose_terminates_real_subprocess() -> None:
    """``MCPToolBackend.aclose`` must tear down the spawned MCP subprocess.

    We can't directly observe the subprocess pid through the SDK, so we
    instead assert that a fresh backend can be opened back-to-back
    without leaking handles -- if ``aclose`` left the subprocess alive,
    pytest's ``filterwarnings = error`` (which promotes ResourceWarning
    is suppressed but unraisable would surface) would still notice
    file-handle leaks across many iterations.
    """

    for _ in range(3):
        backend = MCPToolBackend([_spec("ref")])
        try:
            tools = await backend.list_tools()
            assert any(t.tool_id == "mcp.ref.echo" for t in tools)
        finally:
            await backend.aclose()
