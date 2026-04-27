"""VIGOR runtime package.

Exposes the orchestrator, the echo backend used for tests and demos, a toy
domain adapter, and the Typer-based CLI.
"""

from vigor_runtime.backends import EchoAgentBackend, NullToolBackend
from vigor_runtime.orchestrator import Orchestrator, RunResult
from vigor_runtime.toy_adapter import ToyTextAdapter

__all__ = [
    "EchoAgentBackend",
    "NullToolBackend",
    "Orchestrator",
    "RunResult",
    "ToyTextAdapter",
]

__version__ = "0.1.0"
