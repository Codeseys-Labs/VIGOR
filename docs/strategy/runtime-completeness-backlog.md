<!-- written-by: builder-runtime-strategy -->
# Runtime Completeness Backlog — Implementation Seeds For VIGOR-7724

**Source:** VIGOR-7724 (strategic deep-dive on vigor-runtime production-readiness)
**Authored:** 2026-05-15
**Status:** Initial backlog created. Seeds below should be filed via `sd create` on the same merge cycle as this file. ADRs they reference are draft proposals (Status: Proposed) pending coordinator review.

This is the prioritized implementation backlog for the runtime extensions decided in VIGOR-7724. The seeds below are the work that lands the four ADRs (0034–0037) plus the tactical follow-ups identified in the strategic summary (`docs/strategy/runtime-completeness.md`).

## Summary table

| Seed ID | Priority | Title | ADR / strategic-doc reference |
| --- | :---: | --- | --- |
| [VIGOR-f497](#vigor-f497) | P0 | Implement parallel best-of-N (Budgets.parallel_candidates + asyncio.gather fanout) | ADR-0034; runtime-completeness §Q1 |
| [VIGOR-aa1c](#vigor-aa1c) | P0 | Add advisory archive lock + ArchiveLockedError (single-node enforcement) | ADR-0035; runtime-completeness §Q2 |
| [VIGOR-fb79](#vigor-fb79) | P0 | Iteration checkpoint + Orchestrator.resume(run_id) | ADR-0036; runtime-completeness §Q3 |
| [VIGOR-d8a3](#vigor-d8a3) | P0 | RuntimeObserver Protocol seam at lifecycle boundaries | ADR-0037; runtime-completeness §Q5 |
| [VIGOR-ca10](#vigor-ca10) | P1 | Per-candidate Usage attribution (extends ADR-0028 implementation) | runtime-completeness §Q4; ADR-0028 |
| [VIGOR-a386](#vigor-a386) | P1 | Cancellation propagation + StopReason="cancelled" | runtime-completeness §Q7 |
| [VIGOR-7086](#vigor-7086) | P1 | Orchestrator.run_streaming async-iterator entry point | runtime-completeness §Q6; ADR-0037 |
| [VIGOR-1029](#vigor-1029) | P2 | Harness backpressure / queue management for batched eval | runtime-completeness §Q8 |
| [VIGOR-c09b](#vigor-c09b) | P2 | Adopt atomic write-then-rename across all RunArchive writes | ADR-0036 follow-up |
| [VIGOR-c2ec](#vigor-c2ec) | P3 | Detect concurrent in-process Orchestrator.run on same archive | ADR-0035 follow-up |

**Priority breakdown:** 4× P0, 3× P1, 2× P2, 1× P3 (10 total).

## Why P0 vs P1 vs P2 vs P3

- **P0 — runtime-shape extensions ADR-committed.** Each P0 implements a foundational ADR (0034–0037) decided in this branch. The strategic doc classifies them all `foundational`; without them, VIGOR-the-library cannot credibly be called production-grade for v1.0. All four are independent of each other (no inter-P0 dependency), so a coordinator can parallelize them across builders.
- **P1 — known-shape work that extends an already-decided ADR.** Per-candidate Usage extends ADR-0028 (already proposed in sibling branch). Cancellation propagation and partial-result streaming extend ADR-0037's observer surface. Each has a clear ADR anchor; each is mechanical. None of them require a new ADR.
- **P2 — operator-friendly polish.** Backpressure for batched eval is harness-layer work, not runtime work; archive atomicity is a quality improvement that lifts ADR-0036's checkpoint guarantee to all archive writes. Both can ship in v1.1 without compromising the production-readiness story.
- **P3 — defensive guardrail.** In-process concurrent-run detection is a footgun-prevention addition the ADR-0035 advisory lock does not cover (advisory locks are per-process on POSIX). Plausibly worth adding; nobody is currently asking.

## What is intentionally NOT in this backlog

- **Distributed orchestration / cross-process locking.** Per ADR-0035, deferred to a future hosted `vigor-server`. Filing a Seeds task today would invite the very work the ADR is designed to defer.
- **Process-pool fanout for evaluation.** Per ADR-0034 Alt-A, rejected. In-tree adapters either subprocess (Manim, OpenSCAD) or are I/O-bound (rawpy, photo critics); a process pool is the wrong primitive.
- **Per-candidate checkpointing.** Per ADR-0036 Alt-A, rejected for v1. May revisit if operators ask; nobody has yet.
- **OpenTelemetry hard dependency.** Per ADR-0037 Alt-A, rejected. The `vigor-observability-otel` package is downstream — it can be filed there if/when it lands.
- **Prometheus metrics in `vigor-runtime`.** Per ADR-0037 and `docs/strategy/deployment-and-ops.md`, metrics are a deployment-layer concern. Not in the runtime.
- **Audit log instrumentation.** Already filed as VIGOR-a171 (sibling branch deployment backlog). Distinct from observability per ADR-0037.

## Seed details

### VIGOR-f497

**P0 — Parallel best-of-N.** Implements ADR-0034. Filed 2026-05-15.

**Acceptance criteria:**
1. Add `parallel_candidates: int = 1` to `Budgets` (`packages/vigor-core/src/vigor_core/schemas.py:51-58`).
2. Convert the candidate-generation loop (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:262-275`) to chunked `asyncio.gather` fanout with chunk size `min(parallel_candidates, max_candidates)`.
3. Convert the candidate-evaluation loop (`packages/vigor-runtime/src/vigor_runtime/orchestrator.py:122-128`) to the same chunked-fanout shape.
4. Use `return_exceptions=True` on the `asyncio.gather` calls; rely on `_evaluate_candidate`'s existing per-candidate error handling for the typed failure shape.
5. Default behavior (no `parallel_candidates` set, or set to 1) must be byte-identical to today: same candidate IDs, same iteration order, same archive layout. Verify via existing test suite.
6. New tests: parallel run with `parallel_candidates=4`, assert all candidate JSONs land, assert iteration count and `RunResult` are correct.
7. Documentation: README + `docs/vigor-framework.md` budgets section.

**Out of scope:** observer instrumentation of parallel batches (that's VIGOR-d8a3); per-candidate cost cap (that's an extension to ADR-0028, see VIGOR-ca10).

**Filed as VIGOR-f497.** No upstream dependencies — independent of the other P0 work.

---

### VIGOR-aa1c

**P0 — Advisory archive lock.** Implements ADR-0035. Filed 2026-05-15.

**Acceptance criteria:**
1. Add `ArchiveLockedError` to `vigor_core.errors`.
2. Acquire `archive_dir/.archive.lock` exclusive non-blocking lock in `RunArchive.__init__` (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows). Raise `ArchiveLockedError` if held.
3. Add `RunArchive.close()` (or an `__aexit__`) to release the lock; wire `weakref.finalize` for safety.
4. Update `Orchestrator` and `AgentOrchestrator` lifecycle so the lock is released after each run completes (or after the agent shuts down for long-lived agents).
5. Add `.gitignore` entries for `*/runs/.archive.lock` and example archives in the repo.
6. Documentation: new `docs/architecture/run-archive.md` declaring "archive directory is private to one process."
7. New tests: two `RunArchive` instances on the same dir → second raises `ArchiveLockedError`. Lock released after `close()`.

**Out of scope:** in-process re-entrance detection (VIGOR-c2ec).

**Filed as VIGOR-aa1c.** No upstream dependencies — independent of the other P0 work.

---

### VIGOR-fb79

**P0 — Iteration checkpoint and resume.** Implements ADR-0036. Filed 2026-05-15.

**Acceptance criteria:**
1. Add `IterationCheckpoint` schema to `vigor_core.schemas` (frontmatter version `vigor.iteration_checkpoint.v1`).
2. Add `RunArchive.write_checkpoint(run_id, checkpoint)` and `read_checkpoint(run_id) -> IterationCheckpoint`. Use atomic write-then-rename (introduce `RunArchive._atomic_write` helper used here; full migration of all archive writes is VIGOR-c09b).
3. Orchestrator writes a checkpoint at iteration boundary (after candidate JSONs durable, both on success-break and on iteration-end).
4. Add `Orchestrator.resume(run_id) -> RunResult` and `AgentOrchestrator.resume(run_id) -> RunResult`. Read checkpoint, rehydrate `prior` from per-candidate IRs, re-enter loop at `next_iteration`.
5. Add `NoCheckpointError` to `vigor_core.errors` for the no-checkpoint case.
6. CLI: add `vigor-agent resume <run_id>` subcommand (separate from `vigor-agent run`).
7. New tests: run that crashes mid-iteration leaves a parseable checkpoint; resume continues from `next_iteration` and produces the expected `RunResult`.
8. Documentation: ADR-0036 reference in README; CLI `--help` documents resume.

**Out of scope:** budget-on-resume tracking (the ADR documents that resume starts a new cost/wall-clock counter); atomic-write retrofit for non-checkpoint files (VIGOR-c09b).

**Filed as VIGOR-fb79.** No upstream dependencies — independent of the other P0 work.

---

### VIGOR-d8a3

**P0 — RuntimeObserver Protocol seam.** Implements ADR-0037. Filed 2026-05-15.

**Acceptance criteria:**
1. New module `vigor_core.observability` defining `RuntimeObserver` `Protocol` with the seven methods (`on_run_start`, `on_iteration_start`, `on_candidate_start`, `on_candidate_end`, `on_iteration_end`, `on_run_end`, `on_event`). Decorated with `@runtime_checkable`.
2. `Orchestrator.__init__` accepts optional `observer: RuntimeObserver | None = None`. `runtime_checkable` validation at construction time.
3. Wire the seven emission sites (per ADR-0037 §Decision Outcome). Each call wrapped in `try / except Exception` that logs to `logging.getLogger("vigor.runtime")` at WARNING and continues.
4. `AgentOrchestrator.__init__` threads `observer` through to its `Orchestrator`.
5. CLI: add `--observer-factory <module:func>` flag analogous to `--backend-factory`. When set, calls factory and attaches result.
6. Add `logging.getLogger("vigor.runtime")` calls at lifecycle points (INFO level for run/iteration boundaries; DEBUG level for candidate boundaries) — orthogonal to the observer.
7. New tests: observer mock receives all expected calls in correct order; observer raising an exception does not break the run; default (no observer) emits no calls.
8. Documentation: ADR-0037 reference; example observer in `docs/examples/observer.py` (a simple stdout printer).

**Out of scope:** OpenTelemetry adapter (downstream package); Prometheus adapter (downstream package); audit instrumentation (sibling Seeds).

**Filed as VIGOR-d8a3.** No upstream dependencies — independent of the other P0 work; downstream of three P1 Seeds (VIGOR-ca10, VIGOR-a386, VIGOR-7086) which depend on this observer surface.

---

### VIGOR-ca10

**P1 — Per-candidate Usage attribution.** Extends ADR-0028 implementation. Filed 2026-05-15.

**Acceptance criteria:**
1. Inside `_evaluate_candidate` (`orchestrator.py:277-354`), capture `backend.usage()` snapshots before and after each candidate's work. Compute the per-candidate delta.
2. Persist per-candidate `usage.json` at `archive.candidate_dir(run_id, candidate_id)` alongside `adjudication.json`.
3. Add `RunResult.usage_per_candidate: dict[str, Usage]` aggregating the deltas.
4. The observer's `on_candidate_end` (per ADR-0037) receives the per-candidate `Usage` as an attribute.
5. New tests: a multi-candidate run produces a `usage.json` per candidate; deltas sum to the run total; `RunResult.usage_per_candidate` keyed by `candidate_id`.

**Depends on:** VIGOR-344f (sibling branch — the underlying ADR-0028 implementation must land first), VIGOR-d8a3 (so `on_candidate_end` has the new attribute available).

**Filed as VIGOR-ca10.** Dependency added: `VIGOR-ca10 → VIGOR-d8a3` (observer must land first). Cross-branch dependency on `VIGOR-344f` (cost-ceiling Seeds in sibling branch) recorded here for the merge coordinator; not yet wired via `sd dep` because VIGOR-344f lives in a sibling branch.

---

### VIGOR-a386

**P1 — Cancellation propagation.** Per `docs/strategy/runtime-completeness.md` §Q7. Filed 2026-05-15.

**Acceptance criteria:**
1. Wrap the `Orchestrator.run` body in `try / except asyncio.CancelledError` at `orchestrator.py:101-211`. Convert to a partial `RunResult` with `accepted=False`, `stop_reason="cancelled"`.
2. Add `"cancelled"` to the `StopReason` `Literal` (`packages/vigor-core/src/vigor_core/schemas.py:120-127`). This is a schema bump (additive, same shape as ADR-0028's `"cost_exceeded"` extension).
3. Document in the `AgentOrchestrator.run` docstring that the **caller** is responsible for closing the `ToolBackend` (which today's CLI does at `cli.py:52`).
4. Observer emits `on_run_end(stop_reason="cancelled", accepted=False, ...)` on cancellation.
5. New tests: a run cancelled via `task.cancel()` returns a `RunResult` with `stop_reason="cancelled"`; backend `aclose` was called.

**Depends on:** VIGOR-d8a3 (for the observer call).

**Filed as VIGOR-a386.** Dependency added: `VIGOR-a386 → VIGOR-d8a3`.

---

### VIGOR-7086

**P1 — Streaming entry point.** Per `docs/strategy/runtime-completeness.md` §Q6. Filed 2026-05-15.

**Acceptance criteria:**
1. Add `Orchestrator.run_streaming(task) -> AsyncIterator[RunEvent]` where `RunEvent` is a discriminated union (`IterationStarted`, `CandidateGenerated`, `CandidateEvaluated`, `IterationEnded`, `RunEnded`).
2. Existing `Orchestrator.run(task)` becomes a thin consumer of `run_streaming` that aggregates events into the existing `RunResult` shape — no behavior change for current callers.
3. Use `asyncio.Queue` to bridge the orchestrator's internal control flow with the iterator (events are produced by the orchestrator, consumed by the caller).
4. The streaming surface composes with parallel best-of-N (ADR-0034): events for parallel candidates emit as they complete, not in submission order. Document this.
5. New tests: streaming run emits events in expected types and counts; final `RunEnded` event matches the would-be `RunResult`.

**Depends on:** VIGOR-d8a3 (the streaming events overlap heavily with observer events; the streaming impl should reuse them rather than duplicate the surface).

**Filed as VIGOR-7086.** Dependency added: `VIGOR-7086 → VIGOR-d8a3`.

---

### VIGOR-1029

**P2 — Harness backpressure.** Per `docs/strategy/runtime-completeness.md` §Q8. Filed 2026-05-15.

**Acceptance criteria:**
1. In the harness package (currently `packages/vigor-harness` is not yet shipped per Phase 6 — this Seeds may need to land alongside the harness's first-real-batch implementation), add a `BatchedRunner` that wraps N concurrent `Orchestrator.run` calls under an `asyncio.Semaphore`.
2. Per-batch budget cap via `BatchBudgetTracker` extending ADR-0028's `RunBudgetTracker` shape.
3. Per-task timeout (`asyncio.wait_for`) at the batch level, separate from per-task `Budgets.max_wall_clock_s`.
4. New tests: 100 tasks × `concurrency=10` runs cleanly; budget cap stops the batch when reached; one task failing does not poison siblings.

**Depends on:** VIGOR-a386 (clean failure semantics matter for batch shutdown).

**Filed as VIGOR-1029.** Dependency added: `VIGOR-1029 → VIGOR-a386`.

---

### VIGOR-c09b

**P2 — Atomic archive writes.** ADR-0036 follow-up. Filed 2026-05-15.

**Acceptance criteria:**
1. Refactor `RunArchive._atomic_write(path, data)` (introduced by VIGOR-fb79) to a generic helper.
2. Migrate every `path.write_text(_dump(model))` site in `RunArchive` to use `_atomic_write`. There are roughly 8 such sites at `archive.py:60-168`.
3. New tests: simulate kill-9 mid-write (write partial data with a fake `write` shim that raises after N bytes), verify the archive directory contains either the prior file or the new file, never a partial.

**Depends on:** VIGOR-fb79 (introduces the helper).

**Filed as VIGOR-c09b.** Dependency added: `VIGOR-c09b → VIGOR-fb79`.

---

### VIGOR-c2ec

**P3 — In-process re-entrance detection.** ADR-0035 follow-up. Filed 2026-05-15.

**Acceptance criteria:**
1. Add a per-`RunArchive` instance `asyncio.Lock` held during `Orchestrator.run`.
2. Two concurrent `Orchestrator.run` calls in the same process pointed at the same `archive_dir` raise a clear error rather than corrupting the archive.
3. New tests: `asyncio.gather(orchestrator.run(t1), orchestrator.run(t2))` where both share the same archive raises an explicit error.

**Why P3:** Programming-error case. The ADR-0035 advisory lock catches the cross-process case (the dominant failure mode); the in-process case requires a programmer to write `asyncio.gather(agent.run(t1), agent.run(t2))` which is not a documented pattern.

**Filed as VIGOR-c2ec.** No dependencies.

---

## Cross-document anchors

- **ADRs (this branch):**
  - `docs/adr/0034-parallel-best-of-n-via-asyncio-gather.md`
  - `docs/adr/0035-single-node-orchestrator-posture.md`
  - `docs/adr/0036-iteration-checkpoint-resume.md`
  - `docs/adr/0037-runtime-observer-protocol-seam.md`
- **ADRs (sibling branches, referenced):**
  - `docs/adr/0028-cost-ceiling-enforcement.md` (cost ceiling — VIGOR-ca10 extends its impl)
  - `docs/adr/0029-multi-tenant-subprocess-env-hardening.md` (referenced by ADR-0035 for hosted-layer coordination context)
  - `docs/adr/0030-library-first-deployment-posture.md` (foundational commitment that ADRs 0034–0037 all design against)
- **Strategy docs:**
  - `docs/strategy/runtime-completeness.md` (this branch — strategic synthesis)
  - `docs/strategy/deployment-and-ops.md` (sibling branch — deployment-layer companion)
  - `docs/strategy/deployment-backlog.md` (sibling branch — sibling Seeds backlog)
- **Sibling Seeds (referenced):**
  - VIGOR-344f (cost ceiling implementation — VIGOR-ca10 depends on it)
  - VIGOR-a171 (audit log — distinct from VIGOR-d8a3 per ADR-0037)
  - VIGOR-2585 (tool retry loop — orthogonal to runtime-completeness)
