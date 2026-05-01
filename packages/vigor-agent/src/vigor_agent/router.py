"""Task → adapter routing for the configurable VIGOR agent."""

from __future__ import annotations

from vigor_core.agent_config import RoutingPolicy
from vigor_core.schemas import TaskSpec

from vigor_agent.registry import AdapterRegistry


class RoutingError(RuntimeError):
    """Raised when a `TaskSpec` cannot be unambiguously routed to an adapter."""


class Router:
    """Resolves a `TaskSpec` to an ``adapter_id`` per `RoutingPolicy`."""

    def __init__(self, policy: RoutingPolicy, registry: AdapterRegistry) -> None:
        self._policy = policy
        self._registry = registry

    def resolve(self, task: TaskSpec) -> str:
        override = self._policy.overrides.get(task.task_id)
        if override is not None:
            return override

        strategy = self._policy.strategy
        if strategy == "explicit":
            adapter_id = self._policy.default_adapter_id
            if adapter_id is None:
                raise RoutingError(
                    f"explicit routing requires either an override for task_id "
                    f"{task.task_id!r} or a default_adapter_id"
                )
            return adapter_id

        if strategy == "single":
            if len(self._registry.adapter_ids()) != 1:
                raise RoutingError(
                    "single routing requires exactly one enabled adapter "
                    f"(got {self._registry.adapter_ids()})"
                )
            return self._registry.adapter_ids()[0]

        if strategy == "modality_match":
            matches = [
                spec.adapter_id
                for spec in self._registry.specs()
                if set(spec.modalities) & set(task.modalities)
            ]
        elif strategy == "domain_match":
            domain_name = task.domain.get("name") if isinstance(task.domain, dict) else None
            matches = [
                spec.adapter_id
                for spec in self._registry.specs()
                if domain_name is not None and domain_name in spec.domains
            ]
        else:
            raise RoutingError(f"unsupported routing strategy {strategy!r}")

        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise RoutingError(
                f"task {task.task_id!r} matched multiple adapters {matches!r}; "
                "add a routing.overrides entry to disambiguate"
            )
        if self._policy.default_adapter_id is not None:
            return self._policy.default_adapter_id
        raise RoutingError(
            f"task {task.task_id!r} did not match any adapter via "
            f"strategy={strategy!r} and no default_adapter_id is set"
        )
