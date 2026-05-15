---
status: proposed
date: 2026-05-15
deciders: [VIGOR architecture team]
consulted: [builder-runtime-strategy]
informed: [coordinator]
---

# ADR-0031: Parallel Best-of-N Via `asyncio.gather` Gated By `Budgets.parallel_candidates`

## Context and Problem Statement

`docs/roadmap.md` §"Phase 4: Frontier And Search" classifies "Parallel candidate scheduling" as a **future performance optimization**, deferred while the rest of best-of-N shipped sequentially. Today the runtime evaluates candidates strictly serially:

- Generation: `for _ in range(max(1, task.budgets.max_candidates))` calling `await self._backend.generate(...)` in series at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:262-275`.
- Evaluation: `for ir in candidates: outcome = await self._evaluate_candidate(...)` at `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:122-128`.

Both loops are I/O-bound. Generation is a blocking call to an LLM API (Claude Agent SDK, Strands, or a future backend). Evaluation includes adapter `compile` (often a subprocess call — Manim, OpenSCAD, rawpy), adapter `review` (often hits VLM critics or MCP-backed inspectors), and backend `review` (another LLM call). In aggregate, a `max_candidates=4` run typically costs *4× backend latency + 4× compile latency + 4× reviewer fanout latency*, all sequential.

Mulch record `mx-bc5801` ("Orchestrator.run uses asyncio.gather exactly once: orchestrator.py:507") confirms the runtime already proves the pattern works at the reviewer layer (`asyncio.gather(adapter_reviews(), backend_review())` at `orchestrator.py:507-509`). Lifting the same pattern to candidate generation and evaluation is a small structural change with a 2–4× wall-clock win for the canonical configuration.

The blocker is **budget interaction**. `Budgets.max_wall_clock_s` is enforced at the iteration boundary (`orchestrator.py:116-118`). ADR-0028 wires `Budgets.max_cost_usd` to fire at the same seam. Parallel candidate evaluation must keep that seam single-threaded — a per-iteration check after parallel batches complete — or the bounded-overshoot guarantee ADR-0028 already documented (one iteration's worth of overspend) widens unpredictably. This ADR commits to keeping the enforcement seam exactly where it is.

The complementary question is the concurrency *primitive*. `asyncio.gather` is the obvious choice given the codebase is async-first (ADR-0010), but a process pool (concurrent.futures.ProcessPoolExecutor) would give CPU-bound adapters parallelism the GIL otherwise denies. Adapter compilers that release the GIL (subprocess-based — Manim's CLI, OpenSCAD's CLI, rawpy's C extension) are not blocked by `asyncio.gather`; adapter compilers that don't are out-of-tree concerns the runtime should not solve.

## Decision Drivers

- **Wall-clock cost.** A sequential `max_candidates=4` run with a 30s p95 backend latency and a 5s compile is bounded below at 140s; the same workload with parallel fanout is bounded below at ~35s. Operators care.
- **Budget seam invariance.** The enforcement seam (ADR-0028) must remain a single iteration-boundary check. Parallel candidates may overshoot a ceiling by *one batch's worth*, which is bounded and explicit; per-call enforcement (rejected by ADR-0028 Alt-B) would be racy and unimplementable without rearchitecting the archive.
- **SDK-agnosticism (ADR-0007).** The runtime cannot hard-code a process pool because process pools require pickling, and pickling agent backends (with their async sessions, MCP handles, etc.) is unsafe. The runtime cannot afford to assume backends are picklable.
- **Library-first posture (ADR-0030).** The runtime cannot ship a thread pool's tunable knobs as part of the public surface; the public surface is `AgentOrchestrator.run`. The parallelism cap must be expressed in `Budgets`, which is already part of `TaskSpec`.
- **Backwards compatibility.** Existing tasks with `max_candidates: N` (default 4) must continue to behave deterministically. The default for the new parallelism cap must be `1` (sequential) so existing test fixtures and integration tests do not flip.

## Considered Options

- **Option A — `asyncio.gather` with a `Budgets.parallel_candidates: int = 1` cap.** Default 1 preserves current behavior. Operators raise the cap to enable parallelism, bounded by `min(parallel_candidates, max_candidates)`. Generation and evaluation both fan out under the same cap.
- **Option B — Per-stage `asyncio.gather` (parallel generation, serial evaluation, or vice versa).** Generate all *N* candidates in parallel, then evaluate them serially (or generate serially, evaluate in parallel). Asymmetric.
- **Option C — Process pool for evaluation, async for generation.** Run `_evaluate_candidate` in a `ProcessPoolExecutor` so CPU-bound adapter compilers see real parallelism; keep generation in the event loop.
- **Option D — Status quo (sequential).** Document that parallelism is a future enhancement; ship neither the seam nor the budget knob.

## Decision Outcome

Chosen: **Option A** — `asyncio.gather` with a new `Budgets.parallel_candidates: int = 1` cap.

The rationale: `asyncio.gather` is the same primitive the runtime already uses at `orchestrator.py:507`; adding it to two more sites is structural symmetry, not new architecture. The cap-in-budgets surface keeps the public contract (`TaskSpec.budgets`) as the single tuning surface, consistent with how `max_iterations` and `max_wall_clock_s` work today. Default `1` preserves current behavior — the change is opt-in.

The fanout sites are exactly two:

1. **`_candidate_batch`** (`orchestrator.py:252-275`). Replace the `for _ in range(max(1, task.budgets.max_candidates)): result = await self._backend.generate(...)` loop with a bounded-fanout `asyncio.gather(*[generate_one() for _ in range(max(1, task.budgets.max_candidates))])` chunked into batches of `parallel_candidates`. Within a batch, `asyncio.gather` runs concurrently; across batches, batches run sequentially. The chunking is `min(parallel_candidates, max_candidates)`, with the trailing batch possibly smaller.

2. **The candidate-evaluation loop** (`orchestrator.py:122-128`). Same chunking strategy: replace `for ir in candidates: outcome = await self._evaluate_candidate(...)` with batched fanout via `asyncio.gather`.

The budget enforcement seam (`orchestrator.py:116-118`) is **untouched**. The wall-clock check fires once per iteration, before the candidate batch begins. The cost ceiling check (per ADR-0028) fires at the same point. Parallel candidates within a batch may collectively overshoot the cost ceiling by one batch's worth of spend — the same bounded-overshoot semantics ADR-0028 already documented for sequential candidates.

The new `Budgets.parallel_candidates` field is additive (default 1, current behavior preserved). Schema version stays `vigor.task.v1` — the same call ADR-0028 made for `Budgets.max_cost_usd`'s effective wiring.

Failure handling: `asyncio.gather` with `return_exceptions=False` would cancel sibling tasks on the first error. The runtime today catches every per-candidate error inside `_evaluate_candidate` (`orchestrator.py:282-303`) and converts it into a failure-shaped `CandidateOutcome`. We use `return_exceptions=True` only as a defense-in-depth: any exception that escapes `_evaluate_candidate` is wrapped into a `RuntimeErrorRecord` and the candidate is dropped from the batch. The iteration continues with the surviving candidates. This matches the runtime's existing failure shape — a single bad candidate does not poison the iteration.

Cancellation: when an `asyncio.gather` site receives `asyncio.CancelledError` (from a parent cancellation), the existing `try/finally: await self._backend.aclose()` block (`orchestrator.py:212-214`) catches the cleanup. Per-task `CancelledError` propagates to the gathered tasks and they cooperate via the same backend close. The Seeds task `VIGOR-a386` (filed in `docs/strategy/runtime-completeness-backlog.md`) handles the `StopReason="cancelled"` literal-extension separately; this ADR does not block on it.

### Alt-A: `asyncio.gather` (chosen) vs Option B asymmetric vs Option C process pool vs Option D status quo

| Alternative | Reason Rejected |
| --- | --- |
| Per-stage asymmetric (parallel generation, serial evaluation, or vice versa) | Less code than fully-parallel, but the wall-clock win is also halved. Generation and evaluation are both I/O-bound; parallelizing only one leaves the other as a bottleneck. The added complexity of two control knobs (`parallel_generation`, `parallel_evaluation`) buys nothing — operators want one tuning surface. |
| Process pool for evaluation | Forces backends to be picklable, which they are not (async sessions, MCP handles, lazy SDK imports). Forces adapters to be picklable too, which is a real constraint that excludes Manim and CAD adapters that hold subprocess handles. The CPU-bound case the process pool would unlock is already addressed for in-tree adapters: every compile that matters runs as a subprocess, which the OS schedules in parallel anyway. The remaining case (a Python-CPU-bound adapter not using subprocesses) is hypothetical for in-tree code; out-of-tree adapters that hit the case can build their own process-pool wrapper without runtime support. |
| Status quo (sequential) | The 2–4× wall-clock improvement is the largest single performance win in the entire backlog. Deferring it past v1.0 makes "production-grade VIGOR" structurally slower than the published latency budget any operator would expect. Roadmap.md §"Phase 4" already labels this as the deferred-but-known optimization; this ADR makes the deferral concrete. |
| (Chosen) `asyncio.gather` with `Budgets.parallel_candidates` cap | Smallest structural change. Reuses an existing primitive. Preserves the budget enforcement seam. Default 1 preserves current behavior. Cap surface lives in `TaskSpec.budgets` where every other resource cap lives. |

### Alt-B: Where the parallelism cap lives — `Budgets` field vs orchestrator constructor arg vs environment variable

| Alternative | Reason Rejected |
| --- | --- |
| Orchestrator constructor argument: `Orchestrator(adapter=..., backend=..., parallel_candidates=4)` | Bypasses the public surface ADR-0030 commits to (`AgentOrchestrator.run(task) -> RunResult`). Operators using the agent layer cannot configure parallelism without subclassing. Inconsistent with how every other resource cap is configured (per-task via `Budgets`). |
| Environment variable: `VIGOR_PARALLEL_CANDIDATES=4` | Process-global; doesn't compose with multi-task batched evaluation (Q8). Hides a runtime-affecting knob outside the explicit task contract. Same anti-pattern as `VIGOR_DISABLE_VALIDATION` would be — the schema is the contract. |
| (Chosen) `Budgets.parallel_candidates: int = 1` | Same surface as every other resource cap. Per-task scoping (each task can have a different cap). Default-1 preserves current behavior. Explicit in the schema. |

### Alt-C: Default value — 1 (sequential, opt-in parallelism) vs N (current `max_candidates`, opt-in serialization) vs 4 (sane default)

| Alternative | Reason Rejected |
| --- | --- |
| Default to `Budgets.max_candidates` (full parallelism by default) | Behavior-breaking. Existing tests expect deterministic candidate IDs in deterministic order; full-parallel runs may complete out-of-order, breaking order-sensitive assertions in existing fixtures. Backwards-incompatible without a migration window. |
| Default 4 (split the difference) | Splits the difference badly: existing fixtures still break (any order assumption), but operators who want sequential have to override. Worst of both. |
| (Chosen) Default 1 (sequential) | Preserves all existing test expectations. Operators opt in by setting `parallel_candidates: N`. The migration path is explicit: bump to N when ready. |

### Alt-D: Failure semantics — `return_exceptions=True` vs `return_exceptions=False` vs explicit cancellation

| Alternative | Reason Rejected |
| --- | --- |
| `asyncio.gather(..., return_exceptions=False)` (cancel siblings on first failure) | Aggressive cancellation: a single bad candidate kills the batch, even when surviving candidates would have evaluated cleanly. The orchestrator's existing failure shape (every per-candidate error becomes a failure-shaped `CandidateOutcome`) is exactly the opposite — graceful degradation. Switching to `return_exceptions=False` would inverter the existing posture. |
| Explicit per-task cancellation via `asyncio.TaskGroup` | Python 3.11+ `TaskGroup` has stricter semantics: any task raising cancels the group. Same problem as `return_exceptions=False` plus an explicit dependency on 3.11 (acceptable; ADR-0008 already pins 3.11+). The strictness is the wrong default for VIGOR's failure shape. |
| (Chosen) `return_exceptions=True` plus `_evaluate_candidate` catches everything internally | Two layers of defense: `_evaluate_candidate` catches every documented error path (adapter `VigorError`, generic `Exception`) and converts to a failure `CandidateOutcome`; `return_exceptions=True` is the safety net for any escape. The iteration continues with the surviving candidates. |

## Consequences

### Positive

1. **2–4× wall-clock improvement on canonical configurations.** A `max_candidates=4` task with `parallel_candidates=4` cuts iteration latency by a factor approximately equal to the parallelism cap, bounded by the slowest candidate. For canonical photo / video / CAD adapter latencies, this puts a typical iteration in the 20-40s range instead of 60-180s.
2. **Reuses an existing primitive.** `asyncio.gather` already runs at `orchestrator.py:507`. Lifting the same primitive to the candidate fanout layer is structural symmetry; no new dependencies.
3. **Budget enforcement seam is preserved.** The wall-clock check (`orchestrator.py:116-118`) and the cost ceiling check (per ADR-0028) both fire at iteration boundaries, exactly as today. Bounded overshoot is *one batch's worth* of spend — operators who care set tighter `parallel_candidates`.
4. **Surface stays in `Budgets`.** Every resource knob lives in one place. Operators tune VIGOR by editing `TaskSpec.budgets`, not by editing orchestrator construction sites.
5. **Default 1 preserves current behavior.** Existing tests, fixtures, and integration runs do not flip. The change is fully opt-in.

### Negative

1. **Bounded overshoot widens.** Sequential best-of-N overshoots wall-clock and cost ceilings by *one candidate's* worth of work; parallel best-of-N at `parallel_candidates=4` overshoots by *up to four candidates' worth*. ADR-0028's "one iteration of overshoot" guarantee becomes "one parallel batch of overshoot." Operators who set tight ceilings must lower `parallel_candidates` correspondingly.
2. **Determinism erodes.** Sequential runs produce candidate IDs in stable order (`cand_<task_id>_0000`, `cand_<task_id>_0001`, …). Parallel runs still produce stable IDs (the index is computed before fanout) but the *write order* of `candidate_dir/<id>/ir.json` files is nondeterministic. Tests asserting on filesystem mtime ordering will break. Mitigation: switch any such test to assert on the candidate-ID component, not mtime.
3. **Backend pressure.** A backend with a per-process rate limit (Claude Agent SDK with concurrent-request caps, Strands with provider quotas) sees parallel-candidates × per-call as the new instantaneous load. Backends that throttle internally (the Claude Agent SDK does; Strands does) handle this transparently. Backends without internal throttling (custom in-house backends) may see 429s the first time an operator raises `parallel_candidates` past 1. This is a backend-implementation concern, not a runtime concern.
4. **Adapter contention.** Adapters using a shared resource (a single OpenSCAD subprocess pool, a single rawpy worker thread) cannot benefit from parallel fanout and may contend. The in-tree adapters (`vigor-adapter-photo`, `vigor-adapter-video-manim`, `vigor-adapter-cad-openscad`) all spawn a fresh subprocess per `compile`, so contention is bounded by OS process limits, not by adapter design. Out-of-tree adapters using shared resources need to be aware.

### Neutral

1. The `_run_reviewers` site at `orchestrator.py:507` is **unchanged**. It already runs adapter and backend reviews concurrently. The new fanout sites are at the candidate generation and evaluation loops, one level out.
2. The `parallel_candidates` cap is **independent** of `max_candidates`. The implementation enforces `min(parallel_candidates, max_candidates)` so misconfigurations (`parallel_candidates: 8, max_candidates: 4`) silently cap. This matches the existing `max(1, max_candidates)` clamp at `orchestrator.py:263`.
3. Per-iteration metrics (cost-per-iteration, candidate-count-per-iteration) remain meaningful under parallelism. Per-second metrics (cost-per-second, candidates-per-second) become *aggregate* under parallelism — a 4-parallel iteration produces 4× the cost-per-second of a sequential iteration. This is operationally normal; metrics consumers (per `docs/strategy/deployment-and-ops.md` §"Observability And Telemetry") already think in aggregate terms.

## References

| Source | Path / URL |
| --- | --- |
| Sequential candidate generation loop (target site #1) | `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:262-275` |
| Sequential candidate evaluation loop (target site #2) | `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:122-128` |
| Existing `asyncio.gather` at the reviewer layer (precedent) | `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:507-509` |
| Wall-clock budget enforcement seam | `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:116-118` |
| `Budgets` schema (target field `parallel_candidates`) | `packages/vigor-core/src/vigor_core/schemas.py:51-58` |
| Roadmap deferral (Phase 4) | `docs/roadmap.md` §"Phase 4: Frontier And Search" |
| Mulch confirmation of single-`gather` site | mulch record `mx-bc5801` |
| ADR-0007 (SDK-agnostic core posture) | `0007-sdk-agnostic-core-with-optional-agent-backends.md` |
| ADR-0010 (async core interfaces) | `0010-async-core-interfaces.md` |
| ADR-0028 (cost ceiling enforcement, bounded-overshoot precedent) | `0028-cost-ceiling-enforcement.md` |
| ADR-0030 (library-first posture) | `0030-library-first-deployment-posture.md` |
| Strategic summary | `docs/strategy/runtime-completeness.md` §Q1 |
| Python `asyncio.gather` documentation | https://docs.python.org/3.11/library/asyncio-task.html#asyncio.gather |
