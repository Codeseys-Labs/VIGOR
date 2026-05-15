<!-- written-by: builder-runtime-strategy -->
# VIGOR Runtime Completeness — What Production-Readiness Requires

Status: Draft for review
Date: 2026-05-15
Audience: VIGOR architecture lead, downstream integrators considering VIGOR as a product foundation, sibling builders writing the deployment ADRs (VIGOR-c1ab) and threat model (VIGOR-f44c).
Parent task: VIGOR-7724 (strategic deep-dive on vigor-runtime production-readiness).
Companion deliverables: ADRs 0034–0037 (this branch); Seeds backlog (this branch); deployment ADRs 0028/0029/0030 + `docs/strategy/deployment-and-ops.md` (sibling branch, already merged).

---

## Executive Summary

VIGOR's runtime today (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py`) is **structurally complete for sequential single-process runs**. Phases 1–6 of the roadmap (`docs/roadmap.md`) are shipped: schema, async ABCs (ADR-0010), best-of-N from `Budgets.max_candidates` (`orchestrator.py:114-275`), patch loop, frontier selection, run archive (`packages/vigor-core/src/vigor_core/archive.py`), and the meta-harness outer loop (Phase 6). What is **not** structurally present is anything that would let a downstream operator productize VIGOR: parallel candidate evaluation, checkpoint/resume, partial-result streaming, cancellation propagation, observability instrumentation, and a documented stance on distributed orchestration.

The eight production-readiness questions VIGOR-7724 enumerates split cleanly into three groups:

- **Already addressed by sibling work.** Q4 cost-attribution-per-candidate is the body of ADR-0028 (cost ceilings via `AgentBackend.usage()` and `RunBudgetTracker`). Re-deciding it here would create a sibling-ADR conflict; this document only references it.
- **Decided here as ADRs.** Q1 parallel best-of-N (ADR-0034), Q2 distributed orchestration posture (ADR-0035), Q3 checkpoint/resume (ADR-0036), Q5 observability seam (ADR-0037). Each is foundational enough that a Seeds task without an ADR would risk re-litigation.
- **Filed as Seeds without an ADR.** Q6 partial-result streaming, Q7 cancellation propagation, Q8 backpressure / batched-eval queue management. Each has an obvious shape (an `AsyncIterator` adapter, an `asyncio.CancelledError` propagation pass, and a queue primitive in the meta-harness) but does not require an ADR-level commitment — they extend the existing surface without changing its public contract.

The strategic posture this document recommends is: **(1)** ship parallel best-of-N inside the existing `_candidate_batch` seam (`orchestrator.py:252-275`) gated by a `Budgets.parallel_candidates` cap, treating budgets as the same enforcement axis as wall-clock; **(2)** explicitly defer distributed orchestration to a future `vigor-server` (consistent with ADR-0030 library-first), documenting VIGOR-as-library as **single-node by contract** so the archive's filesystem locking story stays simple; **(3)** wire checkpoint/resume on top of the existing per-iteration `RunArchive` writes, treating mid-run resume as "re-enter the loop with the highest-iteration candidate set"; **(4)** add an OpenTelemetry-shaped `RuntimeObserver` interface as an opt-in seam — no hard `opentelemetry` dependency in `vigor-core` or `vigor-runtime`. The ordering is the same enforcement-cost ordering ADR-0028 already established: paper budgets first (Q1), then defer-and-document (Q2), then state-shape extensions (Q3), then observation seams (Q5).

The deferred items (Q6–Q8) are tactical Seeds. None of them block a v1.0 cut; all of them are valuable polish.

---

## Current Runtime Surface

This section anchors recommendations against the **2026-05-15 worktree commit**. Every `path:line` reference can be opened directly. The internal-survey style follows `docs/strategy/deployment-and-ops.md` (sibling deliverable) — synthesis over re-derivation.

### Concurrency Model

The runtime uses `asyncio` end-to-end (ADR-0010). Within a single run, concurrency is exercised in exactly **one** place:

