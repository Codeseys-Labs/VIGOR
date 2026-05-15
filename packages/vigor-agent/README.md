# vigor-agent

Configurable VIGOR agent. Loads `AgentConfig` (YAML/JSON), instantiates the
declared adapters and backend, attaches optional MCP servers as a
`ToolBackend`, routes incoming `TaskSpec`s to the right adapter, and
delegates each run to the existing `vigor-runtime` orchestrator.

```bash
vigor-agent run --config agent.yaml task.json
```

The CLI is intentionally thin. The same `AgentOrchestrator` class is the
public Python API.
