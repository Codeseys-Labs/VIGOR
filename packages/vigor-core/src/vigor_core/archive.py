"""Filesystem-backed run archive."""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import weakref
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from vigor_core.errors import (
    ArchiveBusyError,
    ArchiveLockedError,
    NoCheckpointError,
    SchemaValidationError,
)
from vigor_core.schemas import (
    AdapterManifest,
    AdjudicationReport,
    ArtifactIR,
    CompileResult,
    ExportBundle,
    Frontier,
    IterationCheckpoint,
    PatchPlan,
    ProvenanceRecord,
    ReviewReport,
    RuntimeErrorRecord,
    TaskSpec,
)

T = TypeVar("T", bound=BaseModel)


def _dump(model: BaseModel) -> str:
    return model.model_dump_json(by_alias=True, indent=2)


def _load(path: Path, cls: type[T]) -> T:
    try:
        return cls.model_validate_json(path.read_text(encoding="utf-8"))
    except ValidationError as exc:
        raise SchemaValidationError(
            f"failed to parse {cls.__name__} at {path}: {exc}",
            evidence_uri=str(path),
        ) from exc


_LOCK_FILENAME = ".archive.lock"


class _ArchiveLockHolder:
    """Process-local advisory lock on an archive root.

    POSIX uses ``fcntl.flock(LOCK_EX | LOCK_NB)``; Windows uses
    ``msvcrt.locking(LK_NBLCK, 1)``. Both are released by the OS on process
    exit (so ``kill -9`` is recoverable on next start) and surface a clear
    failure when a peer process already holds the lock.

    POSIX advisory locks are per-process: a second ``flock`` from the same
    process on a different fd to the same file *succeeds*. Windows
    ``msvcrt.locking`` is per-fd and would otherwise refuse same-process
    re-entry. The module-level refcount registry below makes both platforms
    behave the same way: the first opener acquires the OS lock; subsequent
    openers in the same process share the holder. The orchestrator's
    long-lived ``RunArchive`` plus a transient archive constructed by an
    adapter ``export()`` (e.g. ``vigor_adapter_cad.adapter:RunArchive(...)``)
    coexist without a spurious ``ArchiveLockedError``.
    """

    __slots__ = ("_fd", "_path", "_released")

    def __init__(self, root: Path) -> None:
        self._path = root / _LOCK_FILENAME
        self._released = False
        self._fd: int | None = None
        try:
            fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError as exc:
            raise ArchiveLockedError(
                f"failed to open archive lock file {self._path}: {exc}",
                evidence_uri=str(self._path),
            ) from exc
        try:
            _platform_lock(fd)
        except BlockingIOError as exc:
            os.close(fd)
            raise ArchiveLockedError(
                f"another process holds the archive lock {self._path}; "
                "VIGOR archives are single-node by contract (ADR-0035)",
                evidence_uri=str(self._path),
            ) from exc
        except OSError as exc:
            os.close(fd)
            raise ArchiveLockedError(
                f"failed to acquire archive lock {self._path}: {exc}",
                evidence_uri=str(self._path),
            ) from exc
        self._fd = fd

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        fd = self._fd
        self._fd = None
        if fd is None:
            return
        try:
            _platform_unlock(fd)
        finally:
            with contextlib.suppress(OSError):
                os.close(fd)


if sys.platform == "win32":  # pragma: no cover - exercised on Windows only
    import msvcrt

    def _platform_lock(fd: int) -> None:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _platform_unlock(fd: int) -> None:
        with contextlib.suppress(OSError):
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _platform_lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _platform_unlock(fd: int) -> None:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)


class _LockRegistry:
    """Process-local refcount of active archive locks, keyed on resolved root."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, tuple[_ArchiveLockHolder, int]] = {}

    def acquire(self, root: Path) -> str:
        key = str(root.resolve())
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                holder, count = entry
                self._entries[key] = (holder, count + 1)
                return key
            # Not yet held in this process — take the OS lock.
            holder = _ArchiveLockHolder(root)
            self._entries[key] = (holder, 1)
            return key

    def release(self, key: str) -> None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return
            holder, count = entry
            if count > 1:
                self._entries[key] = (holder, count - 1)
                return
            del self._entries[key]
        holder.release()


_REGISTRY = _LockRegistry()


class _ActiveRunRegistry:
    """Process-local set of archive roots currently driving an orchestrator run.

    Layered on top of :class:`_LockRegistry` (which holds the OS advisory
    lock and refcounts for legitimate same-process re-entry such as adapter
    ``export()`` paths). This registry detects the *different* failure
    mode that ADR-0035 §Negative #1 names: two ``Orchestrator.run`` /
    ``Orchestrator.resume`` calls on the same archive root within one
    process. Such calls would interleave ``write_task`` / ``read_task`` /
    ``write_checkpoint`` against the same files and corrupt the archive.

    A ``threading.Lock``-protected dict keyed on the resolved archive
    root makes :meth:`claim` an atomic check-and-insert under any of:
    multiple coroutines on one event loop, multiple event loops in one
    interpreter, or multiple OS threads. The asyncio-only common case
    works transparently because the lock is uncontended within a single
    event loop tick.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: set[str] = set()

    def claim(self, root: Path) -> str:
        key = str(root.resolve())
        with self._lock:
            if key in self._active:
                raise ArchiveBusyError(
                    f"another orchestrator run is already in flight on archive {key}; "
                    "concurrent in-process runs on the same archive are not supported "
                    "(ADR-0035 §Negative #1, VIGOR-c2ec)",
                    evidence_uri=key,
                )
            self._active.add(key)
            return key

    def release(self, key: str) -> None:
        with self._lock:
            self._active.discard(key)


