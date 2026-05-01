"""VIGOR MCP bridge: expose MCP servers as a `vigor-core` `ToolBackend`."""

from vigor_mcp.backend import MCPBackendError, MCPToolBackend

__all__ = ["MCPBackendError", "MCPToolBackend"]

__version__ = "0.1.0"
