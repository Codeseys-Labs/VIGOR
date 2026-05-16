"""End-to-end AgentOrchestrator tests using the toy adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from vigor_agent.agent import AgentOrchestrator
from vigor_agent.config_loader import load_agent_config
from vigor_agent.factory import FactoryLoadError
from vigor_agent.plugin_discovery import PluginDiscoveryError
from vigor_core.agent_config import (
    AdapterSpec,
    AgentConfig,
    BackendSpec,
    FactoryRef,
    RoutingPolicy,
)
from vigor_core.interfaces import ToolBackend, ToolResult
from vigor_core.schemas import Budgets, TaskSpec, ToolManifest


def _toy_config(archive_dir: Path, **overrides: object) -> AgentConfig:
    payload: dict[str, object] = {
        "agent_id": "agent_test",
        "backend": BackendSpec(
            backend_id="backend_echo",
            factory=FactoryRef(
                factory="vigor_runtime.backends:make_toy_echo_backend",
                allowed_prefixes=["vigor_runtime"],
            ),
        ),
        "adapters": [
            AdapterSpec(
                adapter_id="adapter_toy",
                factory=FactoryRef(
                    factory="vigor_runtime.toy_adapter:ToyTextAdapter",
                    allowed_prefixes=["vigor_runtime"],
                ),
                modalities=["toy_text"],
            )
        ],
        "routing": RoutingPolicy(strategy="single"),
        "archive_dir": str(archive_dir),
    }
    payload.update(overrides)
    return AgentConfig.model_validate(payload, from_attributes=True)


@pytest.mark.asyncio
async def test_agent_runs_toy_adapter_end_to_end(tmp_path: Path) -> None:
    cfg = _toy_config(tmp_path / "runs")
    agent = AgentOrchestrator(cfg)
    try:
        task = TaskSpec(
            task_id="t_agent_demo",
            goal="hello agent",
            modalities=["toy_text"],
            budgets=Budgets(max_iterations=1, max_candidates=1),
        )
        result = await agent.run(task)
        assert result.accepted is True
        assert result.stop_reason == "accepted"

        run_dir = agent.archive.run_dir("t_agent_demo")
        assert (run_dir / "task.json").exists()
        assert (run_dir / "final" / "export_bundle.json").exists()
    finally:
        await agent.aclose()


@pytest.mark.asyncio
async def test_agent_routes_by_modality_across_two_adapters(tmp_path: Path) -> None:
    cfg = _toy_config(
        tmp_path / "runs",
        adapters=[
            AdapterSpec(
                adapter_id="adapter_alpha",
                factory=FactoryRef(
                    factory="vigor_runtime.toy_adapter:ToyTextAdapter",
                    allowed_prefixes=["vigor_runtime"],
                ),
                modalities=["alpha_text"],
            ),
            AdapterSpec(
                adapter_id="adapter_beta",
                factory=FactoryRef(
                    factory="vigor_runtime.toy_adapter:ToyTextAdapter",
                    allowed_prefixes=["vigor_runtime"],
                ),
                modalities=["beta_text"],
            ),
        ],
        routing=RoutingPolicy(strategy="modality_match"),
    )
    agent = AgentOrchestrator(cfg)
    try:
        alpha_task = TaskSpec(
            task_id="t_alpha",
            goal="a",
            modalities=["alpha_text"],
            budgets=Budgets(max_iterations=1, max_candidates=1),
        )
        beta_task = TaskSpec(
            task_id="t_beta",
            goal="b",
            modalities=["beta_text"],
            budgets=Budgets(max_iterations=1, max_candidates=1),
        )
        assert agent.resolve_adapter(alpha_task) == "adapter_alpha"
        assert agent.resolve_adapter(beta_task) == "adapter_beta"

        a_result = await agent.run(alpha_task)
        b_result = await agent.run(beta_task)
        assert a_result.accepted and b_result.accepted
    finally:
        await agent.aclose()


@pytest.mark.asyncio
async def test_agent_rejects_non_adapter_factory(tmp_path: Path) -> None:
    cfg = _toy_config(tmp_path / "runs")
    cfg.adapters[0].factory = FactoryRef(
        factory="vigor_runtime.backends:EchoAgentBackend",
        allowed_prefixes=["vigor_runtime"],
    )
    with pytest.raises(FactoryLoadError, match="did not return a"):
        AgentOrchestrator(cfg)


def test_load_agent_config_yaml(tmp_path: Path) -> None:
    cfg_path = tmp_path / "agent.yaml"
    cfg_path.write_text(
        """
schemaVersion: vigor.agent_config.v1
agentId: agent_yaml
backend:
  backendId: backend_echo
  factory:
    factory: vigor_runtime.backends:make_toy_echo_backend
    allowedPrefixes: [vigor_runtime]
adapters:
  - adapterId: adapter_toy
    factory:
      factory: vigor_runtime.toy_adapter:ToyTextAdapter
      allowedPrefixes: [vigor_runtime]
    modalities: [toy_text]