_ACTIVE_RUNS = _ActiveRunRegistry()


class RunArchive:
    """Persist every record the orchestrator produces.

    Acquires an exclusive non-blocking advisory lock on
    ``<root>/.archive.lock`` for the lifetime of the instance. A second
    process that opens the same archive root raises
    :class:`vigor_core.errors.ArchiveLockedError`. Same-process re-opens
    (e.g. an adapter ``export()`` constructing a transient ``RunArchive``)
    share the lock via a refcount registry. See ADR-0035 for the
    single-node-by-contract rationale.

    Call :meth:`close` to release the lock; ``weakref.finalize`` releases
    it as a safety net if ``close`` is not called before the object is
    garbage-collected.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock_key: str | None = _REGISTRY.acquire(self.root)
        self._finalizer = weakref.finalize(self, _REGISTRY.release, self._lock_key)

    def close(self) -> None:
        """Release the archive lock. Idempotent."""

        key = self._lock_key
        if key is None:
            return
        self._lock_key = None
        # detach() prevents the finalizer from double-releasing; we release
        # explicitly so the OS lock drops promptly instead of waiting for GC.
        if self._finalizer.detach() is not None:
            _REGISTRY.release(key)

    def __enter__(self) -> RunArchive:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @contextlib.contextmanager
    def claim_active_run(self) -> Iterator[None]:
        """Mark this archive root as having an in-flight orchestrator run.

        Used by ``Orchestrator.run`` / ``Orchestrator.resume`` to fail fast
        when a caller attempts a second concurrent run on the same archive
        from the same process (ADR-0035 §Negative #1, VIGOR-c2ec).

        This is independent of the OS advisory lock that :class:`RunArchive`
        already holds. The OS lock is process-scoped (and refcounted within
        a process so adapter ``export()`` can construct a transient
        ``RunArchive``); the active-runs registry is run-scoped within a
        process and exists precisely to catch the case the OS lock cannot.

        Releases on every exit (success or exception). Raises
        :class:`vigor_core.errors.ArchiveBusyError` immediately on entry if
        another claim is already outstanding.
        """

        key = _ACTIVE_RUNS.claim(self.root)
        try:
            yield
        finally:
            _ACTIVE_RUNS.release(key)

    def run_dir(self, run_id: str) -> Path:
        return self._safe_target(run_id)

    def candidate_dir(self, run_id: str, candidate_id: str) -> Path:
        return self._safe_target(f"{run_id}/candidates/{candidate_id}")

    def reviews_dir(self, run_id: str, candidate_id: str) -> Path:
        return self._safe_target(f"{run_id}/candidates/{candidate_id}/reviews")

    def artifacts_dir(self, run_id: str, candidate_id: str) -> Path:
        return self._safe_target(f"{run_id}/candidates/{candidate_id}/artifacts")

    def write_task(self, task: TaskSpec) -> Path:
        run_dir = self.run_dir(task.task_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "task.json"
        path.write_text(_dump(task), encoding="utf-8")
        return path

    def read_task(self, run_id: str) -> TaskSpec:
        return _load(self.run_dir(run_id) / "task.json", TaskSpec)

    def write_manifest(self, run_id: str, manifest: AdapterManifest) -> Path:
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "adapter_manifest.json"
        path.write_text(_dump(manifest), encoding="utf-8")
        return path

    def write_ir(self, run_id: str, ir: ArtifactIR) -> Path:
        cand = self.candidate_dir(run_id, ir.candidate_id)
        cand.mkdir(parents=True, exist_ok=True)
        path = cand / "ir.json"
        path.write_text(_dump(ir), encoding="utf-8")
        return path

    def read_ir(self, run_id: str, candidate_id: str) -> ArtifactIR:
        return _load(self.candidate_dir(run_id, candidate_id) / "ir.json", ArtifactIR)

    def write_compile_result(self, run_id: str, result: CompileResult) -> Path:
        cand = self.candidate_dir(run_id, result.candidate_id)
        cand.mkdir(parents=True, exist_ok=True)
        path = cand / "compile_result.json"
        path.write_text(_dump(result), encoding="utf-8")
        return path

    def write_review(self, run_id: str, review: ReviewReport) -> Path:
        reviews = self.reviews_dir(run_id, review.candidate_id)
        reviews.mkdir(parents=True, exist_ok=True)
        path = self._safe_target(
            f"{run_id}/candidates/{review.candidate_id}/reviews/{review.review_id}.json"
        )
        path.write_text(_dump(review), encoding="utf-8")
        return path

    def list_reviews(self, run_id: str, candidate_id: str) -> list[ReviewReport]:
        reviews = self.reviews_dir(run_id, candidate_id)
        if not reviews.exists():
            return []
        return [_load(path, ReviewReport) for path in sorted(reviews.glob("*.json"))]

    def write_adjudication(self, run_id: str, report: AdjudicationReport) -> Path:
        cand = self.candidate_dir(run_id, report.candidate_id)
        cand.mkdir(parents=True, exist_ok=True)
        path = cand / "adjudication.json"
        path.write_text(_dump(report), encoding="utf-8")
        return path

    def read_adjudication(self, run_id: str, candidate_id: str) -> AdjudicationReport:
        return _load(
            self.candidate_dir(run_id, candidate_id) / "adjudication.json",
            AdjudicationReport,
        )

    def write_patch(self, run_id: str, patch: PatchPlan) -> Path:
        cand = self.candidate_dir(run_id, patch.source_candidate_id)
        cand.mkdir(parents=True, exist_ok=True)
        path = cand / "patch_plan.json"
        path.write_text(_dump(patch), encoding="utf-8")
        return path

    def write_frontier(self, run_id: str, frontier: Frontier) -> Path:
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "frontier.json"
        path.write_text(_dump(frontier), encoding="utf-8")
        return path

    def write_checkpoint(self, run_id: str, checkpoint: IterationCheckpoint) -> Path:
        """Persist the latest iteration checkpoint atomically.

        Writes ``runs/<run_id>/iteration_checkpoint.json`` via the
        write-tmp-then-``os.replace`` pattern from :meth:`_atomic_write`. A
        crash mid-write leaves either the prior checkpoint or the new one
        intact, never a partial JSON. See ADR-0036 §Consequence #4.
        """

        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "iteration_checkpoint.json"
        self._atomic_write(path, _dump(checkpoint))
        return path

    def read_checkpoint(self, run_id: str) -> IterationCheckpoint:
        """Load the latest iteration checkpoint for ``run_id``.

        Raises :class:`vigor_core.errors.NoCheckpointError` if the run
        directory has no ``iteration_checkpoint.json`` (run never reached
        an iteration boundary, or the archive is empty). Per ADR-0036,
        ``Orchestrator.resume`` is opt-in: callers handle this error and
        decide whether to start over instead.
        """

        path = self.run_dir(run_id) / "iteration_checkpoint.json"
        if not path.exists():
            raise NoCheckpointError(
                f"no iteration checkpoint at {path}; run never reached an "
                "iteration boundary or the archive is empty",
                evidence_uri=str(path),
            )
        return _load(path, IterationCheckpoint)

    def _atomic_write(self, path: Path, data: str) -> None:
        """Write ``data`` to ``path`` via tmp-file + ``os.replace``.

        Per ADR-0036 §Consequence #4, the iteration checkpoint must be
        atomic: a crash mid-write must not leave a partial file that the
        resume path would fail to parse. ``os.replace`` is atomic on POSIX
        and Windows (within the same filesystem), so a reader sees either
        the previous file or the new one — never a half-written one.
        VIGOR-c09b will migrate the rest of the archive's writes onto this
        helper.
        """

        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(data, encoding="utf-8")
        os.replace(tmp, path)

    def write_final(
        self,
        run_id: str,
        export_bundle: ExportBundle,
        provenance: ProvenanceRecord,
    ) -> tuple[Path, Path]:
        final_dir = self._safe_target(f"{run_id}/final")
        final_dir.mkdir(parents=True, exist_ok=True)
        export_path = final_dir / "export_bundle.json"
        export_path.write_text(_dump(export_bundle), encoding="utf-8")
        prov_path = final_dir / "provenance.json"
        prov_path.write_text(_dump(provenance), encoding="utf-8")
        return export_path, prov_path

    def list_candidates(self, run_id: str) -> list[str]:
        cands = self.run_dir(run_id) / "candidates"
        if not cands.exists():
            return []
        return sorted(p.name for p in cands.iterdir() if p.is_dir())

    def write_raw(self, relative_path: str, data: str | bytes) -> Path:
        target = self._safe_target(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            target.write_bytes(data)
        else:
            target.write_text(data, encoding="utf-8")
        return target

    def write_json(self, relative_path: str, obj: Any) -> Path:
        return self.write_raw(relative_path, json.dumps(obj, indent=2, default=str))

    def write_error(self, run_id: str, error: RuntimeErrorRecord) -> Path:
        errors_dir = self._safe_target(f"{run_id}/errors")
        errors_dir.mkdir(parents=True, exist_ok=True)
        path = self._safe_target(f"{run_id}/errors/{error.error_id}.json")
        path.write_text(_dump(error), encoding="utf-8")
        return path

    def _safe_target(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ValueError(f"relative_path must not be absolute: {relative_path!r}")
        root_resolved = self.root.resolve()
        target = (self.root / candidate).resolve()
        try:
            target.relative_to(root_resolved)
        except ValueError as exc:
            raise ValueError(f"relative_path escapes archive root: {relative_path!r}") from exc
        return target
