"""Tests for the subprocess env policy in :mod:`vigor_backend_claude_agent_sdk`.

Mirrors :mod:`vigor_mcp.tests.test_transport_env`: the Claude Agent SDK
backend has the same env-passing surface as the MCP stdio transport, so
the same default-deny posture (ADR-0029) applies. These tests exercise
:func:`_build_subprocess_env` directly without spawning the SDK.
"""

from __future__ import annotations

import pytest
from vigor_backend_claude_agent_sdk.backend import (
    _DEFAULT_PASS_THROUGH,
    _build_subprocess_env,
)


def test_default_pass_through_is_path_only() -> None:
    """Mirrors the MCP transport's invariant: PATH only, by ADR amendment otherwise."""

    assert _DEFAULT_PASS_THROUGH == ("PATH",)


def test_build_subprocess_env_drops_unlisted_parent_vars(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "tenant-A-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "tenant-A-secret")

    env = _build_subprocess_env(spec_env={})

    assert "ANTHROPIC_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env


def test_build_subprocess_env_passes_path_through(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    env = _build_subprocess_env(spec_env={})

    assert env == {"PATH": "/usr/bin:/bin"}


def test_build_subprocess_env_omits_path_when_parent_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty parent ``PATH`` must produce an empty dict, not ``PATH=""``."""

    monkeypatch.delenv("PATH", raising=False)

    env = _build_subprocess_env(spec_env={})

    assert env == {}


def test_build_subprocess_env_forwards_operator_declared_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leak")

    env = _build_subprocess_env(
        spec_env={"ANTHROPIC_API_KEY": "explicit-key", "PYTHONUNBUFFERED": "1"}
    )

    assert env["ANTHROPIC_API_KEY"] == "explicit-key"
    assert env["PYTHONUNBUFFERED"] == "1"
    assert env["PATH"] == "/usr/bin"


def test_build_subprocess_env_spec_overrides_parent_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "/host/bin")

    env = _build_subprocess_env(spec_env={"PATH": "/sandbox/bin"})

    assert env["PATH"] == "/sandbox/bin"


def test_build_subprocess_env_returns_independent_dict() -> None:
    spec_env = {"ANTHROPIC_API_KEY": "k"}
    env = _build_subprocess_env(spec_env=spec_env)

    env["ANTHROPIC_API_KEY"] = "tampered"
    assert spec_env["ANTHROPIC_API_KEY"] == "k"
