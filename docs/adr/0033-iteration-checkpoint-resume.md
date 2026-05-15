---
status: proposed
date: 2026-05-15
deciders: [VIGOR architecture team]
consulted: [builder-runtime-strategy]
informed: [coordinator]
---

# ADR-0033: Iteration-Boundary Checkpoint And Opt-In Resume Via `Orchestrator.resume(run_id)`

## Context and Problem Statement

VIGOR-7724 Q3 asks: *How do we serialize partial loop state so a long run can survive process restarts? Archive already persists per-iteration; what's missing?*

The archive (`packages/vigor-core/src/vigor_core/archive.py:43-180`) durably writes per-record JSON files. After iteration *n* finishes, an operator inspecting the archive sees `runs/<run_id>/candidates/<id>/{ir,compile_result,adjudication}.json` for every candidate the iteration produced, plus a `frontier.json` written at run end. What an operator **cannot** see — and what the orchestrator cannot reload — is *iteration-level mutable state*:

- `iteration: int` (the loop counter, `orchestrator.py:114`).
- `prior: list[ArtifactIR]` (the running list of all generated IRs across iterations, `orchestrator.py:111`).
- `current_ir: ArtifactIR | None` (the in-flight patched IR being re-evaluated, `orchestrator.py:112,184`).
- `activities: list[ProvenanceActivity]` (the running provenance log, `orchestrator.py:93`).
- `adjudications: list[AdjudicationReport]` (the running adjudication log, `orchestrator.py:94`).
- `last_candidate_id`, `last_export`, `accepted`, `stop_reason`.

After a process crash mid-run, all of this in-memory state is lost. The archive contains the durable artifacts (IRs, compile results, reviews, adjudications) but nothing that says "we were at iteration 4, with 14 prior candidates accumulated, and `current_ir` was `cand_xyz_0013` mid-patch." A run that took 90 minutes to reach iteration 4 must restart from iteration 0.

The proximal cause: `provenance.json` is written **only at the end of a successful run** (`archive.py:131-143`, called from `orchestrator.py:241` only when `accepted=True`). It is the natural carrier of the state shape we want, but its persistence is post-hoc, not iterative.

The right shape is an **iteration-level checkpoint** written at the *end* of each iteration's evaluation, after all per-candidate JSONs are durable. The orchestrator's resume path reads the latest checkpoint and re-enters the loop at the next iteration with the rehydrated state.

Three tensions inform the design:

- **Atomicity vs cost.** Writing the checkpoint synchronously after each iteration adds one filesystem write per iteration. For a `max_iterations=5` run, that is 5 extra writes — negligible. Writing it before each candidate would be more granular but adds N writes per iteration; the tradeoff is per-candidate resume granularity that no operator has asked for.
- **Resume scope.** A "resume mid-iteration" feature requires re-entering the loop *inside* an iteration (re-running compile, re-running reviewers, re-running patch proposal). Most of these operations are expensive LLM calls or subprocess launches that the orchestrator does not want to redo. **Iteration-boundary resume** gets us 80% of the value at 20% of the cost: a crash mid-iteration loses one iteration's work; a crash between iterations loses zero iterations' work.
- **Backend identity.** Resuming a run after the agent backend's session has expired (Claude Agent SDK conversation rolled, MCP server restarted) is impossible by construction — the conversation context is gone. Resume is **runtime-state resume, not session resume**. The new run gets a fresh backend; the prior IR list is the only context that survives.

The opt-in vs default question: should resume happen automatically when the orchestrator sees a partial archive, or be explicitly requested? **Opt-in** wins because the default failure mode is "if a run dies, start over" — which is what every existing operator expects. Auto-resume would silently change semantics for any operator who today retries a failed run by re-running with the same `task_id`.

## Decision Drivers

