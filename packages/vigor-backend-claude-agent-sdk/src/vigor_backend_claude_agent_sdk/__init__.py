"""Claude Agent SDK-based VIGOR agent backend (optional dependency)."""

from vigor_backend_claude_agent_sdk.backend import (
    ClaudeAgentBackend,
    ClaudeBackendConfig,
)

__all__ = ["ClaudeAgentBackend", "ClaudeBackendConfig"]
__version__ = "0.1.0"
