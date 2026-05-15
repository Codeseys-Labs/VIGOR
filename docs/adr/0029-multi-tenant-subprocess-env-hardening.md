# ADR-0029: Default-Drop Subprocess Environment For MCP Stdio And Per-Tenant Run Archive Scoping

Status: Proposed

Date: 2026-05-15

## Context

The MCP stdio transport in `vigor-mcp` constructs a subprocess via the
official MCP `StdioServerParameters` and forwards `MCPServerSpec.env` directly
to the child process
(`packages/vigor-mcp/src/vigor_mcp/transports/sdk.py:42-44`):

```python
params = StdioServerParameters(
    command=spec.command[0],
    args=list(spec.command[1:]),
    env=dict(spec.env) if spec.env else None,
)
```

The `dict(spec.env) if spec.env else None` ternary delegates to the underlying
SDK's "None means inherit" semantics. When `MCPServerSpec.env` is unset (or set
to `{}`, depending on the truthiness check), the spawned MCP server inherits
the parent process's full environment: `ANTHROPIC_API_KEY`, `AWS_*`,
`OPENAI_API_KEY`, the operator's shell history paths, anything CI injected.
For a single-tenant, single-operator workstation that is benign. For the
hosted multi-tenant deployment posture VIGOR-c1ab is investigating it is a
direct cross-tenant credential leak: tenant A's request triggers an MCP server
spawn that sees tenant B's keys in its environment. The deployment scout
survey (VIGOR-4293, finding §2 and §5, recommendation #4) flags this as
foundational.

The complementary surface is the run archive. `RunArchive` paths are
namespaced by `run_id` only — there is no tenant axis in `run_dir`,
`candidate_dir`, `reviews_dir`, or `artifacts_dir`
(`packages/vigor-core/src/vigor_core/archive.py:43-60`). Two tenants sharing
an `archive_dir` produce a single flat namespace of `{archive_dir}/{run_id}/`
directories. A path-traversal-safe `_safe_target` exists, but it does not
distinguish tenants — it only refuses to escape the archive root. Multi-tenant
operators today must give each tenant a disjoint `archive_dir` by
configuration; the schema does not require it and the runtime does not
enforce it.

ADR-0014 already gives VIGOR a working isolation primitive in a different
domain: the host-level `allowed_plugin_factory_prefixes` allowlist and
per-`FactoryRef.allowed_prefixes` namespace assertion (verified at
`docs/adr/0014-generalized-agent-config.md:40-42`). Plugin factories cannot
import arbitrary Python modules — they are gated by a two-layer allowlist.
The same posture is missing for MCP subprocess environments and for archive
filesystem layout.

This ADR addresses both surfaces because they have one driver (multi-tenant
isolation), share an enforcement boundary (the per-run `RunContext`
construction site), and would otherwise be split into two near-empty ADRs
that violate the "one decision" rule by accident — the decision is "make
isolation default-deny across these two surfaces".

## Decision

VIGOR will harden two multi-tenant leak surfaces by default-denying inheritance
in both, while preserving operator override for single-tenant local
development.

### 1. MCP stdio environment is drop-all-unless-listed

Change the stdio transport so the subprocess receives an explicitly empty
environment by default, augmented only by a small documented pass-through list.

```python
# packages/vigor-mcp/src/vigor_mcp/transports/sdk.py (sketch, ~5 lines)
_DEFAULT_PASS_THROUGH = ("PATH",)  # PATH is required for command resolution
_env: dict[str, str] = dict(spec.env) if spec.env else {}
for k in _DEFAULT_PASS_THROUGH:
    _env.setdefault(k, os.environ.get(k, ""))
params = StdioServerParameters(command=..., args=..., env=_env)
```

`PATH` is the only inherited variable — it is required because most stdio MCP
servers are CLI shims (`uvx`, `npx`, `python -m foo`) that resolve their own
binaries via `PATH`. Anything else the spawned server needs (`PYTHONUNBUFFERED`,
vendor API keys, locale) the operator declares in `MCPServerSpec.env`. The
existing schema validator (which forbids `env` on http/sse and forbids
`headers` on stdio) is unchanged; only the default at the SDK boundary moves
from "inherit-all" to "drop-all-unless-listed".

This is a **breaking default-change**, not a schema change. Existing
`MCPServerSpec`s that relied on inherit-all (any spec where `spec.env` was
unset and the server expected, say, `ANTHROPIC_API_KEY`) will start failing
with a missing-key error from the server itself. The fix is to declare the
key explicitly in `spec.env`. The migration is documented in the changelog
and surfaced in the schema docstring.

### 2. RunArchive admits an explicit tenant scope

`RunArchive` gains an optional `tenant_id: str | None = None` constructor
argument. When set, every path constructed by `_safe_target` is prefixed with
`{tenant_id}/`:

```text
without tenant: {archive_dir}/{run_id}/...
with tenant:    {archive_dir}/{tenant_id}/{run_id}/...
```

The `tenant_id` is validated against the same `ID_PATTERN` other VIGOR ID
fields use (`schemas.py:44`), so it cannot inject path components. Single-tenant
deployments (the default for local development) leave `tenant_id` unset and
see no behavioral change. Hosted multi-tenant deployments set it per
`AgentOrchestrator` instance (one orchestrator per tenant).

This ADR does not yet require `tenant_id` to be set — it makes the
infrastructure available. Requiring it for hosted deployments is the
deployment-posture decision, tracked in a separate ADR / Seeds task.

### 3. Cite ADR-0014's allowlist as the existing isolation primitive

ADR-0014 established that VIGOR's posture for plugin code-loading is two-layer
allowlist (`allowed_plugin_factory_prefixes` host-level + per-`FactoryRef`
`allowed_prefixes`). This ADR's MCP env hardening is the same posture applied
to a different surface: the parent process declares what crosses the boundary,
the child process gets nothing else. Future surfaces (network, filesystem,
filesystem mounts) follow the same default-deny pattern and reference back to
ADR-0014 + this ADR as the precedent.

## Alternatives Considered

### Alt-A: Subprocess env default — drop-all vs inherit-all vs container-per-task

| Alternative | Reason Rejected |
| --- | --- |
| Container-per-task (Docker / nsjail / Firecracker per MCP server) | Strongest isolation, but out of repo scope: requires a container runtime VIGOR does not currently operate, and adds a hard infrastructure dependency that conflicts with the library-first deployment posture. Tracked as future hardening per `docs/readiness/implementation-readiness.md` row C10 — not this ADR. |
| Keep inherit-all, add a documented warning in the MCP setup guide | Hosted multi-tenant operators discover the leak at the worst possible time (post-incident). Documentation that's only read after a leak is no defense. The default must be safe-by-construction. |
| Require operator to set `env={}` explicitly to opt out of inheritance | Footgun-by-default. The operator who forgets — or the operator who copy-pastes a config from the development laptop where inherit-all is fine — is the operator who leaks. The pattern of "secure default + explicit opt-in to broaden" is the entire premise of ADR-0014's allowlist; we apply it here. |
| (Chosen) Drop-all by default, pass `PATH` only, operator declares everything else in `spec.env` | Aligns the stdio default with the http/sse posture (which already has no inheritance — http/sse explicitly forbids `env`). Migration cost is one-time and visible (existing servers fail loudly when their key is missing) rather than silent (existing servers leak when their key is present). |

### Alt-B: Pass-through list — `PATH` only vs a curated set vs nothing

| Alternative | Reason Rejected |
| --- | --- |
| Pass nothing — not even `PATH`. Operator must set `PATH` explicitly in `spec.env` | The most defensible default in absolute terms, but it breaks every CLI-shim MCP server (`uvx`, `npx`, `python -m foo`) on first run. Friction-to-safety ratio is wrong; almost every operator who hits the failure will set `PATH` to `os.environ["PATH"]` — which is what the default does anyway, so the explicit version adds boilerplate without adding security. |
| A curated set (`PATH`, `HOME`, `LANG`, `LC_*`, `TERM`, `TMPDIR`) | Each addition is a leak surface that must be re-examined per-server. `LANG`/`LC_*` are mostly safe but not always; `HOME` reveals the operator's username; `TMPDIR` interacts badly with sandbox roots. Curating widens the contract, which conflicts with the ADR's premise. |
| (Chosen) `PATH` only | Smallest viable pass-through; gives every CLI-shim server a working default; everything else is operator-declared. The list is a tuple constant in the transport module so future additions go through code review. |

### Alt-C: RunArchive tenant scoping — explicit `tenant_id` vs implicit via `archive_dir` vs schema-required

| Alternative | Reason Rejected |
| --- | --- |
| Implicit via `archive_dir`: instruct operators to give each tenant a disjoint root | Status quo; relies on operator discipline; no defense against misconfiguration. Two tenants sharing a root produce a flat namespace and the runtime cannot detect or warn. |
| Schema-required `tenant_id` on `RunArchive` constructor: no default, every caller must pass | Imposes a single-tenant cost for the multi-tenant case. Local development, examples, and tests would all need a synthetic tenant_id. The friction is high enough that operators will set `tenant_id="default"` everywhere, which gives the appearance of isolation without the property. |
| (Chosen) Optional `tenant_id` with no default; hosted deployments opt in by setting it per-orchestrator | Single-tenant code paths unchanged; multi-tenant operators get a one-line opt-in; the scoping decision is visible at the construction site rather than buried in `archive_dir` configuration. The follow-up ADR for hosted-deployment posture can elevate this to required when the hosted entry point ships. |

### Alt-D: Status quo

| Alternative | Reason Rejected |
| --- | --- |
| Document the leak surface in `SECURITY.md`, take no code action | Same pathology as Alt-A's "documented warning" branch: the operator who needs the warning is the operator who already leaked. Multi-tenant readiness is the parent's deliverable; status-quo blocks it. |

## Consequences

### Positive

1. The hosted-multi-tenant credential-leak surface at the MCP stdio boundary
   closes by default. New MCP server adoptions inherit the safe default;
   existing adoptions fail loudly with a missing-key error rather than
   silently leaking.
2. `RunArchive`'s scoping seam exists for the hosted-deployment ADR to lean
   on. The hosted ADR can mandate `tenant_id` without first introducing the
   primitive.
3. The two-layer-allowlist posture established by ADR-0014 extends to a second
   surface, making "default-deny across boundaries" a recognizable VIGOR
   pattern rather than a one-off.
4. The migration is auditable: any `MCPServerSpec` that was relying on
   inherit-all is visible by greppable absence (`spec.env` unset for a server
   that needs a key); the failure mode is a clear server-side error, not a
   silent change in behavior.

### Negative

1. **Breaking default-change at the SDK boundary.** Every existing
   `MCPServerSpec` that relied on inherited environment for any variable other
   than `PATH` will fail on first run after upgrade. This includes any
   adapter that depends on a vendor-keyed MCP server (Claude Vision via
   `tan-yong-sheng/ai-vision-mcp`, the Gemini-keyed servers from ADR-0016)
   without an explicit `env={"GEMINI_API_KEY": "..."}` block. The migration
   guide must enumerate every official server in ADR-0016 and document the
   required env keys; failing to update the migration guide is itself a
   breaking change for downstream operators.
2. **Tenant-scope is opt-in, not enforced.** A hosted operator who forgets
   `tenant_id` shares a flat archive namespace across tenants. This ADR
   makes the primitive available; the enforcement is deferred to the
   hosted-deployment ADR. A future operator who deploys VIGOR multi-tenant
   without reading both ADRs gets the worst of both worlds.
3. **`PATH` is itself a leak axis.** A parent process with a `PATH` that
   points at operator-private binaries (`/home/operator/bin/...`) reveals
   the operator's username to the spawned server. For hosted deployments,
   `PATH` should be normalized to a known-good system value at the
   orchestrator boot — out of scope for this ADR but called out so the
   threat model captures it.
4. **No drop-in fix for `ClaudeBackendConfig.env`.** The Claude Agent SDK
   backend has its own env-passing surface
   (`packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:80`).
   This ADR addresses the MCP stdio boundary only; the Claude SDK env path
   is a sibling concern with the same shape but a different code path. A
   second pass (separate Seeds task) extends the default-drop posture to
   that boundary.
5. **`RunArchive` change is additive, not migratory.** Existing single-tenant
   deployments see no path layout change. Migration to per-tenant scoping
   is an operator decision and requires backfilling `tenant_id` for
   historical runs (or accepting that pre-migration runs live in the
   un-prefixed namespace). This ADR does not specify the backfill — it is
   either left as-is (acceptable for new deployments) or handled by the
   hosted-deployment migration runbook.

### Neutral

1. The change does not affect http/sse transports; those already forbid `env`
   on `MCPServerSpec` (transport schema enforces it at
   `transports/sdk.py:51-52` and `:61-62`). Posture there is already
   "no inheritance".
2. Per-tenant network isolation, per-tenant rate-limiting, and per-tenant
   quotas are deliberately out of scope for this ADR. They depend on a
   hosted entry point that does not yet exist; addressing them now would
   be retrospective rationalization of code that does not exist.

## References

| Source | Path / URL |
| --- | --- |
| MCP stdio env passthrough (target site) | `packages/vigor-mcp/src/vigor_mcp/transports/sdk.py:42-44` |
| `RunArchive` (target for tenant scoping) | `packages/vigor-core/src/vigor_core/archive.py:43-60` |
| `MCPServerSpec.env` schema (no change required) | `packages/vigor-mcp/src/vigor_mcp/schemas.py` |
| ADR-0014 (allowed_plugin_factory_prefixes — existing isolation primitive) | `0014-generalized-agent-config.md` |
| ADR-0016 (MCP transport posture — § "Vendor auth and rotation") | `0016-official-mcp-servers.md` |
| ADR-0017 (Pure-MCP plugin admission — sibling allowlist surface) | `0017-pure-mcp-plugin-support.md` |
| Deployment scout survey (finding §2, §5, recommendation #4) | `.overstory/specs/VIGOR-4293.md` |
| Implementation-readiness row C10 (container sandbox future hardening) | `docs/readiness/implementation-readiness.md` |
| Anthropic Claude Agent SDK environment passing | https://docs.claude.com/en/api/agent-sdk/python |
| Model Context Protocol stdio transport spec | https://modelcontextprotocol.io/specification |
