"""Tests for the AgentConfig schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from vigor_core.agent_config import (
    AdapterSpec,
    AgentConfig,
    BackendSpec,
    FactoryRef,
    MCPServerSpec,
    RoutingPolicy,
    assert_factory_ref_allowed,
)


def _toy_config(**overrides: object) -> AgentConfig:
    payload: dict[str, object] = {
        "agent_id": "agent_default",
        "backend": BackendSpec(
            backend_id="backend_echo",
            factory=FactoryRef(
                factory="vigor_runtime.echo_backend:EchoAgentBackend",
                allowed_prefixes=["vigor_runtime"],
            ),
        ),
        "adapters": [
            AdapterSpec(
                adapter_id="adapter_toy",
                factory=FactoryRef(
                    factory="vigor_runtime.toy_adapter:ToyTextAdapter",
                    allowed_prefixes=["vigor_runtime"],
                ),
                modalities=["text"],
            )
        ],
    }
    payload.update(overrides)
    return AgentConfig.model_validate(payload, from_attributes=True)


def test_minimal_config_roundtrip() -> None:
    cfg = _toy_config()
    data = cfg.model_dump(by_alias=True, mode="json")
    rebuilt = AgentConfig.model_validate(data)
    assert rebuilt.model_dump(by_alias=True, mode="json") == data
    assert rebuilt.schema_version == "vigor.agent_config.v1"


def test_strict_mode_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        AgentConfig.model_validate(
            {
                "agentId": "agent_default",
                "backend": {
                    "backendId": "backend_echo",
                    "factory": {
                        "factory": "vigor_runtime.echo_backend:EchoAgentBackend",
                        "allowedPrefixes": ["vigor_runtime"],
                    },
                },
                "adapters": [
                    {
                        "adapterId": "adapter_toy",
                        "factory": {
                            "factory": "vigor_runtime.toy_adapter:ToyTextAdapter",
                            "allowedPrefixes": ["vigor_runtime"],
                        },
                    }
                ],
                "unknown_field": True,
            }
        )


def test_factory_ref_pattern_enforced() -> None:
    with pytest.raises(ValidationError):
        FactoryRef(factory="missing-colon", allowed_prefixes=["pkg"])
    with pytest.raises(ValidationError):
        FactoryRef(factory="bad name:attr", allowed_prefixes=["pkg"])


def test_factory_ref_requires_allowed_prefixes() -> None:
    with pytest.raises(ValidationError):
        FactoryRef(factory="pkg.mod:fn", allowed_prefixes=[])


def test_adapter_ids_must_be_unique() -> None:
    spec = AdapterSpec(
        adapter_id="adapter_dup",
        factory=FactoryRef(factory="pkg.mod:Cls", allowed_prefixes=["pkg"]),
    )
    with pytest.raises(ValidationError, match="adapter_ids must be unique"):
        _toy_config(adapters=[spec, spec.model_copy()])


def test_mcp_server_ids_must_be_unique() -> None:
    server = MCPServerSpec(
        server_id="mcp_fs",
        transport="stdio",
        command=["npx", "@modelcontextprotocol/server-filesystem", "/tmp"],
    )
    with pytest.raises(ValidationError, match="mcp_server ids must be unique"):
        _toy_config(mcp_servers=[server, server.model_copy()])


def test_stdio_mcp_requires_command() -> None:
    with pytest.raises(ValidationError, match="stdio transport requires"):
        MCPServerSpec(server_id="bad", transport="stdio")


def test_stdio_mcp_rejects_url() -> None:
    with pytest.raises(ValidationError, match="stdio transport must not set url"):
        MCPServerSpec(
            server_id="bad",
            transport="stdio",
            command=["x"],
            url="http://example.com",
        )


def test_http_mcp_requires_url() -> None:
    with pytest.raises(ValidationError, match="http transport requires url"):
        MCPServerSpec(server_id="bad", transport="http")


def test_sse_mcp_rejects_command() -> None:
    with pytest.raises(ValidationError, match="sse transport must not set command"):
        MCPServerSpec(
            server_id="bad",
            transport="sse",
            url="https://example.com/mcp",
            command=["x"],
        )


def test_routing_default_must_match_adapter() -> None:
    with pytest.raises(ValidationError, match="default_adapter_id"):
        _toy_config(routing=RoutingPolicy(default_adapter_id="not_present"))


def test_routing_overrides_must_match_adapter() -> None:
    with pytest.raises(ValidationError, match=r"routing\.overrides"):
        _toy_config(routing=RoutingPolicy(overrides={"task_42": "missing_adapter"}))


def test_routing_overrides_match_known_adapter() -> None:
    cfg = _toy_config(routing=RoutingPolicy(overrides={"task_42": "adapter_toy"}))
    assert cfg.routing.overrides == {"task_42": "adapter_toy"}


def test_camelcase_aliases_on_wire() -> None:
    cfg = _toy_config()
    payload = cfg.model_dump(by_alias=True, mode="json")
    assert "agentId" in payload
    assert "schemaVersion" in payload
    assert payload["adapters"][0]["adapterId"] == "adapter_toy"


def test_mcp_http_transport_accepts_url() -> None:
    server = MCPServerSpec(
        server_id="mcp_remote",
        transport="http",
        url="https://mcp.example.com",
        headers={"Authorization": "Bearer x"},
    )
    assert server.transport == "http"
    assert server.command is None


def test_timeout_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        MCPServerSpec(
            server_id="mcp_fs",
            transport="stdio",
            command=["x"],
            timeout_s=0,
        )


def test_stdio_mcp_rejects_headers() -> None:
    """``headers`` is an http/sse concept; declaring it on stdio is misconfig."""

    with pytest.raises(ValidationError, match="stdio transport must not set headers"):
        MCPServerSpec(
            server_id="bad",
            transport="stdio",
            command=["x"],
            headers={"Authorization": "Bearer x"},
        )


def test_http_mcp_rejects_env() -> None:
    """``env`` is a stdio subprocess concept; declaring it on http is misconfig."""

    with pytest.raises(ValidationError, match="http transport must not set env"):
        MCPServerSpec(
            server_id="bad",
            transport="http",
            url="https://example.com/mcp",
            env={"API_KEY": "x"},
        )


def test_sse_mcp_rejects_env() -> None:
    """``env`` is a stdio subprocess concept; declaring it on sse is misconfig."""

    with pytest.raises(ValidationError, match="sse transport must not set env"):
        MCPServerSpec(
            server_id="bad",
            transport="sse",
            url="https://example.com/mcp",
            env={"API_KEY": "x"},
        )


def test_routing_single_requires_exactly_one_enabled_adapter() -> None:
    """``strategy='single'`` must have one and only one enabled adapter."""

    base = AdapterSpec(
        adapter_id="adapter_other",
        factory=FactoryRef(factory="pkg.mod:Cls", allowed_prefixes=["pkg"]),
    )
    a = base.model_copy(update={"adapter_id": "adapter_a"})
    b = base.model_copy(update={"adapter_id": "adapter_b"})
    with pytest.raises(ValidationError, match="strategy='single' requires exactly one"):
        _toy_config(adapters=[a, b], routing=RoutingPolicy(strategy="single"))


def test_routing_single_with_one_disabled_adapter_passes() -> None:
    """Two adapters but only one enabled satisfies 'single' strategy."""

    first = AdapterSpec(
        adapter_id="adapter_only",
        factory=FactoryRef(factory="pkg.mod:Cls", allowed_prefixes=["pkg"]),
    )
    disabled = AdapterSpec(
        adapter_id="adapter_disabled",
        factory=FactoryRef(factory="pkg.mod:Other", allowed_prefixes=["pkg"]),
        enabled=False,
    )
    cfg = _toy_config(adapters=[first, disabled], routing=RoutingPolicy(strategy="single"))
    assert cfg.routing.strategy == "single"


def test_routing_single_with_zero_enabled_adapter_rejected() -> None:
    """Zero enabled adapters fails the 'single' strategy invariant."""

    disabled = AdapterSpec(
        adapter_id="adapter_disabled",
        factory=FactoryRef(factory="pkg.mod:Cls", allowed_prefixes=["pkg"]),
        enabled=False,
    )
    with pytest.raises(ValidationError, match="strategy='single' requires exactly one"):
        _toy_config(adapters=[disabled], routing=RoutingPolicy(strategy="single"))


def test_allowed_plugin_factory_prefixes_default_empty() -> None:
    """``allowed_plugin_factory_prefixes`` is empty by default — host opts in explicitly."""

    cfg = _toy_config()
    assert cfg.allowed_plugin_factory_prefixes == []


def test_allowed_plugin_factory_prefixes_round_trip() -> None:
    """The plugin allowlist round-trips via camelCase alias on the wire."""

    cfg = _toy_config(allowed_plugin_factory_prefixes=["vigor_adapter_photo"])
    payload = cfg.model_dump(by_alias=True, mode="json")
    assert payload["allowedPluginFactoryPrefixes"] == ["vigor_adapter_photo"]
    rebuilt = AgentConfig.model_validate(payload)
    assert rebuilt.allowed_plugin_factory_prefixes == ["vigor_adapter_photo"]


def test_assert_factory_ref_allowed_rejects_when_host_empty() -> None:
    ref = FactoryRef(factory="pkg.mod:Cls", allowed_prefixes=["pkg"])
    with pytest.raises(ValueError, match="host has no allowed_plugin_factory_prefixes"):
        assert_factory_ref_allowed(ref, [])


def test_assert_factory_ref_allowed_accepts_within_host_namespace() -> None:
    ref = FactoryRef(
        factory="vigor_runtime.toy_adapter:ToyTextAdapter",
        allowed_prefixes=["vigor_runtime", "vigor_runtime.toy_adapter"],
    )
    assert_factory_ref_allowed(ref, ["vigor_runtime"])


def test_assert_factory_ref_allowed_rejects_typosquat_prefix() -> None:
    ref = FactoryRef(
        factory="vigor_runtime_evil.foo:Bar",
        allowed_prefixes=["vigor_runtime_evil"],
    )
    with pytest.raises(ValueError, match="plugin-supplied prefix"):
        assert_factory_ref_allowed(ref, ["vigor_runtime"])


def test_assert_factory_ref_allowed_rejects_when_any_prefix_outside_host() -> None:
    """A plugin needs ALL its declared prefixes within the host allowlist."""

    ref = FactoryRef(
        factory="vigor_runtime.x:y",
        allowed_prefixes=["vigor_runtime", "os"],
    )
    with pytest.raises(ValueError, match="plugin-supplied prefix 'os'"):
        assert_factory_ref_allowed(ref, ["vigor_runtime"])
