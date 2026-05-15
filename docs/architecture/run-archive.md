# RunArchive: single-node by contract

Status: living doc — implements [ADR-0035](../adr/0035-single-node-orchestrator-posture.md).

## Contract

An archive directory is **private to one orchestrator process**. Concurrent
access from multiple processes is unsupported and is detected at archive-open
time.

`vigor_core.archive.RunArchive` acquires an exclusive non-blocking advisory
lock on `<archive_dir>/.archive.lock` in its constructor. A second process
that opens the same `archive_dir` raises
`vigor_core.errors.ArchiveLockedError`. The lock is held for the lifetime of
the `RunArchive` instance and released by `RunArchive.close()`. A
`weakref.finalize` releases the lock as a safety net if `close` is not called
before the object is garbage-collected.

The lock primitive is `fcntl.flock(fd, LOCK_EX | LOCK_NB)` on POSIX and
`msvcrt.locking(fd, LK_NBLCK, 1)` on Windows — stdlib only, no new
dependencies. Both primitives are released by the OS on process exit, so a
`kill -9`'d orchestrator does not leave a stale lock.

## What is and is not detected

| Scenario | Detected? |
| --- | --- |
| Two `vigor-agent run` invocations against the same `archive_dir` | Yes — second invocation raises `ArchiveLockedError` |
| Two `RunArchive(...)` constructions in two separate processes | Yes |
| Two `RunArchive(...)` constructions in the **same** process pointing at the same dir | No — the in-process refcount registry intentionally allows this so adapter `export()` paths that construct a transient `RunArchive(run_dir.parent)` do not collide with the orchestrator's long-lived archive. |
| Two simultaneous `await agent.run(task)` calls in the same `AgentOrchestrator` | **No.** Documented as unsupported per ADR-0035 §Negative §1. Tracked as follow-up `VIGOR-c2ec`. |
| Concurrent process on a network filesystem (NFS) | Best-effort. `fcntl.flock` on NFS has historically been unreliable; shared-filesystem archive directories are unsupported. See ADR-0035 §Negative §2. |
| Direct file writes that bypass `RunArchive` | No — the lock is **advisory**. Operators or scripts that write JSON files directly into the archive directory are not blocked. |

## Lifecycle

The lock is a **process-lifetime** lock, not a per-run lock. A long-lived
orchestrator (Jupyter session, hosted service) holds the lock for the whole
process. Discrete invocations should release it on shutdown:

```python
archive = RunArchive(runs_dir)
try:
    # ... use archive ...
finally:
    archive.close()
```

`AgentOrchestrator.aclose()` already calls `RunArchive.close()` on the agent's
private archive. The CLI demo (`vigor-runtime.cli:demo`) and the harness
evaluator (`vigor_harness.evaluator:evaluate_candidate`) wrap their archive
construction in `try/finally` so the lock drops promptly even on exception.
`RunArchive` also supports the context-manager protocol — `with
RunArchive(root) as archive: ...` is equivalent.

## Future hosted layer

When `vigor-server` lands (see [ADR-0030](../adr/0030-library-first-deployment-posture.md)),
it will pick its own archive backend (Postgres, S3, Redis-coordinated FS, …)
and its own coordination primitive. The library's single-node guardrail does
not constrain that hosting layer's choices: it merely declares that
cross-process coordination is the hosting layer's concern, not the library's.

## References

| Artifact | Path |
| --- | --- |
| ADR-0035 | `docs/adr/0035-single-node-orchestrator-posture.md` |
| ADR-0030 (library-first posture) | `docs/adr/0030-library-first-deployment-posture.md` |
| Implementation | `packages/vigor-core/src/vigor_core/archive.py` |
| Error class | `packages/vigor-core/src/vigor_core/errors.py` (`ArchiveLockedError`) |
| Tests | `packages/vigor-core/tests/test_archive.py` |
| Backlog entry | `docs/strategy/runtime-completeness-backlog.md` (`VIGOR-aa1c`) |
