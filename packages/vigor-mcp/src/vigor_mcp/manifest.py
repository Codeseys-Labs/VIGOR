"""Mapping helpers between MCP tool descriptors and `ToolManifest`."""

from __future__ import annotations

from typing import Any, Literal

from vigor_core.schemas import ToolManifest

DEFAULT_CAPABILITY: Literal["observe"] = "observe"


def mcp_tool_to_manifest(server_id: str, tool: dict[str, Any]) -> ToolManifest:
    """Map an MCP ``tool`` descriptor (name/description/inputSchema/...) to `ToolManifest`.

    The MCP tool name is namespaced by ``server_id`` to keep ids unique
    across multiple attached servers.
    """

    name = tool.get("name") or "unnamed"
    tool_id = f"mcp.{server_id}.{name}"
    description = tool.get("description")
    annotations = tool.get("annotations") or {}
    mutability: Literal["observer", "mutator"] = (
        "mutator" if annotations.get("destructiveHint") else "observer"
    )
    return ToolManifest(
        tool_id=tool_id,
        capability=DEFAULT_CAPABILITY,
        mutability=mutability,
        description=description,
    )
