"""AgentOrchestrator: thin wrapper that wires `AgentConfig` to the runtime."""

from __future__ import annotations

from pathlib import Path

from vigor_core.agent_config import AgentConfig, MCPServerSpec
from vigor_core.archive import RunArchive
from vigor_core.interfaces import AgentBackend, ToolBackend
from vigor_core.schemas import TaskSpec
from vigor_runtime.orchestrator import Orchestrator, RunResult

from vigor_agent.factory import FactoryLoadError, call_factory, load_factory
from vigor_agent.registry import AdapterRegistry
from vigor_agent.router import Router


class AgentOrchestrator:
    """Configurable VIGOR agent.

    Owns one `AdapterRegistry`, one `Router`, an optional `ToolBackend`
    (typically MCP-backed), and a `RunArchive`. Each `run(task)` picks an
    adapter, instantiates a fresh backend, and delegates to the existing
    `vigor-runtime` `Orchestrator`.

    Backend instances are created per-task because `Orchestrator.run`
    calls ``backend.aclose()`` at the end of each run; the
    `AgentOrchestrator` itself owns the longer-lived `ToolBackend` and
    closes it once at agent shutdown.
    """

    def __init__(
        self,
        config: AgentConfig,
        *,
        tool_backend: ToolBackend | None = None,
    ) -> None:
        self._config = config
        self._registry = AdapterRegistry.from_config(config)
        self._router = Router(config.routing, self._registry)
        self._archive = RunArchive(Path(config.archive_dir))
        self._tool_backend = (
            tool_backend
            if tool_backend is not None
            else self._build_tool_backend(config.mcp_servers)
        )
        # validate the backend factory eagerly so misconfigured agents fail at
        # construction time instead of on the first run.
        load_factory(config.backend.factory)

    @staticmethod
    def _build_tool_backend(specs: list[MCPServerSpec]) -> ToolBackend | None:
        if not specs:
            return None
        try:
            from vigor_mcp.backend import MCPToolBackend
        except ImportError as exc:
            raise FactoryLoadError(
                "AgentConfig declares mcp_servers but vigor-mcp is not installed; "
                "install with the [mcp] extra"
            ) from exc
        return MCPToolBackend.from_specs(specs)

    @property
    def archive(self) -> RunArchive:
        return self._archive

    @property
    def registry(self) -> AdapterRegistry:
        return self._registry

    @property
    def tool_backend(self) -> ToolBackend | None:
        return self._tool_backend

    def resolve_adapter(self, task: TaskSpec) -> str:
        """Public hook so callers can inspect routing without running."""

        return self._router.resolve(task)

    async def run(self, task: TaskSpec) -> RunResult:
        adapter_id = self._router.resolve(task)
        adapter = self._registry.get(adapter_id)
        backend = self._build_backend()
        orchestrator = Orchestrator(
            adapter=adapter,
            backend=backend,
            archive=self._archive,
            tools=self._tool_backend,
        )
        return await orchestrator.run(task)

    def _build_backend(self) -> AgentBackend:
        instance = call_factory(self._config.backend.factory)
        if not isinstance(instance, AgentBackend):
            raise FactoryLoadError(
                f"backend factory {self._config.backend.factory.factory!r} did not "
                f"return an AgentBackend (got {type(instance).__name__})"
            )
        return instance

    async def aclose(self) -> None:
        if self._tool_backend is not None:
            close = getattr(self._tool_backend, "aclose", None)
            if close is not None:
                await close()
        self._archive.close()
