"""Factory loading with allowlist gating.

Mirrors the harden-factory pattern used by `vigor_harness.evaluator` so
``module:attr`` strings in `AgentConfig` are resolved consistently.
"""

from __future__ import annotations

import importlib
from typing import Any

from vigor_core.agent_config import FactoryRef


class FactoryLoadError(RuntimeError):
    """Raised when a factory string cannot be resolved or violates the allowlist."""


def load_factory(ref: FactoryRef) -> Any:
    """Resolve a `FactoryRef` to its underlying callable.

    The factory's module must start with one of the declared
    ``allowed_prefixes`` — supply-chain guard.
    """

    module_name, _, attr = ref.factory.partition(":")
    if not module_name or not attr:
        raise FactoryLoadError(f"factory must be 'module:attr', got {ref.factory!r}")
    if not any(module_name.startswith(prefix) for prefix in ref.allowed_prefixes):
        raise FactoryLoadError(
            f"factory module {module_name!r} is not in allowed prefixes {ref.allowed_prefixes!r}"
        )
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise FactoryLoadError(f"cannot import {module_name!r}: {exc}") from exc
    try:
        return getattr(module, attr)
    except AttributeError as exc:
        raise FactoryLoadError(f"module {module_name!r} has no attribute {attr!r}") from exc


def call_factory(ref: FactoryRef) -> Any:
    """Resolve and invoke a factory with its declared kwargs."""

    factory = load_factory(ref)
    return factory(**ref.kwargs)
