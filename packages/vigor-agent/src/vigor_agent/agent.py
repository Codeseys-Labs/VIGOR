"""AgentOrchestrator: thin wrapper that wires `AgentConfig` to the runtime."""

from __future__ import annotations

from pathlib import Path

from vigor_core.agent_config import AdapterSpec, AgentConfig, MCPServerSpec
from vigor_core.archive import RunArchive
from vigor_core.interfaces import AgentBackend, ToolBackend
from vigor_core.observability import RuntimeObserver
from vigor_core.schemas import TaskSpec
from vigor_runtime.orchestrator import Orchestrator, RunResult

from vigor_agent.factory import FactoryLoadError, call_factory, load_factory
from vigor_agent.plugin_discovery import (
    adapter_spec_from_plugin,
    load_plugin_directory,
)
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

    Plugin discovery (``plugin_dirs``) loads each Open-Plugin directory
    and registers its Python ``FactoryRef`` as an additional `AdapterSpec`.
    Each plugin's ``allowed_prefixes`` (declared inside ``.plugin/vigor.json``)
    is gated against ``config.allowed_plugin_factory_prefixes`` via
    :func:`adapter_spec_from_plugin`, preventing a plugin from
    self-authorising into arbitrary namespaces. Construction fails with
    ``PluginDiscoveryError`` if any plugin declares an out-of-allowlist
    prefix — matching the eager-validation posture of ``load_factory``
    above.
    """

    def __init__(
        self,
        config: AgentConfig,
        *,
        tool_backend: ToolBackend | None = None,
        plugin_dirs: list[tuple[str | Path, str]] | None = None,
        observer: RuntimeObserver | None = None,
    ) -> None:
        self._config = (
            config
            if not plugin_dirs
            else config.model_copy(
                update={
                    "adapters": list(config.adapters)
                    + self._load_plugin_adapters(plugin_dirs, config),
                }
            )
        )
        self._registry = AdapterRegistry.from_config(self._config)
        self._router = Router(self._config.routing, self._registry)
        self._archive = RunArchive(Path(self._config.archive_dir))
        # The MCP-backed tool backend is constructed once per agent (long-
        # lived sessions amortize subprocess + handshake cost), so per-task
        # ``Budgets.max_tool_retries`` cannot be threaded in lazily — we
        # resolve it now from the agent-level ``AgentConfig.budgets`` and
        # rely on operators tuning the agent config for retry-sensitive
        # workloads. Per-task overrides would require a runtime setter and
        # are out of scope for VIGOR-2585.
        self._tool_backend = (
            tool_backend
            if tool_backend is not None
            else self._build_tool_backend(
                self._config.mcp_servers,
                max_tool_retries=self._config.budgets.max_tool_retries,
            )
        )
        # ADR-0037: optional observer threaded into every per-run Orchestrator.
        self._observer = observer
        # validate the backend factory eagerly so misconfigured agents fail at
        # construction time instead of on the first run.
        load_factory(self._config.backend.factory)

    @staticmethod
    def _load_plugin_adapters(
        plugin_dirs: list[tuple[str | Path, str]],
        config: AgentConfig,
    ) -> list[AdapterSpec]:
        # host_allowed_prefixes=None bypasses the gate (legacy mode); we always
        # forward the host's list (possibly []) so the gate fires. An empty
        # list raises with a clear "host has no allowed_plugin_factory_prefixes"
        # error from assert_factory_ref_allowed — that's the intended posture
        # when a host opts in to plugins without declaring an allowlist.
        host_prefixes: list[str] = list(config.allowed_plugin_factory_prefixes)
        specs: list[AdapterSpec] = []
        for plugin_dir, adapter_id in plugin_dirs:
            plugin = load_plugin_directory(plugin_dir)
            specs.append(
                adapter_spec_from_plugin(
                    plugin,
                    adapter_id=adapter_id,
                    host_allowed_prefixes=host_prefixes,
                )
            )
        return specs

    @staticmethod
    def _build_tool_backend(
        specs: list[MCPServerSpec],
        *,
        max_tool_retries: int,
    ) -> ToolBackend | None:
        if not specs:
            return None
        try:
            from vigor_mcp.backend import MCPToolBackend
        except ImportError as exc:
            raise FactoryLoadError(
                "AgentConfig declares mcp_servers but vigor-mcp is not installed; "
                "install with the [mcp] extra"
            ) from exc
        return MCPToolBackend.from_specs(specs, max_tool_retries=max_tool_retries)

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
        orchestrator = self._build_orchestrator(task)
        return await orchestrator.run(task)

    async def resume(self, run_id: str) -> RunResult:
        """Resume a partial run from its iteration checkpoint.

        Per ADR-0036, reads the archived ``TaskSpec`` to re-resolve the
        adapter, builds a fresh backend (the prior backend's session is
        unrecoverable across crashes), and delegates to
        :meth:`Orchestrator.resume`. Raises
        :class:`vigor_core.errors.NoCheckpointError` if no checkpoint
        exists for ``run_id``.
        """

        task = self._archive.read_task(run_id)
        orchestrator = self._build_orchestrator(task)
        return await orchestrator.resume(run_id)

    def _build_orchestrator(self, task: TaskSpec) -> Orchestrator:
        adapter_id = self._router.resolve(task)
        adapter = self._registry.get(adapter_id)
        backend = self._build_backend()
        return Orchestrator(
            adapter=adapter,
            backend=backend,
            archive=self._archive,
            tools=self._tool_backend,
            observer=self._observer,
        )

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
