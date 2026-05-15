# vigor-mcp

Bridges Model Context Protocol (MCP) servers to the VIGOR `ToolBackend`
interface so a configurable VIGOR agent can attach any MCP server as an
ambient tool source for adapters.

Supports stdio (subprocess) and HTTP/SSE transports. Activated via
`AgentConfig.mcp_servers` in `vigor-core`. The official `mcp` Python SDK
is an optional extra:

```bash
pip install vigor-mcp[mcp]
```
