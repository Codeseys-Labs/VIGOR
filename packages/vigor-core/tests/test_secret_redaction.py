"""Secret-redaction guarantees for AgentConfig (VIGOR-dfbd).

``MCPServerSpec.env`` and ``MCPServerSpec.headers`` carry vendor
credentials (vendor API keys, ``Authorization: Bearer …`` headers).
They are typed as ``dict[str, SecretStr]`` so accidental serialisation —
either via :meth:`pydantic.BaseModel.model_dump_json` or via Python's
default ``repr`` / ``str`` — never emits the cleartext.

These tests pin the contract that scout finding §2 / recommendation #6
asked for: the JSON dump of an ``AgentConfig`` containing secrets must
not contain any of the cleartext substrings, and the Pydantic instance's
``repr`` must not leak them either. Cleartext only escapes through the
explicit ``SecretStr.get_secret_value()`` call used by the transport
layer at the SDK boundary.
"""

from __future__ import annotations

import json

import pytest
from pydantic import SecretStr
from vigor_core.agent_config import (
    AdapterSpec,
    AgentConfig,
    BackendSpec,
    FactoryRef,
    MCPServerSpec,
)

_RAW_VENDOR_KEY = "sk-anthropic-tenant-A-do-not-leak"
_RAW_BEARER = "Bearer github_pat_do_not_leak_either"


def _config_with_secrets() -> AgentConfig:
    """Construct an ``AgentConfig`` whose env / headers carry real secrets.

    Uses both transports so we cover the env path (stdio) and the headers
    path (http) in one fixture. Plain-string values are deliberately
    passed in to verify that Pydantic's ``SecretStr`` coercion accepts
    them — this is the YAML-loaded shape operators actually have.
    """

    return AgentConfig(
        agent_id="agent_default",
        backend=BackendSpec(
            backend_id="backend_echo",
            factory=FactoryRef(
                factory="vigor_runtime.echo_backend:EchoAgentBackend",
                allowed_prefixes=["vigor_runtime"],
            ),
        ),
        adapters=[
            AdapterSpec(
                adapter_id="adapter_toy",
                factory=FactoryRef(
                    factory="vigor_runtime.toy_adapter:ToyTextAdapter",
                    allowed_prefixes=["vigor_runtime"],
                ),
                modalities=["text"],
            )
        ],
        mcp_servers=[
            MCPServerSpec(
                server_id="mcp_stdio",
                transport="stdio",
                command=["uvx", "some-mcp-server"],
                env={"ANTHROPIC_API_KEY": _RAW_VENDOR_KEY},  # type: ignore[dict-item]
            ),
            MCPServerSpec(
                server_id="mcp_http",
                transport="http",
                url="https://mcp.example.com",
                headers={"Authorization": _RAW_BEARER},  # type: ignore[dict-item]
            ),
        ],
    )


def test_mcp_server_spec_env_values_are_secretstr() -> None:
    """Plain-string env values must coerce to SecretStr at validation time.

    This is the load-time shape operators get from a YAML/JSON file —
    they write ``ANTHROPIC_API_KEY: "sk-…"`` and Pydantic wraps it. If
    coercion silently failed, the redaction guarantee would only apply
    to programmatically-constructed configs, which is the wrong contract.
    """

    spec = MCPServerSpec(
        server_id="mcp_a",
        transport="stdio",
        command=["x"],
        env={"ANTHROPIC_API_KEY": _RAW_VENDOR_KEY},  # type: ignore[dict-item]
    )
    assert isinstance(spec.env["ANTHROPIC_API_KEY"], SecretStr)
    assert spec.env["ANTHROPIC_API_KEY"].get_secret_value() == _RAW_VENDOR_KEY


def test_mcp_server_spec_headers_values_are_secretstr() -> None:
    spec = MCPServerSpec(
        server_id="mcp_h",
        transport="http",
        url="https://mcp.example.com",
        headers={"Authorization": _RAW_BEARER},  # type: ignore[dict-item]
    )
    assert isinstance(spec.headers["Authorization"], SecretStr)
    assert spec.headers["Authorization"].get_secret_value() == _RAW_BEARER


