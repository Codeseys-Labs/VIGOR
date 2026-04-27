"""Small factories used by harness tests and examples."""

from __future__ import annotations

from typing import Any

from vigor_core.interfaces import GenerationRequest
from vigor_runtime.backends import EchoAgentBackend
from vigor_runtime.toy_adapter import ToyTextAdapter


def toy_adapter_factory() -> ToyTextAdapter:
    return ToyTextAdapter()


def _seed(request: GenerationRequest) -> dict[str, Any]:
    return {"text": request.task.goal}


def toy_backend_factory() -> EchoAgentBackend:
    return EchoAgentBackend(seed_ir_factory=_seed)