routing:
  strategy: single
archiveDir: runs
""",
        encoding="utf-8",
    )
    cfg = load_agent_config(cfg_path)
    assert cfg.agent_id == "agent_yaml"
    assert cfg.adapters[0].adapter_id == "adapter_toy"


class _SpyTools(ToolBackend):
    def __init__(self) -> None:
        self.closed = 0

    async def call_tool(
        self,
        tool_id: str,
        payload: dict[str, Any],
        *,
        capabilities: frozenset[str] | None = None,
    ) -> ToolResult:
        return ToolResult(tool_id=tool_id, status="success")

    async def list_tools(self) -> list[ToolManifest]:
        return []

    async def aclose(self) -> None:
        self.closed += 1


@pytest.mark.asyncio
async def test_agent_aclose_calls_tool_backend_aclose(tmp_path: Path) -> None:
    """AgentOrchestrator.aclose() must propagate to the injected ToolBackend."""

    spy = _SpyTools()
    cfg = _toy_config(tmp_path / "runs")
    agent = AgentOrchestrator(cfg, tool_backend=spy)
    await agent.aclose()
    assert spy.closed == 1


def test_load_agent_config_json(tmp_path: Path) -> None:
    cfg_path = tmp_path / "agent.json"
    payload = {
        "schemaVersion": "vigor.agent_config.v1",
        "agentId": "agent_json",
        "backend": {
            "backendId": "backend_echo",
            "factory": {
                "factory": "vigor_runtime.backends:EchoAgentBackend",
                "allowedPrefixes": ["vigor_runtime"],
            },
        },
        "adapters": [
            {
                "adapterId": "adapter_toy",
                "factory": {
                    "factory": "vigor_runtime.toy_adapter:ToyTextAdapter",
                    "allowedPrefixes": ["vigor_runtime"],
                },
                "modalities": ["toy_text"],
            }
        ],
        "routing": {"strategy": "single"},
        "archiveDir": "runs",
    }
    cfg_path.write_text(json.dumps(payload), encoding="utf-8")
    cfg = load_agent_config(cfg_path)
    assert cfg.agent_id == "agent_json"


def _write_plugin_dir(
    root: Path,
    *,
    factory: dict[str, object],
    name: str = "vigor-adapter-test",
) -> Path:
    plugin_dir = root / ".plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(json.dumps({"name": name}), encoding="utf-8")
    (plugin_dir / "vigor.json").write_text(json.dumps(factory), encoding="utf-8")
    return root


def test_agent_orchestrator_rejects_plugin_outside_host_allowlist(tmp_path: Path) -> None:
    """A plugin self-declaring `evil` allowed_prefixes must be rejected at construction."""

    plugin_root = _write_plugin_dir(
        tmp_path / "plugin",
        factory={
            "factory": "evil.module:EvilAdapter",
            "allowedPrefixes": ["evil"],
        },
    )
    cfg = _toy_config(
        tmp_path / "runs",
        allowed_plugin_factory_prefixes=["vigor_runtime"],
    )
    with pytest.raises(PluginDiscoveryError, match="plugin-supplied prefix 'evil'"):
        AgentOrchestrator(cfg, plugin_dirs=[(plugin_root, "adapter_evil")])


def test_agent_orchestrator_rejects_plugin_when_host_allowlist_empty(tmp_path: Path) -> None:
    """allowed_plugin_factory_prefixes default ([]) means 'no plugins'."""

    plugin_root = _write_plugin_dir(
        tmp_path / "plugin",
        factory={
            "factory": "vigor_runtime.toy_adapter:ToyTextAdapter",
            "allowedPrefixes": ["vigor_runtime"],
        },
    )
    cfg = _toy_config(tmp_path / "runs")
    assert cfg.allowed_plugin_factory_prefixes == []
    with pytest.raises(PluginDiscoveryError, match="host has no allowed_plugin_factory_prefixes"):
        AgentOrchestrator(cfg, plugin_dirs=[(plugin_root, "adapter_x")])


@pytest.mark.asyncio
async def test_agent_orchestrator_admits_plugin_within_host_allowlist(tmp_path: Path) -> None:
    """A plugin whose allowed_prefixes is contained in the host's list is registered."""

    plugin_root = _write_plugin_dir(
        tmp_path / "plugin",
        factory={
            "factory": "vigor_runtime.toy_adapter:ToyTextAdapter",
            "allowedPrefixes": ["vigor_runtime"],
        },
    )
    cfg = _toy_config(
        tmp_path / "runs",
        allowed_plugin_factory_prefixes=["vigor_runtime"],
        routing=RoutingPolicy(strategy="modality_match"),
    )
    agent = AgentOrchestrator(
        cfg,
        plugin_dirs=[(plugin_root, "adapter_plugin")],
    )
    try:
        adapter_ids = agent.registry.adapter_ids()
        assert "adapter_plugin" in adapter_ids
        assert "adapter_toy" in adapter_ids
    finally:
        await agent.aclose()
