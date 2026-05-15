# ADR-0012: Enforce Cost Ceilings Via AgentBackend Usage Telemetry And A RunBudgetTracker

Status: Proposed

Date: 2026-05-15

## Context

`Budgets.max_cost_usd` has been a declared field of `TaskSpec.budgets` since the
schema was first written (`packages/vigor-core/src/vigor_core/schemas.py:51-58`),
but no code in the runtime reads it. The orchestrator's loop only checks two of
the five `Budgets` fields: `max_iterations` (the `for iteration in range(...)`
header at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:114`) and
`max_wall_clock_s` (the seam at `orchestrator.py:116-118`). `max_cost_usd` and
`max_tool_retries` are paper budgets — present in the contract, absent from the
implementation. The deployment scout survey (VIGOR-4293, finding §3) classifies
this as the cheapest high-impact win in the entire backlog.

The token telemetry that would feed a cost ceiling is already produced by the
agent backends but discarded. The Claude Agent SDK delivers per-turn token
counts inside `ResultMessage`, which the VIGOR backend currently consumes only
to read `subtype == "success" and not msg.is_error` before dropping the rest of
the message on the floor
(`packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:92-95`).
Strands and any future backend exposing usage telemetry are in the same shape:
the data exists, the seam to surface it does not.

ADR-0007 commits VIGOR to an SDK-agnostic core with optional agent backends; a
cost ceiling that lived inside any single backend would either re-introduce the
SDK coupling that ADR forbids, or work for one backend and silently no-op for
the others. ADR-0010 defines `AgentBackend` as the async ABC every backend
implements (`packages/vigor-core/src/vigor_core/interfaces.py`). The cost
ceiling must therefore be a contract on that ABC, with per-backend
implementations that return zero / unknown when the underlying SDK does not
expose usage data.

The hosted-deployment work tracked under VIGOR-c1ab and the threat-modelling
work depending on it cannot proceed credibly while a documented budget field
silently fails open. Operators who configure `max_cost_usd: 5.00` today and
launch a run get no enforcement — the run can spend arbitrary tokens until
`max_iterations` or `max_wall_clock_s` happens to fire.

## Decision

VIGOR will treat cost ceilings as a first-class orchestrator concern, surfaced
through the `AgentBackend` contract and enforced at the same loop boundary that
already enforces `max_wall_clock_s`.

The change has four parts.

1. **Extend the `AgentBackend` ABC** with a `usage()` accessor returning a new
   `Usage` value object:

   ```python
   class Usage(_VigorBase):
       schema_version: Literal["vigor.usage.v1"] = "vigor.usage.v1"
       input_tokens: int = 0
       output_tokens: int = 0
       usd: float | None = None  # None = backend cannot self-price
   ```

   Backends accumulate usage across every `generate / review / propose_patch`
   call and expose the running total via `usage()`. The Claude Agent SDK
   backend reads `ResultMessage.usage` (the existing field currently dropped at
   `backend.py:92-95`); a backend that does not expose token counts returns
   `Usage()` (zeros) and is, by construction, exempt from cost-ceiling
   enforcement — operators who care must use a backend that reports.

2. **Introduce `RunBudgetTracker` in `vigor-runtime`** as a thin sibling to the
   existing wall-clock check, reading `task.budgets.max_cost_usd` once at run
   start and polling each backend's `usage()` at iteration boundaries.

3. **Add `StopReason="cost_exceeded"`** to the closed `Literal` at
   `schemas.py:120-127`. This is a schema bump (the union widens) but no
   backwards-incompatible field rename — existing consumers reading
   `RunResult.stop_reason` keep working; new consumers branch on the new value.

4. **Check at the same seam as wall-clock.** The orchestrator's per-iteration
   guard (`orchestrator.py:116-118`) gains a sibling cost check. Crossing the
   ceiling sets `stop_reason="cost_exceeded"` and breaks the loop the same way
   wall-clock exhaustion does — no in-flight cancellation of the current
   iteration's work, consistent with how `max_wall_clock_s` behaves today.

The check fires only at iteration boundaries, not inside `_candidate_batch` or
inside individual backend calls. This keeps the enforcement seam visible in one
place and avoids racing partial cost updates across concurrent candidate
evaluations. The accepted consequence is that a single iteration can overshoot
the ceiling by up to one iteration's worth of spend — operators who need
tighter bounds set `max_candidates` lower.

## Alternatives Considered

### Alt-A: Where the usage accessor lives — `AgentBackend` ABC vs per-backend opt-in vs orchestrator-side scraping

| Alternative | Reason Rejected |
| --- | --- |
| Per-backend opt-in: backends that want to support cost ceilings declare a `supports_usage = True` class attribute and override an optional method | Silent budget bypass. Operators who switch backends discover at runtime that their declared `max_cost_usd: 5.00` is ignored, which is the failure mode the ADR exists to fix. The contract must be on the ABC so missing implementations are visible at type-check time. |
| Orchestrator-side scraping: the orchestrator wraps each backend in a counter that intercepts every method call and tallies bytes / tokens from request/response shapes | The orchestrator does not see token counts — it sees IR JSON. Backends are the only layer where the SDK exposes the LLM provider's accounting, and that accounting is the only ground truth for `usd`. Scraping reproduces the SDK's tokenizer in the runtime, which ADR-0007 explicitly forbids. |
| External accounting service: ship a separate sidecar that the runtime calls over HTTP for "is this run still under budget" | Adds a hard runtime dependency on an external process for a check that should be local. Rejected on operational grounds — VIGOR is library-first per ADR-0007/ADR-0009 and shipping a coupled service is out of that posture. |
| (Chosen) `AgentBackend.usage()` on the ABC, returning `Usage()` zeros for backends that cannot report | Default-zero degrades open: the cost ceiling silently is never hit. That is the same failure mode as the status quo, which is why the operator-visible signal is the choice of backend: a backend that returns zeros surfaces in `RunResult.usage` (also new) so the operator can see "we ran for 47 iterations against a backend that does not report usage" and react. |

### Alt-B: When to check — iteration boundary vs every backend call vs end of run

| Alternative | Reason Rejected |
| --- | --- |
| Check after every `backend.generate / backend.review / backend.propose_patch` call | Tight bound but adds N checks per iteration where N is candidate count × reviewer count × patch attempts. The check itself is cheap, but the cancellation semantics are not: aborting mid-candidate leaves partial state in `RunArchive` that the orchestrator's reducers (`_evaluate_candidate`) are not designed to handle. Implementable, but the structural change is larger than the per-iteration check by an order of magnitude and Phase-1 should ship the simpler shape. |
| Check only at end of run (post-mortem mode) | Useless — the budget exists to stop spend, not to report it. Rejected without further consideration. |
| (Chosen) Check at iteration boundary, alongside `max_wall_clock_s` | One enforcement seam matching the existing pattern. Bounded overshoot of one iteration's worth of spend is acceptable for the same reason wall-clock overshoot of one iteration is acceptable today. |

### Alt-C: Status quo (do nothing)

| Alternative | Reason Rejected |
| --- | --- |
| Leave `Budgets.max_cost_usd` as paper, document it as "informational" in the schema docstring | Documented budget that does nothing is worse than no budget — operators rely on the field name. Either remove the field (a schema break for any consumer that already references it) or wire it (this ADR). Removing is the worse trade because the budget shape is the right one; only the implementation is missing. |

## Consequences

### Positive

1. The schema's documented budget becomes a real, enforced budget. Operators
   who set `max_cost_usd: 5.00` get the spend cap they configured, terminated
   with a clear `stop_reason`.
2. `AgentBackend.usage()` is a small, contract-level addition that any future
   backend (Strands, custom in-house) must implement. The contract is visible
   at type-check time and lint time, not buried in runtime fallthrough.
3. `RunBudgetTracker` is a single object with a single responsibility — adding
   future budget axes (e.g. `max_tool_calls`, `max_input_tokens`) is a tactical
   extension, not a rearchitecture.
4. Token telemetry that the Claude Agent SDK already produces stops being
   silently discarded. `RunResult.usage` (the new aggregate) becomes a useful
   signal for downstream cost-attribution work even when no ceiling is set.

### Negative

1. **Schema bump.** `StopReason` is a closed `Literal` at `schemas.py:120-127`.
   Adding `"cost_exceeded"` widens the union; any consumer pattern-matching
   exhaustively on `StopReason` (linters, dashboards) must learn the new
   value. The version bump is `vigor.task.v1` → `vigor.task.v2` if we treat
   the union as load-bearing; the runtime can stay on v1 if we treat
   `StopReason` as additive within v1, which is the lighter migration but the
   more debatable call. The implementing builder must decide and document.
2. **Backends without usage telemetry are exempt by construction.** Operators
   running against an in-house backend that returns `Usage()` zeros get no
   enforcement and may mis-read `max_cost_usd` as universal. The mitigation —
   surface the backend's reporting capability in `RunResult.usage` — is
   informational, not preventative. A stricter posture (refuse to start a run
   with a non-reporting backend if `max_cost_usd` is set) is plausible but
   defers to the implementing builder; this ADR does not commit to it.
3. **Bounded overshoot.** Iteration-boundary enforcement allows up to one
   iteration's worth of overspend before the loop exits. For a run with
   `max_candidates: 4` and four expensive critics per candidate, the
   overshoot can be substantial. Operators who care set tighter
   `max_iterations` or `max_candidates`.
4. **Pricing the run is the backend's problem.** `Usage.usd` is `None` when
   the backend cannot self-price (e.g. token counts only, no model name).
   `RunBudgetTracker` then cannot enforce `max_cost_usd` and must either
   degrade to a token-count ceiling (out of scope for this ADR) or fall
   open. Falling open is the documented behavior; operators who need
   guaranteed enforcement use a backend that reports `usd`.
5. **`max_tool_retries` remains unaddressed by this ADR.** The other paper
   budget identified by the scout survey is a sibling problem (retry loop in
   `MCPToolBackend.call_tool`) but architecturally unrelated; bundling them
   would violate the "one decision per ADR" rule. A separate Seeds task
   tracks it.

### Neutral

1. The wall-clock seam at `orchestrator.py:116-118` and the new cost-ceiling
   seam are structurally identical; future budget axes plug into the same
   pattern.
2. Per-tenant cost attribution is a stronger requirement than this ADR
   delivers — `RunBudgetTracker` is per-run, not per-tenant. Aggregating
   across runs is a deployment concern handled by the audit-log work
   (separate ADR / Seeds task).

## References

| Source | Path / URL |
| --- | --- |
| `Budgets` schema (target field `max_cost_usd`) | `packages/vigor-core/src/vigor_core/schemas.py:51-58` |
| Wall-clock enforcement seam (template for cost check) | `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:116-118` |
| Claude SDK backend dropping `ResultMessage` token counts | `packages/vigor-backend-claude-agent-sdk/src/vigor_backend_claude_agent_sdk/backend.py:92-95` |
| `StopReason` closed Literal (target for new `"cost_exceeded"` value) | `packages/vigor-core/src/vigor_core/schemas.py:120-127` |
| ADR-0007 (SDK-agnostic core posture) | `0007-sdk-agnostic-core-with-optional-agent-backends.md` |
| ADR-0010 (async core interfaces — `AgentBackend` ABC) | `0010-async-core-interfaces.md` |
| ADR-0011 (IR schema versioning — pattern for `vigor.usage.v1`) | `0011-ir-schema-versioning.md` |
| Deployment scout survey (finding §3, recommendation #1) | `.overstory/specs/VIGOR-4293.md` |
| Anthropic guidance on cost ceilings in agent harnesses | https://www.anthropic.com/engineering/building-effective-agents |
| Anthropic Claude Agent SDK `ResultMessage.usage` | https://docs.claude.com/en/api/agent-sdk/python |
