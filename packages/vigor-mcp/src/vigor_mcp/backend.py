"""MCP-backed `ToolBackend` for VIGOR.

`MCPToolBackend` accepts a list of `MCPServerSpec`s, opens one client
session per server (lazily, on first use), and dispatches `call_tool`
requests by parsing the tool id ``mcp.<server_id>.<name>``.

Sessions live for the lifetime of the backend (one connect per server,
one close at agent shutdown) to amortize subprocess / handshake costs.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AsyncExitStack
from typing import Any, Protocol

from vigor_core.agent_config import MCPServerSpec
from vigor_core.audit import AuditEvent, AuditOutcome, AuditSink
from vigor_core.errors import VigorError
from vigor_core.interfaces import ToolBackend, ToolResult
from vigor_core.schemas import ToolManifest
from vigor_core.util import sha256_text, stable_json

from vigor_mcp.manifest import mcp_tool_to_manifest

EventIdFactory = Callable[[], str]
SleepFn = Callable[[float], Awaitable[None]]
# Default to zero retries at the constructor seam so direct construction
# preserves the legacy single-attempt behavior; the agent wiring layer
# (AgentOrchestrator._build_tool_backend) reads ``Budgets.max_tool_retries``
# off ``AgentConfig.budgets`` and threads it into ``from_specs`` so production
# runs default to the Budgets value (2 today). Production opts in; tests stay
# byte-identical unless they pass max_tool_retries explicitly.
_DEFAULT_MAX_TOOL_RETRIES = 0
_DEFAULT_RETRY_BASE_DELAY_S = 0.1


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
        audit_sink: AuditSink | None = None,
        actor: str | None = None,
        run_id: str | None = None,
        tenant_id: str | None = None,
        event_id_factory: EventIdFactory | None = None,
        max_tool_retries: int = _DEFAULT_MAX_TOOL_RETRIES,
        retry_base_delay_s: float = _DEFAULT_RETRY_BASE_DELAY_S,
        sleep: SleepFn | None = None,
    ) -> None:
        if session_opener is None:
            from vigor_mcp.transports.sdk import open_session

            session_opener = open_session
        if max_tool_retries < 0:
            raise ValueError(f"max_tool_retries must be >= 0, got {max_tool_retries!r}")
        if retry_base_delay_s < 0:
            raise ValueError(f"retry_base_delay_s must be >= 0, got {retry_base_delay_s!r}")
        self._opener = session_opener
        self._handles: dict[str, _ServerHandle] = {
            spec.server_id: _ServerHandle(spec) for spec in specs
        }
        self._audit_sink = audit_sink
        self._actor = actor
        self._run_id = run_id
        self._tenant_id = tenant_id
        self._event_id_factory: EventIdFactory = (
            event_id_factory if event_id_factory is not None else _default_event_id
        )
        self._max_tool_retries = max_tool_retries
        self._retry_base_delay_s = retry_base_delay_s
        self._sleep: SleepFn = sleep if sleep is not None else asyncio.sleep

    @classmethod
    def from_specs(
        cls,
        specs: list[MCPServerSpec],
        *,
        max_tool_retries: int = _DEFAULT_MAX_TOOL_RETRIES,
    ) -> MCPToolBackend:
        return cls(specs, max_tool_retries=max_tool_retries)

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
            await self._emit_audit(tool_id, payload, "denied")
            return gate
        assert handle is not None

        # Retry loop bounded by max_tool_retries (Budgets.max_tool_retries).
        # max_tool_retries=N means up to N+1 total attempts (1 initial + N retries).
        # Only transient failures retry: timeouts, transient transport errors
        # (MCPBackendError / OSError / RuntimeError on the call path), and
        # VigorErrors marked retryable=True. ToolResult-shaped failures from
        # the server (isError=True) are NOT retried — those are
        # application-level outcomes, not infrastructure blips. Audit is
        # emitted exactly once at the call boundary with the final outcome
        # so the sink-owned hash chain (mx-0eae76) does not see per-attempt
        # events for what callers see as one logical call.
        max_attempts = self._max_tool_retries + 1
        result: ToolResult
        for attempt in range(max_attempts):
            result, retryable = await self._dispatch_once(handle, tool_id, tool_name, payload)
            if not retryable or attempt == max_attempts - 1:
                break
            await self._sleep(self._retry_base_delay_s * (2**attempt))
        await self._emit_audit(tool_id, payload, result.status)
        return result

    async def _dispatch_once(
        self,
        handle: _ServerHandle,
        tool_id: str,
        tool_name: str,
        payload: dict[str, Any],
    ) -> tuple[ToolResult, bool]:
        """One attempt at session.call_tool, with timeout / failure mapping.

        Returns ``(result, retryable)``. Does NOT emit audit — the caller
        emits exactly once after the retry loop settles. ``retryable`` is
        the bit the loop reads to decide whether to back off and retry;
        it is independent of ``ToolResult.status`` so a "failure" from a
        transient transport blip can retry while a "failure" from a
        non-retryable ``VigorError`` cannot.
        """

        try:
            session = await handle.ensure_open(self._opener)
            # asyncio.wait_for cancels the inner task on timeout but does
            # NOT roll back any session state the call had taken. Tear
            # down the handle so the next attempt (or next call_tool on
            # this server) opens a fresh session rather than reusing a
            # half-completed one.
            try:
                raw = await asyncio.wait_for(
                    session.call_tool(tool_name, payload),
                    timeout=handle.spec.timeout_s,
                )
            except TimeoutError:
                await handle.aclose()
                return (
                    ToolResult(
                        tool_id=tool_id,
                        status="timeout",
                        error=f"timed out after {handle.spec.timeout_s}s",
                    ),
                    True,
                )
        except VigorError as exc:
            # VigorError carries an explicit ``retryable`` flag (see
            # vigor_core.errors). ToolTimeoutError / ReviewerError set it
            # True; schema/validation/contract errors set it False.
            if exc.retryable:
                await handle.aclose()
            return (
                ToolResult(tool_id=tool_id, status="failure", error=exc.message),
                exc.retryable,
            )
        except (MCPBackendError, RuntimeError, OSError) as exc:
            # Transport-layer transients per the task description:
            # "timeouts/network blips dominate transient MCP failures".
            # The session likely held partial state; tear it down so the
            # next attempt re-handshakes.
            await handle.aclose()
            return (
                ToolResult(tool_id=tool_id, status="failure", error=str(exc)),
                True,
            )
        return self._wrap_result(tool_id, raw), False

    async def _emit_audit(
        self,
        tool_id: str,
        payload: dict[str, Any],
        outcome: str,
    ) -> None:
        """Write one ``vigor.audit_event.v1`` record at the call boundary.

        No-op when no ``audit_sink`` is configured. Sink exceptions
        propagate (fail-closed): an unrecorded tool call must not appear
        to succeed, since the audit chain is the integrity record.
        """

        if self._audit_sink is None:
            return
        if self._actor is None or self._run_id is None:
            raise ValueError("MCPToolBackend.audit_sink requires actor and run_id at construction")
        event = AuditEvent(
            event_id=self._event_id_factory(),
            tenant_id=self._tenant_id,
            run_id=self._run_id,
            actor=self._actor,
            tool_id=tool_id,
            payload_sha256=sha256_text(stable_json(payload)),
            outcome=_coerce_outcome(outcome),
        )
        await self._audit_sink.emit(event)

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


def _default_event_id() -> str:
    return f"evt_{uuid.uuid4().hex}"


def _coerce_outcome(status: str) -> AuditOutcome:
    """Map a ToolResult status (or 'denied') onto the AuditOutcome literal."""

    if status in ("success", "failure", "timeout", "denied"):
        return status  # type: ignore[return-value]
    return "failure"
