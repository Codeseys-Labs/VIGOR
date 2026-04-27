"""CLI smoke test."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner
from vigor_runtime.cli import app


def test_cli_demo_writes_run(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "demo",
            "--goal",
            "Hello CLI",
            "--runs-dir",
            str(tmp_path),
            "--task-id",
            "cli_demo",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "accepted=True" in result.output
    assert (tmp_path / "cli_demo" / "task.json").exists()