def test_model_dump_json_redacts_env_secrets() -> None:
    """The serialised JSON must not contain the raw env-key cleartext."""

    cfg = _config_with_secrets()
    payload = cfg.model_dump_json(by_alias=True)

    assert _RAW_VENDOR_KEY not in payload, (
        "raw vendor API key leaked through model_dump_json — "
        "MCPServerSpec.env must redact via SecretStr"
    )
    # And the redacted form should be present in its place.
    parsed = json.loads(payload)
    stdio = next(s for s in parsed["mcpServers"] if s["serverId"] == "mcp_stdio")
    assert stdio["env"]["ANTHROPIC_API_KEY"] == "**********"


def test_model_dump_json_redacts_header_secrets() -> None:
    """The serialised JSON must not contain the raw Authorization header."""

    cfg = _config_with_secrets()
    payload = cfg.model_dump_json(by_alias=True)

    assert _RAW_BEARER not in payload, (
        "raw Authorization header leaked through model_dump_json — "
        "MCPServerSpec.headers must redact via SecretStr"
    )
    parsed = json.loads(payload)
    http = next(s for s in parsed["mcpServers"] if s["serverId"] == "mcp_http")
    assert http["headers"]["Authorization"] == "**********"


def test_repr_redacts_env_and_headers() -> None:
    """``repr(spec)`` must not surface secret cleartext.

    This is a tighter bar than ``model_dump_json`` because logging
    libraries (and pdb sessions, and ``print(spec)`` debugging) reach
    for ``repr`` long before they reach for the JSON serialiser.
    SecretStr's ``__repr__`` returns ``SecretStr('**********')``.
    """

    cfg = _config_with_secrets()
    repr_text = repr(cfg)

    assert _RAW_VENDOR_KEY not in repr_text
    assert _RAW_BEARER not in repr_text


def test_str_redacts_env_and_headers() -> None:
    """``str(spec)`` must not surface secret cleartext either.

    Pydantic models default ``__str__`` to a field-name=value listing,
    which would print the raw value if SecretStr's ``__str__`` were not
    redacting. The redaction is a SecretStr property, not a Pydantic one.
    """

    cfg = _config_with_secrets()
    text = str(cfg)

    assert _RAW_VENDOR_KEY not in text
    assert _RAW_BEARER not in text


def test_model_dump_json_round_trip_preserves_secret_values() -> None:
    """Round-tripping through redacted JSON would lose the cleartext.

    This test pins the (deliberately asymmetric) behaviour: SecretStr
    redacts on dump, so a round trip via ``model_dump_json`` cannot
    rebuild the cleartext. Operators who need a true round-trip must
    re-load from the original YAML/JSON source, not from a redacted dump.
    """

    cfg = _config_with_secrets()
    payload = cfg.model_dump_json(by_alias=True)
    rebuilt = AgentConfig.model_validate_json(payload)

    stdio = next(s for s in rebuilt.mcp_servers if s.server_id == "mcp_stdio")
    # The rebuilt value is whatever the redacted JSON contained, NOT the original.
    assert stdio.env["ANTHROPIC_API_KEY"].get_secret_value() == "**********"


def test_get_secret_value_yields_cleartext() -> None:
    """The explicit unwrap path must still produce the original value.

    Without this, the transport layer cannot pass the real key to the
    SDK boundary, and the whole subprocess-env policy collapses.
    """

    cfg = _config_with_secrets()
    stdio = next(s for s in cfg.mcp_servers if s.server_id == "mcp_stdio")
    assert stdio.env["ANTHROPIC_API_KEY"].get_secret_value() == _RAW_VENDOR_KEY

    http = next(s for s in cfg.mcp_servers if s.server_id == "mcp_http")
    assert http.headers["Authorization"].get_secret_value() == _RAW_BEARER


def test_secretstr_inputs_are_accepted_directly() -> None:
    """Programmatic constructors that already hold SecretStr must work."""

    spec = MCPServerSpec(
        server_id="mcp_pre",
        transport="stdio",
        command=["x"],
        env={"GEMINI_API_KEY": SecretStr(_RAW_VENDOR_KEY)},
    )
    assert spec.env["GEMINI_API_KEY"].get_secret_value() == _RAW_VENDOR_KEY


@pytest.mark.parametrize("alias", [True, False])
def test_dump_json_redacts_under_both_alias_modes(alias: bool) -> None:
    """``by_alias`` flips between ``serverId`` and ``server_id`` shapes
    on the wire, but redaction must hold either way."""

    cfg = _config_with_secrets()
    payload = cfg.model_dump_json(by_alias=alias)
    assert _RAW_VENDOR_KEY not in payload
    assert _RAW_BEARER not in payload
