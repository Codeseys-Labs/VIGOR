<!-- written-by: builder-deployment-adrs-backlog -->
# Deployment & Hardening Backlog

**Source:** VIGOR-a29a (parent VIGOR-c1ab — deployment strategy v2 deep-dive)
**Authored:** 2026-05-15
**Status:** Initial backlog created. Items below are open Seeds issues; sd ready will surface unblocked work.

This is the single point of reference for the follow-on implementation work
falling out of the deployment strategy deep-dive. The seeds below are the
prioritized backlog; the ADRs they reference are draft proposals (Status:
Proposed) pending coordinator review on the same merge cycle as this file.

## Summary table

| Seed ID | Priority | Title | ADR / scout reference |
| --- | :---: | --- | --- |
| [VIGOR-344f](#vigor-344f) | P0 | Implement Budgets.max_cost_usd enforcement (RunBudgetTracker + AgentBackend.usage + StopReason='cost_exceeded') | ADR-0028; scout §3 / rec #1 |
| [VIGOR-6468](#vigor-6468) | P0 | Harden MCP stdio subprocess env (drop-all default unless spec.env lists vars) | ADR-0029; scout §2 + §5 / rec #4 |
| [VIGOR-b38b](#vigor-b38b) | P0 | Wire ToolManifest.mutability into MCPToolBackend.call_tool capability check | ADR-0016 §3.2; scout §4 / rec #3 |
| [VIGOR-2585](#vigor-2585) | P1 | Implement Budgets.max_tool_retries retry loop in MCPToolBackend.call_tool | scout §1 / rec #2 |
| [VIGOR-a171](#vigor-a171) | P1 | Add audit_event.v1 schema + write site at MCPToolBackend.call_tool boundary | scout §6 + ext §E / rec #6 |
| [VIGOR-dfbd](#vigor-dfbd) | P1 | Adopt pydantic SecretStr for AgentConfig.headers / spec.env / vendor keys | scout §2 / rec #6 |
| [VIGOR-b2fc](#vigor-b2fc) | P2 | Add Dockerfile (multi-stage uv build) for vigor-agent CPU orchestrator | ADR-0030; ext §A / rec #7 |
| [VIGOR-4e62](#vigor-4e62) | P2 | Add Dockerfile.gpu for vigor-mcp reviewer (VideoScore2 14GB VRAM) | ADR-0016; ext §A / rec #7 |
| [VIGOR-26b6](#vigor-26b6) | P2 | Lift ResourceWarning suppression in vigor-mcp tests (subprocess leak detection) | scout §1 fn / rec #8 |
| [VIGOR-6ce6](#vigor-6ce6) | P3 | Archive or correct stale mulch record mx-560586 | scout finding #10 |

**Priority breakdown:** 3× P0, 3× P1, 3× P2, 1× P3 (10 total).

## Why P0 vs P1 vs P2

- **P0 — paper-budget / leak surfaces.** Three documented commitments
  (`max_cost_usd`, MCP env hygiene, mutator capability) currently fail open.
  Each is a foundational gap; the deployment-strategy deep-dive cannot
  recommend hosted multi-tenant readiness while any of the three remain
  unwired. ADR-0028, ADR-0029, and ADR-0016 §3.2 are the corresponding
  written commitments.
- **P1 — known-shape work that reduces operator friction.** Retry loop,
  audit log, and SecretStr adoption are well-specified, well-anchored, and
  unblock downstream operators / threat-model work. Each has clean,
  bounded scope.
- **P2 — operator-facing infrastructure.** Docker images and test-harness
  cleanups. Library-first per ADR-0030: VIGOR ships these as
  *convenience*, not as the supported deployment mode.
- **P3 — hygiene / mulch.** One stale record correction.

## What is intentionally NOT in the backlog

- **`packages/vigor-server` HTTP wrapper.** Per ADR-0030, hosted hosting is
  an explicitly deferred downstream concern. A skeleton "experimental"
  service is the worst of both worlds (per ADR-0030 Alt-A). If a future
  ADR supersedes ADR-0030 to commit to a hosted service, that ADR will
  open the corresponding Seeds work.
- **Container sandbox per task** (Docker / nsjail / Firecracker per MCP
  server). Per ADR-0029 Alt-A and `docs/readiness/implementation-readiness.md`
  row C10, this remains future hardening — out of repo scope today.
- **Per-tenant authentication, OAuth2 / OIDC.** Depends on a hosted entry
  point that does not exist (ADR-0030). Threat-model surface only.
- **Path sandboxing at the MCPToolBackend boundary.** ADR-0016 §5
  mandates archive-root containment for MCP server inputs but the runtime
  enforcement at the `MCPToolBackend.call_tool` boundary is not yet
  filed as a Seeds issue. May be picked up under VIGOR-29d8 (the open
  ADR-0017 host-gating task) or filed as a follow-up after that lands.

## Seed details

### VIGOR-344f

**P0 — Cost ceiling enforcement.** Wires `Budgets.max_cost_usd` from paper
to enforced. Adds `AgentBackend.usage()` to the ABC, a `RunBudgetTracker`
checked at the orchestrator iteration boundary, and a new
`StopReason="cost_exceeded"` literal. Per ADR-0028. Anchors:
`packages/vigor-core/src/vigor_core/schemas.py:51-58`,
`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:116-118`,
`packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:92-95`.

### VIGOR-6468

**P0 — MCP stdio env hardening.** Default-drop subprocess environment in
`packages/vigor-mcp/src/vigor_mcp/transports/sdk.py:42-44`; only `PATH`
passes through unless explicitly listed in `spec.env`. Breaking
default-change for any spec relying on inherit-all. Per ADR-0029.

### VIGOR-b38b

**P0 — Mutator capability enforcement.** `ToolManifest.mutability` is on the
schema (`packages/vigor-core/src/vigor_core/schemas.py:80`) but unenforced.
Add `RunContext.tool_capabilities: frozenset[str]`; reject mutator calls
without orchestrator-issued capability. Closes ADR-0016 §3.2's gap.

### VIGOR-2585

**P1 — Retry loop.** Wire `Budgets.max_tool_retries` and `retryable=True`
into a real exponential-backoff retry loop in `MCPToolBackend.call_tool`.
Today these fields are populated but consumed only by `_reviewer_error_report`
at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:545`. From
scout recommendation #2.

### VIGOR-a171

**P1 — Audit event schema.** New `vigor.audit_event.v1` schema sibling to
`vigor.provenance.v1`, capturing tool calls, tenant ID (per ADR-0029),
hash chain. Write at every adapter / backend / `MCPToolBackend.call_tool`
boundary. From scout finding §6 + external survey §E.

### VIGOR-dfbd

**P1 — SecretStr redaction.** Wrap `MCPServerSpec.env` /
`MCPServerSpec.headers` / `ClaudeBackendConfig.env` / vendor key fields in
pydantic `SecretStr`. Verify `model_dump_json` output never contains
raw secrets. Composes with VIGOR-6468 (env hardening) and VIGOR-a171
(audit log).

### VIGOR-b2fc

**P2 — CPU Dockerfile.** Multi-stage uv build for the orchestrator process.
Per ADR-0030, optional operator infra, not a hosted service.

### VIGOR-4e62

**P2 — GPU Dockerfile.** `Dockerfile.gpu` for the VideoScore2 reviewer
wrap (`packages/vigor-tool-mcp-videoscore2`). Pairs with VIGOR-b2fc as
the two-image deployment pattern from ADR-0016 + external survey §A.

### VIGOR-26b6

**P2 — Resource warning suppression.** Lift `pyproject.toml:51-52`
suppression for the `vigor-mcp` test package; surface and fix any
real subprocess leaks revealed.

### VIGOR-6ce6

**P3 — Mulch hygiene.** Archive or supersede stale `mx-560586` record
(claims `ToolBackend` lacks `aclose()`; no longer true per
`packages/vigor-core/src/vigor_core/interfaces.py:152-159`).

## Cross-document anchors

- **ADRs (this branch):** `docs/adr/0028-cost-ceiling-enforcement.md`,
  `docs/adr/0029-multi-tenant-subprocess-env-hardening.md`,
  `docs/adr/0030-library-first-deployment-posture.md`.
- **ADRs (sibling branches, referenced):** `docs/adr/0014-generalized-agent-config.md`,
  `docs/adr/0016-official-mcp-servers.md`, `docs/adr/0017-pure-mcp-plugin-support.md`.
- **Scout survey:** `.overstory/specs/VIGOR-4293.md`.
- **Implementation readiness:** `docs/readiness/implementation-readiness.md`.
