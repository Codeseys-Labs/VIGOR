"""Runtime observability seam (ADR-0037).

Defines the ``RuntimeObserver`` ``Protocol`` the orchestrator emits
lifecycle events into. The library never imports a specific telemetry
SDK — downstream packages (``vigor-observability-otel``,
``vigor-observability-prometheus``, ad-hoc loggers) implement the
Protocol against their preferred sink.

Default behavior: no observer attached → no events emitted, zero
overhead beyond an ``is None`` check at each emission site. See
``docs/adr/0037-runtime-observer-protocol-seam.md``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from vigor_core.schemas import (
    AdjudicationReport,
    CompileResult,
    ReviewReport,
    TaskSpec,
)


@runtime_checkable
class RuntimeObserver(Protocol):
    """Opt-in seam for emitting runtime lifecycle events.

    Implementations live downstream of vigor-runtime; the library
    never imports a specific telemetry SDK. Methods are best-effort:
    the runtime catches and discards exceptions raised inside any
    observer method to prevent observer bugs from breaking runs.

    **Async-safety.** Under ADR-0034 parallel best-of-N, multiple
    ``on_candidate_start`` / ``on_candidate_end`` calls can fire
    concurrently from the same iteration. Implementations must be
    safe to call from inside an ``asyncio.gather`` batch — typically
    by relying on already-async-safe primitives (OpenTelemetry's
    tracer, ``prometheus_client``'s internal locks) or by guarding
    shared mutable state with ``asyncio.Lock``.

    **Sync, not async.** Methods are sync to keep the contract
    visible: an observer that needs to do async work (ship spans to
    a remote collector, write to disk) must spawn a background task
    itself; the runtime will not ``await`` the observer.
    """

    def on_run_start(self, run_id: str, task: TaskSpec) -> None:
        """Called once when ``Orchestrator.run`` begins, after the task is archived."""

    def on_iteration_start(self, run_id: str, iteration: int) -> None:
        """Called at the top of every iteration, after the wall-clock budget check."""

    def on_candidate_start(self, run_id: str, iteration: int, candidate_id: str) -> None:
        """Called when a candidate begins evaluation (validate → compile → review)."""

    def on_candidate_end(
        self,
        run_id: str,
        iteration: int,
        candidate_id: str,
        compile_result: CompileResult,
        reviews: list[ReviewReport],
        adjudication: AdjudicationReport,
    ) -> None:
        """Called when a candidate's evaluation finishes (any of: validation
        failure, compile failure, success). All three early-return paths in
        ``Orchestrator._evaluate_candidate`` route through this method.
        """

    def on_iteration_end(
        self,
        run_id: str,
        iteration: int,
        candidate_count: int,
        accepted_candidate_id: str | None,
    ) -> None:
        """Called at the bottom of each iteration body. ``accepted_candidate_id``
        is the id of the accepted candidate when the iteration ended on
        ``accept`` — otherwise ``None``.
        """

    def on_run_end(
        self,
        run_id: str,
        accepted: bool,
        stop_reason: str,
        selected_candidate_id: str | None,
    ) -> None:
        """Called once at the very end of ``Orchestrator.run``, just before the
        ``RunResult`` is returned. Always fires — success, failure, exception.
        """

    def on_event(self, name: str, attributes: dict[str, object]) -> None:
        """Open-ended escape hatch for non-lifecycle events.

        The runtime emits a small fixed set of canonical events
        (``patch_applied``, ``export_failed``, ``cancelled``); observers
        should pattern-match on ``name`` defensively.
        """


__all__ = ["RuntimeObserver"]