- **Cost of lost work.** An iteration in a canonical photo / video / CAD task takes minutes; a 5-iteration run can take 30–60 minutes. Losing all of it because of a process crash is the largest single source of operator pain that v1.0 production-readiness should fix.
- **Atomicity guarantees of the existing archive.** Per-record JSON writes are the established pattern. A checkpoint is just one more JSON file written atomically (write-then-rename). No new persistence layer.
- **Backend identity is unrecoverable.** The Claude Agent SDK's `ResultMessage`-bearing conversation, the Strands agent's session, the MCP servers' subprocess state — none of it survives a process crash. Resume must accept this and rebuild backends from scratch on resume.
- **Default-preserving change.** Existing operators who today re-run a failed task expect to start over. Auto-resume would change that behavior silently. Resume must be opt-in.
- **Single-node-by-contract (ADR-0032).** Resume is a single-process operation against a single-archive directory. The advisory lock from ADR-0032 ensures the resuming orchestrator is the only writer; concurrent-resume is undefined and unsupported.
- **No additional dependencies.** No write-ahead log, no SQLite, no separate transaction coordinator. The checkpoint is a Pydantic model serialized to JSON, identical in shape to every other archive record.

## Considered Options

- **Option A — Iteration-boundary checkpoint, opt-in resume via `Orchestrator.resume(run_id)`.** Write `iteration_checkpoint.json` at the end of each iteration. Add `Orchestrator.resume(run_id) -> RunResult` that loads the checkpoint and re-enters the loop. Default behavior on a re-run with the same `task_id` is *unchanged* (start over); resume is explicit.
- **Option B — Per-candidate checkpoint.** Write a checkpoint after each candidate's evaluation. Maximum resume granularity (lose at most one candidate's work). N× the write volume.
- **Option C — Auto-resume on archive presence.** When `Orchestrator.run` is called with a `task_id` that already has an archive, auto-resume from the latest checkpoint. No explicit resume entry point.
- **Option D — Defer.** Document checkpoint/resume as a future enhancement; ship v1.0 without it.
- **Option E — Write-ahead log.** Add a `runs/<run_id>/wal.jsonl` append-only log capturing every state transition, replay-on-recovery. Database-style.

## Decision Outcome

Chosen: **Option A** — iteration-boundary checkpoint, opt-in resume.

The rationale: per-iteration is the correct granularity for the cost (one write per iteration is negligible) and the value (most lost-work pain is between iterations, not within one). Opt-in resume preserves existing semantics. The implementation is a thin layer on top of the existing archive — no new persistence shape, no new transaction model.

The implementation has four parts.

1. **A new `IterationCheckpoint` schema** in `vigor_core.schemas`:

   ```python
   class IterationCheckpoint(_VigorBase):
       schema_version: Literal["vigor.iteration_checkpoint.v1"] = "vigor.iteration_checkpoint.v1"
       checkpoint_id: str = Field(pattern=ID_PATTERN)
       created_at: str = Field(default_factory=utcnow_iso)
       run_id: str = Field(pattern=ID_PATTERN)
       next_iteration: int  # 0-based; the iteration the resume should re-enter at
       prior_candidate_ids: list[str]  # all generated candidate_ids across completed iterations
       current_candidate_id: str | None  # in-flight patched IR if any (for the next iteration's _candidate_batch)
       activities: list[ProvenanceActivity]  # cumulative
       adjudication_ids: list[str]  # cumulative; adjudications themselves remain in candidate_dirs
       last_candidate_id: str | None
   ```

   `prior` (list of `ArtifactIR` objects) is **not** stored in the checkpoint directly — it is rehydrated on resume by reading each `prior_candidate_ids` entry from the archive (`archive.read_ir(run_id, candidate_id)`). The checkpoint stores IDs only, keeping it small. Same for `adjudications`.

