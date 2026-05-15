# ADR-0019: Ship VIGOR As Library + CLI; Defer Hosted vigor-server As Downstream Concern

Status: Proposed

Date: 2026-05-15

## Context

VIGOR's deployment surface today is a Python library plus a single CLI entry
point — `vigor-agent run --config agent.yaml task.json`. There is no
`packages/vigor-server`, no Dockerfile in the orchestrator package, no k8s
manifest, no FastAPI/Starlette adapter, no hosted HTTP wrapper. The
`AgentOrchestrator` class at
`packages/vigor-agent/src/vigor_agent/agent.py:18` exposes a single async
entry point — `AgentOrchestrator.run(task: TaskSpec) -> RunResult`
(line 81) — and `vigor-runtime`'s `_AgentOrchestrator.run` at
`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:88` is the
analogous internal seam. The deployment scout survey (VIGOR-4293) classifies
this state as "library + CLI" with no hosted-service infrastructure
(survey §"Executive Summary" and §1; recommendation #5 explicitly asks the
strategic deep-dive to commit one way or the other).

The strategic deep-dive (parent VIGOR-c1ab) faces a forking decision: either
ship `packages/vigor-server` with FastAPI/Starlette + auth and commit to a
hosted-service maintenance burden, or document explicitly that VIGOR is
library-first and that production hosting is a downstream concern owned by
operators or by a separate (currently nonexistent) project. The current
README implicitly favors library-first; nothing yet codifies it. Without an
explicit commitment, sibling ADR work cannot make consistent decisions:
ADR-0012's cost ceiling, ADR-0013's tenant scoping, the audit-log ADR (Seeds
task), and the threat-model deliverable all need to know whether they are
designing for a single-process library or a hosted multi-tenant service.

This ADR is intentionally narrow. It does **not** decide:

- Whether `packages/vigor-server` is ever built (it can be, downstream).
- Whether VIGOR ships Docker images (a separate Seeds task tracks `Dockerfile`).
- The audit-log schema or PII redaction approach (separate ADRs / Seeds).
- Multi-tenant authentication (out of scope without a hosted entry point).

It decides one thing: VIGOR's supported public surface is the Python library
(specifically `AgentOrchestrator.run` and the schemas it consumes/produces)
plus the CLI. Hosting on top of that surface — whether by VIGOR maintainers,
operators, or downstream forks — is explicitly a separate concern and not
part of this ADR's commitments.

## Decision

VIGOR is committed to a **library-first** deployment posture for the
foreseeable future. Concretely:

1. **The supported public surface is `AgentOrchestrator.run(task) -> RunResult`**
   plus the pydantic schemas that flow across that boundary (`TaskSpec`,
   `RunResult`, `Budgets`, `StopReason`, `ProvenanceRecord`, `AdjudicationReport`,
   `ExportBundle`, and the IR types per ADR-0011's versioning rules). Anything
   else — `_AgentOrchestrator` private internals, adapter-internal helpers,
   transport-layer plumbing — is unsupported surface and may change without an
   ADR. ADR-0007's SDK-agnostic-core principle already implies this; this ADR
   makes it explicit.

2. **The CLI (`vigor-agent run`) is the supported integration surface for
   non-Python callers.** Operators who want to invoke VIGOR from a different
   language or process model use the CLI's JSON-in / JSON-out contract, not a
   custom wrapper. The CLI's input is `TaskSpec` (validated against the
   schema); its output is `RunResult` (validated against the schema). The
   subprocess boundary is the documented integration point.

3. **A hosted HTTP wrapper (`packages/vigor-server`) is an explicitly
   deferred downstream concern.** It is acceptable to build one outside this
   repo; it is acceptable to build one inside this repo as a separate
   package; either way it is a downstream choice that does not block any
   other VIGOR work. The strategic deep-dive (VIGOR-c1ab) need not commit to
   delivering one. If it ever lands, it is a thin adapter on top of
   `AgentOrchestrator.run` — not a rearchitecture.

4. **Operational concerns (rate limiting, tenant authentication,
   request-level logging, signed audit chains, container builds) are
   downstream of this ADR.** They belong on whatever hosting layer wraps
   `AgentOrchestrator.run`. The `AgentBackend` and `ToolBackend` ABCs already
   give that layer the seams it needs (per ADR-0007 and ADR-0010); the
   library does not pre-build for them.

