"""MCP-backed `ToolBackend` for VIGOR.

`MCPToolBackend` accepts a list of `MCPServerSpec`s, opens one client
session per server (lazily, on first use), and dispatches `call_tool`
requests by parsing the tool id ``mcp.<server_id>.<name>``.

Sessions live for the lifetime of the backend (one connect per server,
one close at agent shutdown) to amortize subprocess / handshake costs.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from typing import Any, Protocol

from vigor_core.agent_config import MCPServerSpec
from vigor_core.interfaces import ToolBackend, ToolResult
from vigor_core.schemas import ToolManifest

from vigor_mcp.manifest import mcp_tool_to_manifest


class MCPBackendError(RuntimeError):
    """Raised when an MCP server cannot be reached or returns an unusable response."""


class _MCPSession(Protocol):
    async def list_tools(self) -> Any: ...
    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any: ...


SessionOpener = Callable[[MCPServerSpec, AsyncExitStack], Awaitable[_MCPSession]]


class _ServerHandle:
    """Per-server connection state."""

    __slots__ = ("_lock", "_stack", "_tools_cache", "session", "spec")

    def __init__(self, spec: MCPServerSpec) -> None:
        self.spec = spec
        self.session: _MCPSession | None = None
        self._lock = asyncio.Lock()
        self._stack = AsyncExitStack()
        self._tools_cache: list[ToolManifest] | None = None

    async def ensure_open(self, opener: SessionOpener) -> _MCPSession:
        async with self._lock:
            if self.session is None:
                self.session = await opener(self.spec, self._stack)
            return self.session

    async def list_tools(self, opener: SessionOpener) -> list[ToolManifest]:
        if self._tools_cache is not None:
            return self._tools_cache
        session = await self.ensure_open(opener)
        result = await session.list_tools()
        manifests: list[ToolManifest] = []
        tools_iter = getattr(result, "tools", None) or []
        for tool in tools_iter:
            payload = tool.model_dump() if hasattr(tool, "model_dump") else dict(tool)
            if (
                self.spec.tool_allowlist is not None
                and payload.get("name") not in self.spec.tool_allowlist
            ):
                continue
            manifests.append(mcp_tool_to_manifest(self.spec.server_id, payload))
        self._tools_cache = manifests
        return manifests

    async def aclose(self) -> None:
        async with self._lock:
            await self._stack.aclose()
            self.session = None
            self._tools_cache = None


class MCPToolBackend(ToolBackend):
    """Aggregate `ToolBackend` that fans out to one session per MCP server."""

    def __init__(
        self,
        specs: list[MCPServerSpec],
        *,
        session_opener: SessionOpener | None = None,
    ) -> None:
        if session_opener is None:
            from vigor_mcp.transports.sdk import open_session

            session_opener = open_session
        self._opener = session_opener
        self._handles: dict[str, _ServerHandle] = {
            spec.server_id: _ServerHandle(spec) for spec in specs
        }

    @classmethod
    def from_specs(cls, specs: list[MCPServerSpec]) -> MCPToolBackend:
        return cls(specs)

    async def list_tools(self) -> list[ToolManifest]:
        results: list[ToolManifest] = []
        for handle in self._handles.values():
            results.extend(await handle.list_tools(self._opener))
        return results

    async def call_tool(self, tool_id: str, payload: dict[str, Any]) -> ToolResult:
        server_id, tool_name = self._parse_tool_id(tool_id)
        handle = self._handles.get(server_id)
        if handle is None:
            return ToolResult(
                tool_id=tool_id,
                status="failure",
                error=f"unknown MCP server_id {server_id!r}",
            )
        if handle.spec.tool_allowlist is not None and tool_name not in handle.spec.tool_allowlist:
            return ToolResult(
                tool_id=tool_id,
                status="failure",
                error=f"tool {tool_name!r} blocked by allowlist on {server_id!r}",
            )
        try:
            session = await handle.ensure_open(self._opener)
            result = await asyncio.wait_for(
                session.call_tool(tool_name, payload),
                timeout=handle.spec.timeout_s,
            )
        except TimeoutError:
            return ToolResult(
                tool_id=tool_id,
                status="timeout",
                error=f"timed out after {handle.spec.timeout_s}s",
            )
        except (MCPBackendError, RuntimeError, OSError) as exc:
            return ToolResult(tool_id=tool_id, status="failure", error=str(exc))
        return self._wrap_result(tool_id, result)

    async def aclose(self) -> None:
        for handle in self._handles.values():
            await handle.aclose()

    @staticmethod
    def _parse_tool_id(tool_id: str) -> tuple[str, str]:
        if not tool_id.startswith("mcp."):
            raise MCPBackendError(f"MCP tool ids must start with 'mcp.', got {tool_id!r}")
        rest = tool_id[len("mcp.") :]
        server_id, sep, name = rest.partition(".")
        if not sep or not name:
            raise MCPBackendError(f"MCP tool id must be 'mcp.<server>.<tool>', got {tool_id!r}")
        return server_id, name

    @staticmethod
    def _wrap_result(tool_id: str, result: Any) -> ToolResult:
        is_error = bool(getattr(result, "isError", False))
        content = getattr(result, "content", None)
        output: dict[str, Any] = {}
        if content is not None:
            output["content"] = [
                block.model_dump() if hasattr(block, "model_dump") else block for block in content
            ]
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            output["structured"] = structured
        if is_error:
            return ToolResult(
                tool_id=tool_id,
                status="failure",
                error=_extract_error(content) or "MCP server returned isError",
                output=output,
            )
        return ToolResult(tool_id=tool_id, status="success", output=output)


def _extract_error(content: Any) -> str | None:
    if not content:
        return None
    for block in content:
        text = getattr(block, "text", None)
        if isinstance(text, str):
            return text
    return None
