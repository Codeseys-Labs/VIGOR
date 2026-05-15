---
status: proposed
date: 2026-05-15
deciders: [VIGOR architecture team]
consulted: [builder-runtime-strategy]
informed: [coordinator]
---

# ADR-0032: VIGOR-The-Library Is Single-Node By Contract; Defer Distributed Orchestration

## Context and Problem Statement

VIGOR-7724 Q2 asks: *Can multiple Orchestrators share an archive? Cross-process locking? Or do we explicitly defer this and document VIGOR as single-node?*

`RunArchive` (`packages/vigor-core/src/vigor_core/archive.py:43-180`) is a filesystem-backed JSON store. Two orchestrator processes pointed at the same `archive_dir` can both call `write_task`, `write_ir`, `write_compile_result`, etc. without any coordination. The path-traversal guard `_safe_target` (`archive.py:170-180`) prevents directory escape but is silent on concurrent writers. The current single-CLI-per-invocation usage pattern (one operator, one shell, one `vigor-agent run` at a time) makes this safe by convention, not by enforcement.

Two distinct futures are plausible:

1. **Hosted multi-replica `vigor-server`** — N orchestrator replicas behind a load balancer, sharing a network filesystem or object store, all writing to the same archive root. Each tenant gets a path prefix (per ADR-0029's tenant scoping), and replicas coordinate via lease-based locks or via routing requests to a stable replica per `run_id`.
2. **Single-process library** — one `AgentOrchestrator` per process, one `archive_dir` per orchestrator. The CLI's `vigor-agent run` is the canonical invocation; library users in long-lived processes (Jupyter, scripts) call `await agent.run(task)` once or sequentially.

ADR-0030 has already committed to library-first: "VIGOR is committed to a **library-first** deployment posture for the foreseeable future." The hosted-multi-replica future is **explicitly deferred** to a downstream `vigor-server` that the project does not currently maintain. The question this ADR answers is: given that commitment, *does the runtime ship cross-process coordination primitives anyway*?

The temptation to ship them is real. Distributed coordination is a one-way door: a runtime that ships single-node-only and later wants to be distributed has to retrofit locking into every archive write site, which is invasive. A runtime that ships with locking primitives upfront preserves the option.

The temptation must be resisted because:

- **YAGNI.** No operator today is asking for multi-replica VIGOR. The hypothetical future is not yet on the roadmap.
- **Wrong abstraction layer.** Distributed coordination belongs in the hosting layer (`vigor-server` per ADR-0030), not in the library. A future `vigor-server` that picks PostgreSQL, S3, or DynamoDB as its archive backend will pick its own coordination primitive — file-system advisory locks are the wrong primitive for any of those.
- **Footgun risk.** A runtime that *advertises* multi-replica safety while actually only providing best-effort filesystem locking is worse than a runtime that says "single-node only" — operators trust the advertised safety, deploy multi-replica, and discover the failure mode in production.
- **Cost.** Adding `fcntl` advisory locking to every write site in `archive.py` is roughly a day of work and adds a Linux-vs-Windows portability tax (Windows uses different lock APIs). For a feature no operator is asking for, the cost is hard to justify.

The decision is between *enforcing* single-node, *advertising* single-node, and *building partial-distributed*.

## Decision Drivers

- **ADR-0030 library-first commitment.** The supported public surface is `AgentOrchestrator.run(task) -> RunResult` plus the schemas. Distributed orchestration is hosting-layer concern.
- **Operator footgun avoidance.** A runtime that lets two processes write to the same archive without any signal is more dangerous than one that refuses on detection.
- **Code simplicity.** The archive's per-record JSON write pattern is dead-simple to read, debug, and extend. Adding a coordination layer at every write site doubles the cognitive load for a feature no shipping consumer needs.
- **Cross-platform reach.** VIGOR runs on Linux (CI), macOS (developers), Windows-WSL (some developers). File-system advisory locking has different semantics on each — `fcntl.flock` (Linux), `fcntl.lockf` (POSIX), `msvcrt.locking` (Windows native, doesn't apply to WSL). A coordination primitive must work everywhere or it is a portability bug.
- **Future flexibility.** A future `vigor-server` that picks a different archive backend (Postgres, S3, Redis-coordinated filesystem) cannot reuse a `fcntl`-based primitive anyway. Building one in the library would commit us to a primitive that the eventual hosted layer will discard.

## Considered Options

- **Option A — Single-node by contract, lightweight detection.** Document VIGOR-the-library as single-node-per-archive. Add a process-lifetime advisory lock at `RunArchive.__init__` (a `.archive.lock` sentinel file with `fcntl.flock` on POSIX, `msvcrt.locking` on Windows). A second process opening the same archive directory raises `ArchiveLockedError`. The lock is a *guardrail* — it surfaces the misconfiguration, not a coordination primitive that supports concurrent writers.
- **Option B — Full cross-process coordination.** Add `fcntl`-based file locking around every `write_*` method in `RunArchive`. Allow multiple orchestrator processes to share an archive cleanly. Pay the portability and complexity tax to preserve the multi-replica future.
- **Option C — Status quo.** Document nothing; let operators discover concurrent-write hazards in production.
- **Option D — Switch archive backend to a database (SQLite, Postgres) with native concurrency.** Replace the filesystem layout with a database that handles concurrent access natively.

## Decision Outcome

Chosen: **Option A** — single-node by contract, lightweight detection.

The rationale is the four bullets in §Decision Drivers, distilled: the library is single-node by ADR-0030, the runtime should *enforce* that posture (a guardrail prevents the silent-corruption failure mode), and the runtime should *not* invest in coordination primitives that the eventual hosted layer will discard.

The implementation is small:

1. **`RunArchive.__init__` acquires an advisory lock** on `archive_dir/.archive.lock` (created if absent). The lock is *exclusive*, *non-blocking*, and held for the lifetime of the `RunArchive` instance. On Linux/macOS, `fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)`. On Windows, `msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)`. Failure raises `ArchiveLockedError`, a new exception in `vigor_core.errors`. Lock release happens in `RunArchive.close()` (a new method) and via `weakref.finalize` for safety.

2. **The `vigor-runtime` `Orchestrator` does not change.** The lock is acquired once when the archive is constructed; the orchestrator simply receives a `RunArchive` instance.

3. **The `vigor-agent` `AgentOrchestrator` does not change.** Same delegation.

4. **The CLI (`vigor-agent run`) does not change.** Single invocation per process; the lock is acquired-and-released cleanly via the `agent.aclose()`-in-`finally` pattern at `cli.py:52`.

5. **`docs/architecture/run-archive.md`** (new doc, written alongside the implementation Seeds) declares: "An archive directory is private to one orchestrator process. Concurrent access is not supported and is detected at archive-open time."

6. **`AgentOrchestrator` documentation** declares: "Two simultaneous `await agent.run(task)` calls in the same process are unsupported. Concurrent batched evaluation is the harness's job (Phase 6); the agent itself is single-task."

The lock is a **process-lifetime** lock, not a per-run lock. A long-lived orchestrator (Jupyter, a service) holds the lock for the duration of the process. A second process pointed at the same directory fails fast at archive-open. A second `AgentOrchestrator` in the same process pointed at the same directory *does not fail* (advisory locks are per-process on POSIX) — that case is documented as "unsupported" and is a programming error the library does not detect.

For the multi-replica future: when `vigor-server` lands, it will pick its own archive backend. If the chosen backend is shared filesystem with multiple orchestrator replicas, the hosting layer is responsible for partitioning runs across replicas (deterministic routing by `run_id`, lease-based distributed locks via etcd/Consul/Postgres advisory locks, or whatever the chosen runtime uses). The library's single-node-by-contract posture does not preclude that hosting; it just declares that the coordination primitive is the hosting layer's concern, not the library's.

### Alt-A: Lightweight detection (chosen) vs full cross-process coordination vs status quo vs database backend

| Alternative | Reason Rejected |
| --- | --- |
| Full cross-process coordination via `fcntl` locks at every write site | A speculative-future feature with no current customer. Doubles the surface of `archive.py`, adds a Windows-vs-POSIX portability tax, and is the wrong primitive for any database-backed future archive. The hosted-multi-replica use case (the only one that needs it) is deferred to `vigor-server` per ADR-0030; the hosting layer will pick its own coordination primitive (likely not `fcntl` on a network filesystem — the well-known horror story). |
| Status quo: ship nothing, document nothing | Operators who run two `vigor-agent run` invocations against the same `archive_dir` corrupt the archive silently. No error, no warning. The corruption mode (interleaved JSON file writes) is hard to debug because the symptoms are downstream — a `ValidationError` reading a half-written `provenance.json`, days after the corruption. The detection cost (one advisory lock at archive open) is dwarfed by the debugging cost of a single such incident. |
| Switch archive backend to SQLite / Postgres for native concurrency | Major rearchitecture of every read/write site in the runtime, every test fixture, and every CLI debugging workflow that today greps through `runs/<run_id>/...` JSON files. The filesystem layout is the *debugging* surface — operators read the archive directly with `cat`, `jq`, and `find`. A database eliminates that affordance. Out of scope for a runtime-completeness ADR; if the eventual `vigor-server` wants a database, it can layer one on top. |
| (Chosen) Lightweight detection — advisory lock at archive open, single-node-by-contract documentation | Smallest possible commitment that prevents the silent-corruption failure mode. Cross-platform via stdlib (`fcntl` + `msvcrt`). Does not preclude a future hosted layer from doing whatever it wants. Documents the contract explicitly so operators know what they are buying. |

### Alt-B: Lock granularity — process-lifetime vs per-run vs per-record

| Alternative | Reason Rejected |
| --- | --- |
| Per-run lock (`runs/<run_id>/.lock`) | Allows two processes to share an archive directory if they happen to operate on different `run_id`s. Sounds like a feature; in practice it commits us to per-run coordination semantics that are vulnerable to lock-during-rename races (the orchestrator writes `task.json` *before* it acquires a per-run lock unless we add an explicit upfront step) and that interfere with archive-wide operations like `RunArchive.list_runs` (not yet implemented but plausible). Per-record locks have the same problems at a finer scale. |
| Per-record lock (`<file>.lock` per JSON) | Maximum fine-grained safety, maximum complexity. Every `_safe_target` write site grows a lock-acquire and a lock-release. Indistinguishable from "ship a database." Out of scope. |
| (Chosen) Process-lifetime lock at archive root | Coarsest possible granularity that detects the misconfiguration. Single lock acquisition per process, single release at archive close. Covers all the failure modes a downstream-`vigor-server` would not have already solved with its own coordination primitive. |

### Alt-C: Lock primitive — `fcntl` advisory vs `flock(2)` direct vs file-rename atomicity

| Alternative | Reason Rejected |
| --- | --- |
| `flock(2)` direct via `os.open` | Lower-level than `fcntl.flock`, no real advantage. `fcntl` wraps it correctly and adds the cross-platform `LOCK_EX | LOCK_NB` constants we want. |
| File-rename atomicity (create `.archive.lock.<pid>` and rename, refusing if a non-self lock file exists) | Stale lock files after a kill-9: the next `vigor-agent run` finds the stale lock and refuses. Operator must manually delete. Worse UX than `fcntl` advisory locks (which are released by the OS on process exit, including kill-9). |
| (Chosen) `fcntl.flock` on POSIX, `msvcrt.locking` on Windows | Stdlib only. Released by the OS on process exit (so kill-9 is recoverable on next start). Standard primitive, well-understood. Cross-platform via the same conditional we already use for path handling. |

## Consequences

### Positive

1. **Silent-corruption failure mode is gone.** A second process opening the same archive directory fails fast with `ArchiveLockedError`. The operator sees a clear message instead of debugging interleaved JSON writes days later.
2. **Library-first commitment is concrete.** ADR-0030 declared the posture; this ADR enforces it at the runtime boundary. Sibling ADRs (cost ceiling, observability, checkpoint/resume) can assume single-node semantics without hedging.
3. **No portability tax.** Stdlib-only (`fcntl` + `msvcrt`), no new dependencies. The conditional is the same shape Python's standard library already uses for cross-platform file operations.
4. **Future hosted layer is unblocked.** `vigor-server` can pick any archive backend it wants — the library's single-node guardrail does not constrain the hosted layer's coordination choices.
5. **Debugging affordance preserved.** Operators continue to `cat runs/<run_id>/task.json` for postmortem inspection. The archive remains a transparent filesystem layout.

### Negative

1. **Two simultaneous `agent.run(task)` calls in the same process are unsupported and undetected.** Advisory locks are per-process on POSIX — a second `agent.run` in the same process does not see the lock as held by another. The library documents this as "unsupported" but does not detect it. Operators who run concurrent runs in the same process (e.g. `asyncio.gather(agent.run(t1), agent.run(t2))`) corrupt the archive silently. Mitigation: the `Orchestrator` could add a per-run-id reentrance check; this is filed as a follow-up Seeds task `VIGOR-c2ec` (see backlog).
2. **Network filesystems may misbehave.** `fcntl.flock` on NFS has historically been unreliable (NFSv3 silently no-ops; NFSv4 is better). Operators using a network-filesystem `archive_dir` may see the lock acquired but not effectively held across nodes. The runtime cannot detect this; the library's documentation will say "shared-filesystem archive directories are unsupported." Operators in that case need a coordination primitive the hosting layer provides — and per ADR-0030, that is `vigor-server`'s job, not the library's.
3. **No graceful waiting.** The non-blocking lock fails immediately. There is no "wait for the existing process to finish, then take the lock." Operators who want sequenced multi-process runs (rare, but plausible for batch jobs) write a wrapper script that retries on `ArchiveLockedError` with a sleep. The runtime does not provide a wait primitive — that is a coordination feature, which ADR-0032 is committing not to ship.
4. **A new exception (`ArchiveLockedError`) widens the public error surface.** Per ADR-0030's tight public-surface stance, every new exposed exception is an ADR-level commitment. This is one. The exception is added to `vigor_core.errors` and surfaces in `RunArchive.__init__`. Sibling builders writing `vigor-server` will need to know about it; the docs will say so.

### Neutral

1. The `_safe_target` path-containment check (`archive.py:170-180`) is unchanged. Path traversal is still rejected; concurrent writers are now also rejected — the two are independent guardrails.
2. The lock is *advisory*, meaning a process that bypasses `RunArchive` (a script that writes JSON files directly into the archive directory with `os.write`) is not blocked. This is a known limitation of advisory locks across the stdlib; a malicious or curious operator can always bypass it. The runtime's threat model is not adversarial here — the lock is a guardrail against accidental concurrent invocations, not a security boundary.
3. The lock file (`.archive.lock`) appears in the archive directory. Operators' `git`-tracked archives will see it; we recommend `.gitignore`-ing it. The Seeds task implementing this ADR adds the `.gitignore` line in the runtime monorepo's example archive directories.

## References

| Source | Path / URL |
| --- | --- |
| `RunArchive` (target for `__init__` lock acquisition) | `packages/vigor-core/src/vigor_core/archive.py:43-180` |
| `_safe_target` path containment (sibling guardrail) | `packages/vigor-core/src/vigor_core/archive.py:170-180` |
| `vigor_core.errors` (target for new `ArchiveLockedError`) | `packages/vigor-core/src/vigor_core/errors.py` |
| CLI archive open and close pattern | `packages/vigor-runtime/src/vigor_runtime/cli.py` |
| ADR-0007 (SDK-agnostic core posture) | `0007-sdk-agnostic-core-with-optional-agent-backends.md` |
| ADR-0009 (monorepo layout) | `0009-monorepo-layout.md` |
| ADR-0029 (per-tenant archive scoping; hosted-layer coordination) | `0029-multi-tenant-subprocess-env-hardening.md` |
| ADR-0030 (library-first posture; deferral of hosted layer) | `0030-library-first-deployment-posture.md` |
| Strategic summary | `docs/strategy/runtime-completeness.md` §Q2 |
| Python `fcntl.flock` documentation | https://docs.python.org/3.11/library/fcntl.html#fcntl.flock |
| NFS `fcntl` reliability discussion | https://www.kernel.org/doc/html/latest/filesystems/nfs/index.html |
