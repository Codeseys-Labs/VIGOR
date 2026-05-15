"""Tests for the stdio subprocess env policy in ``vigor_mcp.transports.sdk``.

Covers ADR-0029: the stdio transport must default-deny inheritance and
forward only operator-declared keys plus the documented ``PATH`` pass-through.
The unit tests exercise :func:`_build_stdio_env` directly and the
integration test patches the MCP SDK boundary to capture what is handed to
``StdioServerParameters``.
"""

from __future__ import annotations

import sys
import types
from contextlib import AsyncExitStack
from typing import Any

import pytest
from vigor_core.agent_config import MCPServerSpec
from vigor_mcp.transports.sdk import _DEFAULT_PASS_THROUGH, _build_stdio_env


def test_default_pass_through_is_path_only() -> None:
    """Per ADR-0029 Alt-B, the pass-through list is exactly ``("PATH",)``.

    Adding a key here widens the default contract for every operator and
    requires an ADR amendment, so the test pins the constant rather than
    just checking that ``PATH`` is present.
    """

    assert _DEFAULT_PASS_THROUGH == ("PATH",)


def test_build_stdio_env_drops_unlisted_parent_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Vendor keys present in the parent must not leak into the child."""

    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "tenant-A-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "tenant-A-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "tenant-A-secret")

    env = _build_stdio_env(spec_env=None)

    assert "ANTHROPIC_API_KEY" not in env
    assert "GEMINI_API_KEY" not in env
    assert "OPENAI_API_KEY" not in env


def test_build_stdio_env_passes_path_through(monkeypatch: pytest.MonkeyPatch) -> None:
    """``PATH`` is required for CLI-shim servers (uvx/npx/python -m foo)."""

    monkeypatch.setenv("PATH", "/usr/bin:/bin")

    env = _build_stdio_env(spec_env=None)

    assert env == {"PATH": "/usr/bin:/bin"}


def test_build_stdio_env_omits_path_when_parent_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the parent has no ``PATH``, the result must not invent one.

    Inventing an empty string would be worse than absent — the child would
    see ``PATH=""`` and silently fail to resolve any binary.
    """

    monkeypatch.delenv("PATH", raising=False)

    env = _build_stdio_env(spec_env=None)

    assert env == {}


def test_build_stdio_env_forwards_operator_declared_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keys named in ``spec.env`` are copied verbatim, exactly as declared."""

    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leak")

    env = _build_stdio_env(spec_env={"GEMINI_API_KEY": "explicit-value"})

    assert env["GEMINI_API_KEY"] == "explicit-value"
    assert env["PATH"] == "/usr/bin"
    assert "ANTHROPIC_API_KEY" not in env


def test_build_stdio_env_spec_overrides_parent_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator can pin ``PATH`` explicitly; the parent value must not win."""

    monkeypatch.setenv("PATH", "/host/bin")

    env = _build_stdio_env(spec_env={"PATH": "/sandbox/bin"})

    assert env["PATH"] == "/sandbox/bin"


def test_build_stdio_env_returns_independent_dict() -> None:
    """The returned dict must not alias the input, so callers can mutate freely."""

    spec_env = {"GEMINI_API_KEY": "k"}
    env = _build_stdio_env(spec_env=spec_env)

    env["GEMINI_API_KEY"] = "tampered"
    assert spec_env["GEMINI_API_KEY"] == "k"


@pytest.mark.asyncio
async def test_open_session_passes_explicit_env_to_stdio_params(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capture what ``open_session`` actually forwards to ``StdioServerParameters``.

    This is the regression bar: a future refactor that lets ``env=None``
    leak back into the call site re-opens the inherit-all default. The
    test pins the SDK boundary by stubbing ``mcp`` with a fake module
    whose ``StdioServerParameters`` records its kwargs.
    """

    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leak")

    captured: dict[str, Any] = {}

    class _FakeStdioServerParameters:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    class _FakeClientSession:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeClientSession:
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        async def initialize(self) -> None:
            return None

    class _FakeStdioCtx:
        async def __aenter__(self) -> tuple[object, object]:
            return (object(), object())

        async def __aexit__(self, *_: Any) -> None:
            return None

    def _fake_stdio_client(_params: Any) -> _FakeStdioCtx:
        return _FakeStdioCtx()

    fake_mcp = types.ModuleType("mcp")
    fake_mcp.StdioServerParameters = _FakeStdioServerParameters  # type: ignore[attr-defined]
    fake_mcp.ClientSession = _FakeClientSession  # type: ignore[attr-defined]
    fake_mcp.stdio_client = _fake_stdio_client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)

    from vigor_mcp.transports.sdk import open_session

    spec = MCPServerSpec(
        server_id="alpha",
        transport="stdio",
        command=["uvx", "some-mcp-server"],
        env={"GEMINI_API_KEY": "explicit"},
    )

    async with AsyncExitStack() as stack:
        await open_session(spec, stack)

    assert captured["command"] == "uvx"
    assert captured["args"] == ["some-mcp-server"]

    forwarded_env = captured["env"]
    assert forwarded_env is not None, "env must never be None — that re-enables inherit-all"
    assert forwarded_env["GEMINI_API_KEY"] == "explicit"
    assert forwarded_env["PATH"] == "/usr/bin"
    assert "ANTHROPIC_API_KEY" not in forwarded_env


@pytest.mark.asyncio
async def test_open_session_passes_explicit_env_when_spec_env_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even with ``spec.env={}`` the SDK boundary must receive a concrete dict.

    This is the specific regression of the prior bug: empty ``spec.env``
    fell to the ``else None`` branch and unlocked inherit-all in the SDK.
    """

    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-leak")

    captured: dict[str, Any] = {}

    class _FakeStdioServerParameters:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    class _FakeClientSession:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        async def __aenter__(self) -> _FakeClientSession:
            return self

        async def __aexit__(self, *_: Any) -> None:
            return None

        async def initialize(self) -> None:
            return None

    class _FakeStdioCtx:
        async def __aenter__(self) -> tuple[object, object]:
            return (object(), object())

        async def __aexit__(self, *_: Any) -> None:
            return None

    fake_mcp = types.ModuleType("mcp")
    fake_mcp.StdioServerParameters = _FakeStdioServerParameters  # type: ignore[attr-defined]
    fake_mcp.ClientSession = _FakeClientSession  # type: ignore[attr-defined]
    fake_mcp.stdio_client = lambda _p: _FakeStdioCtx()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)

    from vigor_mcp.transports.sdk import open_session

    spec = MCPServerSpec(
        server_id="alpha",
        transport="stdio",
        command=["uvx", "some-mcp-server"],
        # env left at its default (empty dict).
    )

    async with AsyncExitStack() as stack:
        await open_session(spec, stack)

    forwarded_env = captured["env"]
    assert forwarded_env is not None
    assert forwarded_env == {"PATH": "/usr/bin"}
