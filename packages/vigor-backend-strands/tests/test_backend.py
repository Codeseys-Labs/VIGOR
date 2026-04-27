"""Smoke tests for the Strands backend skeleton.

These tests verify the backend imports cleanly without strands-agents
installed and raises a helpful error when a method needing the real SDK is
called.
"""

from __future__ import annotations

import pytest
from vigor_backend_strands import StrandsAgentBackend, StrandsBackendConfig
from vigor_core.interfaces import GenerationRequest, RepresentationPlan
from vigor_core.schemas import TaskSpec


def test_backend_instantiates_without_strands() -> None:
    backend = StrandsAgentBackend(StrandsBackendConfig(provider="bedrock"))
    assert isinstance(backend, StrandsAgentBackend)


@pytest.mark.asyncio
async def test_generate_raises_without_strands() -> None:
    backend = StrandsAgentBackend(StrandsBackendConfig(provider="bedrock"))
    task = TaskSpec(task_id="t", goal="g", modalities=["toy"])
    plan = RepresentationPlan(ir_type="toy.v1")
    with pytest.raises(ImportError, match="strands-agents"):
        await backend.generate(GenerationRequest(task=task, plan=plan))
