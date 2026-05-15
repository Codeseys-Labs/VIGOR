"""Router resolution tests."""

from __future__ import annotations

import pytest
from vigor_agent.router import Router, RoutingError
from vigor_core.agent_config import AdapterSpec, FactoryRef, RoutingPolicy
from vigor_core.schemas import Budgets, TaskSpec


class _FakeRegistry:
    def __init__(self, specs: list[AdapterSpec]) -> None:
        self._specs = specs

    def adapter_ids(self) -> list[str]:
        return [s.adapter_id for s in self._specs]

    def specs(self) -> list[AdapterSpec]:
        return list(self._specs)


def _spec(
    adapter_id: str,
    *,
    modalities: list[str] | None = None,
    domains: list[str] | None = None,
) -> AdapterSpec:
    return AdapterSpec(
        adapter_id=adapter_id,
        factory=FactoryRef(factory="pkg.mod:Cls", allowed_prefixes=["pkg"]),
        modalities=modalities or [],
        domains=domains or [],
    )


def _task(
    task_id: str = "t1",
    modalities: list[str] | None = None,
    domain: dict | None = None,
) -> TaskSpec:
    return TaskSpec(
        task_id=task_id,
        goal="g",
        modalities=modalities or ["text"],
        budgets=Budgets(),
        domain=domain or {},
    )


def test_modality_match_resolves_unique_adapter() -> None:
    registry = _FakeRegistry(
        [
            _spec("adapter_text", modalities=["text"]),
            _spec("adapter_photo", modalities=["image"]),
        ]
    )
    router = Router(RoutingPolicy(strategy="modality_match"), registry)
    assert router.resolve(_task(modalities=["text"])) == "adapter_text"
    assert router.resolve(_task(modalities=["image"])) == "adapter_photo"


def test_modality_match_ambiguous_raises() -> None:
    registry = _FakeRegistry(
        [
            _spec("a", modalities=["text"]),
            _spec("b", modalities=["text"]),
        ]
    )
    router = Router(RoutingPolicy(strategy="modality_match"), registry)
    with pytest.raises(RoutingError, match="multiple adapters"):
        router.resolve(_task(modalities=["text"]))


def test_modality_match_no_match_uses_default() -> None:
    registry = _FakeRegistry(
        [
            _spec("adapter_text", modalities=["text"]),
        ]
    )
    policy = RoutingPolicy(strategy="modality_match", default_adapter_id="adapter_text")
    router = Router(policy, registry)
    assert router.resolve(_task(modalities=["unknown"])) == "adapter_text"


def test_modality_match_no_default_raises() -> None:
    registry = _FakeRegistry(
        [
            _spec("adapter_text", modalities=["text"]),
        ]
    )
    router = Router(RoutingPolicy(strategy="modality_match"), registry)
    with pytest.raises(RoutingError, match="did not match any adapter"):
        router.resolve(_task(modalities=["unknown"]))


def test_overrides_take_precedence() -> None:
    registry = _FakeRegistry(
        [
            _spec("adapter_text", modalities=["text"]),
            _spec("adapter_photo", modalities=["image"]),
        ]
    )
    policy = RoutingPolicy(strategy="modality_match", overrides={"t1": "adapter_photo"})
    router = Router(policy, registry)
    assert router.resolve(_task("t1", modalities=["text"])) == "adapter_photo"
    assert router.resolve(_task("t2", modalities=["text"])) == "adapter_text"


def test_domain_match_uses_task_domain() -> None:
    registry = _FakeRegistry(
        [
            _spec("adapter_photo", domains=["photo_editing"]),
            _spec("adapter_cad", domains=["cad"]),
        ]
    )
    router = Router(RoutingPolicy(strategy="domain_match"), registry)
    task = _task(domain={"name": "cad"})
    assert router.resolve(task) == "adapter_cad"


def test_single_strategy_requires_one_adapter() -> None:
    one = _FakeRegistry([_spec("only", modalities=["text"])])
    router = Router(RoutingPolicy(strategy="single"), one)
    assert router.resolve(_task()) == "only"

    two = _FakeRegistry([_spec("a"), _spec("b")])
    router2 = Router(RoutingPolicy(strategy="single"), two)
    with pytest.raises(RoutingError, match="exactly one"):
        router2.resolve(_task())


def test_explicit_strategy_uses_default_when_no_override() -> None:
    registry = _FakeRegistry([_spec("a"), _spec("b")])
    policy = RoutingPolicy(strategy="explicit", default_adapter_id="b")
    router = Router(policy, registry)
    assert router.resolve(_task()) == "b"


def test_explicit_strategy_without_default_or_override_raises() -> None:
    registry = _FakeRegistry([_spec("a"), _spec("b")])
    router = Router(RoutingPolicy(strategy="explicit"), registry)
    with pytest.raises(RoutingError, match="explicit routing"):
        router.resolve(_task())
