"""Smoke tests for the Claude Agent SDK backend skeleton."""

from __future__ import annotations

import pytest
from vigor_backend_claude_agent_sdk import (
    ClaudeAgentBackend,
    ClaudeBackendConfig,
)
from vigor_core.interfaces import GenerationRequest, RepresentationPlan
from vigor_core.schemas import TaskSpec


def test_backend_instantiates_without_sdk() -> None:
    backend = ClaudeAgentBackend(ClaudeBackendConfig())
    assert isinstance(backend, ClaudeAgentBackend)


@pytest.mark.asyncio
async def test_generate_raises_without_sdk() -> None:
    backend = ClaudeAgentBackend(ClaudeBackendConfig())
    task = TaskSpec(task_id="t", goal="g", modalities=["toy"])
    plan = RepresentationPlan(ir_type="toy.v1")
    with pytest.raises(ImportError, match="claude-agent-sdk"):
        await backend.generate(GenerationRequest(task=task, plan=plan))
