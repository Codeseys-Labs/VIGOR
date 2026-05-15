# Deployment And Operational Posture For VIGOR

Status: Draft for review
Date: 2026-05-15
Audience: VIGOR architecture lead, ops/security reviewers, downstream integrators evaluating a hosted VIGOR
Parent task: VIGOR-c1ab (strategic deep-dive on deployment and operational posture)
Companion deliverables (sibling builders): threat model (`docs/security/threat-model.md`), companion ADR drafts on deployment posture, multi-tenant isolation, and cost-ceiling enforcement, and a prioritized seeds backlog.

---

## Executive Summary

VIGOR's deployment story today is **library + CLI**: `vigor-agent run --config agent.yaml task.json` is the only documented entry point. There is no `vigor-server`, no Dockerfile, no audit-log schema, no rate-limit primitive, and no enforced cost ceiling. The hardening shipped to date concentrates on three axes — factory-namespace allowlists (ADR-0014, ADR-0017), MCP transport posture and tool allowlists (ADR-0016), and path containment — but several declared budgets are *paper budgets* (present in the schema, never read by the runtime), and several error-handling fields are *dead metadata* (populated, never consumed).

The strategic posture this document recommends is: **(1)** stay library-first, ship a thin opt-in `vigor-server` rather than embedding HTTP into the orchestrator; **(2)** commit to a **two-image deployment shape** (CPU orchestrator + GPU reviewer over MCP http/sse); **(3)** close the named implementation gaps — cost ceilings, retry loop, mutator-capability enforcement, subprocess env containment, audit log, container build — in a deliberate order, with cost ceilings as the foundational first move. Threat modeling and ADR drafts are sibling deliverables; this document is the synthesis they hang off, framing every recommendation as strategic posture rather than implementation plan and deferring code shapes, Dockerfile contents, and runbooks to the companion ADRs and the seeds backlog.

---

## Current Deployment Surface

This section synthesizes §1–§7 of the VIGOR-4293 internal survey (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py`, `packages/vigor-mcp/src/vigor_mcp/backend.py`, `packages/vigor-core/src/vigor_core/{schemas.py,agent_config.py,interfaces.py}`). All `path:line` citations are anchored against the 2026-05-15 cutoff commit.

### Failure Boundary

The single load-bearing failure boundary is `packages/vigor-runtime/src/vigor_runtime/orchestrator.py`. Within one run loop, the failure shape is well-typed at every adapter and backend seam:

- **Adapter `compile` raising `VigorError`** is wrapped in `_safe_compile` (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:391`) into `CompileResult(status="failure", errors=[err])`; the iteration continues so other candidates can still proceed.
- **Adapter `export` raising `VigorError`** is logged into the run archive by `_safe_export` (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:413`); the run finishes with `stop_reason="failed"`.
- **Adapter `review` raising `VigorError`** is coerced inside `_run_reviewers.adapter_reviews` (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:451`) to a single fail-shaped `ReviewReport` so adjudication can still run.
- **Backend `review` raising `VigorError`** receives the same coercion in `_run_reviewers.backend_review` (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:475`).
- **Top-level `VigorError`** at the run-loop scope is caught at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:188`, recording a `fatal_error` and setting `stop_reason="failed"`.
- **Generic `Exception`** at the run-loop scope is caught at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:202`, with the same shape but `kind="generic"`.
- **Patch produced an invalid IR** is detected inline at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:170` and is a hard fail; the run aborts.
- **Wall-clock budget exhaustion** is checked once per iteration at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:116`; the loop breaks with `stop_reason="budget_exhausted"`.
- **MCP `call_tool` timeout** is enforced inside `MCPToolBackend.call_tool` at `packages/vigor-mcp/src/vigor_mcp/backend.py:144`; the handle is torn down (`packages/vigor-mcp/src/vigor_mcp/backend.py:148`) so the next call opens a fresh session, and a `ToolResult(status="timeout")` is returned. The call does **not** raise.
- **MCP transport boot failure** in `_ServerHandle.ensure_open` (`packages/vigor-mcp/src/vigor_mcp/backend.py:58`) rolls back the partially-entered `AsyncExitStack` to avoid leaking subprocesses or sockets and re-raises.
- **MCP non-timeout call exceptions** (`MCPBackendError | RuntimeError | OSError`) are caught at `packages/vigor-mcp/src/vigor_mcp/backend.py:155` and converted to `ToolResult(status="failure")`. Other exceptions propagate.

The surface is **structured but skeletal**. Three gaps are named in the scout report:

- **`retryable` is dead metadata.** `VigorError.retryable`, `RuntimeErrorRecord.retryable`, `Budgets.max_tool_retries=2`, and `ToolManifest.retry_policy: dict` all exist but are never read by the runtime to drive a retry loop. The single consumer is `_reviewer_error_report` (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:545`) which uses it to choose `recommended_action = "patch" if retryable else "fail"`. There is no retry loop or backoff anywhere in the codebase.
- **No rate limit, no circuit breaker.** Per-MCP-server, per-adapter, and per-task throttling are all absent. Nothing tracks recent failures or paces calls.
- **No cancellation primitive beyond `asyncio.wait_for`.** Run-level cancellation is best-effort. A Ctrl-C while patch-loop is running leaks any in-flight MCP subprocess unless the caller wraps `agent.aclose()` in a `finally`. The CLI does this; a hosted entry point would need to too.

A fourth observation: `pyproject.toml:51` suppresses `ResourceWarning` repo-wide. Subprocess-leak detection in tests is muted by configuration, which means a hosted deployment that leaks subprocesses cannot be caught by the existing test suite as a leading indicator.

### Secrets Surface

VIGOR has no first-class secrets handling. The full surface area:

- **MCP stdio subprocess env** flows from `MCPServerSpec.env: dict[str, str]` into `StdioServerParameters(env=...)` at `packages/vigor-mcp/src/vigor_mcp/transports/sdk.py:42`. Plain dict, passed verbatim.
- **MCP http/sse headers** flow from `MCPServerSpec.headers: dict[str, str]` into `sse_client(headers=...)` and `streamablehttp_client(headers=...)` at `packages/vigor-mcp/src/vigor_mcp/transports/sdk.py:54` and `packages/vigor-mcp/src/vigor_mcp/transports/sdk.py:65`. The schema validator (`packages/vigor-core/src/vigor_core/agent_config.py:71`) forbids `env` on http/sse and forbids `headers` on stdio — the right shape, but not redaction.
- **Claude Agent SDK env** flows from `ClaudeBackendConfig.env: dict[str, str]` into `ClaudeAgentOptions(env=...)` at `packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:80`. Same plain dict, lazy SDK import.
- **Manim renderer env** is the cleanest in the repo: `env={"PATH": os.environ.get("PATH", ""), "PYTHONUNBUFFERED": "1"}` (`packages/vigor-adapter-video-manim/src/vigor_adapter_video_manim/renderer.py:106`). Inherited `PATH` only.
- **ADR-0016 vendor keys** (Anthropic, Gemini, the VideoScore2 wrap, PRC vendors via `luma-mcp`) are required to live in agent env, never on disk in artifacts, with monthly rotation. **Enforcement is policy-only** — no code enforces it.

Four gaps follow from the scout report:

- **No redaction.** `AgentConfig` is loaded from YAML/JSON via `config_loader`. If the agent config is ever serialized — e.g. via `AgentConfig.model_dump_json()` — `headers` and `env` are written verbatim. There is no `SecretStr` wrapping in pydantic.
- **No KMS/Vault hook.** Env-var-only is the only path. Hosted deployments must inject secrets at process boot.
- **No per-server rotation primitive.** ADR-0016's monthly-rotation expectation is a doc commitment, not a runtime hook.
- **Subprocess env inheritance is implicit.** A stdio MCP subprocess receives `spec.env` if set, otherwise `None` — which means inherit-all from the parent. For hosted multi-tenant deployments this is a leak surface: a forgotten `env={}` will leak `AWS_*`, `ANTHROPIC_API_KEY`, and friends into the MCP server process.

### Budgets — Schema vs Enforcement

`Budgets` (`packages/vigor-core/src/vigor_core/schemas.py:51`) declares five fields. **Only three are enforced**:

- `max_iterations` (default 5): enforced at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:114`.
- `max_candidates` (default 4): enforced at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:263`.
- `max_wall_clock_s` (default 1800): enforced at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:116`.
- `max_cost_usd` (default `None`): **not enforced** — no code references it outside the schema definition.
- `max_tool_retries` (default 2): **not enforced** — no code references it outside the schema definition.

Cost telemetry itself is not collected anywhere. There is no `tokens_used`, `usd_spent`, or `tool_calls` counter on `RunResult` or `ProvenanceRecord`. The Claude Agent SDK exposes per-turn token counts in `ResultMessage` (`packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:92`) but VIGOR currently drops them on the floor.

### MCP Transport Posture

ADR-0016 (Proposed, 2026-05-15) is the policy doc. The `vigor-mcp` implementation honors most of it:

- **stdio default for local** is honored at config level by `MCPServerSpec.transport: Literal["stdio", "http", "sse"]` (`packages/vigor-core/src/vigor_core/agent_config.py:62`).
- **Tool allowlist (default-deny)** is enforced at the `call_tool` boundary (`packages/vigor-mcp/src/vigor_mcp/backend.py:131`) and the `list_tools` boundary (`packages/vigor-mcp/src/vigor_mcp/backend.py:81`). Default `None` means "allow all" — operators must remember to set the allowlist; the schema does not require it.
- **Mutator capability** is present on the schema (`ToolManifest.mutability: Literal["observer", "mutator"]` at `packages/vigor-core/src/vigor_core/schemas.py:80`) but **not enforced** in `call_tool`. No code rejects a mutator call without an orchestrator-issued capability.
- **Per-server timeout** is enforced via `asyncio.wait_for` (`packages/vigor-mcp/src/vigor_mcp/backend.py:144`); returns `ToolResult(status="timeout")` rather than raising.
- **Timeout-rollback** tears down the half-completed handle (`packages/vigor-mcp/src/vigor_mcp/backend.py:148`) so the next call opens a fresh session.
- **Path sandboxing** for MCP inputs is not enforced at the `MCPToolBackend` boundary; ADR-0016 §5 mandates archive-root containment, but adapters that pass paths to MCP servers are individually responsible.
- **Network isolation** for unauth servers (ADR-0016 §6 mandates loopback-only) is policy-only; no runtime check.
- **Two-layered factory allowlist** is implemented for code factories (`packages/vigor-core/src/vigor_core/agent_config.py:175`), gating Python imports against host-controlled prefixes.
- **Plugin-supplied MCP-server identity allowlist** (the natural ADR-0017 extension) is not yet implemented.

### Multi-Tenant Process Isolation

Today: none beyond `asyncio` task isolation. A single Python process can host multiple `AgentOrchestrator` instances — each owns its own `AdapterRegistry`, `Router`, and `MCPToolBackend` — but the scope of *isolation* this provides is narrow:

- Subprocess MCP servers inherit the parent's `os.environ` if `spec.env` is unset.
- The `vigor_core.factory.load_factory` import path is process-global. Once a factory module is imported for tenant A, tenant B sees the same module instance.
- `RunArchive` paths are namespaced by `run_id` rather than by tenant. Two tenants must use disjoint `archive_dir`s by configuration.
- The Claude Agent SDK backend is created per-task at `packages/vigor-agent/src/vigor_agent/agent.py:84` and `aclose`d after, so backend state is task-scoped, but the SDK's own subprocess pool is not visible to VIGOR and is not bounded per-tenant.

### Audit and Provenance

`ProvenanceRecord` (`packages/vigor-core/src/vigor_core/schemas.py:287`) tracks per-run activities: generation, compile, review, adjudication, patch, export. **It does not track**:

- MCP tool calls (any `ToolBackend.call_tool` invocation).
- Token / cost telemetry.
- Caller identity. No notion of tenant or user.
- PII redaction policy.
- Retention policy.

`RunArchive` writes JSON-per-record to disk under `{archive_dir}/{run_id}/`. There is no rotation, no GDPR-style erasure hook, no hash chain, no signing.

### CI / Build / Deployment Artifacts

`.github/workflows/` ships `ci.yml` and `skill-drift.yml` only. There is no container build, no SBOM, no signing, and no release pipeline. Per `docs/readiness/implementation-readiness.md` row C10: *"container sandbox remains future hardening."*

The `pyproject.toml:51` `ResourceWarning` suppression is the leading-indicator hole: tests cannot detect leaked subprocesses today.

### Surface Summary

The current deployment surface, distilled:

- **What works in production** *as a library*: the iterative loop, the per-iteration wall-clock budget, the best-of-N batch, the MCP allowlist enforcement, the per-server timeout, the timeout-rollback handle teardown, the factory-namespace allowlist, the `_safe_compile` / `_safe_export` error coercion, the `aclose()` cleanup pattern.
- **What is paper-only**: `Budgets.max_cost_usd`, `Budgets.max_tool_retries`, `ToolManifest.mutability="mutator"`, `ToolManifest.retry_policy`, ADR-0016's vendor-key-rotation cadence, ADR-0016 §6 network-isolation policy.
- **What is dead metadata**: `VigorError.retryable`, `RuntimeErrorRecord.retryable` (read by exactly one consumer at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:545`).
- **What does not exist**: cost telemetry, per-server rate limits, audit log, container build, `vigor-server`, multi-tenant isolation primitives, secrets-backend hooks, signed-MCP-server provenance, MCP-server identity allowlist for plugin-supplied servers.

