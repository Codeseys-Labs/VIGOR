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

    __slots__ = ("_allowlist", "_lock", "_stack", "_tools_cache", "session", "spec")

    def __init__(self, spec: MCPServerSpec) -> None:
        self.spec = spec
        self.session: _MCPSession | None = None
        self._lock = asyncio.Lock()
        self._stack = AsyncExitStack()
        self._tools_cache: list[ToolManifest] | None = None
        self._allowlist: frozenset[str] | None = (
            frozenset(spec.tool_allowlist) if spec.tool_allowlist is not None else None
        )

    @property
    def allowlist(self) -> frozenset[str] | None:
        """Frozen membership-test view of ``spec.tool_allowlist`` (or None)."""

        return self._allowlist

    async def ensure_open(self, opener: SessionOpener) -> _MCPSession:
        async with self._lock:
            if self.session is None:
                try:
                    self.session = await opener(self.spec, self._stack)
                except BaseException:
                    # Roll back any partially-entered transport contexts so a
                    # failed handshake does not leak subprocesses or sockets.
                    await self._stack.aclose()
                    self._stack = AsyncExitStack()
                    self.session = None
                    raise
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
            if self._allowlist is not None and payload.get("name") not in self._allowlist:
                continue
            manifests.append(mcp_tool_to_manifest(self.spec.server_id, payload))
        self._tools_cache = manifests
        return manifests

    async def get_manifest(self, opener: SessionOpener, tool_id: str) -> ToolManifest | None:
        """Return the cached `ToolManifest` for ``tool_id`` on this server.

        Triggers a one-shot ``list_tools`` round-trip on first lookup so
        the call_tool path can read ``mutability`` without a per-call
        protocol roundtrip. Returns None if the tool is not in the
        listed surface (which, with an allowlist, also means denied).
        """

        manifests = await self.list_tools(opener)
        for manifest in manifests:
            if manifest.tool_id == tool_id:
                return manifest
        return None

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

    async def call_tool(
        self,
        tool_id: str,
        payload: dict[str, Any],
        *,
        capabilities: frozenset[str] | None = None,
    ) -> ToolResult:
        server_id, tool_name = self._parse_tool_id(tool_id)
        handle = self._handles.get(server_id)
        gate = await self._gate_call(handle, tool_id, server_id, tool_name, capabilities)
        if gate is not None:
            return gate
        assert handle is not None
        try:
            session = await handle.ensure_open(self._opener)
            # asyncio.wait_for cancels the inner task on timeout but does
            # NOT roll back any session state the call had taken. Tear
            # down the handle so the next call_tool on this server opens
            # a fresh session rather than reusing a half-completed one.
            try:
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, payload),
                    timeout=handle.spec.timeout_s,
                )
            except TimeoutError:
                await handle.aclose()
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

    async def _gate_call(
        self,
        handle: _ServerHandle | None,
        tool_id: str,
        server_id: str,
        tool_name: str,
        capabilities: frozenset[str] | None,
    ) -> ToolResult | None:
        """Pre-dispatch checks: server, allowlist, mutator capability.

        Returns a ``ToolResult`` if the call should be denied, or
        ``None`` if it can proceed. Mutator gating per ADR-0016 §3.2.
        """

        if handle is None:
            return ToolResult(
                tool_id=tool_id,
                status="failure",
                error=f"unknown MCP server_id {server_id!r}",
            )
        if handle.allowlist is not None and tool_name not in handle.allowlist:
            return ToolResult(
                tool_id=tool_id,
                status="failure",
                error=f"tool {tool_name!r} blocked by allowlist on {server_id!r}",
            )
        try:
            manifest = await handle.get_manifest(self._opener, tool_id)
        except (MCPBackendError, RuntimeError, OSError) as exc:
            return ToolResult(tool_id=tool_id, status="failure", error=str(exc))
        if manifest is not None and manifest.mutability == "mutator":
            granted = capabilities or frozenset()
            if tool_id not in granted:
                return ToolResult(
                    tool_id=tool_id,
                    status="failure",
                    error=(
                        f"mutator tool {tool_id!r} requires capability grant; "
                        f"caller has {sorted(granted)!r}"
                    ),
                )
        return None

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
