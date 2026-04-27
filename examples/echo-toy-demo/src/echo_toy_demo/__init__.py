"""Minimal runnable demo.

Run with:

    uv run python -m echo_toy_demo

or via the CLI:

    uv run vigor demo --goal "Hello VIGOR" --runs-dir runs --task-id demo_0001
"""

import asyncio
from pathlib import Path

from vigor_core.archive import RunArchive
from vigor_core.schemas import TaskSpec
from vigor_runtime.backends import EchoAgentBackend
from vigor_runtime.orchestrator import Orchestrator
from vigor_runtime.toy_adapter import ToyTextAdapter


async def _main() -> None:
    runs_dir = Path("runs")
    archive = RunArchive(runs_dir)
    adapter = ToyTextAdapter()
    backend = EchoAgentBackend(seed_ir_factory=lambda req: {"text": req.task.goal})
    orchestrator = Orchestrator(adapter=adapter, backend=backend, archive=archive)

    task = TaskSpec(
        task_id="echo_demo_0001",
        goal="Hello VIGOR!",
        modalities=["toy_text"],
        target_outputs=["output.txt"],
    )
    result = await orchestrator.run(task)
    print(
        f"run_id={result.run_id} accepted={result.accepted} "
        f"stop_reason={result.stop_reason} selected={result.selected_candidate_id}"
    )


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
