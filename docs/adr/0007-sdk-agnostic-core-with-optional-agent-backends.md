# ADR-0007: Build VIGOR As An SDK-Agnostic Core With Optional Agent Backends

Status: Accepted

Date: 2026-04-26

## Context

VIGOR needs to support downstream projects such as agentic video generation, CAD, photo editing, Blender/3D, UI design, code, and other artifact-generation domains.

Examples alone would fragment schemas, scoring, provenance, and review policies. Hard-coupling VIGOR to a single agent SDK would make the framework less portable and confuse VIGOR's artifact contracts with one runtime's agent concepts.

## Decision

VIGOR is packaged as an **SDK-agnostic core library** with optional agent backends and domain adapters.

Current package family:

```text
vigor-core
vigor-runtime
vigor-backend-strands
vigor-backend-claude-agent-sdk
vigor-adapter-photo
vigor-adapter-video-manim
vigor-adapter-cad
vigor-harness
examples/
```

Future compatibility packages can be added, such as `vigor-adapter-video-aiecf`, once external access and assumptions are verified.

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
| Custom full agent SDK | Unnecessary; VIGOR defines artifact-runtime contracts, not every agent framework feature. |

## Consequences

Positive:

1. VIGOR can be imported as a module by downstream projects.
2. Domain projects share schemas, scoring, provenance, and review logic.
3. Strands and Claude Agent SDK can both be used where they fit.
4. Reference examples remain useful without becoming one-off forks.

Negative:

1. Requires careful interface design.
2. Optional backend feature parity must be managed.
3. Documentation must distinguish VIGOR core concepts from backend-specific concepts.

## Citations

| Source | URL |
| --- | --- |
| Strands Agent-to-Agent docs | https://strandsagents.com/docs/user-guide/concepts/multi-agent/agent-to-agent/index.md |
| Strands TypeScript SDK announcement | https://strandsagents.com/blog/strands-agents-typescript-sdk/index.md |
| Claude Agent SDK docs | https://docs.anthropic.com/en/api/agent-sdk/python |
| Anthropic Building Effective Agents | https://www.anthropic.com/engineering/building-effective-agents |