5. **Library-first does not mean "no hardening".** ADR-0012 (cost ceilings),
   ADR-0013 (multi-tenant subprocess env), the audit-log ADR, and the
   threat-model deliverable all do real work. The point of this ADR is that
   they target the library surface and the seams a hosting layer would
   consume — not a hosted entry point that the library does not own.

The decision is consistent with ADR-0007's "SDK-agnostic core with optional
agent backends" stance and with ADR-0009's "single UV monorepo" layout: the
project is a published Python distribution, not a hosted service.

## Alternatives Considered

### Alt-A: Library-first vs ship-vigor-server vs hybrid

| Alternative | Reason Rejected |
| --- | --- |
| Ship `packages/vigor-server` now: FastAPI app + auth middleware + Dockerfile + k8s manifest + hosted-service maintenance burden | Forces multi-tenant decisions (auth, rate limiting, audit, cost attribution, request logging) into the critical path of every other ADR. The team currently making decisions for VIGOR-c1ab is sized for the library, not for a hosted service; committing to "ship a hosted service" without the operational foundation produces a half-built service that is worse than no service. The auth surface alone (OAuth2 + tenant management + key rotation) is months of work that the project has not staffed. |
| Hybrid: ship a minimal `vigor-server` skeleton (uvicorn + one endpoint, no auth, no rate limit) and call it "experimental" | Worst of both. Operators discover the skeleton, deploy it as if it were production-ready, and the security failures are then VIGOR's failures rather than the operator's. ADR-0016's "officially supported" five-criteria contract exists exactly because experimental-status software gets deployed; we should not repeat the pattern at the deployment layer. |
| Defer the question entirely; let it linger | Sibling ADRs (cost ceiling, multi-tenant isolation, audit log) cannot make consistent decisions without knowing what they are designing for. The cost of leaving the question open exceeds the cost of writing this ADR. |
| (Chosen) Library-first: lock the public surface as `AgentOrchestrator.run` + CLI, defer hosted wrapper as a separate downstream concern | Matches the actual code today, the actual maintenance capacity, and the design ADR-0007 already committed to. Frees sibling ADRs to design against the library boundary. Does not preclude `vigor-server` ever existing — a future ADR can supersede this one if the project's posture changes. |

### Alt-B: Public surface — whole package vs `AgentOrchestrator.run` vs a smaller subset

| Alternative | Reason Rejected |
| --- | --- |
| Treat the entire `vigor-agent` and `vigor-runtime` public Python API as supported surface | Includes private helpers, internal builders, factory machinery. Pinning all of that as supported means breaking changes require an ADR even for refactors that change nothing observable from outside the run. ADR-0011 already pins schema-version compatibility at the IR boundary; the library surface should be consistent — pin the entrypoint and the schemas, leave everything else free to refactor. |
| Pin a smaller subset — only `TaskSpec` in / `RunResult` out, no `AgentOrchestrator` class | Implementer-flexible but means there is no Python entry point that operators can pin. They would have to use the CLI exclusively, which is the wrong default for a Python library. The class is small, the surface is small, pinning it costs little. |
| (Chosen) `AgentOrchestrator.run(task) -> RunResult` plus the schemas it touches, plus the CLI's JSON-in/out contract | Smallest pinnable surface that supports both Python callers (use the class) and non-Python callers (use the CLI). Refactors of internals — `_AgentOrchestrator`, candidate batching, adapter registration — remain unblocked by ADR. |

### Alt-C: Documentation only vs ADR-recorded

| Alternative | Reason Rejected |
| --- | --- |
| Add a "Deployment posture" section to `README.md` and `docs/strategy/deployment-and-ops.md` and call the question settled without writing an ADR | A README section is editable without consensus; an ADR is not. The decision binds future architectural work — sibling ADRs reference it. Recording the decision as an ADR makes the binding visible and the override path explicit (write a superseding ADR). |
| (Chosen) Record as ADR-0019 with explicit deferral language | Same posture as ADR-0017 ("admit pure-MCP plugins") and ADR-0016 ("official MCP servers"): commitments that constrain future work get ADRs. |

## Consequences

### Positive

1. Sibling ADRs (cost ceiling, tenant scoping, audit log, threat model) have a
   stable target to design against. "Design for the library surface" is a
   concrete constraint; "design for whatever VIGOR ends up being" is not.
