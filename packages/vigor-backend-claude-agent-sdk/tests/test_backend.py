"""Smoke tests for the Claude Agent SDK backend skeleton."""

from __future__ import annotations

from types import SimpleNamespace

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


@pytest.mark.asyncio
async def test_usage_default_is_zero_and_unpriced() -> None:
    backend = ClaudeAgentBackend(ClaudeBackendConfig())
    usage = await backend.usage()
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.usd is None


@pytest.mark.asyncio
async def test_accumulate_usage_sums_tokens_and_marks_priced() -> None:
    backend = ClaudeAgentBackend(ClaudeBackendConfig())
    backend._accumulate_usage(  # type: ignore[attr-defined]
        SimpleNamespace(usage={"input_tokens": 100, "output_tokens": 40}, total_cost_usd=0.01)
    )
    backend._accumulate_usage(  # type: ignore[attr-defined]
        SimpleNamespace(usage={"input_tokens": 250, "output_tokens": 80}, total_cost_usd=0.03)
    )
    usage = await backend.usage()
    assert usage.input_tokens == 350
    assert usage.output_tokens == 120
    assert usage.usd == pytest.approx(0.04)


@pytest.mark.asyncio
async def test_accumulate_usage_unpriced_when_total_cost_missing() -> None:
    backend = ClaudeAgentBackend(ClaudeBackendConfig())
    backend._accumulate_usage(  # type: ignore[attr-defined]
        SimpleNamespace(usage={"input_tokens": 50, "output_tokens": 25}, total_cost_usd=None)
    )
    usage = await backend.usage()
    assert usage.input_tokens == 50
    assert usage.output_tokens == 25
    assert usage.usd is None  # No priced data yet → fall open


@pytest.mark.asyncio
async def test_accumulate_usage_handles_missing_usage_attr() -> None:
    backend = ClaudeAgentBackend(ClaudeBackendConfig())
    backend._accumulate_usage(SimpleNamespace())  # type: ignore[attr-defined]
    usage = await backend.usage()
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.usd is None
