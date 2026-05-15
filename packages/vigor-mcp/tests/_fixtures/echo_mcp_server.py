"""Lightweight reference MCP server used by ``test_integration_real``.

Exposes three tools so the integration test can exercise the full
``MCPToolBackend`` surface against a real subprocess + stdio transport:

- ``echo`` -- returns its argument as text (happy path).
- ``add``  -- structured arithmetic, used to assert the namespacing
  ``mcp.<server_id>.<tool>`` survives a round-trip.
- ``slow`` -- sleeps longer than the backend's ``timeout_s``, used to
  drive ``MCPToolBackend.call_tool`` into the timeout/teardown branch.
- ``boom`` -- raises so the server returns ``isError=true``, used to
  assert ``ToolResult.status == "failure"`` propagation.

Run as ``python -m vigor_mcp_test_fixtures.echo_mcp_server`` (when the
test installs the fixture path on ``PYTHONPATH``) or directly via
``python <path-to-this-file>``. The server uses stdio framing and
terminates when the parent closes stdin.
"""

from __future__ import annotations

import asyncio

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("vigor-mcp-echo-fixture")


@mcp.tool()
def echo(message: str) -> str:
    """Return ``message`` verbatim."""

    return message


@mcp.tool()
def add(a: int, b: int) -> int:
    """Return ``a + b`` so structured output round-trips."""

    return a + b


@mcp.tool()
async def slow(seconds: float = 2.0) -> str:
    """Sleep for ``seconds`` then return -- used to test backend timeout."""

    await asyncio.sleep(seconds)
    return f"slept {seconds}s"


@mcp.tool()
def boom(reason: str = "fixture failure") -> str:
    """Raise so the server reports ``isError=true``."""

    raise RuntimeError(reason)


if __name__ == "__main__":
    mcp.run()