- `Orchestrator._run_reviewers` (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:443-511`) calls `asyncio.gather(adapter_reviews(), backend_review())` to fan out the adapter's deterministic reviewers and the agent backend's model-critic concurrently. This is confirmed by mulch record `mx-bc5801` ("Orchestrator.run uses asyncio.gather exactly once: orchestrator.py:507").

Everything else is sequential by construction:

- **Candidate generation** is a `for _ in range(max(1, task.budgets.max_candidates))` loop calling `await self._backend.generate(...)` in series (`orchestrator.py:262-275`). Each `generate` call blocks the next, so a backend with a 30s p95 latency at `max_candidates=4` produces a 120s lower bound on the iteration even if every candidate is independent.
- **Candidate evaluation** is a `for ir in candidates: outcome = await self._evaluate_candidate(...)` loop (`orchestrator.py:122-128`). Evaluation includes compile + reviewer-fanout, both of which are CPU- and I/O-bound; running them sequentially across candidates is the largest single source of wall-clock cost in the current runtime.
- **Iteration boundary** is the budget-enforcement seam (`orchestrator.py:114-118`). The wall-clock check fires once per iteration; the cost ceiling (ADR-0028) plugs into the same spot.

`Budgets.max_candidates` is the surface that *would* govern parallelism; today it only governs sequential count.

### Persistence Model

`RunArchive` (`packages/vigor-core/src/vigor_core/archive.py:43-180`) is filesystem-backed. Writes are per-record JSON files with path containment (`_safe_target` at `archive.py:170-180`):

- `task.json` and `adapter_manifest.json` at run root.
- Per-candidate: `ir.json`, `compile_result.json`, `adjudication.json`, `patch_plan.json`, plus a `reviews/` directory (`archive.py:78-122`).
- `frontier.json` at run root (`archive.py:124-129`).
- `final/{export_bundle.json,provenance.json}` written only on `accepted=True` (`archive.py:131-143`).
- `errors/{error_id}.json` for `RuntimeErrorRecord`s (`archive.py:163-168`).

What is **not** present:

- **No iteration-checkpoint marker.** A reader of an archive cannot tell, from the filesystem alone, "iteration 3 completed; iteration 4 was in progress when the process died" without scanning candidates and inferring from filename patterns.
- **No write-ahead intent log.** A patch is written by `write_patch` after `propose_patch` succeeds; there is no record that a patch was *attempted* between `propose_patch` returning and `write_patch` finishing. Recovery from a crash mid-`write_patch` is by inspection.
- **No cross-process locking.** `_safe_target` rejects path traversal but does not prevent two processes opening the same `archive_dir` and writing to the same `run_id`. The current single-CLI entry point makes this safe by convention.
- **No archive schema version.** The archive's directory layout is implicit. Renaming `candidates/` to `attempts/` would break every reader, but the archive does not declare a version that readers could pin against.

### Cancellation Surface

The CLI wraps `agent.aclose()` in a `finally` block (`packages/vigor-runtime/src/vigor_runtime/cli.py:52`). That is the entire cancellation story. Inside the orchestrator:

- The run loop has no `try/except asyncio.CancelledError` handler. A Ctrl-C during the inner `await self._evaluate_candidate(...)` propagates up, the `finally: await self._backend.aclose()` at `orchestrator.py:212-214` fires (good), and the run terminates with an unhandled exception trace.
- MCP subprocess teardown is best-effort: `MCPToolBackend.aclose` is invoked via `agent.aclose()` only if the caller wraps it. The orchestrator does not own the `ToolBackend` (it receives one in `__init__`), so the orchestrator cannot close it.
- There is no `StopReason="cancelled"` literal. A user-cancelled run terminates as an exception, not as a clean `RunResult`.

The deployment-and-ops doc (sibling, lines 533-541) flags `"cancelled"` as a literal-extension TODO; the present document elevates it to a Seeds task (VIGOR-a386, see backlog).

### Observability Surface

There is no instrumentation at all. The runtime emits:

- `RunArchive` JSON files (state, not telemetry).
- `RunResult` returned from `run` (terminal aggregate, not progressive).
- Nothing else. No `logging` calls, no `print` statements, no metric counters, no spans.

For a library user wanting "tell me when iteration 3 finishes", the only path today is to wrap the orchestrator and poll the archive directory. That is the right shape for a pure library, but it is hostile to any productized hosting layer (`vigor-server` per ADR-0030) and to development debugging.

### Cost Telemetry Surface

ADR-0028 commits to `AgentBackend.usage()` returning a `Usage` value object. That ADR does **not** discuss per-candidate attribution: the ceiling is per-run. Per-candidate attribution (Q4 in the task spec) is **structurally enabled** by ADR-0028 — backends already see candidate-scoped requests — but no ADR has committed to recording the per-candidate `Usage` slice into the archive. This document treats Q4 as an **extension to ADR-0028's implementation Seeds** (VIGOR-344f), not a new ADR.

### Backpressure / Queue Surface

The harness use case (Phase 6, `docs/roadmap.md:85-96`) runs the orchestrator over many `TaskSpec` files. The current evaluator is implicitly serial (the harness calls `await orchestrator.run(task)` per task in a loop). There is no shared queue, no per-tenant rate cap, no backpressure when the eval set is large enough that the agent backend rate-limits. Operators today work around this by running fewer tasks at a time; the runtime offers no primitive.

---

## The Eight Questions: Strategic Recommendations

Each question is classified following the deployment-and-ops convention: `foundational` (must be decided before v1.0), `tactical` (clear shape, defer to Seeds), `observational` (worth recording but not blocking), `future` (downstream of this ADR set).

### Q1: Parallel best-of-N — *foundational*

**Question.** What's the right concurrency model for evaluating candidates? `asyncio.gather` vs process pool? How does it interact with budgets?

**Recommendation.** `asyncio.gather` with a `Budgets.parallel_candidates` cap. **Not** a process pool. **ADR-0034** records the decision in detail; the executive answer is:

- Generation is I/O-bound (LLM API calls). `asyncio.gather` is the right primitive — process pools serialize on the GIL only when CPU-bound, which agent generation is not.
- Compile + adapter reviewers can be CPU-bound (rawpy, OpenSCAD, Manim subprocesses). Adapters that are CPU-bound should already be releasing the GIL (subprocess calls do); adapters that aren't are out-of-tree concerns. The runtime does not mandate a process pool to compensate.
- Budget interaction: the cost ceiling check (ADR-0028) and the new wall-clock check both run at iteration boundaries. Parallel candidate evaluation does **not** move the enforcement seam — the iteration is still the unit. The accepted consequence is bounded overshoot of one parallel batch's worth of spend.

The fanout site is the existing `_candidate_batch` and the inner `for ir in candidates` loop in `Orchestrator.run` (`orchestrator.py:122-128, 252-275`). The new control knob is `Budgets.parallel_candidates: int = 1` (default 1 preserves current sequential behavior; raising the cap enables the new parallelism). See ADR-0034 for the alternatives table and the bounded-overshoot consequence analysis.

**Anchors.** `orchestrator.py:114-275`; `schemas.py:51-58`; ADR-0034.

### Q2: Distributed orchestration — *foundational*, defer-and-document

**Question.** Can multiple Orchestrators share an archive? Cross-process locking? Or do we explicitly defer this and document VIGOR as single-node?

**Recommendation.** Explicitly defer. **ADR-0035** declares VIGOR-the-library is **single-node by contract**: one orchestrator process per `archive_dir`. No cross-process locking primitive. No distributed coordination. The one-line rule: **the archive directory is private to one orchestrator process**.

This is consistent with ADR-0030's library-first commitment. A future hosted `vigor-server` may add tenant-scoped archives (sibling ADR-0029 §"Per-Tenant Run Archive Scoping") and lease-based coordination across replicas; that work is **not** library work. Building cross-process locking into `RunArchive` today would pull VIGOR toward a deployment shape it has not committed to, in service of a use case (multi-replica `vigor-server`) that ADR-0030 explicitly defers.

The mitigation surface — surfacing the constraint to operators — is two-part:

1. `RunArchive.__init__` acquires a process-lifetime advisory lock on `archive_dir/.archive.lock` at archive open. A second orchestrator process opening the same directory raises `ArchiveLockedError`. This is a guardrail, not a coordination primitive.
2. The library's published surface (`AgentOrchestrator.run` per ADR-0030) documents that two simultaneous runs in the same process are unsupported. The CLI invokes one run per process invocation; the library user is on their honor.

See ADR-0035 for the alternatives table — including why we are not building lease-based locking and not switching to a database backend for the archive.

**Anchors.** `archive.py:43-180`; ADR-0030; ADR-0035.

### Q3: Checkpoint/resume mid-run — *foundational*

**Question.** How do we serialize partial loop state so a long run can survive process restarts? Archive already persists per-iteration; what's missing?

**Recommendation.** Add a per-iteration `iteration_checkpoint.json` written at the *end* of each iteration's evaluation, then add a `resume_run_id: str | None` field to `TaskSpec` (or, alternatively, an explicit `Orchestrator.resume(run_id)` entry point — see ADR-0036 for the alternatives). On resume, the orchestrator loads the most recent `iteration_checkpoint.json`, rehydrates `prior` and `current_ir`, and re-enters the run loop at the next iteration.

Three subtleties drive the decision:

- **Checkpoint shape.** The orchestrator's per-iteration mutable state is `iteration` (int), `prior: list[ArtifactIR]`, `current_ir: ArtifactIR | None`, `activities: list[ProvenanceActivity]`, `adjudications: list[AdjudicationReport]`, `last_candidate_id`, `last_export`, `accepted`, `stop_reason`. All but the first are already represented as JSON-serializable Pydantic models or simple lists. The checkpoint is a thin envelope around them — no new modeling, no new persistence layer.
- **Atomicity.** `iteration_checkpoint.json` is written atomically (via `write + os.replace`) at the *end* of an iteration's evaluation, after all candidate JSONs are durable. A crash mid-iteration leaves the previous checkpoint as the resume point; the orphaned partial-iteration candidates are surfaced by `iteration_checkpoint.next_iteration` mismatching the candidate filenames, and the orchestrator's resume path tolerates them.
- **Backend identity.** Resuming a run after the agent backend's session has expired (Claude Agent SDK token rolled, MCP server restarted) is impossible by construction — the conversation context is gone. ADR-0036 declares resume is **runtime-state resume, not session resume**: the new run gets a fresh backend, the prior IR list is the only context that survives.

ADR-0036 records the alternatives — including why we are not using the `provenance.json` as the resume point (it is written only on success), why we are not introducing a write-ahead log (overkill for the failure modes we observe), and why resume is **opt-in** (the default is "if a run dies, start over").

**Anchors.** `orchestrator.py:88-250`; `archive.py:131-143`; ADR-0036.

### Q4: Cost attribution per candidate — *tactical*, depends on ADR-0028

**Question.** Token count, wall-clock, MCP call count tracked per candidate so users can see expensive paths.

**Recommendation.** Extend ADR-0028's `Usage` value object with a per-candidate slice, recorded into `archive.candidate_dir(run_id, candidate_id) / usage.json` at the same point `_evaluate_candidate` writes the adjudication. Add `RunResult.usage_per_candidate: dict[str, Usage]` for the aggregate view.

This is **not a new ADR** — it is an extension to the implementation Seeds for ADR-0028 (VIGOR-344f). The ADR commits to per-run aggregation; the per-candidate slice is the same data with a finer-grained accumulator. ADR-0028's `AgentBackend.usage()` accessor already sees candidate-scoped requests by virtue of being called inside `_candidate_batch` and `_evaluate_candidate`. Adding a snapshot-before / snapshot-after pair around each candidate's work is mechanical.

The Seeds task (filed in this branch's backlog) extends VIGOR-344f's acceptance criteria with two new items: per-candidate `usage.json` write site, and `RunResult.usage_per_candidate` field. It does **not** open a new ADR.

**Anchors.** `orchestrator.py:277-354`; ADR-0028.

### Q5: Observability — *foundational*

**Question.** OpenTelemetry traces? Structured logging conventions? Prometheus metrics? What's the minimal viable instrumentation?

**Recommendation.** Add a `RuntimeObserver` Protocol (Python `typing.Protocol`, not ABC — duck-typed for non-VIGOR consumers) with a small fixed surface: `on_run_start`, `on_iteration_start`, `on_candidate_start`, `on_candidate_end`, `on_iteration_end`, `on_run_end`, plus an `on_event(name, attributes)` escape hatch. **ADR-0037** records the decision.

Crucial design point: **`vigor-core` and `vigor-runtime` do not depend on `opentelemetry`.** The Protocol is an opt-in seam; an OpenTelemetry-emitting `Observer` lives in a separate `vigor-observability-otel` package (or downstream). Per ADR-0007 SDK-agnosticism, the runtime cannot ship a hard dependency on a specific telemetry SDK; per ADR-0030 library-first, observability sinks are deployment-time choices.

Logging conventions: a single `logging.getLogger("vigor.runtime")` plus structured `extra` fields (run_id, iteration, candidate_id) at INFO level for life-cycle events, DEBUG for per-call timing. No JSON formatter in the library — that is a deployment choice (the `vigor-server` package, when it lands, will configure one).

Metrics: not in the runtime. Metrics are aggregations of observer events; producing them is an `Observer` implementation's job, not the runtime's. The deployment-and-ops sibling doc (lines 484-499) commits to Prometheus at the `vigor-server` layer; this ADR is consistent with that commitment.

ADR-0037 records the alternatives — including why we are not adopting OpenTelemetry's `tracer.start_as_current_span` directly (it would force the dependency), why we are not using a global default observer (silent telemetry is worse than none), and why we are not making `Observer` an ABC (Protocol matches Python's structural typing better for opt-in seams).

**Anchors.** `orchestrator.py:88-250`; ADR-0007; ADR-0030; ADR-0037; deployment-and-ops.md §"Observability And Telemetry".

### Q6: Partial-result streaming — *tactical*, defer to Seeds

**Question.** Async generators that emit candidates as they're produced, instead of returning a single `RunResult` at the end?

**Recommendation.** File as Seeds, not an ADR. The shape is obvious — add `Orchestrator.run_streaming(task) -> AsyncIterator[RunEvent]` alongside the existing `Orchestrator.run` — and it does not violate any architectural commitment. `RunEvent` is a discriminated union: `IterationStarted`, `CandidateGenerated`, `CandidateEvaluated`, `IterationEnded`, `RunEnded`. The existing `Orchestrator.run` becomes the consumer of `run_streaming`'s events for callers who want the aggregate.

The reason this is a Seeds task and not an ADR: the public contract (`AgentOrchestrator.run` returning `RunResult` per ADR-0030) does not change, and `run_streaming` is purely additive. There is no "alternatives considered" worth a 200-line ADR; the alternative ("return events via an `Observer` only") is captured as a one-line note in the Seeds task.

The Seeds task is **VIGOR-7086** (see backlog). Implementation effort estimate: 1–2 days for a builder familiar with async iterators.

**Anchors.** `orchestrator.py:88-250`; ADR-0030; ADR-0037 (the Observer seam is the natural source of stream events).

### Q7: Cancellation propagation — *tactical*, defer to Seeds

**Question.** User Ctrl-C / asyncio cancellation reaching adapters and MCP servers cleanly.

**Recommendation.** File as Seeds. Three concrete sub-actions:

1. Wrap the run loop in `try / except asyncio.CancelledError` and convert to `stop_reason="cancelled"`, return a partial `RunResult` (with `accepted=False`).
2. Add `"cancelled"` to the `StopReason` `Literal` (`schemas.py:120-127`). This is a schema bump but additive — sibling to ADR-0028's `"cost_exceeded"` extension.
3. Ensure the existing `finally: await self._backend.aclose()` (`orchestrator.py:212-214`) is also reached when the orchestrator does not own the `ToolBackend` — the contract change is "the *caller* of `Orchestrator.run` is responsible for closing the `ToolBackend`," which is already how the CLI uses it (`cli.py:52`); we just document the contract.

This is mechanical work that does not warrant an ADR-level commitment beyond what ADR-0028 already established for `StopReason` extension. The Seeds task is **VIGOR-a386** (see backlog).

**Anchors.** `orchestrator.py:88-250`; `cli.py:52`; deployment-and-ops.md §"Migration And Backwards Compatibility" (which already flags `"cancelled"` as a planned extension).

### Q8: Backpressure / queue management for batched eval — *tactical*, defer to Seeds

**Question.** Queue management for the harness use case (Phase 6 evaluator) so a large eval set does not saturate the agent backend or blow the cost ceiling.

**Recommendation.** File as Seeds. The right primitive is an `asyncio.Semaphore`-gated runner in the harness package (`packages/vigor-harness`, when it ships — Phase 6 currently has only the evaluator) that runs *N* concurrent `Orchestrator.run` calls and propagates per-task budget enforcement up to a per-batch budget cap. ADR-0028's `RunBudgetTracker` extends naturally to a `BatchBudgetTracker` with the same iteration-boundary check pattern.

This is **harness-layer** work, not runtime work. The runtime's `Orchestrator.run` is the unit of concurrency; how many of them run at once is a deployment-time concern. Filing as an ADR would over-commit; filing as Seeds keeps the option open. The Seeds task is **VIGOR-1029** (see backlog).

**Anchors.** Phase 6 in `docs/roadmap.md`; ADR-0028; harness package (not yet in tree).

---

## Recommendations Table

| ID | Question | Classification | Decision Mechanism | Reference |
| --- | --- | --- | --- | --- |
| Q1 | Parallel best-of-N | foundational | ADR-0034 | this branch |
| Q2 | Distributed orchestration | foundational | ADR-0035 (defer) | this branch |
| Q3 | Checkpoint / resume mid-run | foundational | ADR-0036 | this branch |
| Q4 | Cost attribution per candidate | tactical | extend Seeds VIGOR-344f | sibling branch ADR-0028 |
| Q5 | Observability seam | foundational | ADR-0037 | this branch |
| Q6 | Partial-result streaming | tactical | Seeds VIGOR-7086 | this branch backlog |
| Q7 | Cancellation propagation | tactical | Seeds VIGOR-a386 | this branch backlog |
| Q8 | Backpressure / batched eval | tactical | Seeds VIGOR-1029 | this branch backlog |

---

## What This Document Does Not Decide

- **The `vigor-server` HTTP wrapper.** ADR-0030 has already committed to library-first; this document is consistent with that.
- **Multi-tenant authentication.** Out of scope for any library-level ADR. Consumed by sibling threat model (VIGOR-f44c) only.
- **Tool-backend retry semantics.** Already filed as Seeds VIGOR-2585 (sibling backlog). Out of scope for runtime-completeness.
- **Audit-log schema.** Already filed as Seeds VIGOR-a171 (sibling backlog) per ADR-0029. The observability seam in ADR-0037 is **operational telemetry, not audit** — they share insertion points, but `Observer` events are sampled and lossy by design; audit events are append-only and hash-chained.
- **The order in which these ADRs are implemented.** The Seeds backlog (`docs/strategy/runtime-completeness-backlog.md`) pins priorities; the implementation order is a coordinator decision.

---

## Reading Guide

A reader pressed for time should read, in order: §"Executive Summary", §"The Eight Questions" Q1–Q8, §"Recommendations Table". Everything else is supporting context.

The "Current Runtime Surface" section is dense with `path:line` anchors and is meant to be read with the codebase open. The eight question sections each end with `**Anchors.**` listing the file:line citations that ground the recommendation. ADRs 0034–0037 inherit those anchors; the Seeds backlog inherits them too.

This document is the **strategic synthesis** that the four ADRs hang off; the ADRs are the **load-bearing commitments** that future work pins against. Conflicts between this document and an ADR resolve in favor of the ADR.

---

## Document Provenance

This document was authored by builder agent `builder-runtime-strategy` for task VIGOR-7724 on 2026-05-15. It synthesizes the existing ADR set as of the same date — explicitly building on the deployment ADRs 0028/0029/0030 and the deployment-and-ops strategy doc (sibling branch, 2026-05-15) — and the runtime code as of the worktree commit. Companion deliverables in the same branch: ADRs 0034–0037 (parallel best-of-N, single-node posture, checkpoint/resume, observability seam) and the runtime-completeness Seeds backlog. The expectation is that this document moves to `Status: Accepted` once the four ADRs land; until then, every recommendation is provisional on those ADRs agreeing.

For the architecture lead's convenience, every recommendation in §"The Eight Questions" is anchored to a `file:line` citation that can be opened directly. Classification labels (`foundational`, `tactical`, `observational`, `future`) are stable across the document and feed the Seeds backlog verbatim, matching the convention established by `docs/strategy/deployment-and-ops.md`.
