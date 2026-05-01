"""VIGOR agent configuration schema.

`AgentConfig` declaratively wires one VIGOR agent: which adapters to load,
which MCP servers to attach, which agent backend to use, how tasks are
routed across multiple adapters, and the run-archive directory.

The aim is to let one configurable VIGOR agent serve any combination of
modalities, instead of forking the runtime per use-case.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from vigor_core.schemas import (
    ID_PATTERN,
    Budgets,
    _VigorBase,
)

FACTORY_PATTERN = r"^[\w\.]+:[\w\.]+$"


class FactoryRef(_VigorBase):
    """Reference to a Python factory callable as ``module:attr``.

    The ``allowed_prefixes`` field is a supply-chain guard mirroring
    ``vigor_harness.evaluator._load_factory`` — only modules whose dotted
    path begins with one of these prefixes can be imported by the loader.
    """

    factory: str = Field(pattern=FACTORY_PATTERN)
    kwargs: dict[str, Any] = Field(default_factory=dict)
    allowed_prefixes: list[str] = Field(min_length=1)


class AdapterSpec(_VigorBase):
    """Declares one adapter that the agent can dispatch tasks to."""

    adapter_id: str = Field(pattern=ID_PATTERN)
    factory: FactoryRef
    domains: list[str] = Field(default_factory=list)
    modalities: list[str] = Field(default_factory=list)
    enabled: bool = True


class MCPServerSpec(_VigorBase):
    """Declares one MCP server to expose as a `ToolBackend`.

    Stdio servers use ``command`` (argv); HTTP/SSE servers use ``url``
    plus optional ``headers``. ``role_mapping`` reserves space for a
    future MCP-as-DomainAdapter convention; v1 keeps it empty.
    """

    server_id: str = Field(pattern=ID_PATTERN)
    transport: Literal["stdio", "http", "sse"]
    command: list[str] | None = None
    url: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)
    tool_allowlist: list[str] | None = None
    timeout_s: int = Field(default=30, ge=1)
    role_mapping: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check_transport_fields(self) -> MCPServerSpec:
        if self.transport == "stdio":
            if not self.command:
                raise ValueError("stdio transport requires a non-empty command")
            if self.url is not None:
                raise ValueError("stdio transport must not set url")
        else:
            if not self.url:
                raise ValueError(f"{self.transport} transport requires url")
            if self.command is not None:
                raise ValueError(f"{self.transport} transport must not set command")
        return self


class BackendSpec(_VigorBase):
    """Declares the agent backend that drives generate/review/propose_patch."""

    backend_id: str = Field(pattern=ID_PATTERN)
    factory: FactoryRef


class RoutingPolicy(_VigorBase):
    """Decides which adapter should handle a given `TaskSpec`.

    - ``modality_match``: adapter whose ``modalities`` intersect with
      ``TaskSpec.modalities`` (error on ambiguity).
    - ``domain_match``: adapter whose ``domains`` contain
      ``TaskSpec.domain.name``.
    - ``explicit``: look up ``TaskSpec.task_id`` in ``overrides``.
    - ``single``: use the only enabled adapter (error if more than one).

    ``default_adapter_id`` is used as a fallback when a strategy yields
    no match and no override applies.
    """

    strategy: Literal["modality_match", "domain_match", "explicit", "single"] = "modality_match"
    default_adapter_id: str | None = Field(default=None, pattern=ID_PATTERN)
    overrides: dict[str, str] = Field(default_factory=dict)


class AgentConfig(_VigorBase):
    """Top-level configuration for one VIGOR agent."""

    schema_version: Literal["vigor.agent_config.v1"] = "vigor.agent_config.v1"
    agent_id: str = Field(pattern=ID_PATTERN)
    backend: BackendSpec
    adapters: list[AdapterSpec] = Field(min_length=1)
    mcp_servers: list[MCPServerSpec] = Field(default_factory=list)
    routing: RoutingPolicy = Field(default_factory=RoutingPolicy)
    budgets: Budgets = Field(default_factory=Budgets)
    archive_dir: str = "runs"

    @model_validator(mode="after")
    def _check_unique_ids_and_routing(self) -> AgentConfig:
        adapter_ids = [a.adapter_id for a in self.adapters]
        if len(set(adapter_ids)) != len(adapter_ids):
            raise ValueError("adapter_ids must be unique within an AgentConfig")

        server_ids = [s.server_id for s in self.mcp_servers]
        if len(set(server_ids)) != len(server_ids):
            raise ValueError("mcp_server ids must be unique within an AgentConfig")

        known = set(adapter_ids)
        if (
            self.routing.default_adapter_id is not None
            and self.routing.default_adapter_id not in known
        ):
            raise ValueError(
                f"routing.default_adapter_id {self.routing.default_adapter_id!r} "
                "does not match any declared adapter"
            )
        for task_id, adapter_id in self.routing.overrides.items():
            if adapter_id not in known:
                raise ValueError(
                    f"routing.overrides[{task_id!r}] = {adapter_id!r} does not match "
                    "any declared adapter"
                )
        return self
