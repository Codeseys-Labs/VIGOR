# vigor-backend-strands

Thin VIGOR `AgentBackend` adapter built on the [Strands Agents Python SDK](https://strandsagents.com/).

Strands is an optional dependency. Install with:

```bash
uv add 'vigor-backend-strands[strands]'
# or with a provider extra
uv add 'vigor-backend-strands[anthropic]'
```

If `strands-agents` is not installed, importing `StrandsAgentBackend` raises a helpful `ImportError`. This keeps `vigor-core` and `vigor-runtime` usable without the Strands dependency.
