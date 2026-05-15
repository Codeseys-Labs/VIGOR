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

    The ``allowed_prefixes`` field is a namespace assertion mirroring
    ``vigor_harness.evaluator._load_factory``: a module passes the gate
    when it equals one of the prefixes or is a dotted-component
    descendant (``prefix`` or ``prefix.subpkg``). Plain ``startswith``
    matches typosquats like ``vigor_runtime_evil`` and is intentionally
    rejected. Plugin-supplied prefixes are gated separately by the host
    via :func:`assert_factory_ref_allowed`.
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

    Subprocess env policy (stdio only, breaking default-change per ADR-0029)
    -----------------------------------------------------------------------
    For the ``stdio`` transport, ``env`` is the **explicit pass-through** for
    the spawned MCP server. The transport now starts the child with a
    drop-all-by-default environment: only keys named in this dict (plus
    ``PATH``, which is required for CLI shims like ``uvx``/``npx``) reach
    the child process. Vendor keys (``ANTHROPIC_API_KEY``, ``GEMINI_API_KEY``,
    ``AWS_*``, ``OPENAI_API_KEY``, ...) are **not** inherited from the parent
    process and must be declared here if the server needs them.

    This is a breaking default-change from the prior inherit-all-when-empty
    behavior. The migration is server-by-server: any official MCP server
    that previously relied on inherited env keys will fail loudly with a
    missing-key error from the server itself; declaring the key in
    ``MCPServerSpec.env`` resolves it. See ``docs/adr/0016-official-mcp-servers.md``
    for the per-server required-key list.

    For ``http`` and ``sse`` transports, ``env`` MUST be empty — those
    transports do not spawn a subprocess.
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
            if self.headers:
                raise ValueError("stdio transport must not set headers (http/sse only)")
        else:
            if not self.url:
                raise ValueError(f"{self.transport} transport requires url")
            if self.command is not None:
                raise ValueError(f"{self.transport} transport must not set command")
            if self.env:
                raise ValueError(
                    f"{self.transport} transport must not set env (stdio subprocess only)"
                )
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
    """Top-level configuration for one VIGOR agent.

    ``allowed_plugin_factory_prefixes`` is the host-side allowlist that
    constrains which prefixes a plugin's ``.plugin/vigor.json`` may
    declare in its `FactoryRef`. Without it, a plugin could opt itself
    into any namespace (e.g. ``allowed_prefixes=["os"]``) and bypass the
    per-`FactoryRef` namespace assertion. Empty list (default) means
    "no plugins" — host must explicitly opt in to plugin-supplied
    factories.
    """

    schema_version: Literal["vigor.agent_config.v1"] = "vigor.agent_config.v1"
    agent_id: str = Field(pattern=ID_PATTERN)
    backend: BackendSpec
    adapters: list[AdapterSpec] = Field(min_length=1)
    mcp_servers: list[MCPServerSpec] = Field(default_factory=list)
    routing: RoutingPolicy = Field(default_factory=RoutingPolicy)
    budgets: Budgets = Field(default_factory=Budgets)
    archive_dir: str = "runs"
    allowed_plugin_factory_prefixes: list[str] = Field(default_factory=list)

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
        if self.routing.strategy == "single":
            enabled_count = sum(1 for adapter in self.adapters if adapter.enabled)
            if enabled_count != 1:
                raise ValueError(
                    "routing.strategy='single' requires exactly one enabled adapter, "
                    f"found {enabled_count}"
                )
        return self


def assert_factory_ref_allowed(
    ref: FactoryRef, host_allowed_prefixes: list[str] | tuple[str, ...]
) -> None:
    """Verify a plugin-supplied `FactoryRef` only declares host-allowed prefixes.

    Plugins ship their own ``allowed_prefixes`` inside
    ``.plugin/vigor.json``. The host registering the plugin MUST gate
    those prefixes against its own allowlist using dotted-component
    matching, otherwise any plugin author could opt themselves into
    arbitrary namespaces (the prefix becomes self-authorization).

    Raises ``ValueError`` if any of the plugin's declared prefixes is
    not contained in (or equal to) one of the host-allowed prefixes.
    """

    if not host_allowed_prefixes:
        raise ValueError(
            "host has no allowed_plugin_factory_prefixes configured; refuse to "
            "register plugin factory"
        )
    host = list(host_allowed_prefixes)
    for prefix in ref.allowed_prefixes:
        if not any(prefix == allowed or prefix.startswith(allowed + ".") for allowed in host):
            raise ValueError(
                f"plugin-supplied prefix {prefix!r} is not within host-allowed prefixes {host!r}"
            )