2. **`RunArchive.write_checkpoint(run_id, checkpoint)` and `read_checkpoint(run_id)`** added to the archive. Latest checkpoint at `runs/<run_id>/iteration_checkpoint.json`. Atomic via the standard write-then-rename pattern (which the archive does not currently use — see Consequence #4).

3. **Orchestrator writes a checkpoint at the end of each iteration**, at the bottom of the iteration body, after all candidate JSONs are durable. This is between `orchestrator.py:184` (the patched-IR assignment) and the `else: stop_reason = "budget_exhausted"` clause at `orchestrator.py:185-186`, in the success path of the iteration. On the accept path (early break at `orchestrator.py:147`) the checkpoint is also written, so a crash *after* an iteration accepted but *before* `provenance.json` is finalized still has a recovery point.

4. **`Orchestrator.resume(run_id) -> RunResult`** is a new entry point on `Orchestrator`. It:
   - Reads `task.json` from the archive (`archive.read_task`).
   - Reads the latest `iteration_checkpoint.json`. If absent, raises `NoCheckpointError`.
   - Rehydrates `prior` by calling `archive.read_ir(run_id, cid)` for each `prior_candidate_ids`.
   - Rehydrates `current_ir` by reading the current candidate's IR if `current_candidate_id` is set.
   - Calls `await self._adapter.describe_capabilities()` and `await self._adapter.plan_representation(task)` again — these are cheap and safe to redo.
   - Re-enters the run loop at `iteration = checkpoint.next_iteration`, re-running `_candidate_batch`, `_evaluate_candidate`, etc.
   - On completion, writes the final `provenance.json` with the cumulative activities and adjudications.

The `vigor-agent` `AgentOrchestrator` gets a corresponding `resume(run_id)` method that delegates the same way `run(task)` does. The CLI gets a `vigor-agent resume <run_id>` subcommand (out-of-scope for this ADR — implementation Seeds will add it).

**Resume is structurally idempotent for the orchestrator's perspective**: re-running from the next iteration produces a new candidate set with new candidate_ids (the orchestrator's `_candidate_batch` increments candidate index based on `len(prior_candidates)`, so resumed iterations never collide with the pre-crash candidates). Existing per-candidate JSONs are not overwritten; new ones are added.

**What resume does not preserve**:

- **Wall-clock budget.** The pre-crash run ate some `max_wall_clock_s`; the resumed run starts a new wall-clock counter from the resume time. Operators who care about end-to-end wall-clock can manually shrink `max_wall_clock_s` on resume; the runtime does not subtract elapsed time across crashes (the archive does not record that elapsed time anyway).
- **Cost budget.** ADR-0028's `RunBudgetTracker` polls each backend's `usage()`. A fresh backend on resume reports zero usage — the cumulative usage from before the crash is on a backend that no longer exists. The resumed run starts a new cost counter from zero. Operators who care set tighter `max_cost_usd` on resume.
- **Backend conversation context.** Already discussed; structurally unrecoverable.

The opt-in story is concrete: if a user calls `await agent.run(task)` with a `task_id` that already has an archive, the run **starts over** (same as today). To resume, the user explicitly calls `await agent.resume(task.task_id)`. The CLI's resume subcommand (when added) makes this explicit too: `vigor-agent run` is start-or-restart; `vigor-agent resume` is resume-or-fail.

### Alt-A: Iteration-boundary (chosen) vs per-candidate vs auto-resume vs defer vs WAL

