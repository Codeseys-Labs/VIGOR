"""Typer CLI for the configurable VIGOR agent."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer
from vigor_core.schemas import TaskSpec

from vigor_agent.agent import AgentOrchestrator
from vigor_agent.config_loader import load_agent_config

app = typer.Typer(
    help="VIGOR configurable agent: run tasks against adapter+MCP configs.",
    add_completion=False,
    no_args_is_help=True,
)


@app.command("version")
def version() -> None:
    """Print vigor-agent version."""

    from vigor_agent import __version__

    typer.echo(__version__)


@app.command("run")
def run(
    config: Path = typer.Option(..., "--config", "-c", help="Path to AgentConfig YAML/JSON."),
    task_path: Path = typer.Argument(..., help="Path to a TaskSpec JSON file."),
) -> None:
    """Load an agent config, then run one TaskSpec end-to-end."""

    cfg = load_agent_config(config)
    task_payload = json.loads(task_path.read_text(encoding="utf-8"))
    task = TaskSpec.model_validate(task_payload)

    agent = AgentOrchestrator(cfg)

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


if __name__ == "__main__":
    app()
