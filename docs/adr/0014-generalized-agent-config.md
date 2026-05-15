# ADR-0014: Generalized Agent Configuration

Status: Accepted

Date: 2026-05-01

## Context

VIGOR ships per-modality adapter packages and the `Orchestrator` is
hardwired to a single `DomainAdapter` and a single `AgentBackend` per
run. Each new use-case has therefore required either a new adapter
package or a custom Python wiring script. There is no MCP integration,
no declarative way to attach external tool servers, and no way to ship
"one VIGOR agent" that handles multiple modalities through configuration.

ADR-0003 separates adapters from orchestration. ADR-0007 keeps the core
SDK-agnostic with optional backends. ADR-0011 gives every IR a versioned
schema. None of these ADRs answer how a deployed VIGOR agent should be
**configured** to compose adapters, MCPs, and a backend at runtime.

## Decision

VIGOR adds a declarative `AgentConfig` schema (`vigor.agent_config.v1`)
and a thin `vigor-agent` package that consumes it.

`AgentConfig` (in `vigor-core`) declares:

1. `adapters` — one or more `AdapterSpec`s (factory ref + modalities/domains).
2. `backend` — one `BackendSpec` (factory ref) used per run.
3. `mcp_servers` — zero or more `MCPServerSpec`s exposed to adapters as a
   shared `ToolBackend` via `RunContext.tools`.
4. `routing` — a `RoutingPolicy` (`modality_match` / `domain_match` /
   `explicit` / `single`) that resolves `TaskSpec` to one adapter.
5. `budgets`, `archive_dir`, and identifiers.

`vigor-agent` provides:

1. `load_agent_config(path)` for YAML / JSON.
2. `AdapterRegistry.from_config(cfg)` — eager factory resolution under
   the `allowed_prefixes` namespace assertion + dotted-component prefix
   match (typosquat-resistant; the host config also gates plugin-supplied
   prefixes via `allowed_plugin_factory_prefixes`).
3. `Router(policy, registry).resolve(task)`.
4. `AgentOrchestrator(cfg)` — constructs a single agent that, per run,
   picks an adapter and instantiates a fresh backend, delegating to the
   existing `vigor-runtime` `Orchestrator`.
5. `vigor-agent run --config x.yaml task.json` CLI.

The runtime `Orchestrator.run` body is unchanged. The only additive core
change is an optional `tools: ToolBackend | None = None` field on
`RunContext` (see ADR-0010). Existing photo/cad/video adapters work
unmodified.

MCP integration ships as a separate optional package `vigor-mcp` whose
`MCPToolBackend` implements the existing `ToolBackend` interface and is
attached by `AgentOrchestrator` only when `mcp_servers` is non-empty.

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| Pivot to a host-agent runtime (Claude Agent SDK / Strands / Hermes / PI) and ship adapters as plugins | Loses VIGOR's verifiable iterative loop — the orchestrator IS the value-add. We instead make adapters Open-Plugin-Spec-compliant (see ADR-0015) so they ALSO work as plugins, without giving up the loop. |
| Extend `vigor-runtime` directly with config + router + MCP | Mixes the loop engine with config/wiring concerns; existing per-concern packaging (ADR-0007) is cleaner. |
| Make the `Orchestrator` itself accept a list of adapters | Breaks the constructor contract used by `vigor-harness/src/vigor_harness/evaluator.py`; per-task router-then-construct preserves backward compatibility. |
| Put MCP tools into `AdapterManifest.tools` | `ToolManifest.capability` is a tight `Literal` enum (`schemas.py:77`); arbitrary MCP tools either pollute the schema or require lossy mapping. |
| Cross-modal task composition (one task → multiple adapters) | Deferred. v1 routes one task to one adapter; the schema reserves `RoutingPolicy.strategy` for future composition. |

## Consequences

Positive:

1. One configurable VIGOR agent now serves any combination of declared
   adapters and MCP servers without forking the runtime.
2. Existing adapters keep working unchanged (zero breaking changes).
3. MCP integration is opt-in via the `[mcp]` extra; users who don't
   need it pay no dependency cost.
4. `AgentOrchestrator` is a thin shell, so the iterative loop, archive,
   provenance, and scoring policies are still owned in one place.

Negative:

1. New users have one more abstraction (the config) to learn before they
   can run a multi-modality agent.
2. The factory allowlist is required per adapter and backend; misconfig
   surfaces at agent construction, which is louder but stricter than
   discovery-by-failure.
3. Routing ambiguity (a task that matches multiple adapters) errors at
   resolve time rather than picking a default, which is intentional.

## Citations

| Source | URL |
| --- | --- |
| Anthropic Agent SDK plugins | https://docs.claude.com/en/docs/agent-sdk/plugins |
| MCP Python SDK | https://github.com/modelcontextprotocol/python-sdk |
| ADR-0003 | docs/adr/0003-separate-adapters-from-orchestration.md |
| ADR-0007 | docs/adr/0007-sdk-agnostic-core-with-optional-agent-backends.md |
| ADR-0010 | docs/adr/0010-async-core-interfaces.md |