Each line above maps to a question in §"Strategic Recommendations".

---

## 2026 External Posture

This section synthesizes §A–§E of the VIGOR-4293 external survey. Citations follow the scout report's verification cutoff of 2026-05-14; where the scout cited a URL, that URL is preserved here; where the scout summarized a 2026 trend without a single canonical link, this doc preserves the scout's framing rather than fabricating new ones.

### Agent Deployment Topologies

The 2026 consensus across the production-grade agent SDKs (Claude Agent SDK, Strands, Hermes, Goose) is that **process isolation is the unit of trust** for untrusted tool exposure. Anthropic's "Building Effective Agents" guidance still favors subprocess isolation per agent run; the Claude Agent SDK's permission model (`permission_mode`, `allowed_tools`, `disallowed_tools`, `setting_sources=[]`) is the in-process equivalent and is the posture VIGOR already wires at `packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:42`.

Container shape has settled around a minimal Python 3.11/3.12 base, `uv sync --no-dev` at build time, and a separate stage for ML deps when the `[strands]` or `[claude]` extras are needed. ADR-0016 calls out 14 GB VRAM for VideoScore2 — that is **not** packageable in the same image as the orchestrator, which forces a multi-image deployment.

The **two-image pattern** — orchestrator (CPU, slim) plus reviewer (GPU, dedicated) connected over MCP http/sse — is the cleanest match to ADR-0016's transport split, and it is the dominant 2026 shape for hosted reviewer ensembles.

The **MCP gateway pattern** is emerging in 2026: hosts run a fleet of MCP servers behind a single auth+allowlist gateway, the agent connects to the gateway over http, and the gateway fans out to per-server stdio/http connections. This reduces per-agent subprocess proliferation in multi-tenant deployments. VIGOR's `MCPToolBackend.from_specs` is structurally compatible — the agent points at one gateway URL instead of N stdio commands — but VIGOR has not committed to this pattern in any ADR yet.