2. The maintenance contract is honest. The team can deliver on a library +
   CLI; it cannot currently deliver on a hosted multi-tenant service. The
   ADR aligns the public commitment with the maintenance capacity.
3. Downstream operators who want a hosted wrapper can build one without
   waiting for VIGOR to ship it. The library's supported surface is exactly
   what they need to wrap.
4. ADR-0007's SDK-agnostic posture and ADR-0009's monorepo layout are
   reinforced rather than undermined. A hosted service inside this monorepo
   would have pulled VIGOR toward a different deployment shape; deferring
   keeps the centre of gravity on the library.
5. The pinning is narrow (one method + the schemas), so internal refactors
   remain ADR-free. Only changes to `AgentOrchestrator.run`'s signature, the
   CLI contract, or the surfaced schemas need an ADR.

### Negative

1. **Operators expecting a hosted service get a "build it yourself" answer.**
   For users coming from frameworks that ship a hosted server out of the box
   (Goose, Hermes Backend, Strands' future hosted offering), this is friction
   they may not tolerate. The library-first answer is correct given the
   team's capacity, but it is genuinely less convenient than a shipped
   `vigor-server` would be. Adoption stories that rely on "deploy this URL"
   are weaker.
2. **Some integration patterns are awkward.** Webhooks, async job queues,
   browser-driven UIs, and similar "long-lived process talks to VIGOR over
   HTTP" patterns require operators to write the HTTP layer themselves.
   Several will write incompatible variants, and the ecosystem will fragment
   exactly where a shipped wrapper would have provided one canonical shape.
3. **The CLI becomes a load-bearing integration surface.** Stability of the
   CLI's flag set, exit codes, and stdout/stderr contract is now part of the
   supported surface. Breaking changes to the CLI require an ADR. This
   raises the bar on CLI hygiene.
4. **The deferred ADR temptation.** Future contributors may notice every
   sibling ADR pointing at "the hosted layer" and decide to ship that hosted
   layer to close the gap. Without explicit re-deciding (a superseding ADR),
   that drift is exactly the failure mode this ADR exists to prevent.
   Mitigation: every PR that adds runtime concerns naturally belonging in a
   hosting layer (rate limit primitives, request-id propagation, etc.) gets
   reviewed against this ADR.
5. **Threat-model scope.** The threat model produced under VIGOR-c1ab is
   constrained to the library + CLI surface and cannot speak to threats
   that only emerge in a hosted service. This is the correct scoping but
   means downstream operators are responsible for their own hosting-layer
   threat model. The threat-model document must say so explicitly.

### Neutral

1. The CLI's `vigor-agent run --config agent.yaml task.json` surface is
   already supported in practice; this ADR does not change behavior, only
   commitment level.
2. A future ADR can supersede this one if the project's capacity or strategy
   changes. The supersession path is the standard one — write a new ADR,
   flip this one's status to `Superseded by ADR-NNNN`. No special handling.
3. Containers, k8s manifests, Helm charts, terraform modules, and similar
   infrastructure-as-code artifacts are all downstream concerns. Shipping
   them would not change the library surface; not shipping them does not
   change it either. They remain in the "operator owns" bucket.

## References

| Source | Path / URL |
| --- | --- |
| `AgentOrchestrator.run` (locked public surface) | `packages/vigor-agent/src/vigor_agent/agent.py:81` |
| `_AgentOrchestrator.run` (internal seam) | `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:88` |
| `TaskSpec` / `RunResult` schemas | `packages/vigor-core/src/vigor_core/schemas.py` |
| ADR-0007 (SDK-agnostic core posture — premise) | `0007-sdk-agnostic-core-with-optional-agent-backends.md` |
| ADR-0009 (single UV monorepo layout — premise) | `0009-monorepo-layout.md` |
| ADR-0012 (cost ceilings on the library surface — sibling) | `0012-cost-ceiling-enforcement.md` |
| ADR-0013 (multi-tenant subprocess env hardening — sibling) | `0013-multi-tenant-subprocess-env-hardening.md` |
| Deployment scout survey (recommendation #5) | `.overstory/specs/VIGOR-4293.md` |
| `docs/readiness/implementation-readiness.md` row C10 (container sandbox = future hardening) | `docs/readiness/implementation-readiness.md` |
| Anthropic guidance on agent harness shapes | https://www.anthropic.com/engineering/harness-design-long-running-apps |
