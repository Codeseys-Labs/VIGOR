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

## Tests

Unit tests use a stubbed `SessionOpener` and run unconditionally:

```bash
uv run pytest packages/vigor-mcp/tests/test_backend.py
```

`tests/test_integration_real.py` spawns a tiny in-tree FastMCP server
(`tests/_fixtures/echo_mcp_server.py`) as a real subprocess and drives
it through the production stdio transport. It is marked
`requires_mcp` and is auto-skipped when the optional `mcp` SDK is not
installed.

```bash
# Run only the integration suite
uv run pytest packages/vigor-mcp -m requires_mcp

# Skip the integration suite (e.g., minimal CI matrix)
uv run pytest packages/vigor-mcp -m "not requires_mcp"
```