The Anthropic skill/plugin packaging trend has the **Open Plugin Spec v1** in flux as of 2026-05-04 (the vercel-labs PR #3 is open). VIGOR's ADR-0017 explicitly defers deeper investment until OPS stabilizes; that is a sound bet given the ecosystem evidence.

### Multi-Tenant Isolation Patterns

Four shapes are visible in the 2026 ecosystem:

- **Sub-account separation** (Anthropic Workspaces, Google Cloud-native): one API key per tenant, billed separately. Cleanest. VIGOR's per-tenant secrets posture is a precondition.
- **Subprocess-per-task** (Anthropic computer-use containers, Claude Agent SDK's subprocess model): hard isolation, simpler reasoning, real per-process startup cost.
- **Worktree-per-task** (overstory's own pattern): file-system isolation in addition to process isolation. Useful for adapters that read/write code; heavy for short tasks.
- **Container-per-session** (Devin-class, Claude Code, OpenAI Agents): the 2026 "agent OS" frameworks are standardizing here, accepting the cost in exchange for security posture and recoverability.

The ecosystem trend is toward **container-per-session** rather than `asyncio`-task isolation. The cost is real — process boot, image pull, container lifecycle — but security posture and recoverability are categorical wins.

The cost calculation is worth making explicit. Container-per-session pays roughly:

- *Cold start* — image pull (network bandwidth + registry rate limit) plus container init (kernel + runtime overhead). On a warm node with a cached image, this is sub-second; on a cold node, tens of seconds.
- *Lifecycle overhead* — orchestration plane work (scheduling, network attach, log forwarding setup). Typically 100ms–1s per container.
- *Memory floor* — each container has a baseline RSS that the OS cannot share. For a Python orchestrator image, this is on the order of 100–300 MB.

Container-per-tenant pays these costs once per tenant per *deployment cycle*; container-per-session pays them once per *task*. For VIGOR's iterative loop (typically 5 iterations × 4 candidates × tens of seconds per iteration = a few minutes per task), the container-per-session cost is a 10–30% overhead on the task itself when starting cold. That overhead is acceptable for high-trust isolation but excessive for the v1 threat profile.

The strategic posture commits to container-per-tenant *as the floor* (a misconfiguration cannot drop below this) and names container-per-session *as the ceiling* (a v2 commitment, justified when the threat profile warrants it). The boundary between the two is a deployment-time configuration knob, not a code change.

### Cost Ceilings

The strongest 2026 pattern pull is around **hard caps at the SDK level**:

- The Claude Agent SDK's `ResultMessage` exposes per-turn token counts; Anthropic's Workspace supports usage limits per key.
- Strands SDK uses `LangSmith`-style trace-based cost accounting.
- The common shape is `max_input_tokens`, `max_output_tokens`, `max_tool_calls`, `max_cost_usd`, and `hard_stop_at_threshold: bool`. The agent SDK aborts mid-run on threshold.

VIGOR's loop is structurally compatible: the per-iteration check at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:116` is the existing seam where a `RunBudgetTracker.check()` would slot in.

The 2026 best practice is that ceilings live on the `AgentBackend` (where token counts come from the LLM provider) and are surfaced up to the orchestrator via an event/callback rather than pulled. `AgentBackend.aclose()` already exists in VIGOR's interface (`packages/vigor-core/src/vigor_core/interfaces.py:139`); an analogous `AgentBackend.usage()` returning a structured `Usage(input_tokens, output_tokens, usd)` is the minimal extension.

MCP rate limits in 2026 are typically per-server tokens-per-second, not cost. The `ToolManifest.retry_policy: dict[str, Any]` slot at `packages/vigor-core/src/vigor_core/schemas.py:84` is the natural home for a `{"qps": int, "burst": int}` shape.

### MCP Transport Security

The 2026 transport security consensus is short and dense:

- **stdio default for local** is unanimous across 2026 hosts. ADR-0016 already commits.
- **http/sse for hosted** GPU-resident or stateful servers is the post-2025 default. VideoScore2 is the canonical example.
- **Auth shapes**: `Authorization: Bearer` for vendor APIs, mTLS for inter-VPC, OAuth2 device flow for human-in-loop. ADR-0016 already endorses these.
- **MCP server hardening checklist** (the 2026 minimum): default-deny tool surface, per-tool capability tags (`observer`/`mutator`/`destructive`), timeouts, path sandboxing, network isolation, signed-server provenance. Signed-server provenance is emerging — `mcp-server-signing` was proposed late 2025 — but is not yet standardized.
- **Allowlist-based plugin loading**: VIGOR's two-layer allowlist (host vendoring plus per-`FactoryRef` namespace assertion) is **stronger than the current MCP-host norm**, which usually relies on a single trusted-server list. This is a posture VIGOR should preserve, not relax.

### Audit Logs

The 2026 norm for agent audit logs is structured, append-only, and signed. Per-event JSON with `event_id`, `tenant_id`, `run_id`, `actor`, `tool_id`, `payload_sha256`, `timestamp`, and `prev_event_sha256` (forming a hash chain). Retention is typically 90–365 days hot in a write-optimized store and S3 IA cold thereafter.

PII scrubbing happens at write time: redact known patterns (email, phone, key-shaped tokens) before persist. Pydantic `SecretStr` plus a `redact()` pass on `model_dump_json` is the reference shape.

The single highest-leverage insertion point for **MCP-call audit** is the `MCPToolBackend.call_tool` boundary (`packages/vigor-mcp/src/vigor_mcp/backend.py:122`). Every invocation should be logged with `tool_id`, input digest (not values), output digest, status, and duration.

### Synthesis: Where 2026 Meets VIGOR

Cross-cutting against the internal survey, the 2026 patterns map to VIGOR's existing seams unusually cleanly:

- **Subprocess isolation (Anthropic guidance)** maps to `packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:42` — VIGOR already wires `permission_mode="dontAsk"` and `setting_sources=[]`. No deployment-hardening change needed at the agent-SDK layer.
- **MCP gateway pattern** maps to `MCPToolBackend.from_specs` — the orchestrator points at one URL instead of N stdio commands. No code change required to *adopt* a gateway; the gateway is upstream of `vigor-mcp`.
- **Cost ceilings (SDK-level hard caps)** map to `Budgets.max_cost_usd` — the schema slot already exists; the *check site* is `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:116`. Q5's recommendation is closing the unwired schema, not adding a new one.
- **Default-deny tool surface** is already implemented at `packages/vigor-mcp/src/vigor_mcp/backend.py:131` — the only gap is that the *schema* does not require an allowlist. Operators must remember to set it; that is policy, not implementation.
- **Two-image deployment** maps directly to ADR-0016's transport split. The CPU/GPU boundary is already drawn at the *transport* layer; the *deployment* layer commitment is what this document adds.
- **Hash-chained audit log** is greenfield — no existing code; `ProvenanceRecord` is the per-run summary, not the per-event firehose. Q6's recommendation is the largest net-new shape in the wave.

The pattern is consistent: **most of the 2026 deployment-hardening posture is already half-implemented in VIGOR**. The work is closing the unwired schemas and committing to the implicit deployment shapes, not bolting on net-new infrastructure. That observation is the source of the strategic optimism in §"Executive Summary".

---

## Strategic Recommendations

This section answers the nine deployment questions in VIGOR-c1ab's seed verbatim, in the order they appear there. Each recommendation states the strategic posture, the implementation seam (file/line), and a classification:

- **foundational** — should land in the first deployment-hardening wave; preconditions for hosted multi-tenant use; companion ADR.
- **tactical** — net-new capability that follows once the foundational pieces ship; companion ADR optional.
- **observational** — a smell or finding worth tracking but not necessarily blocking; lands as a seeds task, no ADR.
- **future** — explicit deferral past the deployment-hardening horizon; strategic doc only commits to the deferral itself.

### Q1 — Containerization

**Recommendation.** Ship a multi-stage `uv`-based Dockerfile per the **two-image deployment shape** (see the dedicated section below): a slim CPU orchestrator image and a dedicated GPU reviewer image. Multi-stage builds with `extras` selected at build time (`uv sync --no-dev --extra <name>`); slim runtime base (Python 3.11 distroless or `python:3.11-slim`, no pip in the runtime layer). Reviewer image inherits from a CUDA base only when the `[claude]`+VideoScore2 extras are present.

**Implementation seam.** New `Dockerfile.orchestrator`, `Dockerfile.reviewer`, plus a `.github/workflows/container-build.yml` that builds both on tag push. No changes to `packages/vigor-runtime/` or `packages/vigor-agent/`.

**Classification: foundational.** This is the precondition for every other hosted-deployment recommendation in this section. ADR draft (companion ADR on deployment posture) commits to the two-image shape and the build pipeline.

**Why now.** ADR-0016 already implies two images by mandating http/sse for VideoScore2 and 14 GB VRAM colocation. The strategic posture should make the implication explicit and produce the artifacts.

**Alternatives considered.**
- *Single-image with optional GPU.* Rejected: pulls 14 GB of VRAM-class dependencies into every orchestrator process; precludes sharing GPU across runs; conflicts with ADR-0016's transport split.
- *Per-adapter image (one image per modality).* Rejected: image proliferation, layer-cache fragmentation, and no clean way to share `vigor-core` across them. The two-image split is the smallest deployable shape that respects the GPU/CPU boundary; finer slicing buys nothing.
- *Pre-built community image (e.g. consume an upstream VideoScore2 server image).* Rejected: ADR-0016 §"Definition of official support" requires a pinned version range and CI smoke; consuming a third-party image undermines both. The reviewer image is VIGOR-built per ADR-0016's `vigor-tool-mcp-videoscore2` package commitment.

**Operational implications.** Container build runs on tag push (release) and on PRs that touch `packages/vigor-tool-mcp*`, the orchestrator package set, or the Dockerfiles. CI smoke tests (per ADR-0016's mcp-smoke.yml) gate the reviewer image; the orchestrator image is gated by the existing `ci.yml`. SBOM artifacts and image signatures are emitted as part of the same workflow.

### Q2 — Multi-Tenant Agent Isolation

**Recommendation.** **Two AgentConfigs MUST NOT share a process** in production multi-tenant deployments. The `vigor_core.factory.load_factory` import path is process-global (see "Multi-Tenant Process Isolation" above), and subprocess MCP servers inherit the parent's `os.environ` when `spec.env` is unset. The library-level posture is "best-effort isolation"; the deployment-level posture is **container-per-tenant** as the floor and **container-per-session** as the ceiling. Worktree-per-task isolation is reserved for adapters that read/write code (which VIGOR's adapter layer already does in some configurations).

**Implementation seam.** No code change to the orchestrator. The strategic commitment is at the deployment layer: container image is the unit of tenancy; a pool of orchestrator containers behind a load balancer; one container handles N tasks for one tenant before being recycled.

**Classification: foundational.** Cannot be retrofitted after a multi-tenant deployment is live without an isolation incident. Companion ADR on multi-tenant isolation enumerates the three shapes (sub-account, subprocess-per-task, container-per-session) and commits to container-per-tenant for the v1 hosted path.

**Alternatives considered.**
- *In-process tenancy with stricter import-isolation* (e.g. per-tenant `sys.modules` namespacing). Rejected: defeats CPython's module cache, fights the language rather than working with it, and still leaves `os.environ` global. The cost of being clever exceeds the cost of paying for one container per tenant.
- *Subprocess-per-task without container-per-tenant.* Rejected as the v1 floor: subprocess isolation does not bound network egress, file-system writes outside the worktree, or memory consumption. Containers do.
- *Container-per-session as the v1 floor.* Rejected: real cost (image pull on cold-start, container lifecycle overhead, registry pressure) for a threat profile that does not yet justify it. Named as the v2 ceiling.

**Cross-tenant signals to monitor.** Once container-per-tenant is the floor, the remaining cross-tenant leak surfaces are (a) the GPU reviewer image (shared by design — ADR-0016's transport split), (b) any shared object storage backing `RunArchive`, (c) any shared metrics/log destination. Each must namespace by tenant; the audit-log work in Q6 makes this enforceable rather than aspirational.

### Q3 — Secrets Management For MCP Servers

**Recommendation.** Adopt a layered posture:

1. **Library default stays env-var-only** — the local-CLI use case must not regress.
2. **Subprocess env containment is the breaking change worth making**: change the default in `open_session` so a stdio MCP subprocess receives `env=spec.env or {"PATH": os.environ.get("PATH", "")}` (drop-all-by-default). Document the breaking change. `PATH` is the only environment variable most stdio MCP servers actually need.
3. **Hosted deployments use process-boot injection from a Vault/KMS sidecar**, with rotation hooks that restart the orchestrator container rather than rotating in-place. ADR-0016's "monthly rotation" expectation becomes operational rather than aspirational.
4. **Add `SecretStr` wrapping** on `MCPServerSpec.env`, `MCPServerSpec.headers`, and `ClaudeBackendConfig.env` so `model_dump_json()` redacts by default. Plain `str` fields remain available for rendering only inside the transport layer.

**Implementation seam.**
- `packages/vigor-mcp/src/vigor_mcp/transports/sdk.py:42` — change the env-default for stdio.
- `packages/vigor-core/src/vigor_core/agent_config.py:53` — wrap `env` and `headers` with `SecretStr`.
- `packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:80` — same wrapping.

**Classification: foundational.** The drop-all-by-default change closes a real leak surface and is the single highest-leverage hardening step that does not require a new package.

**Alternatives considered.**
- *Inherit-all-by-default, document the risk.* This is the current behavior. Rejected: documentation-only mitigations of leak surfaces have a poor track record. The breaking change is small, the migration is mechanical (`env={}` becomes the explicit equivalent of today's `env=None`), and the security gain is real.
- *Inherit only an allowlist of "known-safe" env vars.* Rejected: the allowlist would have to be host-defined or hard-coded, and either choice leaks responsibility ambiguously between the host and the spec author. `PATH`-only is the smallest defensible default; anything else is per-server `spec.env` opt-in.
- *Adopt `pydantic-settings` and resolve secrets from a backend at config-load time.* Rejected for v1: introduces a runtime dependency on a secrets backend even for the local CLI use case. The hosted-deployment story (process-boot injection from Vault/KMS sidecar) does not need this — the orchestrator container reads its env at boot, the same as any other 12-factor service.

**Migration path.** The breaking change ships behind a one-version deprecation: in version *N*, `MCPServerSpec` with `env` unset emits a `DeprecationWarning` and behaves as today (inherit-all). In version *N+1*, the default flips to `{"PATH": os.environ.get("PATH", "")}`. The repo-wide `ResourceWarning` filter at `pyproject.toml:51` is lifted for `vigor-mcp` tests as part of the same wave so the change is observable.

### Q4 — Rate Limiting

**Recommendation.** Three levels, only the first two of which are in scope for the deployment-hardening wave:

1. **Per-MCP-server QPS/burst** lives on `ToolManifest.retry_policy: dict[str, Any]` at `packages/vigor-core/src/vigor_core/schemas.py:84` (the existing slot). Schema reserves `{"qps": int, "burst": int}`. Enforcement lives in `MCPToolBackend.call_tool` (`packages/vigor-mcp/src/vigor_mcp/backend.py:122`) as a token-bucket per `server_id`.
2. **Per-adapter request pacing** is a thin extension above (1) — the adapter's `_run_reviewers` invocations share a token bucket per `adapter_id`. Same enforcement pattern.
3. **Per-task budgets** are subsumed by `Budgets.max_iterations` and the cost-ceiling work (Q5). Not a separate primitive.

The `AgentConfig.budgets` schema does not need a new top-level field for rate limits in v1; per-server and per-adapter limits ride on existing `ToolManifest.retry_policy` and adapter-level config.

**Implementation seam.** `packages/vigor-mcp/src/vigor_mcp/backend.py:122` (token-bucket per `server_id`); per-adapter wiring is in `packages/vigor-runtime/src/vigor_runtime/orchestrator.py` around `_run_reviewers`.

**Classification: tactical.** The schema slot exists; the implementation is roughly 80–150 LOC plus tests. Lands after cost ceilings (Q5) because cost ceilings define the abort path that rate-limits also need.

**Alternatives considered.**
- *Add a top-level `RateLimit` field on `AgentConfig`.* Rejected: pollutes the agent-level config with a per-tool concern. The natural locality is `ToolManifest.retry_policy`, which is already per-tool.
- *Use a sidecar (e.g. an MCP gateway, Q-3 in the external survey) to enforce rate limits outside VIGOR.* Endorsed for production deployments but **not** as a substitute for the in-process token bucket. The in-process bucket protects VIGOR's own runtime from runaway adapters; the sidecar protects the upstream MCP server from VIGOR.
- *Adopt a third-party library (`limits`, `aiolimiter`, `pyrate-limiter`).* Endorsed if the chosen library has a small surface and async-first; rejected if it pulls a heavy dep tree. The decision rides with implementation, not strategy.

**Failure shape.** When the bucket is empty, `MCPToolBackend.call_tool` should return `ToolResult(status="rate_limited", error=...)` rather than raise — same shape as the existing timeout return. This requires extending the `ToolResult.status` Literal; the StopReason bump in Q5 is a reasonable wave-mate for the schema migration.

### Q5 — Cost Ceilings

**Recommendation (this is the cheapest high-impact win in the entire deployment-hardening wave).** Wire `Budgets.max_cost_usd` end-to-end. Three small additions:

1. **`AgentBackend.usage()` accessor** returning a structured `Usage(input_tokens, output_tokens, usd)`. Implementations harvest from `claude_agent_sdk.ResultMessage` (currently dropped at `packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:92`) and from the Strands SDK equivalent.
2. **`RunBudgetTracker` on `RunContext`** that accumulates per-call `Usage` deltas. Lives next to the existing wall-clock check.
3. **Iteration-boundary check** at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:116`, mirroring the existing wall-clock check. New `StopReason="cost_exceeded"` literal; `StopReason` is a closed `Literal` at `packages/vigor-core/src/vigor_core/schemas.py:120`, so this is a deliberate schema bump that lands behind a versioned migration.

Per-call (rather than per-iteration) checks are deferred: the LLM cost-per-call dominates and per-iteration granularity is sufficient for v1.

**Implementation seam.**
- `packages/vigor-core/src/vigor_core/interfaces.py:130` (new `usage()` method on `AgentBackend`).
- `packages/vigor-core/src/vigor_core/schemas.py:120` (extend `StopReason`).
- `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:116` (check site).
- `packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:92` (token harvest).

**Classification: foundational.** Approximately 150–300 LOC across the four files. Companion ADR on cost-ceiling enforcement commits to the shape of `Usage`, the placement of the tracker, and the new `StopReason`.

**Alternatives considered.**
- *Pull-model usage* (orchestrator polls the backend each iteration). Rejected: backends know their own cost shape better than the orchestrator does; push-via-`usage()`-accessor is symmetric with the existing `aclose()` pattern.
- *Per-call cost check rather than per-iteration.* Rejected for v1 because per-iteration is sufficient (the LLM cost-per-call dominates any orchestration overhead) and per-call adds branching to every tool boundary. May be revisited if a single tool call ever costs more than a typical iteration's worth of headroom.
- *Soft caps* (warn but don't abort). Rejected as the v1 default: hard caps are the 2026 norm and the pattern users expect. A soft-cap mode lands as `hard_stop_at_threshold: bool = True` (the 2026-common shape from the external survey) so downstream integrators can opt into warn-only if they need it.
- *Cost ceiling on `RunResult` with no abort path.* Rejected: defeats the purpose of the field. If the ceiling does not abort, it is observability rather than a budget.

**Cost-attribution edge cases worth naming.**
- **Best-of-N candidates** (the `max_candidates` loop at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:263`) multiply the per-iteration cost by `max_candidates`. The check site at iteration boundary catches this — the bump is observable on the iteration after the overshoot, not before.
- **Reviewer ensembles** also multiply per-iteration cost. Same boundary check; same observability profile.
- **MCP tool calls** are typically free at the LLM-cost layer but may have provider-specific costs (e.g. the VideoScore2 wrap if it's a paid hosted endpoint). `Usage` should accept a `tool_costs: dict[str, float]` map so per-server tool costs surface alongside LLM tokens.
- **Streamed responses** (Strands SDK supports streaming) report final usage in the closing event. `usage()` is called after the request completes; partial streaming costs are accumulated by the backend and surfaced once.

### Q6 — Audit Logs

**Recommendation.** Introduce a new `vigor.audit_event.v1` schema sibling to `vigor.provenance.v1` (`packages/vigor-core/src/vigor_core/schemas.py:287`), with one event per:

- adapter `compile`, `review`, `export` boundary,
- backend `generate`, `review`, `propose_patch` boundary,
- every `ToolBackend.call_tool` invocation (`packages/vigor-mcp/src/vigor_mcp/backend.py:122`).

Required fields per event: `event_id`, `tenant_id`, `run_id`, `actor` (adapter / backend / tool), `tool_id` (where applicable), `payload_sha256` (digest of inputs, not the inputs themselves), `output_sha256`, `status`, `duration_ms`, `timestamp`, `prev_event_sha256` (hash chain). PII scrubbing via Pydantic `SecretStr` adoption on the schema fields that can carry secrets, plus a redact-known-patterns pass on free-text fields at write time.

Retention policy lives in deployment configuration, not in code: 90 days hot (write-optimized store), 365 days cold (object storage IA tier). GDPR-style erasure hook: `RunArchive.delete_events(tenant_id, before)` becomes a real method rather than the current "remove the directory" approach.

`ProvenanceRecord` is preserved unchanged; it remains the per-run summary. `AuditEvent.v1` is the per-event firehose.

**Implementation seam.** New `vigor_core.audit` module; new `AuditLog` interface (a sibling to `RunArchive`). Insertion points are all five adapter/backend/tool boundaries listed above.

**Classification: foundational.** Greenfield. Not strictly required for an isolated single-tenant CLI deployment, but a precondition for any hosted multi-tenant offering. Companion ADR draft is on the v2 backlog (sibling builder VIGOR-a29a's scope is the deployment, isolation, and cost-ceiling ADRs; the audit-log schema may land as a follow-on).

**Alternatives considered.**
- *Extend `ProvenanceRecord` with the per-call events.* Rejected: conflates the per-run summary with the per-call firehose. The two have different cardinality, different retention, and different consumers (run-summary readers want the latest record; audit-firehose readers want the historical chain).
- *Adopt OpenTelemetry traces as the audit log.* Rejected as the *only* mechanism: OpenTelemetry is the right shape for *observability*, not for *audit*. Audit logs need append-only-ness, hash chains, and PII redaction guarantees that the OTel pipeline does not provide by default. OTel is endorsed alongside `AuditEvent.v1` (see "Observability and Telemetry" below) but is not a substitute.
- *Free-text logs (the `logging` module).* Rejected for any production deployment: free-text logs do not satisfy the structured-and-signed 2026 norm, and PII redaction over free text is fundamentally fragile.

**Hash-chain shape.** `prev_event_sha256` is the SHA-256 of the previous event's full JSON serialization (canonical sort-keys, no whitespace). The first event of a run has `prev_event_sha256 = sha256(run_id)` so the chain is rooted in the run identity. Verification walks the chain from root to head; tampering shows up as a hash mismatch at the tampered event.

**Retention and erasure.** Hot retention (write-optimized store, indexed by `tenant_id`/`run_id`/`timestamp`) is 90 days by default; cold retention (object storage IA tier) is 365 days. The GDPR-style erasure hook is `AuditLog.delete_events(tenant_id, before)`; the implementation rewrites the affected hash chain with `redacted=True` markers rather than physically deleting events, so the chain remains verifiable. Operational runbooks for erasure live with the deployment-posture ADR's follow-ons.

**Storage backend.** v1 commits to a JSON-Lines-on-object-storage shape: one file per `{tenant_id, run_id, hour}` partition, append-only, sealed when the run terminates. Indexed via a small SQLite or Postgres metadata table for `(tenant_id, run_id, event_id) → object key` lookup. v2 may adopt a purpose-built audit-log service (e.g. a managed Kafka topic or a BigQuery sink); the strategic posture commits to JSON-Lines because it is portable across cloud providers and is the lowest-friction shape for downstream compliance review. The `AuditLog` interface is storage-backend-agnostic by design.

**Per-event size budget.** Audit events are dense — input/output digests rather than payloads — so per-event size is bounded at roughly 1 KB serialized. A run that produces 100 events (typical for a 5-iteration × 4-candidate run with reviewer ensembles) costs ~100 KB; a year of hot retention for 10K runs/tenant is single-digit GB per tenant. Cost is dominated by the indexing layer, not the audit storage itself.

**Cardinality of `actor`.** The `actor` field has a closed enum: `orchestrator`, `adapter:<adapter_id>`, `backend:<backend_id>`, `tool:<server_id>:<tool_name>`. Other shapes are rejected at validate time. This keeps the audit log queryable by actor type without free-text matching.

### Q7 — CLI vs Library vs HTTP Service

**Recommendation.** Keep the library as the system of record. **Add a thin opt-in `vigor-server` package that exposes `AgentOrchestrator` as a typed HTTP API.** Do **not** embed HTTP serving inside `vigor-runtime` or `vigor-agent`.

Posture details:

- The CLI (`vigor-agent run --config agent.yaml task.json`) remains the canonical local entry point.
- `packages/vigor-server` (new) depends on `vigor-agent` and adds FastAPI/Starlette plus a small auth layer (Bearer token in v1, OAuth2 device flow in v2).
- The HTTP shape is `POST /runs` (start), `GET /runs/{run_id}` (status + frontier + provenance), `GET /runs/{run_id}/events` (audit-event stream), `DELETE /runs/{run_id}` (cancel + archive cleanup).
- The current README's implicit "VIGOR is library-first; production hosting is downstream" stance becomes explicit: `vigor-server` is **opt-in infrastructure**, not the recommended default. Downstream integrators who need HTTP get a vetted shape rather than reinventing it.

**Implementation seam.** New `packages/vigor-server/` package; `packages/vigor-agent/src/vigor_agent/agent.py:81` (the `run` method) is the wrapped entry point. No changes to the orchestrator.

**Classification: tactical.** The runtime is structurally ready; the FastAPI surface is roughly 200–400 LOC plus auth wiring. Companion ADR on deployment posture should resolve whether `vigor-server` ships in the same wave as the Dockerfile or a wave later. The recommendation here is "same wave" — the container story is incomplete without the HTTP entrypoint.

**Alternatives considered.**
- *Embed HTTP serving inside `vigor-runtime` or `vigor-agent`.* Rejected: violates the per-concern packaging discipline ADR-0007 commits to. Library users who do not need HTTP would still pay the FastAPI dependency cost (or its lazy-import equivalent), and the `[server]` extra is the cleaner shape.
- *Use gRPC instead of HTTP.* Rejected for v1: HTTP/JSON is the lowest-friction integration shape for downstream callers; gRPC is a wave-2 consideration if performance becomes the binding constraint. The audit-log streaming use case is the strongest argument for gRPC, and Server-Sent Events over HTTP is the v1 substitute.
- *Adopt an existing agent-server framework* (LangServe, FastAPI Agents). Rejected: those frameworks own opinions about agent shape that conflict with VIGOR's iterative-loop posture; the wrapping cost would be similar to the from-scratch FastAPI surface.

**Authentication shape.**
- v1: `Authorization: Bearer <token>` with tokens issued out-of-band (env-var configured per deployment).
- v2: OAuth2 device flow for human-in-loop integrations; mTLS for service-to-service when downstream callers are inside the same VPC.
- Both shapes are 2026-norm per VIGOR-4293 §D and ADR-0016's vendor-auth guidance.

**API surface in outline** (full shapes belong in the companion ADR):
- `POST /runs` — start a run; body is `TaskSpec`; returns `{run_id, status_url}`.
- `GET /runs/{run_id}` — current run status; returns `RunResult`-shaped JSON.
- `GET /runs/{run_id}/events` — Server-Sent Events stream of `AuditEvent.v1` records for the run.
- `DELETE /runs/{run_id}` — cancel an in-flight run; idempotent.
- `GET /runs/{run_id}/frontier` — final or in-progress frontier; returns `Frontier`-shaped JSON.
- `GET /healthz`, `GET /readyz` — Kubernetes-style liveness/readiness probes.

### Q8 — Failure Mode Coverage

**Recommendation.** Three concrete actions, ordered by leverage:

1. **Wire `Budgets.max_tool_retries` into a real retry loop** in `MCPToolBackend.call_tool` (`packages/vigor-mcp/src/vigor_mcp/backend.py:122`). MCP timeouts and network blips dominate transient failures in the wild; the schema slot already exists and the behavior matches the 2026 norm. Backoff should be exponential with jitter; max-retries must stop the loop, not propagate.
2. **Make cancellation a first-class primitive.** Run-level `cancel(run_id)` lives on `AgentOrchestrator`. The `agent.aclose()`-in-`finally` pattern at the CLI (`packages/vigor-runtime/src/vigor_runtime/cli.py:52`) is wrapped into a `RunHandle` returned by `AgentOrchestrator.run`. Hosted entry points (`vigor-server`, Q7) gain a clean cancellation signal; `Ctrl-C` semantics in the CLI are unchanged.
3. **Decide explicitly on OOM and adapter-mid-run-crash.** Today, both shapes propagate via the generic-Exception handler at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:202` and the run terminates with `stop_reason="failed"`. Strategic posture: this is correct for v1 (fail-fast over best-effort recovery), and the audit log (Q6) is the recovery surface. Containerized deployments (Q1) get OS-level OOM kills handled by the container runtime; the orchestrator does not need an in-process OOM strategy.

`retryable` (the dead metadata named in the scout report) becomes live after action (1).

**Implementation seam.**
- Retry loop: `packages/vigor-mcp/src/vigor_mcp/backend.py:122`.
- Cancellation: `packages/vigor-agent/src/vigor_agent/agent.py:81` (return type changes from awaitable `RunResult` to `RunHandle`; existing callers keep working via `RunHandle.result()`).

**Classification: tactical.** The retry loop is highest-leverage; cancellation is second; OOM/adapter-crash is observational (no code change required, just the doc commitment).

**Failure-mode coverage matrix** (strategic posture; per-mode runbook items belong with deployment-posture ADR follow-ons):

- **Adapter raises mid-`compile`.** Caught at `_safe_compile` (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:391`). Run continues; iteration may still produce a winner from other candidates. *Posture: fail-closed at the candidate level, fail-open at the run level.*
- **Adapter raises mid-`review`.** Coerced at `_run_reviewers.adapter_reviews` (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:451`). Adjudication still runs against the coerced report. *Posture: same as above.*
- **Adapter raises mid-`export`.** Logged via `_safe_export` (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:413`). Run terminates with `stop_reason="failed"`. *Posture: fail-closed at the run level — export is the irreversible step.*
- **MCP server unreachable.** Boot failure rolls back the `AsyncExitStack` (`packages/vigor-mcp/src/vigor_mcp/backend.py:58`); subsequent `call_tool` returns `ToolResult(status="failure")`. *Posture: fail-soft at the tool level; the orchestrator decides whether the run can proceed.*
- **MCP call timeout.** Returns `ToolResult(status="timeout")`; handle is torn down (`packages/vigor-mcp/src/vigor_mcp/backend.py:148`). After Q8 item 1, retries up to `Budgets.max_tool_retries` with exponential backoff. *Posture: retry-then-fail-soft.*
- **Budget exhausted (wall-clock).** Caught at orchestrator iteration boundary (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:116`); `stop_reason="budget_exhausted"`. *Posture: fail-closed; the budget is the contract.*
- **Budget exhausted (cost — post-Q5).** Same iteration-boundary check; `stop_reason="cost_exceeded"`. *Posture: fail-closed.*
- **Cancellation (post-Q8 item 2).** `RunHandle.cancel()` triggers cooperative cancellation; in-flight tool calls are torn down by `aclose()`; the run terminates with `stop_reason="cancelled"` (extension to the `StopReason` literal). *Posture: cooperative — the runtime promises a clean teardown but cannot promise immediate stop.*
- **OOM.** Out of `vigor-runtime`'s control. The container runtime kills the process; Kubernetes-style restart policies decide whether the run resumes (it does not — runs are not resumable in v1). *Posture: fail-fast at the OS level.*
- **Adapter mid-run crash (segfault, infinite loop, hung subprocess).** Out of `vigor-runtime`'s control by definition. The container runtime's CPU/memory limits and the per-call MCP timeout (`packages/vigor-mcp/src/vigor_mcp/backend.py:144`) are the upstream defenses. *Posture: defense-in-depth via container limits.*

### Q9 — Supply-Chain Hardening

**Recommendation.** VIGOR's two-layer factory allowlist is already stronger than the 2026 MCP-host norm; the production posture should preserve and extend it:

1. **Resolve VIGOR-8bdf** (the open seed on `FactoryRef.allowed_prefixes` self-authorization) before merging ADR-0017 from `proposed` to `accepted`. ADR-0017's own "Follow-ups required" section names this as a hard prerequisite.
2. **Add a host-side MCP-server identity allowlist** (`AgentConfig.plugin_allowed_mcp_servers`) mirroring the existing `allowed_plugin_factory_prefixes` (`packages/vigor-core/src/vigor_core/agent_config.py:175`). Required by ADR-0017 for pure-MCP plugins; useful independently for the hosted deployment shape.
3. **Pin every official MCP server** per ADR-0016's "definition of official support" criteria (pinned version range, CI smoke test, response-schema validation, allowlist-asserted-in-test, license audit). The CI smoke test is the load-bearing link in the chain; without it, a renamed-upstream-tool can silently slip past the allowlist.
4. **SBOM and signing** are 2026 hygiene rather than VIGOR-specific concerns; CycloneDX SBOM emitted by `uv` at build time, container images signed with cosign. These are pipeline concerns that land with Q1's container-build workflow.
5. **Track but defer signed-MCP-server provenance** (`mcp-server-signing` is proposed but not standardized as of the 2026-05-14 cutoff). Re-evaluate when the ecosystem standardizes.

**Implementation seam.**
- `packages/vigor-core/src/vigor_core/agent_config.py:175` (extend host allowlist to MCP-server identity).
- `.github/workflows/container-build.yml` (new — SBOM emission, image signing).
- `.github/workflows/mcp-smoke.yml` (named in ADR-0016's implementation notes; net-new).

**Classification: foundational** for items (1) and (2); **tactical** for (3) and (4); **future** for (5).

**Alternatives considered.**
- *Drop `allowed_prefixes` and trust the configured factory blindly.* Rejected outright: the entire point of the two-layer allowlist is that `FactoryRef` is loaded from disk and may be attacker-controlled. Removing the gate is a regression.
- *Single-layer (host-only) allowlist without per-`FactoryRef.allowed_prefixes`.* Rejected: per-`FactoryRef` namespace assertions catch typosquats (`vigor_runtime_evil` vs `vigor_runtime`) that a host-level prefix list would miss in some valid configurations. The two layers cover different threats.
- *Vendoring all official MCP servers* (no third-party MCP packages at runtime). Rejected: the maintenance burden is large, the upstream versioning would still drift, and the vendored copy can lag security fixes. Pinned upstream with CI smoke is the better trade.
- *Reproducible builds.* Endorsed as a v2 commitment but not in this wave; reproducible Python is hard, and the SBOM + cosign baseline is the achievable v1 commitment.

---

## Two-Image Deployment Shape

The single deployment shape this document commits to is the **two-image split**:

- **Orchestrator image** — CPU, slim. Built from `python:3.11-slim` or distroless equivalent. `uv sync --no-dev --extra claude` (or `--extra strands`); installs `vigor-core`, `vigor-runtime`, `vigor-agent`, `vigor-mcp`, the chosen agent backend, and the chosen adapters. Boots `vigor-server` (Q7) or invokes the CLI directly. No GPU, no ML model weights.
- **Reviewer image** — GPU, dedicated. Built from a CUDA base (`nvidia/cuda:12.x-runtime-ubuntu22.04` or equivalent). Runs only the reviewer-side packages: VideoScore2 wrap (`packages/vigor-tool-mcp-videoscore2`), any GPU-resident objective validators. Exposes itself as an MCP server over `http/sse` per ADR-0016 §"Transport policy". The orchestrator image consumes it via `MCPServerSpec(transport="sse", url="https://reviewer.internal/...")`.

This shape preserves three properties:

1. **GPU is shared across runs and tenants**, not per-agent. The 14 GB VRAM cost (ADR-0016) is amortized across the reviewer fleet, not multiplied by the orchestrator concurrency.
2. **Orchestrator process startup is fast** because the slim image is small. Container-per-tenant (Q2) and container-per-session shapes are both viable without paying the GPU-init cost on every boot.
3. **The MCP transport split that ADR-0016 already commits to** is the *deployment* split. There is one transport contract between the two images; that contract is already specified.

The orchestrator image **does not** ship the reviewer's model weights, vendor SDKs that require GPU, or `torch`. The reviewer image **does not** ship the agent backends, the adapter Python factories, or the `AgentOrchestrator` itself.

**Networking.** Reviewer image is reachable on a private network only; the orchestrator authenticates via `Authorization: Bearer` per ADR-0016 §"Vendor auth and rotation", with mTLS optional for inter-VPC (the 2026 norm per VIGOR-4293 §D). The reviewer image is **not** reachable from public networks; allowing it to be is a misconfiguration that future operational runbooks must call out.

**Build pipeline.** A new `.github/workflows/container-build.yml` builds both images on tag push. Multi-stage `uv` build per image; SBOM emission (CycloneDX); image signing (cosign). Layer cache is shared via the repo's CI cache.

**Resource sizing (rough order-of-magnitude, not commitments).**
- Orchestrator container: 0.5–2 vCPU, 1–4 GB RAM. Most of the orchestrator's work is `asyncio` coordination plus per-iteration LLM round-trips; CPU is bounded by adapter `compile`/`apply_patch` work, which varies per modality.
- Reviewer container: 1 GPU (≥ 14 GB VRAM for VideoScore2 per ADR-0016), 4–16 GB RAM, 2–4 vCPU. Bounded by the heaviest reviewer model loaded; the wrap can host multiple reviewers if VRAM permits.
- Concurrency: one orchestrator container handles tens of concurrent `asyncio` runs (the limit is the LLM provider's per-key rate cap, not the orchestrator's CPU). One reviewer container handles concurrent inference up to the GPU's batch capacity.
- These are **rough** numbers; production sizing depends on per-tenant traffic, modality mix, and cost ceilings. The companion deployment-posture ADR may pin tighter ranges.

**Failure-of-image-boundary cases.**
- *Reviewer unreachable from orchestrator.* Falls back to `ToolResult(status="failure")` per the existing MCP boundary; the run continues with whatever non-reviewer signals are available. After the mutator-capability work (Q9 + threat-model), some adapters may degrade to "review-only" mode rather than abort.
- *Orchestrator restarts mid-run.* Runs are not resumable in v1 (named explicitly in Q8 — OOM is fail-fast). The audit log captures the in-flight events; the next process boot starts fresh. Resumable runs are a v2 commitment.
- *Reviewer image upgraded (rolling deployment).* The orchestrator's `MCPToolBackend._handles` cache means a long-lived orchestrator container will see stale handles after a reviewer redeploy; `aclose()` on the next-failed-call invalidates the handle and the next-call-after opens a fresh session. The strategic posture is: rolling reviewer deployments are safe, but the orchestrator may see one transient `ToolResult(status="failure")` during the swap.

**Out-of-scope for this strategic doc.** Specific Dockerfile contents, base-image version pins, k8s manifests, helm charts. Those land in the companion ADR draft on deployment posture and the seeds backlog (sibling builder VIGOR-a29a).

---

## Observability And Telemetry

Audit logs (Q6) are the *legal/compliance* surface; observability is the *operational* surface. The two share insertion points but differ in retention, redaction, and consumer. The strategic posture is to wire **both** without conflating them:

- **Metrics.** Per-run gauges (active runs, tokens-spent, USD-spent), per-iteration histograms (iteration duration, candidate count, reviewer-score distribution), per-tool counters (tool calls, timeouts, failures, retries-after-Q8). Prometheus-compatible `/metrics` endpoint on `vigor-server` (Q7); the library emits via `prometheus_client` if installed, no-op otherwise.
- **Traces.** OpenTelemetry spans at every adapter, backend, and tool boundary. Span hierarchy follows the orchestrator's call structure: `run > iteration > candidate > {compile, review[], adjudication, patch}`. Tool calls are leaf spans tagged with `server_id` and `tool_id`. Trace context is propagated into MCP servers via `traceparent` headers when the transport is http/sse; stdio servers do not get trace propagation in v1 (the protocol does not standardize it).
- **Logs.** Structured JSON to stdout (12-factor); the container runtime collects them. Logs are *operational*, not audit — they may be lossy, may be sampled, and do not need a hash chain. PII redaction still applies (a `redact()` filter on the log handler).
- **Health.** `GET /healthz` returns 200 if the orchestrator process is alive; `GET /readyz` returns 200 only if all configured `MCPServerSpec`s have completed their first `list_tools` round-trip (proof that they are reachable). Readiness is a *deployment-time* signal, not a runtime one.

Observability vs audit, summarized:

- *Audit* (`AuditEvent.v1`) — append-only, hash-chained, retained 90/365 days, consumed by compliance reviewers. Cannot be sampled.
- *Metrics* (Prometheus) — aggregate counters/histograms, retained per the metrics-store policy, consumed by oncall. Aggregation is the point.
- *Traces* (OpenTelemetry) — per-request spans, sampled (typically 1–10% in production), consumed by performance debugging. Sampling is the point.
- *Logs* (stdout JSON) — free-form structured events, consumed by humans during incidents. Lossy by design.

The companion ADR on deployment posture should commit to OpenTelemetry and Prometheus as the v1 baseline; alternative sinks (Datadog, Honeycomb, Grafana Cloud) are deployment-time choices, not architectural ones.

---

## Cost Model Sketch

The cost-ceiling work in Q5 introduces `Usage(input_tokens, output_tokens, usd, tool_costs)` on `AgentBackend`. The cost *model* — how `usd` is computed from tokens — is a deployment-time concern, but the strategic posture has three commitments worth recording:

- **Per-model pricing tables** are loaded from a versioned source (deployment config or a dedicated `vigor_pricing.yaml` keyed by `model_id`). The pricing table is **not** hard-coded in the backend; vendor pricing changes too often. The Claude Agent SDK already exposes the model identifier in `ResultMessage`, so the backend can look up the right rate.
- **Cost is a derived field**, not a vendor-reported one. Vendors report tokens; the deployment computes `usd` by multiplying tokens by the per-model rate. This means the cost ceiling is enforced against *VIGOR's accounting*, not against a vendor invoice that arrives weeks later. Discrepancies between VIGOR's accounting and the vendor's are reconciled out-of-band.
- **Tool costs are reported by tools, not estimated.** Tools that have a cost (e.g. the VideoScore2 wrap) report `tool_costs[server_id] += cost` via a hook on `MCPServerSpec`. Tools that are free at the cost layer (most stdio servers) do not report.

This separation — vendor-reports-tokens, deployment-defines-rates, tool-reports-tool-cost — keeps the cost model honest about its uncertainties. The companion ADR on cost-ceiling enforcement should call out that the `usd` field is **estimated** and that the ground-truth is the vendor invoice, not the runtime-accumulated total.

---

## Migration And Backwards Compatibility

The deployment-hardening wave introduces several breaking changes. The strategic posture is to **stage them behind versioned deprecations** so existing library users (the local-CLI use case) are not penalized for the hosted-deployment commitments.

The breaking changes are:

- **Subprocess env containment** (Q3 item 2). Stdio MCP servers no longer inherit the parent's `os.environ` by default. Migration: explicit `env={}` is the equivalent of today's `env=None`.
- **`StopReason` literal extension** (Q5, Q8 item 2). Adds `"cost_exceeded"`, `"cancelled"`. Schema version bump (`vigor.task.v1` stays; the `StopReason` Literal is the bump). Consumers that exhaustively match `StopReason` need a default case.
- **`AgentBackend.usage()` method** (Q5). New abstract method on `AgentBackend`. Existing backends gain a default implementation that returns `Usage()` (zeros). Custom backends should override; the default is a soft floor, not a contract.
- **`ToolResult.status` literal extension** (Q4). Adds `"rate_limited"`. Same default-case caveat as `StopReason`.
- **`AuditLog` interface** (Q6). New required dependency for `vigor-runtime`'s instantiation in hosted deployments; optional for library users (defaults to no-op `NullAuditLog`).
- **`AgentOrchestrator.run` return type** (Q8 item 2). Changes from awaitable `RunResult` to `RunHandle`. Existing callers keep working via `await handle.result()`, which is structurally equivalent.

Each breaking change ships behind a one-version `DeprecationWarning` cycle: warning in version *N*, hard break in version *N+1*. The CHANGELOG documents the migration paths; downstream integrators have a known-window to adapt.

**Non-breaking changes** in the same wave:
- `MCPServerSpec.env` and `MCPServerSpec.headers` wrapped in `SecretStr`. Existing `dict[str, str]` literals continue to validate.
- New `vigor.audit_event.v1` schema. Additive; no existing schema is touched.
- `vigor-server` package. Net-new; no existing import surface changes.
- Container build pipeline. Net-new; no existing CI changes.

---

## Phase-Gated Acceptance Criteria

The deployment-hardening wave is large; treating it as one ship is risky. The strategic posture is **three phases with explicit acceptance criteria each**:

**Phase 1 — Library hardening.** Closes the named runtime gaps without introducing hosted-deployment artifacts.

- Acceptance: `Budgets.max_cost_usd` is enforced; `Budgets.max_tool_retries` is enforced; subprocess env default is `{"PATH": ...}`-only; `SecretStr` wraps secret-bearing fields; `pyproject.toml:51` `ResourceWarning` filter is lifted for `vigor-mcp` tests.
- Backwards compatibility: deprecation warnings on the env-default change; otherwise additive.
- Out of scope: containers, `vigor-server`, audit logs.

**Phase 2 — Hosted-deployment baseline.** Introduces the artifacts that make a hosted deployment achievable.

- Acceptance: orchestrator and reviewer Dockerfiles ship; CI builds both; SBOM + cosign signing on tag push; `vigor-server` package with v1 Bearer-auth; `AuditEvent.v1` schema and emission at adapter/backend/tool boundaries; Prometheus `/metrics`; OpenTelemetry tracing; container-per-tenant commitment documented; VIGOR-8bdf resolved; MCP-server identity allowlist landed.
- Backwards compatibility: `vigor-server` is opt-in; audit log defaults to `NullAuditLog` for library users.
- Out of scope: container-per-session, signed-MCP-server provenance, OAuth2 device flow.

**Phase 3 — Production polish.** Closes the remaining tactical gaps.

- Acceptance: rate limiting (per-server QPS/burst); cancellation primitive (`RunHandle`); CI smoke tests for every official MCP server; OAuth2 device flow on `vigor-server` v2; KMS/Vault integration documented (pattern, not code).
- Backwards compatibility: rate-limit failures use `ToolResult(status="rate_limited")`; cancellation extends `StopReason`.
- Out of scope: container-per-session, signed-MCP-server provenance, gRPC transport for `vigor-server`.

Each phase is sequenced rather than parallel: phase 2 depends on phase 1 (cost ceilings inform rate-limit design); phase 3 depends on phase 2 (`vigor-server` is the substrate for the cancellation surface). Sibling builder VIGOR-a29a's seeds backlog should reflect this sequencing; the companion ADRs should each name the phase they target.

---

## Deployment Topology Reference

Three reference deployment topologies are worth naming so downstream integrators can pattern-match against the closest fit. None is prescriptive; the strategic posture only commits to *what is supported*, not to one preferred shape.

### Topology A: Local CLI (the v0 baseline)

Single-process `vigor-agent run --config agent.yaml task.json` invocation. No `vigor-server`, no audit log (defaults to `NullAuditLog`), no container, no GPU reviewer (or a developer-local GPU if the workstation has one). MCP servers are stdio subprocesses owned by the agent process; secrets are in the developer's environment. This is the v0 baseline; it remains supported indefinitely and is *not* a target for hardening removal.

### Topology B: Single-tenant hosted (the v1 target)

Orchestrator container behind a load balancer; one container handles many concurrent runs for one tenant. `vigor-server` exposes the HTTP API (Q7); audit log writes to a tenant-scoped store; cost ceilings enforce per-run budgets; rate limits enforce per-server QPS. GPU reviewer is a separate image, shared across orchestrator containers, reachable only on the private network. Secrets injected at process boot from a Vault/KMS sidecar; rotation triggers container restart. This is the **v1 hosted commitment** of this document.

### Topology C: Multi-tenant hosted (v1 ceiling, v2 floor)

Container-per-tenant pool: each tenant gets a dedicated orchestrator container (or a small pool, sized to per-tenant traffic). All other components are shared: GPU reviewer, audit-log backend (with tenant-scoped queries), `vigor-server` ingress (with tenant-scoping in the auth layer). Per-tenant API keys for vendor LLMs (sub-account separation per VIGOR-4293 §B). Per-tenant rate limits enforced at both the in-process bucket (Q4) and an external API gateway (deployment-layer concern).

The boundary between Topology B and Topology C is the *tenant-scoping* of the components, not a different deployment topology. C adds tenant-scoped multitenancy on top of B; both ride the same two-image shape.

### What Each Topology Pays For

- **Topology A pays for nothing extra.** Library use; the local CLI has been supported since VIGOR-c1ab's pre-cursors.
- **Topology B pays for the foundational wave** (cost ceilings, env containment, audit log, container build, `vigor-server`).
- **Topology C pays for the foundational wave plus the tactical wave** (rate limiting, identity allowlist, OAuth2 device flow, CI smoke, KMS/Vault docs).

The phasing in §"Phase-Gated Acceptance Criteria" lines up with this: Phase 1 ships the library hardening (everyone benefits); Phase 2 ships Topology B's surface; Phase 3 closes Topology C's gaps.

---

## Adoption Signals

A small number of leading indicators tell the architecture lead whether the deployment-hardening wave is succeeding once shipped. Naming them now keeps the post-ship retrospective grounded.

- **Schema-vs-runtime drift count** — the count of `Budgets.*` and `ToolManifest.*` fields that are stored but not read by the runtime. Today: 2 (`max_cost_usd`, `max_tool_retries`). Target after Phase 1: 0.
- **Mean time to detect leaked subprocess in tests** — today, untestable (`pyproject.toml:51` filters the warning). Target after Phase 1: tests fail loudly on the next leak.
- **Audit-log coverage** — fraction of adapter / backend / tool boundary calls that produce an `AuditEvent.v1`. Today: 0. Target after Phase 2: 100% of named boundaries.
- **Mean cold-start latency for an orchestrator container** — directly affects the container-per-session viability calculus. Target after Phase 2: under 5 seconds with a warm image cache.
- **Mean per-run cost variance** (between runtime-accumulated USD and vendor invoice) — directly affects whether the cost-ceiling enforcement is trustworthy. Target after Phase 2: under 5% relative variance per month.
- **CI smoke-test stability for official MCP servers** — fraction of runs that pass without flake. Target after Phase 3: 95%+ over a rolling 30-day window.
- **`vigor-server` integration count** — number of distinct downstream integrators using `vigor-server` rather than the library directly. Not a target (library-first is the strategic anchor); but a non-zero count validates the opt-in shape.

These signals are the empirical floor for "the deployment-hardening wave shipped successfully". They are not commitments; they are *signals*. The architecture lead should review them quarterly.

---

## Threat-Model Anchor

This document is one half of the deployment strategic deep-dive; the other half is sibling builder VIGOR-f44c's STRIDE-style threat model at `docs/security/threat-model.md`. The strategic recommendations above are **anchors** the threat model can ground its findings in:

- **Spoofing.** The two-layer factory allowlist (host-side + per-`FactoryRef.allowed_prefixes`) plus the proposed MCP-server identity allowlist (Q9 item 2) cover spoofing of plugin sources. `Authorization: Bearer` (Q7) covers spoofing of `vigor-server` clients.
- **Tampering.** The hash-chained audit log (Q6) covers post-hoc tampering. Path containment (`RunArchive._safe_target`, ADR-0016 §5) covers in-flight tampering with archive contents.
- **Repudiation.** Per-tenant audit events with `actor` and `prev_event_sha256` make repudiation infeasible. The `tenant_id` field is mandatory.
- **Information disclosure.** `SecretStr` adoption (Q3 item 4), drop-all-by-default subprocess env (Q3 item 2), and tenant-scoped storage (Q2) cover the leak surfaces named in the scout report.
- **Denial of service.** Cost ceilings (Q5), rate limiting (Q4), and per-tool timeouts (`packages/vigor-mcp/src/vigor_mcp/backend.py:144`) cover internal DoS. External DoS is a deployment-layer concern (CDN, WAF) and out of scope here.
- **Elevation of privilege.** Mutator-capability enforcement (a runtime check that `ToolManifest.mutability="mutator"` is gated by an orchestrator-issued capability — see VIGOR-4293 §"Cross-Cutting Findings" item 3) is the highest-leverage missing control. Companion ADR on multi-tenant isolation should commit.

The threat model goes deeper on each axis; this list is the bridge.

---

## Open Decisions Deferred To ADRs

The following decisions are **named here but not resolved here**. Each lands in a companion ADR draft authored by sibling builder VIGOR-a29a; this document does not name specific ADR numbers because the numbering is the sibling's responsibility.

- **Companion ADR on deployment posture.** Commits to the two-image shape. Specifies the orchestrator and reviewer Dockerfiles in outline (not in full content), the build pipeline, the SBOM/signing posture, and the relationship to ADR-0016's transport split. Decides whether `vigor-server` ships in the same wave as the container build.
- **Companion ADR on multi-tenant isolation.** Enumerates the four isolation shapes (sub-account, subprocess-per-task, worktree-per-task, container-per-session). Commits to **container-per-tenant** as the v1 floor. Names the deferred future work (container-per-session with hot-pool warmup) without committing.
- **Companion ADR on cost-ceiling enforcement.** Commits to the `Usage` shape on `AgentBackend.usage()`, the placement of `RunBudgetTracker` (on `RunContext` rather than as a sibling), the iteration-boundary check site, and the new `StopReason="cost_exceeded"` literal. Names the StopReason schema bump as a versioned migration concern.
- **Follow-on ADR on audit-log schema** (likely a separate wave). The `vigor.audit_event.v1` schema, the hash-chain shape, the retention/erasure hooks, and the redaction policy. Not in sibling builder VIGOR-a29a's scope; lands as a deployment-hardening v2 deliverable.
- **Follow-on ADR on rate limiting** (tactical, post-cost-ceiling). The `ToolManifest.retry_policy` dict's reserved-key shape (`qps`, `burst`), per-adapter pacing, and the relationship to cost ceilings.
- **Follow-on ADR on `vigor-server` shape**. Authentication scheme, HTTP API surface, run-handle / cancellation semantics. May be folded into the deployment-posture ADR if the lead prefers a single document.

The following are **explicitly not deferred to ADRs and remain follow-ups in the seeds backlog only**:

- Lifting the `pyproject.toml:51` `ResourceWarning` suppression for at least the `vigor-mcp` test package as a leading-indicator for subprocess leaks.
- The mulch record correction noted in VIGOR-4293 (`mx-560586` claims `ToolBackend` lacks `aclose()`; this is no longer true per `packages/vigor-core/src/vigor_core/interfaces.py:152`).
- VIGOR-9ef8 ("orchestrator extension points for production readiness") sibling overlap. The lead must de-conflict scope before architect synthesis; this document does not pre-empt that decision.

---

## Cross-Cutting Posture Statements

A handful of statements ride above the per-question recommendations and are worth restating as the strategic frame for the deployment-hardening wave:

1. **VIGOR is library-first and remains so.** Hosted deployment is supported via `vigor-server` (opt-in package), not by embedding HTTP into the runtime. Downstream integrators may choose container-per-session, container-per-tenant, or in-process tenancy at their own risk and with the postures named above.
2. **Paper budgets are technical debt** and should be either enforced or removed. `Budgets.max_cost_usd` becomes enforced (Q5); `Budgets.max_tool_retries` becomes enforced (Q8); `retryable` becomes live metadata (Q8). The schema-vs-runtime drift the scout report named is the smell that justifies the deployment-hardening wave at all.
3. **The two-image shape is the deployment commitment.** ADR-0016 already implies it. The strategic posture promotes the implication to a commitment and produces the build-pipeline artifacts. CPU orchestrator + GPU reviewer over MCP http/sse is the only shape this document blesses for production.
4. **Default-deny is the security stance.** Tool allowlists, factory-namespace allowlists, plugin-supplied MCP-server identity allowlists, drop-all-by-default subprocess env. Every gate that exists today is closed by default; every new gate this document recommends adds another closed default.
5. **Audit at boundaries, summarize at runs.** `AuditEvent.v1` (the firehose) is the per-call record at adapter / backend / tool boundaries. `ProvenanceRecord` (the existing summary) is the per-run record. Neither is a replacement for the other.
6. **Container-per-tenant first; container-per-session later.** The 2026 ecosystem trend is container-per-session, but the cost is real and the threat profile of v1 hosted does not justify it as the floor. Container-per-tenant is the v1 commitment; container-per-session is named as the v2 ceiling.
7. **Schema migrations are deliberate, not casual.** Every extension to a closed `Literal` (`StopReason`, `ToolResult.status`, error `kind`) is a versioned bump with a deprecation cycle. Schema-vs-runtime drift is the failure mode this whole document is designed to prevent; the cure cannot be a worse version of the disease.
8. **Hosted is opt-in, not the default.** The library-first stance is the strategic anchor. Every recommendation here that introduces hosted-deployment infrastructure is **structurally additive**: existing single-tenant CLI users do not pay the cost. `vigor-server` is a separate package; the audit log defaults to `NullAuditLog`; the container build is a separate workflow. A user running `vigor-agent run --config agent.yaml task.json` after this wave ships should see no behavioral change beyond the cost-ceiling enforcement (which is opt-in via `Budgets.max_cost_usd`).

---

## Strategic Tensions And Trade-Offs

A handful of recommendations in this document are in genuine tension. Naming them explicitly helps downstream readers see where the strategic posture made a judgment call rather than a forced move.

- **Library-first vs hosted-first.** The 2026 ecosystem trend leans toward hosted-first (Anthropic Workspaces, Claude Code, Devin-class agent OSes). VIGOR's strategic anchor is library-first. The trade-off: hosted-first would simplify multi-tenant isolation and audit (one deployment, one tenant model) but would exclude the local-CLI use case that VIGOR's downstream integrators rely on. The `vigor-server` opt-in package is the bridge; it costs more in maintenance than a single-target hosted deployment but preserves the library posture.
- **Two-image vs single-image.** Two images cost more in build complexity and registry storage; one image would let the orchestrator and reviewer share dependencies. The 14 GB VRAM cost of VideoScore2 forces the split. Once split, the GPU image is shared across runs (a savings); a single image would multiply the GPU cost by orchestrator concurrency.
- **Container-per-tenant vs container-per-session.** Per-tenant is cheaper (containers are reused for many tasks within one tenant); per-session is more secure (a fresh container per task means no per-task cross-task leak surface). The v1 trade is per-tenant first because the threat profile of a still-evolving hosted deployment does not justify per-session, and per-session can be added later without re-architecting per-tenant.
- **In-process token bucket vs external gateway.** The in-process bucket protects VIGOR from runaway adapters; the external gateway protects upstream MCP servers from VIGOR. Both are valuable; v1 ships the in-process bucket because it can land in `vigor-mcp` without a deployment-layer dependency. The gateway is endorsed as a deployment-layer follow-on, not a substitute.
- **Hard caps vs soft caps for cost ceilings.** Hard caps abort runs mid-loop; soft caps warn but proceed. The 2026 norm is hard caps; the trade-off is that a hard cap can interrupt a run that is one iteration away from accepting a winner. The v1 default is hard; soft mode is opt-in via `hard_stop_at_threshold: bool = True` (default `True`).
- **Hash-chained audit log vs append-only-with-WORM-storage.** The hash chain is in-application; WORM storage is a deployment-layer property. Both prevent tampering but with different trust assumptions. The v1 strategic posture commits to the hash chain because it is portable across storage backends; WORM storage is deployment-time hardening on top.
- **`SecretStr` adoption vs structured-secret-references.** `SecretStr` redacts in serialization but the secret is still in process memory. Structured secret references (e.g. `secret://vault/path/to/key`) defer the resolution to the secrets backend. The v1 trade is `SecretStr` because it is purely additive; structured references are a v2 commitment that requires a secrets-backend abstraction.

These tensions do not resolve "right" or "wrong"; they resolve *for v1*. Each is named in the corresponding companion ADR so the v2 cycle can revisit with hindsight rather than re-discovering the trade.

---

## Implementation Wave Ordering

This section is informational, not prescriptive. The strategic ordering that falls out of the classifications above is:

1. **Foundational, wave 1.** Cost ceilings (Q5), subprocess env containment (Q3 item 2), Dockerfile + build pipeline (Q1), container-per-tenant commitment (Q2), VIGOR-8bdf resolution (Q9 item 1). These are the smallest changes with the largest deployment-readiness gain.
2. **Foundational, wave 2.** Audit-log schema and emission (Q6), MCP-server identity allowlist (Q9 item 2), `vigor-server` thin HTTP package (Q7).
3. **Tactical, wave 3.** Retry loop wired (Q8 item 1), cancellation primitive (Q8 item 2), per-server rate limit (Q4 item 1), `SecretStr` adoption (Q3 item 4), CI smoke tests for official MCP servers (Q9 item 3).
4. **Tactical, wave 4.** Per-adapter pacing (Q4 item 2), SBOM + cosign in the container pipeline (Q9 item 4), KMS/Vault integration documentation (Q3 item 3).
5. **Observational follow-ups.** `ResourceWarning` suppression lifted for `vigor-mcp` tests; mulch record correction; sibling-overlap de-confliction with VIGOR-9ef8.
6. **Future / deferred.** Container-per-session shape (Q2 ceiling), signed-MCP-server provenance (Q9 item 5), cross-modal task composition (out-of-scope for this document; named in `packages/vigor-core/src/vigor_core/agent_config.py:99`).

The wave ordering is the recommendation; the actual implementation cadence is the architect lead's call and lands in the seeds backlog (sibling builder VIGOR-a29a).

---

## What This Document Does Not Cover

To stay focused on strategic posture rather than implementation, this document explicitly does **not** cover:

- Specific Dockerfile contents or base-image SHA pins.
- k8s manifests, helm charts, or Terraform.
- Specific FastAPI route signatures or request/response shapes for `vigor-server`.
- The full `vigor.audit_event.v1` schema (only the required fields are sketched above).
- The OAuth2 device-flow integration steps for `vigor-server` v2.
- Threat modeling — that is sibling builder VIGOR-f44c's deliverable (`docs/security/threat-model.md`).
- The seeds backlog itself — that is sibling builder VIGOR-a29a's deliverable.
- Specific ADR numbers — sibling builder VIGOR-a29a authors the companion ADRs; this document references them generically.
- Any per-modality content (photo / video / CAD adapter operational concerns). Modality concerns ride on the strategic posture above, not under it.

If something is missing here that the lead expects to see, the most likely answer is "deferred to a sibling deliverable" rather than "not considered". The 2026-05-15 cutoff is firm for this draft; deferred items are visible in the seeds backlog.

---

## Open Questions And Unknowns

The strategic posture above is grounded in the VIGOR-4293 scout report, the existing ADRs, and the codebase as of the 2026-05-15 cutoff. A handful of questions remain open and should be flagged as `unknown` or `follow-up` per the spec's guidance to not speculate beyond scout evidence:

- **Sibling overlap with VIGOR-9ef8.** VIGOR-4293 §"Cross-Cutting Findings" item 9 flags that VIGOR-9ef8 (orchestrator extension points for production readiness) likely covers cost-ceilings (Q5) and retry-loop wiring (Q8 item 1) from a different angle. The scope de-confliction is **the lead's call**, not this document's. If VIGOR-9ef8 ships first, this document's Phase 1 acceptance criteria should be reread against what landed there.
- **Vendor invoice reconciliation.** The cost model sketch above commits to "deployment-defines-rates, vendor-reports-tokens, runtime-accumulates-USD" but the reconciliation cadence between VIGOR's accumulated USD and the actual vendor invoice is **unknown**. Likely cadence is monthly per the ADR-0016 vendor-key-rotation cadence; that is a deployment-time question, not a strategic one.
- **Per-tenant resource quotas at the container layer.** Container-per-tenant gives a tenancy boundary; whether the deployment layer (k8s, Nomad, ECS) enforces per-tenant CPU/memory/network quotas on top is **deployment-time**. This document recommends container-per-tenant; it does not prescribe quota shapes.
- **MCP gateway adoption timing.** The 2026 MCP gateway pattern (VIGOR-4293 §A) is *emerging*, not yet *standardized*. Adoption is endorsed as a follow-on but the timing depends on which gateway implementations stabilize. Re-evaluate during the v2 cycle.
- **Open Plugin Spec v1 stabilization.** ADR-0017 explicitly defers deeper investment until OPS stabilizes; PR #3 (vercel-labs/open-plugin-spec) is open as of 2026-05-04. If OPS v1 stabilizes, both ADR-0017 and this document's plugin-supplied MCP-server allowlist (Q9 item 2) need to be reread.
- **VIGOR-8bdf resolution shape.** Q9 item 1 commits to resolving VIGOR-8bdf before promoting ADR-0017 to `accepted`. The *shape* of the resolution (whether it adds a host-side allowlist field, whether it enforces it at validate-time or at load-time, whether it requires a signature) is **the architect's call**. This document's recommendations assume resolution lands; they do not prescribe how.
- **GPU-reviewer hosting.** ADR-0016 commits to a VIGOR-built VideoScore2 wrap over http/sse but does not commit to a specific hosting provider (AWS GPU instances, Modal, Replicate, on-prem). Choice is **deployment-time**; the strategic posture only commits to the *transport* shape (http/sse) and the *isolation* shape (separate image, shared across runs).
- **ResultMessage cost-telemetry stability.** Q5's cost-attribution shim depends on `claude_agent_sdk.ResultMessage` exposing token counts. The current SDK does (`packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:92`); future SDK versions might rename or restructure. The companion ADR on cost-ceiling enforcement should pin the SDK version range that the cost shim assumes.
- **Strands SDK cost-telemetry parity.** The external survey notes Strands uses LangSmith-style trace-based accounting. The mapping from Strands' shape to `Usage(input_tokens, output_tokens, usd, tool_costs)` is **unknown** without a deeper dive into the Strands SDK. Likely a wave-3 follow-up; the v1 cost ceiling supports Claude SDK first.
- **AIECF integration timing.** Per `docs/readiness/implementation-readiness.md`, AIECF integration is blocked on external repository access. If AIECF lands during the deployment-hardening waves, the audit-log schema and the per-adapter rate-limit shapes need to handle the AIECF adapter's tool surface. Currently a no-op assumption; revisit if AIECF unblocks.

This list is the explicit `unknown` set the spec asks for. Items here are not recommendations against; they are recommendations to defer until the relevant evidence arrives.

---

## References

### Architecture Decision Records

- `docs/adr/0014-generalized-agent-config.md` — Generalized AgentConfig (Accepted, 2026-05-01).
- `docs/adr/0016-official-mcp-servers.md` — Official MCP Servers and Security Posture (Proposed, 2026-05-15).
- `docs/adr/0017-pure-mcp-plugin-support.md` — Admit Pure-MCP Plugins as Ambient Tool Sources (Proposed, 2026-05-15).
- `docs/adr/0010-async-core-interfaces.md` — Async core interfaces (background; the `ToolBackend.aclose()` contract).
- `docs/adr/0004-reviewer-ensemble-and-adjudicator.md` — Reviewer ensemble (background; the reviewer categories cited above).

### Code Anchors

- `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:114` — `max_iterations` enforcement.
- `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:116` — `max_wall_clock_s` enforcement (cost-ceiling check site).
- `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:188` — top-level `VigorError` handler.
- `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:202` — generic `Exception` handler.
- `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:263` — `max_candidates` enforcement (best-of-N batch).
- `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:391` — `_safe_compile`.
- `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:413` — `_safe_export`.
- `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:451` — adapter-review error coercion.
- `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:475` — backend-review error coercion.
- `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:545` — `retryable` consumer (the only one).
- `packages/vigor-mcp/src/vigor_mcp/backend.py:48` — allowlist installation.
- `packages/vigor-mcp/src/vigor_mcp/backend.py:81` — `list_tools` allowlist filter.
- `packages/vigor-mcp/src/vigor_mcp/backend.py:122` — `call_tool` (rate-limit / retry / audit insertion point).
- `packages/vigor-mcp/src/vigor_mcp/backend.py:131` — `call_tool` allowlist gate.
- `packages/vigor-mcp/src/vigor_mcp/backend.py:144` — per-server `asyncio.wait_for` timeout.
- `packages/vigor-mcp/src/vigor_mcp/backend.py:148` — timeout-rollback (`handle.aclose()`).
- `packages/vigor-mcp/src/vigor_mcp/transports/sdk.py:42` — stdio subprocess `env` default (the leak surface).
- `packages/vigor-mcp/src/vigor_mcp/transports/sdk.py:54` — sse `headers` injection.
- `packages/vigor-mcp/src/vigor_mcp/transports/sdk.py:65` — http `headers` injection.
- `packages/vigor-core/src/vigor_core/schemas.py:51` — `Budgets`.
- `packages/vigor-core/src/vigor_core/schemas.py:75` — `ToolManifest` (`mutability` field).
- `packages/vigor-core/src/vigor_core/schemas.py:84` — `ToolManifest.retry_policy` (rate-limit slot).
- `packages/vigor-core/src/vigor_core/schemas.py:120` — `StopReason` literal (cost-ceiling extension site).
- `packages/vigor-core/src/vigor_core/schemas.py:287` — `ProvenanceRecord` (the existing per-run summary).
- `packages/vigor-core/src/vigor_core/agent_config.py:53` — `MCPServerSpec` (`env`, `headers`, `tool_allowlist`).
- `packages/vigor-core/src/vigor_core/agent_config.py:175` — host-side `assert_factory_ref_allowed`.
- `packages/vigor-core/src/vigor_core/interfaces.py:130` — `AgentBackend` ABC (`usage()` extension site).
- `packages/vigor-core/src/vigor_core/interfaces.py:143` — `ToolBackend` ABC.
- `packages/vigor-core/src/vigor_core/interfaces.py:152` — `ToolBackend.aclose()` (mulch correction reference).
- `packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:42` — Claude Agent SDK permission-mode posture.
- `packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:80` — Claude Agent SDK env propagation.
- `packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:92` — `ResultMessage` cost telemetry (currently dropped).
- `packages/vigor-agent/src/vigor_agent/agent.py:81` — `AgentOrchestrator.run` (cancellation extension site).
- `packages/vigor-runtime/src/vigor_runtime/cli.py:52` — `agent.aclose()`-in-`finally` pattern.
- `pyproject.toml:51` — repo-wide `ResourceWarning` suppression.

### Research and Survey Inputs

- `.overstory/specs/VIGOR-4293.md` — primary scout report (internal + external survey, cutoff 2026-05-15).
- `docs/research/2026-mcp-reviewer-survey.md` — MCP reviewer ecosystem survey (cutoff 2026-05-14).
- `docs/research/vigor-research-synthesis.md` — VIGOR research synthesis (tone reference for this document).
- `docs/research/open-plugin-spec-host-compatibility.md` — Open Plugin Spec v1 host compatibility research.
- `docs/readiness/implementation-readiness.md` — readiness assessment (the "container sandbox remains future hardening" anchor).

### Sibling Strategic Deliverables

- `docs/security/threat-model.md` — sibling builder VIGOR-f44c (STRIDE-style threat model for VIGOR-in-production).
- Companion ADR drafts (deployment posture, multi-tenant isolation, cost-ceiling enforcement) — sibling builder VIGOR-a29a.
- Prioritized seeds backlog — sibling builder VIGOR-a29a.

### External References Cited Indirectly

The 2026 external posture section synthesizes survey findings rather than re-fetching URLs. For canonical links to Anthropic's "Building Effective Agents", the Claude Agent SDK plugin docs, the Open Plugin Spec v1 vercel-labs PR #3, the Model Context Protocol specification, the TIGER-Lab VideoScore2 model card, and the per-server upstream repositories cited in ADR-0016, see the corresponding ADRs and the `docs/research/` survey documents listed above.

### Reading Guide

A reader pressed for time should read, in order: §"Executive Summary", §"Strategic Recommendations" Q1–Q9, §"Two-Image Deployment Shape", §"Phase-Gated Acceptance Criteria". Everything else is supporting context. The threat-model anchor section is the bridge to sibling builder VIGOR-f44c's deliverable; the open-questions section is the bridge to sibling builder VIGOR-a29a's seeds backlog.

The internal survey (§"Current Deployment Surface") is dense with `path:line` anchors and is meant to be read with the codebase open. The external survey (§"2026 External Posture") is dense with named ecosystem patterns and is meant to be read alongside `docs/research/2026-mcp-reviewer-survey.md`. Either can be skimmed if the reader is already familiar with the corresponding source.

### Document Provenance

This document was authored by builder agent `builder-deployment-strategy-doc` for task VIGOR-ef9a (sub-task of VIGOR-c1ab) on 2026-05-15. It synthesizes the VIGOR-4293 scout report (`scout-deployment-survey`) and the existing ADR set as of the same date. The cutoff for external survey claims is 2026-05-14 per the underlying scout report; for internal code anchors, the cutoff is 2026-05-15 (the current commit). Sibling deliverables are cited above where they exist; where they are still in flight, the references say "companion ADR on …" rather than naming a specific document so that file-renames do not break the cross-reference graph.

For the architecture lead's convenience, every recommendation in §"Strategic Recommendations" is anchored to a *file:line* citation that can be opened directly. The classification labels (`foundational`, `tactical`, `observational`, `future`) are stable across the document and feed the seeds backlog (sibling builder VIGOR-a29a) verbatim. Companion ADR drafts (sibling builder VIGOR-a29a) inherit the classification and cite this document as the strategic anchor.

This is a Status: Draft document. Review feedback should land as comments on the file in the parent worktree's review pass; substantive changes (new recommendations, revised classifications, deferred items promoted) trigger a re-version that updates the Status and Date headers.

The expectation is that the document moves to `Status: Accepted` once the parent task VIGOR-c1ab merges and the companion ADRs land; until then, every recommendation here is provisional on the threat-model and ADR drafts agreeing.
