"""Default MCP transports backed by the official `mcp` Python SDK.

Imports of the SDK are kept inside the connector functions so the
package can be imported even when the SDK is not installed (the
`AgentOrchestrator` only needs the bridge when MCP servers are declared).
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any

from vigor_core.agent_config import MCPServerSpec

if TYPE_CHECKING:  # pragma: no cover - only for type checkers
    from mcp import ClientSession


async def open_session(spec: MCPServerSpec, stack: AsyncExitStack) -> ClientSession:
    """Open an `mcp.ClientSession` over the transport declared in ``spec``.

    The lifetimes of the underlying transport context AND the session
    are pushed onto ``stack`` so the caller can close everything by
    exiting the stack once.
    """

    from mcp import ClientSession, StdioServerParameters
    from mcp import stdio_client as _stdio_client

    read: Any
    write: Any
    if spec.transport == "stdio":
        if not spec.command:
            raise ValueError("stdio MCPServerSpec requires a command")
        params = StdioServerParameters(
            command=spec.command[0],
            args=list(spec.command[1:]),
            env=dict(spec.env) if spec.env else None,
        )
        read, write = await stack.enter_async_context(_stdio_client(params))
    elif spec.transport == "sse":
        from mcp.client.sse import sse_client

        if not spec.url:
            raise ValueError("sse MCPServerSpec requires a url")
        read, write = await stack.enter_async_context(
            sse_client(url=spec.url, headers=dict(spec.headers) or None)
        )
    elif spec.transport == "http":
        from mcp.client.streamable_http import streamablehttp_client

        if not spec.url:
            raise ValueError("http MCPServerSpec requires a url")
        ctx = await stack.enter_async_context(
            streamablehttp_client(url=spec.url, headers=dict(spec.headers) or None)
        )
        # streamablehttp_client returns (read, write, session_callback).
        read, write = ctx[0], ctx[1]
    else:
        raise ValueError(f"unsupported transport {spec.transport!r}")

    session = ClientSession(read, write)
    await stack.enter_async_context(session)
    await session.initialize()
    return session
