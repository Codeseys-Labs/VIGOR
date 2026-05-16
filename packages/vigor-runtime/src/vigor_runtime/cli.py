"""Typer CLI for the VIGOR runtime."""

from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
from typing import Any

import typer
from vigor_core.archive import RunArchive
from vigor_core.interfaces import GenerationRequest
from vigor_core.observability import RuntimeObserver
from vigor_core.schemas import TaskSpec

from vigor_runtime.backends import EchoAgentBackend
from vigor_runtime.orchestrator import Orchestrator
from vigor_runtime.toy_adapter import ToyTextAdapter


def _resolve_observer_factory(
    factory_ref: str | None, allowed_prefixes: list[str]
) -> RuntimeObserver | None:
    """Lightweight observer factory resolver for the demo CLI (ADR-0037).

    The runtime CLI does not depend on vigor-agent (which owns the
    canonical FactoryRef-driven loader), so this duplicates the dotted-
    prefix gate in a minimal form. Production callers should use
    ``vigor-agent run --observer-factory``.
    """

    if factory_ref is None:
        return None
    module_name, _, attr = factory_ref.partition(":")
    if not module_name or not attr:
        raise typer.BadParameter(f"--observer-factory must be 'module:attr', got {factory_ref!r}")
    if not any(
        module_name == prefix or module_name.startswith(prefix + ".") for prefix in allowed_prefixes
    ):
        raise typer.BadParameter(
            f"observer factory module {module_name!r} not in allowed prefixes {allowed_prefixes!r}"
        )
    module = importlib.import_module(module_name)
    factory = getattr(module, attr)
    instance = factory()
    if not isinstance(instance, RuntimeObserver):
        raise typer.BadParameter(
            f"observer factory {factory_ref!r} did not return a RuntimeObserver "
            f"(got {type(instance).__name__})"
        )
    return instance


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
    observer_factory: str | None = typer.Option(
        None,
        "--observer-factory",
        help=(
            "Optional 'module:func' factory returning a vigor_core.observability."
            "RuntimeObserver (ADR-0037)."
        ),
    ),
    observer_allowed_prefixes: list[str] = typer.Option(
        ["vigor_"],
        "--observer-allowed-prefix",
        help="Allowed module prefixes for --observer-factory (default ['vigor_']).",
    ),
) -> None:
    """Run the end-to-end toy adapter loop using the echo backend."""

    archive = RunArchive(runs_dir)
    try:
        adapter = ToyTextAdapter()

        def seed(request: GenerationRequest) -> dict[str, Any]:
            return {"text": request.task.goal}

        backend = EchoAgentBackend(seed_ir_factory=seed)
        observer = _resolve_observer_factory(observer_factory, list(observer_allowed_prefixes))
        orchestrator = Orchestrator(
            adapter=adapter, backend=backend, archive=archive, observer=observer
        )

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