| Alternative | Reason Rejected |
| --- | --- |
| Per-candidate checkpoint | Maximum granularity. The cost is N× more writes per iteration (one per candidate), and the value is "lose at most one candidate's work" — but with parallel best-of-N (ADR-0031), candidates within a batch are concurrent and a per-candidate checkpoint after each one is racy (which candidate wrote it last?). A per-batch checkpoint after the parallel batch finishes is structurally identical to iteration-boundary checkpointing, since the batch *is* the iteration's evaluation phase. The granularity gain is illusory. |
| Auto-resume on archive presence | Changes existing semantics silently. An operator who today retries a failed run by re-running gets a started-over run; with auto-resume they get a resumed run, which may be desirable but is not what they asked for. The behavior change is the *exact* failure mode — a runtime that does something different than what the operator expects, with no signal. Resume must be explicit. |
| Defer to v2 | The largest single operator-pain mitigation in the runtime backlog. A 60-minute run that crashes at minute 55 and starts over at minute 0 is the kind of incident that drives operators away from a framework. Deferring this past v1.0 makes "production-grade VIGOR" structurally fragile. |
| Write-ahead log | Database-style transaction model. Solves the per-candidate-recovery case the iteration-boundary checkpoint does not, at the cost of a new persistence shape, replay logic, and a serialization format orthogonal to the per-record JSONs the archive already uses. The 80/20 case is covered by iteration-boundary checkpointing; the remaining 20% (per-candidate recovery) is not yet a documented operator request. If ever requested, a WAL can be layered on top of the iteration-boundary checkpoint without breaking it. |
| (Chosen) Iteration-boundary checkpoint, opt-in resume via explicit entry point | Smallest possible commitment that recovers most of the lost-work pain. Reuses the existing archive shape (per-record JSON). Preserves existing default semantics (re-run starts over). Single new entry point (`resume(run_id)`). |

### Alt-B: Checkpoint storage — full state vs ID-only references vs hybrid

| Alternative | Reason Rejected |
| --- | --- |
| Full state in checkpoint (every `ArtifactIR` and `AdjudicationReport` embedded inline) | The checkpoint becomes O(iterations × candidates) in size — for a max-iterations=5, max-candidates=4 run, ~20 IR objects copied into the checkpoint. Doubles the storage cost of the archive (the IRs are already on disk in `candidates/<id>/ir.json`). |
| Hybrid (IDs for IRs, embedded for adjudications) | The asymmetry is arbitrary. Adjudications are also already on disk; embedding them is just as wasteful as embedding IRs. |
| (Chosen) ID-only references (rehydrate from archive on resume) | Checkpoint stays small (~hundreds of bytes for typical runs). Source of truth for IRs and adjudications remains the per-candidate JSONs, which are already the load-bearing storage. Resume reads them; no consistency concerns. |

### Alt-C: Resume entry point — `Orchestrator.resume(run_id)` (chosen) vs `TaskSpec.resume_run_id` flag vs CLI-only

| Alternative | Reason Rejected |
| --- | --- |
| `TaskSpec.resume_run_id: str | None` flag — the same `Orchestrator.run(task)` entry point handles both new runs and resumes | Conflates two operations into one entry point. Operators reading the public surface see one method that does two different things based on a field on the task. Worse for type-checking, worse for documentation, worse for the "principle of least astonishment." |
| CLI-only resume (no library entry point) | Library users (Jupyter notebooks, in-process callers) cannot use resume. Inconsistent with ADR-0030's library-first commitment — CLI-only features are deployment-layer concerns; resume is a library-layer feature. |
| (Chosen) `Orchestrator.resume(run_id)` plus `AgentOrchestrator.resume(run_id)` | Distinct entry point, clear intent. Library users and CLI users both get it. Documented, type-checked, ADR-0030 compliant. |

## Consequences

### Positive

1. **Long runs survive crashes.** A 60-minute run that crashes at minute 55 can resume from the most recent iteration boundary with one command. The vast majority of lost-work pain is recovered.
2. **No new persistence layer.** The checkpoint is one more JSON file in the archive directory. Operators familiar with the archive layout already know how to debug it.
3. **Existing semantics preserved.** `agent.run(task)` with a previously-used `task_id` starts over, exactly as today. Resume is explicit.
4. **Composes with parallel best-of-N (ADR-0031).** Per-batch fanout finishes; checkpoint writes after; resume re-enters at the next iteration. No race conditions.
5. **Composes with cost ceiling (ADR-0028).** Resume starts a new cost counter; explicit operator action (lowering `max_cost_usd`) controls the resumed budget. No silent budget extension across crashes.

### Negative

