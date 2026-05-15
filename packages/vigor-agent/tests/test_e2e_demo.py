"""End-to-end test for ``examples/agent-demo``.

Boots the example ``AgentConfig`` with a fake MCP ``SessionOpener`` so
no subprocess actually runs, then exercises all three first-slice
adapters (photo, video-manim, cad) through the configurable
``AgentOrchestrator``.

Why a fake ``SessionOpener``? The example ships with one MCP server
declared via stdio (``npx ... server-filesystem``), which works for
operators who installed the MCP package but is unsafe and slow in CI.
:func:`vigor_mcp.backend.MCPToolBackend` exposes ``session_opener`` as
its documented injection point precisely so tests can run the agent's
production wiring without touching the network.
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from vigor_agent.agent import AgentOrchestrator
from vigor_agent.config_loader import load_agent_config
from vigor_core.agent_config import MCPServerSpec
from vigor_core.schemas import TaskSpec
from vigor_mcp.backend import MCPToolBackend

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_DIR = REPO_ROOT / "examples" / "agent-demo"


@dataclass
class _FakeTool:
    name: str
    description: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description}


@dataclass
class _FakeListResult:
    tools: list[_FakeTool] = field(default_factory=list)


@dataclass
class _FakeContentBlock:
    text: str

    def model_dump(self) -> dict[str, Any]:
        return {"type": "text", "text": self.text}


@dataclass
class _FakeCallResult:
    content: list[_FakeContentBlock] = field(default_factory=list)
    isError: bool = False
    structuredContent: dict[str, Any] | None = None


class _FakeFilesystemSession:
    """Fake stand-in for an MCP filesystem server.

    Honors the ``tool_allowlist`` declared in ``agent.yaml`` so the
    test exercises the same allowlist path production runs would.
    """

    async def list_tools(self) -> _FakeListResult:
        return _FakeListResult(
            tools=[
                _FakeTool(name="read_file", description="read a file"),
                _FakeTool(name="list_directory", description="list a directory"),
            ]
        )

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> _FakeCallResult:
        return _FakeCallResult(
            content=[_FakeContentBlock(text=f"fake:{name}:{arguments}")],
            structuredContent={"name": name, "arguments": arguments},
        )


async def _fake_opener(spec: MCPServerSpec, stack: AsyncExitStack) -> _FakeFilesystemSession:
    assert spec.server_id == "filesystem"
    return _FakeFilesystemSession()


def _agent_with_fake_mcp() -> AgentOrchestrator:
    """Construct an `AgentOrchestrator` with the fake MCP session opener.

    The example's ``agent.yaml`` declares one MCP server. Building a
    real subprocess would require an external dependency, so we
    construct the ``MCPToolBackend`` ourselves with the same specs and
    inject our fake opener, then hand it to ``AgentOrchestrator`` via
    its ``tool_backend`` injection point.
    """

    cfg = load_agent_config(DEMO_DIR / "agent.yaml")
    fake_tools = MCPToolBackend(cfg.mcp_servers, session_opener=_fake_opener)
    return AgentOrchestrator(cfg, tool_backend=fake_tools)


def _load_task(name: str) -> TaskSpec:
    payload = json.loads((DEMO_DIR / "tasks" / f"{name}.json").read_text(encoding="utf-8"))
    return TaskSpec.model_validate(payload)


@pytest.mark.asyncio
async def test_demo_routes_each_modality_to_its_adapter() -> None:
    agent = _agent_with_fake_mcp()
    try:
        assert agent.resolve_adapter(_load_task("photo")) == "adapter_photo"
        assert agent.resolve_adapter(_load_task("video")) == "adapter_video_manim"
        assert agent.resolve_adapter(_load_task("cad")) == "adapter_cad"
    finally:
        await agent.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "task_name, expected_export_type",
    [
        ("photo", "final_artifact"),
        ("video", "final_artifact"),
        ("cad", "openscad_source"),
    ],
)
async def test_demo_runs_modality_end_to_end(
    tmp_path: Path, task_name: str, expected_export_type: str
) -> None:
    """Each task type should run cleanly with the example AgentConfig."""

    cfg = load_agent_config(DEMO_DIR / "agent.yaml")
    # Redirect archive writes into pytest's tmp_path so test runs are
    # isolated and the repo's ``examples/agent-demo/runs/`` stays clean.
    cfg = cfg.model_copy(update={"archive_dir": str(tmp_path / "runs")})
    fake_tools = MCPToolBackend(cfg.mcp_servers, session_opener=_fake_opener)
    agent = AgentOrchestrator(cfg, tool_backend=fake_tools)
    try:
        task = _load_task(task_name)
        result = await agent.run(task)
        assert result.accepted, f"{task_name} run failed: {result.stop_reason}"
        assert result.stop_reason == "accepted"
        assert result.export_bundle is not None
        export_types = {entry.type for entry in result.export_bundle.exports}
        assert expected_export_type in export_types
    finally:
        await agent.aclose()


@pytest.mark.asyncio
async def test_demo_mcp_backend_uses_fake_session_opener() -> None:
    """Verify the test wiring: MCP calls hit the fake session, not a subprocess."""

    cfg = load_agent_config(DEMO_DIR / "agent.yaml")
    fake_tools = MCPToolBackend(cfg.mcp_servers, session_opener=_fake_opener)
    try:
        manifests = await fake_tools.list_tools()
        # Allowlist in agent.yaml restricts to read_file + list_directory.
        assert {m.tool_id for m in manifests} == {
            "mcp.filesystem.read_file",
            "mcp.filesystem.list_directory",
        }
        result = await fake_tools.call_tool("mcp.filesystem.read_file", {"path": "/tmp/x"})
        assert result.status == "success"
        assert result.output["structured"]["name"] == "read_file"
    finally:
        await fake_tools.aclose()
