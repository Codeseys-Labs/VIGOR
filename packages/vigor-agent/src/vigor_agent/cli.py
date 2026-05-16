"""Typer CLI for the configurable VIGOR agent."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from vigor_core.agent_config import FactoryRef
from vigor_core.observability import RuntimeObserver
from vigor_core.schemas import TaskSpec

from vigor_agent.agent import AgentOrchestrator
from vigor_agent.config_loader import load_agent_config
from vigor_agent.factory import FactoryLoadError, call_factory

app = typer.Typer(
    help="VIGOR configurable agent: run tasks against adapter+MCP configs.",
    add_completion=False,
    no_args_is_help=True,
)


def _build_observer(factory_ref: str | None, allowed_prefixes: list[str]) -> RuntimeObserver | None:
    """Resolve ``--observer-factory`` to a `RuntimeObserver`.

    Mirrors the FactoryRef allowlist convention used elsewhere in the
    codebase (ADR-0014 / harness): the module path must satisfy a
    dotted-component prefix match against ``allowed_prefixes``.
    """

    if factory_ref is None:
        return None
    ref = FactoryRef(factory=factory_ref, allowed_prefixes=allowed_prefixes)
    instance = call_factory(ref)
    if not isinstance(instance, RuntimeObserver):
        raise FactoryLoadError(
            f"observer factory {factory_ref!r} did not return a RuntimeObserver "
            f"(got {type(instance).__name__})"
        )
    return instance


@app.command("version")
def version() -> None:
    """Print vigor-agent version."""

    from vigor_agent import __version__

    typer.echo(__version__)


@app.command("run")
def run(
    config: Path = typer.Option(..., "--config", "-c", help="Path to AgentConfig YAML/JSON."),
    task_path: Path = typer.Argument(..., help="Path to a TaskSpec JSON file."),
    observer_factory: str | None = typer.Option(
        None,
        "--observer-factory",
        help=(
            "Optional 'module:func' factory returning a vigor_core.observability."
            "RuntimeObserver (ADR-0037). The module must satisfy --observer-allowed-"
            "prefixes."
        ),
    ),
    observer_allowed_prefixes: list[str] = typer.Option(
        ["vigor_"],
        "--observer-allowed-prefix",
        help=(
            "Allowed module prefixes for --observer-factory. May be repeated. "
            "Defaults to ['vigor_']."
        ),
    ),
) -> None:
    """Load an agent config, then run one TaskSpec end-to-end."""

    cfg = load_agent_config(config)
    task_payload = json.loads(task_path.read_text(encoding="utf-8"))
    task = TaskSpec.model_validate(task_payload)
    observer = _build_observer(observer_factory, list(observer_allowed_prefixes))

    agent = AgentOrchestrator(cfg, observer=observer)

    async def _run() -> None:
        try:
            result = await agent.run(task)
            typer.echo(
                f"run_id={result.run_id} accepted={result.accepted} "
                f"stop_reason={result.stop_reason} "
                f"selected={result.selected_candidate_id}"
            )
        finally:
            await agent.aclose()

    asyncio.run(_run())


@app.command("resolve")
def resolve(
    config: Path = typer.Option(..., "--config", "-c", help="Path to AgentConfig YAML/JSON."),
    task_path: Path = typer.Argument(..., help="Path to a TaskSpec JSON file."),
) -> None:
    """Print which adapter would be selected for a TaskSpec, without running."""

    cfg = load_agent_config(config)
    task_payload = json.loads(task_path.read_text(encoding="utf-8"))
    task = TaskSpec.model_validate(task_payload)
    agent = AgentOrchestrator(cfg)
    typer.echo(agent.resolve_adapter(task))


@app.command("resume")
def resume(
    config: Path = typer.Option(..., "--config", "-c", help="Path to AgentConfig YAML/JSON."),
    run_id: str = typer.Argument(..., help="run_id of a partial run with an iteration checkpoint."),
) -> None:
    """Resume a partial run from its iteration checkpoint (ADR-0036).

    Reads ``runs/<run_id>/iteration_checkpoint.json`` from the configured
    archive directory, re-resolves the adapter from the archived TaskSpec,
    builds a fresh backend, and re-enters the run loop at
    ``checkpoint.next_iteration``. Wall-clock and cost budgets restart
    from zero on the resumed run; tighten ``Budgets.max_cost_usd`` /
    ``max_wall_clock_s`` on the archived task before resuming if you
    require an end-to-end ceiling.
    """

    cfg = load_agent_config(config)
    agent = AgentOrchestrator(cfg)

    async def _resume() -> None:
        try:
            result = await agent.resume(run_id)
            typer.echo(
                f"run_id={result.run_id} accepted={result.accepted} "
                f"stop_reason={result.stop_reason} "
                f"selected={result.selected_candidate_id}"
            )
        finally:
            await agent.aclose()

    asyncio.run(_resume())


if __name__ == "__main__":
    app()