1. **Checkpoint after the iteration, not before.** A crash *during* iteration *n*'s `_evaluate_candidate` loses that iteration's work. Resume re-enters at *n*, redoes the work. Mitigation: ship iteration-boundary checkpointing (this ADR), file per-candidate checkpoint as a future enhancement if operators ask. None have yet.
2. **Backend conversation context is unrecoverable.** A backend that builds up multi-turn conversation state across iterations loses it on resume. The new backend on resume sees the prior IR list as context (passed via `GenerationRequest.prior_candidates`) but does not see prior tool-call traces, prior reviewer rationales, or prior backend reasoning. This is fundamental — no library-layer ADR can fix it. Operators using stateful backends should be aware that resumed runs may diverge from the pre-crash trajectory.
3. **Wall-clock and cost budgets reset on resume.** A user with a strict end-to-end budget (e.g. "this run must not exceed $5 total across crashes") cannot enforce it via the runtime. They must track elapsed cost externally and set tighter ceilings on resume. The ADR documents this; the runtime does not solve it.
4. **Atomic-write requirement on the archive.** The current archive's `write_*` methods do plain `path.write_text` (not atomic). For checkpoints, atomicity matters — a crash mid-write leaves a half-written `iteration_checkpoint.json` that the resume path would fail to parse. The implementation Seeds adds a `RunArchive._atomic_write` helper (write to `<file>.tmp`, then `os.replace`) used by `write_checkpoint`. This helper is general-purpose and could be retroactively applied to other archive writes; that is filed as a follow-up Seeds task `VIGOR-c09b` (see backlog).
5. **`provenance.json` written twice in some paths.** A run that completed successfully writes `provenance.json` at the end. A resumed run that completed successfully also writes `provenance.json` — overwriting the prior one if any. This is intentional (the resumed provenance has the cumulative activities) but means readers cannot rely on the prior `provenance.json` being preserved. The Seeds task documents this in the resume implementation.

### Neutral

1. The new `IterationCheckpoint` schema follows the existing `_VigorBase` config (`schemas.py:21-32`): strict mode, `extra="forbid"`, alias_generator. Indistinguishable from every other schema in shape.
2. `Orchestrator.resume(run_id)` is opt-in. Operators who never call it pay zero cost (one extra filesystem write per iteration is the only cost they pay; they can ignore the new file).
3. The advisory lock (ADR-0032) ensures only one process is resuming at a time. Concurrent-resume is undefined; the lock prevents it.

## References

| Source | Path / URL |
| --- | --- |
| Run loop iteration body (target site for checkpoint write) | `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:114-184` |
| Provenance write site (existing post-hoc state capture) | `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:228-241` |
| `RunArchive` JSON write pattern (target for `write_checkpoint`) | `packages/vigor-core/src/vigor_core/archive.py:78-129` |
| `_VigorBase` schema config (target for `IterationCheckpoint`) | `packages/vigor-core/src/vigor_core/schemas.py:21-32` |
| `ProvenanceRecord` schema (cumulative activities reference) | `packages/vigor-core/src/vigor_core/schemas.py:287-298` |
| ADR-0010 (async core interfaces) | `0010-async-core-interfaces.md` |
| ADR-0011 (IR schema versioning — pattern for `vigor.iteration_checkpoint.v1`) | `0011-ir-schema-versioning.md` |
| ADR-0028 (cost ceiling — bounded-overshoot precedent and budget-on-resume rule) | `0028-cost-ceiling-enforcement.md` |
| ADR-0030 (library-first posture — resume must work in-library, not CLI-only) | `0030-library-first-deployment-posture.md` |
| ADR-0031 (parallel best-of-N — per-batch fanout interacts with iteration-boundary checkpointing) | `0031-parallel-best-of-n-via-asyncio-gather.md` |
| ADR-0032 (single-node posture — advisory lock prevents concurrent resume) | `0032-single-node-orchestrator-posture.md` |
| Strategic summary | `docs/strategy/runtime-completeness.md` §Q3 |
