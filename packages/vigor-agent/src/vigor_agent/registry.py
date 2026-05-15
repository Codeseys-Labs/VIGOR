"""Adapter registry: instantiate and look up adapters declared in `AgentConfig`."""

from __future__ import annotations

from vigor_core.agent_config import AdapterSpec, AgentConfig
from vigor_core.interfaces import DomainAdapter

from vigor_agent.factory import FactoryLoadError, call_factory


class AdapterRegistry:
    """Holds instantiated adapters keyed by ``adapter_id``."""

    def __init__(self, adapters: dict[str, DomainAdapter], specs: dict[str, AdapterSpec]) -> None:
        self._adapters = adapters
        self._specs = specs

    @classmethod
    def from_config(cls, config: AgentConfig) -> AdapterRegistry:
        adapters: dict[str, DomainAdapter] = {}
        specs: dict[str, AdapterSpec] = {}
        for spec in config.adapters:
            if not spec.enabled:
                continue
            instance = call_factory(spec.factory)
            if not isinstance(instance, DomainAdapter):
                raise FactoryLoadError(
                    f"factory for adapter {spec.adapter_id!r} did not return a "
                    f"DomainAdapter (got {type(instance).__name__})"
                )
            adapters[spec.adapter_id] = instance
            specs[spec.adapter_id] = spec
        if not adapters:
            raise ValueError("AgentConfig contains no enabled adapters")
        return cls(adapters, specs)

    def get(self, adapter_id: str) -> DomainAdapter:
        try:
            return self._adapters[adapter_id]
        except KeyError as exc:
            raise KeyError(f"unknown adapter_id {adapter_id!r}") from exc

    def spec(self, adapter_id: str) -> AdapterSpec:
        return self._specs[adapter_id]

    def adapter_ids(self) -> list[str]:
        return list(self._adapters)

    def specs(self) -> list[AdapterSpec]:
        return list(self._specs.values())
