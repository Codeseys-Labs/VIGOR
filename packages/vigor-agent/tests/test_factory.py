"""Tests for the factory loader supply-chain guards."""

from __future__ import annotations

import pytest
from vigor_agent.factory import FactoryLoadError, call_factory, load_factory
from vigor_core.agent_config import FactoryRef


def test_load_factory_rejects_module_outside_allowlist() -> None:
    ref = FactoryRef(factory="os.path:join", allowed_prefixes=["vigor_runtime"])
    with pytest.raises(FactoryLoadError, match="not in allowed prefixes"):
        load_factory(ref)


def test_load_factory_rejects_unknown_module() -> None:
    ref = FactoryRef(
        factory="vigor_runtime.does_not_exist:thing",
        allowed_prefixes=["vigor_runtime"],
    )
    with pytest.raises(FactoryLoadError, match="cannot import"):
        load_factory(ref)


def test_load_factory_rejects_unknown_attribute() -> None:
    ref = FactoryRef(
        factory="vigor_runtime.toy_adapter:NotAClass",
        allowed_prefixes=["vigor_runtime"],
    )
    with pytest.raises(FactoryLoadError, match="has no attribute"):
        load_factory(ref)


def test_call_factory_invokes_with_kwargs() -> None:
    ref = FactoryRef(
        factory="vigor_runtime.backends:EchoAgentBackend",
        allowed_prefixes=["vigor_runtime"],
    )
    instance = call_factory(ref)
    assert instance.__class__.__name__ == "EchoAgentBackend"


def test_load_factory_rejects_typosquat_prefix() -> None:
    """`vigor_runtime_evil.foo` must not satisfy a `vigor_runtime` prefix."""

    ref = FactoryRef(
        factory="vigor_runtime_evil.backends:EchoAgentBackend",
        allowed_prefixes=["vigor_runtime"],
    )
    with pytest.raises(FactoryLoadError, match="not in allowed prefixes"):
        load_factory(ref)


def test_load_factory_accepts_exact_prefix_match() -> None:
    """Exact match against the prefix itself is allowed."""

    ref = FactoryRef(factory="vigor_runtime:_does_not_exist", allowed_prefixes=["vigor_runtime"])
    with pytest.raises(FactoryLoadError, match="has no attribute"):
        load_factory(ref)


def test_load_factory_accepts_dotted_subpackage() -> None:
    """``prefix.sub.module`` is a legitimate subpackage and passes."""

    ref = FactoryRef(
        factory="vigor_runtime.backends:EchoAgentBackend",
        allowed_prefixes=["vigor_runtime"],
    )
    factory = load_factory(ref)
    assert factory.__name__ == "EchoAgentBackend"
