"""Secret-redaction guarantees for ``ClaudeBackendConfig`` (VIGOR-dfbd).

Mirrors :mod:`vigor_core.tests.test_secret_redaction` for the dataclass
side of the policy: ``ClaudeBackendConfig.env`` is wrapped in
:class:`pydantic.SecretStr` so vendor keys do not leak into ``repr``,
``str``, or any structured logging that reaches the dataclass instance.
The cleartext is only materialised at the SDK boundary inside
:func:`_build_subprocess_env`, which the existing env-policy tests cover.
"""

from __future__ import annotations

from pydantic import SecretStr
from vigor_backend_claude_agent_sdk.backend import (
    ClaudeBackendConfig,
    _build_subprocess_env,
)

_RAW_VENDOR_KEY = "sk-anthropic-tenant-A-do-not-leak"


def test_config_env_string_input_is_coerced_to_secretstr() -> None:
    """Plain-string env values must coerce so the redaction guarantee
    is uniform regardless of how operators construct the config."""

    cfg = ClaudeBackendConfig(env={"ANTHROPIC_API_KEY": _RAW_VENDOR_KEY})
    assert isinstance(cfg.env["ANTHROPIC_API_KEY"], SecretStr)
    assert cfg.env["ANTHROPIC_API_KEY"].get_secret_value() == _RAW_VENDOR_KEY


def test_config_env_secretstr_input_is_preserved() -> None:
    cfg = ClaudeBackendConfig(env={"ANTHROPIC_API_KEY": SecretStr(_RAW_VENDOR_KEY)})
    assert cfg.env["ANTHROPIC_API_KEY"].get_secret_value() == _RAW_VENDOR_KEY


def test_repr_redacts_env_secrets() -> None:
    """``repr(cfg)`` must not surface the cleartext API key.

    SecretStr's ``__repr__`` redacts to ``SecretStr('**********')``;
    the dataclass auto-generated ``__repr__`` then composes that into
    the outer config repr, keeping the leak surface closed.
    """

    cfg = ClaudeBackendConfig(env={"ANTHROPIC_API_KEY": _RAW_VENDOR_KEY})
    assert _RAW_VENDOR_KEY not in repr(cfg)


def test_str_redacts_env_secrets() -> None:
    cfg = ClaudeBackendConfig(env={"ANTHROPIC_API_KEY": _RAW_VENDOR_KEY})
    assert _RAW_VENDOR_KEY not in str(cfg)


def test_build_subprocess_env_unwraps_secretstr_to_cleartext() -> None:
    """At the SDK boundary cleartext is required so the spawned subprocess
    actually sees the key. This is the explicit, audited unwrap path."""

    cfg = ClaudeBackendConfig(env={"ANTHROPIC_API_KEY": _RAW_VENDOR_KEY})
    materialised = _build_subprocess_env(cfg.env)
    assert materialised["ANTHROPIC_API_KEY"] == _RAW_VENDOR_KEY


def test_build_subprocess_env_accepts_plain_str_for_unit_tests() -> None:
    """The existing env-policy tests pass plain ``dict[str, str]`` directly;
    the helper must keep tolerating that shape so they continue to pass."""

    materialised = _build_subprocess_env({"ANTHROPIC_API_KEY": _RAW_VENDOR_KEY})
    assert materialised["ANTHROPIC_API_KEY"] == _RAW_VENDOR_KEY
