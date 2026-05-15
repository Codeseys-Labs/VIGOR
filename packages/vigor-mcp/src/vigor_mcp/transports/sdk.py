"""Default MCP transports backed by the official `mcp` Python SDK.

Imports of the SDK are kept inside the connector functions so the
package can be imported even when the SDK is not installed (the
`AgentOrchestrator` only needs the bridge when MCP servers are declared).

Subprocess environment policy (ADR-0029)
----------------------------------------
The stdio transport spawns the MCP server as a child process. Since the
2026-05 hardening pass, the child is started with an **explicit, default-deny**
environment: only the keys an operator names in ``MCPServerSpec.env`` are
forwarded, plus a small documented pass-through (currently ``PATH`` only)
which is required for CLI shims like ``uvx``/``npx``/``python -m foo`` to
resolve their own binaries.

Previously the default was inherit-all-parent-env (any vendor key in the
parent process — ``ANTHROPIC_API_KEY``, ``GEMINI_API_KEY``, ``AWS_*`` —
silently reached the spawned server). For multi-tenant deployments this
was a cross-tenant credential leak. Operators that need their server to
see a vendor key must now declare it explicitly in ``MCPServerSpec.env``.
This is a breaking default-change, not a schema change; the failure mode
is a clear server-side missing-key error rather than a silent leak.
"""

from __future__ import annotations

import os
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any

from vigor_core.agent_config import MCPServerSpec

if TYPE_CHECKING:  # pragma: no cover - only for type checkers
    from mcp import ClientSession

# Minimum tuple length for streamablehttp_client returning at least (read, write).
_MIN_STREAMABLEHTTP_TUPLE = 2

# Parent-environment keys forwarded to the spawned stdio MCP subprocess by
# default. Per ADR-0029 this list is intentionally minimal: ``PATH`` is the
# only inherited variable, since virtually every CLI-shim MCP server (uvx,
# npx, python -m ...) resolves its own binary via PATH. Anything else the
# spawned server needs (vendor API keys, locale, PYTHONUNBUFFERED, ...) must
# be declared explicitly in ``MCPServerSpec.env``. Adding a key here widens
# the default contract for every operator and so requires an ADR amendment.
_DEFAULT_PASS_THROUGH: tuple[str, ...] = ("PATH",)


def _build_stdio_env(spec_env: dict[str, str] | None) -> dict[str, str]:
    """Build the subprocess environment for a stdio MCP server (ADR-0029).

    The returned dict is the explicit pass-through:

    * Every key from ``spec_env`` is copied verbatim (operator-declared).
    * Each key in :data:`_DEFAULT_PASS_THROUGH` is set from the parent
      process via :func:`os.environ.get` — but only if the operator did
      not already pin it, so ``spec.env`` always wins.

    The result is *always* a concrete dict; callers must not pass it to a
    sentinel-aware API like :class:`mcp.StdioServerParameters` as ``None``,
    which would re-enable the SDK's inherit-all default. Returning an empty
    dict (no spec env, no pass-through key set in parent) is the safe state.
    """

    env: dict[str, str] = dict(spec_env) if spec_env else {}
    for key in _DEFAULT_PASS_THROUGH:
        parent_value = os.environ.get(key)
        if parent_value is not None:
            env.setdefault(key, parent_value)
    return env


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
        if spec.headers:
            raise ValueError("stdio MCPServerSpec must not declare headers")
        params = StdioServerParameters(
            command=spec.command[0],
            args=list(spec.command[1:]),
            env=_build_stdio_env(spec.env),
        )
        read, write = await stack.enter_async_context(_stdio_client(params))
    elif spec.transport == "sse":
        from mcp.client.sse import sse_client

        if not spec.url:
            raise ValueError("sse MCPServerSpec requires a url")
        if spec.env:
            raise ValueError("sse MCPServerSpec must not declare env")
        read, write = await stack.enter_async_context(
            sse_client(url=spec.url, headers=dict(spec.headers) if spec.headers else None)
        )
    elif spec.transport == "http":
        from mcp.client.streamable_http import streamablehttp_client

        if not spec.url:
            raise ValueError("http MCPServerSpec requires a url")
        if spec.env:
            raise ValueError("http MCPServerSpec must not declare env")
        ctx = await stack.enter_async_context(
            streamablehttp_client(
                url=spec.url, headers=dict(spec.headers) if spec.headers else None
            )
        )
        # streamablehttp_client returns (read, write, session_callback).
        # Tolerate both the 2-tuple legacy shape and the 3-tuple current shape.
        if not isinstance(ctx, tuple) or len(ctx) < _MIN_STREAMABLEHTTP_TUPLE:
            raise ValueError(
                f"streamablehttp_client returned unexpected shape {type(ctx).__name__}"
            )
        read, write = ctx[0], ctx[1]
    else:
        raise ValueError(f"unsupported transport {spec.transport!r}")

    session = ClientSession(read, write)
    await stack.enter_async_context(session)
    await session.initialize()
    return session
