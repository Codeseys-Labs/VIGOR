"""Typer CLI for the VIGOR runtime."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import typer
from vigor_core.archive import RunArchive
from vigor_core.interfaces import GenerationRequest
from vigor_core.schemas import TaskSpec

from vigor_runtime.backends import EchoAgentBackend
from vigor_runtime.orchestrator import Orchestrator
from vigor_runtime.toy_adapter import ToyTextAdapter

app = typer.Typer(
    help="VIGOR: Verifiable Iterative Generation Over Representations",
    add_completion=False,
    no_args_is_help=True,
)


@app.command("version")
def version() -> None:
    """Print VIGOR runtime version."""

    from vigor_runtime import __version__

    typer.echo(__version__)


@app.command("demo")
def demo(
    goal: str = typer.Option(
        "Hello VIGOR",
        help="Text the toy adapter should echo.",
    ),
    runs_dir: Path = typer.Option(
        Path("runs"),
        help="Directory where run archives are written.",
    ),
    task_id: str = typer.Option(
        "demo_0001",
        help="Stable task id. Reused if you re-run.",
    ),
) -> None:
    """Run the end-to-end toy adapter loop using the echo backend."""

    archive = RunArchive(runs_dir)
    try:
        adapter = ToyTextAdapter()

        def seed(request: GenerationRequest) -> dict[str, Any]:
            return {"text": request.task.goal}

        backend = EchoAgentBackend(seed_ir_factory=seed)
        orchestrator = Orchestrator(adapter=adapter, backend=backend, archive=archive)

        task = TaskSpec(
            task_id=task_id,
            goal=goal,
            modalities=["toy_text"],
            target_outputs=["output.txt"],
        )
        result = asyncio.run(orchestrator.run(task))
        typer.echo(
            f"run_id={result.run_id} accepted={result.accepted} "
            f"stop_reason={result.stop_reason} selected={result.selected_candidate_id}"
        )
    finally:
        archive.close()


if __name__ == "__main__":
    app()
