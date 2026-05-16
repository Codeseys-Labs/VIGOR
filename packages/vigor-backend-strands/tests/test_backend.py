"""Smoke tests for the Strands backend skeleton.

These tests verify the backend imports cleanly without strands-agents
installed and raises a helpful error when a method needing the real SDK is
called.
"""

from __future__ import annotations

import sys

import pytest
from vigor_backend_strands import StrandsAgentBackend, StrandsBackendConfig
from vigor_core.interfaces import GenerationRequest, RepresentationPlan
from vigor_core.schemas import TaskSpec


@pytest.fixture
def strands_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force ``from strands import Agent`` to raise ImportError.

    Setting ``sys.modules[name] = None`` makes Python's import machinery
    raise ImportError on the next ``import name``, even when the package
    is installed on disk. Lets us exercise the lazy-import fallback path
    in environments where the optional SDK is present (e.g.
    ``uv sync --all-extras`` in CI).
    """
    monkeypatch.setitem(sys.modules, "strands", None)


def test_backend_instantiates_without_strands() -> None:
    backend = StrandsAgentBackend(StrandsBackendConfig(provider="bedrock"))
    assert isinstance(backend, StrandsAgentBackend)


@pytest.mark.asyncio
async def test_generate_raises_without_strands(strands_absent: None) -> None:
    backend = StrandsAgentBackend(StrandsBackendConfig(provider="bedrock"))
    task = TaskSpec(task_id="t", goal="g", modalities=["toy"])
    plan = RepresentationPlan(ir_type="toy.v1")
    with pytest.raises(ImportError, match="strands-agents"):
        await backend.generate(GenerationRequest(task=task, plan=plan))
