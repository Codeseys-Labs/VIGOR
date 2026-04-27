# ADR-0007: Build VIGOR As An SDK-Agnostic Core With Optional Agent Backends

Status: Accepted

Date: 2026-04-26

## Context

VIGOR needs to support downstream projects such as agentic video generation, CAD, photo editing, Blender/3D, UI design, code, and other artifact-generation domains.

There are two tempting but incomplete implementation paths:

1. Keep VIGOR as a set of example projects such as `agentic-blender`, `agentic-cad`, and `agentic-photo-editing`.
2. Build VIGOR directly on one agent framework such as Strands Agents or the Claude Agent SDK.

Examples alone would fragment the architecture and duplicate schemas, scoring, provenance, and review policies. Hard-coupling to one agent SDK would make VIGOR less portable and would confuse VIGOR's artifact contracts with one framework's agent runtime concepts.

Strands and Claude Agent SDK are both useful. Strands provides multi-provider agents, tool schemas, MCP integration, graph/swarm multi-agent patterns, session persistence, observability, and A2A support. Claude Agent SDK provides Claude Code-powered custom agents with tool access, MCP integration, permissions, hooks, checkpointing, cost/usage tracking, OpenTelemetry, and deployment guidance.

## Decision

VIGOR will be packaged as an **SDK-agnostic core library** with optional agent backends and domain adapters.

The package family should be:

```text
vigor-core
vigor-runtime
vigor-backend-strands
vigor-backend-claude-agent-sdk
vigor-adapter-photo
vigor-adapter-video-aiecf
vigor-adapter-cad
examples/
```

The VIGOR core owns:

1. Runtime schemas.
2. Adapter contracts.
3. Review report contracts.
4. Scoring and adjudication.
5. Run archives and provenance.
6. Frontier selection.
7. Budget and stop-condition policy.

Agent backends own:

1. Model calls.
2. Agent sessions.
3. Tool invocation mechanisms.
4. Framework-specific hooks, permissions, streaming, and observability integrations.

Domain adapters own:

1. Domain IRs.
2. Compilers/renderers/simulators.
3. Domain reviewers.
4. Export formats.
5. Domain-specific patch operations.

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| Examples only | Fast, but loses reusable VIGOR architecture and causes duplicated scoring/provenance logic. |
| Monolithic all-in-one VIGOR package | Creates dependency sprawl across video, CAD, photo, browser, and model tooling. |
| Strands-only implementation | Strong general backend, but would lock VIGOR to Strands runtime concepts. |
| Claude Agent SDK-only implementation | Strong Claude-native backend, but would lock VIGOR to Claude Code concepts and model/provider choices. |
| Custom full agent SDK | Unnecessary; VIGOR should define artifact-runtime contracts, not recreate every agent framework feature. |

## Consequences

Positive:

1. VIGOR can be imported as a module by downstream projects.
2. Domain projects can share schemas, scoring, provenance, and review logic.
3. Strands and Claude Agent SDK can both be used where they fit.
4. New backends can be added without changing adapters.
5. Reference examples remain useful without becoming one-off forks.

Negative:

1. Requires more careful interface design upfront.
2. Optional backend feature parity must be managed.
3. Documentation must distinguish VIGOR core concepts from backend-specific concepts.

## Implementation Notes

First implementation sequence:

1. Build `vigor-core` with pure schemas, archive, scoring, and adapter interfaces.
2. Build a minimal `vigor-runtime` that can run a toy adapter without any external agent SDK.
3. Build `vigor-backend-strands` as the first general backend.
4. Build `vigor-backend-claude-agent-sdk` for coding-heavy and Claude-native workflows.
5. Build `vigor-adapter-photo` and `vigor-adapter-video-aiecf` as first real adapters.
6. Keep `agentic-photo-editing`, `agentic-video`, and `agentic-cad` as examples powered by shared packages.

The core interface should be small:

```python
class AgentBackend:
    async def generate(self, request): ...
    async def review(self, request): ...
    async def patch(self, request): ...

class ToolBackend:
    async def call_tool(self, tool_id: str, payload: dict): ...
    def list_tools(self): ...
```

## Citations

| Source | URL |
| --- | --- |
| Strands Agent-to-Agent docs | https://strandsagents.com/docs/user-guide/concepts/multi-agent/agent-to-agent/index.md |
| Strands TypeScript SDK announcement | https://strandsagents.com/blog/strands-agents-typescript-sdk/index.md |
| Claude Code overview / Agent SDK docs | https://docs.anthropic.com/en/docs/claude-code |
| Claude Agent SDK MCP docs | https://console.anthropic.com/docs/en/agent-sdk/mcp |
| Anthropic Building Effective Agents | https://www.anthropic.com/engineering/building-effective-agents |
