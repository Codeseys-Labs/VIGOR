"""Minimal `RuntimeObserver` example: print every lifecycle event to stdout.

Wire it into the runtime via:

    vigor-agent run --config agent.yaml task.json \\
        --observer-factory docs.examples.observer:make_stdout_observer \\
        --observer-allowed-prefix docs.examples

Or in code:

    from docs.examples.observer import StdoutObserver
    orchestrator = Orchestrator(
        adapter=...,
        backend=...,
        archive=...,
        observer=StdoutObserver(),
    )

This is the canonical "is the seam wired?" smoke test. Production
observers ship spans to OpenTelemetry, increment Prometheus counters,
or write structured JSON; the surface is identical to this stub.

See ``docs/adr/0037-runtime-observer-protocol-seam.md``.
"""

from __future__ import annotations

import sys

from vigor_core.observability import RuntimeObserver  # noqa: F401  (informational import)
from vigor_core.schemas import (
    AdjudicationReport,
    CompileResult,
    ReviewReport,
    TaskSpec,
)


class StdoutObserver:
    """Prints every lifecycle event. Implements the RuntimeObserver Protocol structurally."""

    def on_run_start(self, run_id: str, task: TaskSpec) -> None:
        print(f"[observer] run_start run_id={run_id} task_id={task.task_id}", file=sys.stdout)

    def on_iteration_start(self, run_id: str, iteration: int) -> None:
        print(f"[observer] iteration_start run_id={run_id} iteration={iteration}")

    def on_candidate_start(self, run_id: str, iteration: int, candidate_id: str) -> None:
        print(
            f"[observer] candidate_start run_id={run_id} iteration={iteration} "
            f"candidate_id={candidate_id}"
        )

    def on_candidate_end(
        self,
        run_id: str,
        iteration: int,
        candidate_id: str,
        compile_result: CompileResult,
        reviews: list[ReviewReport],
        adjudication: AdjudicationReport,
    ) -> None:
        print(
            f"[observer] candidate_end run_id={run_id} iteration={iteration} "
            f"candidate_id={candidate_id} compile_status={compile_result.status} "
            f"reviews={len(reviews)} decision={adjudication.decision}"
        )

    def on_iteration_end(
        self,
        run_id: str,
        iteration: int,
        candidate_count: int,
        accepted_candidate_id: str | None,
    ) -> None:
        print(
            f"[observer] iteration_end run_id={run_id} iteration={iteration} "
            f"candidate_count={candidate_count} accepted={accepted_candidate_id}"
        )

    def on_run_end(
        self,
        run_id: str,
        accepted: bool,
        stop_reason: str,
        selected_candidate_id: str | None,
    ) -> None:
        print(
            f"[observer] run_end run_id={run_id} accepted={accepted} "
            f"stop_reason={stop_reason} selected={selected_candidate_id}"
        )

    def on_event(self, name: str, attributes: dict[str, object]) -> None:
        print(f"[observer] event name={name} attributes={attributes}")


def make_stdout_observer() -> StdoutObserver:
    """Factory entrypoint for ``--observer-factory`` CLI flag."""

    return StdoutObserver()
