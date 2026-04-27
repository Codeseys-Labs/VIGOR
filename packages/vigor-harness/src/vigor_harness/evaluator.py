"""Minimal harness evaluation runner."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from vigor_core.archive import RunArchive
from vigor_core.interfaces import AgentBackend, DomainAdapter
from vigor_core.schemas import TaskSpec
from vigor_runtime.orchestrator import Orchestrator

from vigor_harness.models import HarnessCandidate, HarnessEvalReport, SplitManifest


@dataclass(slots=True)
class HarnessEvaluationResult:
    report: HarnessEvalReport
    output_dir: Path


def _load_factory(path: str, allowed_prefixes: list[str]) -> Any:
    module_name, _, attr = path.partition(":")
    if not module_name or not attr:
        raise ValueError(f"factory path must be 'module:attr', got {path!r}")
    if not any(module_name.startswith(prefix) for prefix in allowed_prefixes):
        raise ValueError(
            f"factory module {module_name!r} is not in allowed prefixes {allowed_prefixes!r}"
        )
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def _load_tasks(split: SplitManifest) -> list[TaskSpec]:
    tasks: list[TaskSpec] = []
    for uri in split.task_uris:
        payload = json.loads(Path(uri).read_text(encoding="utf-8"))
        tasks.append(TaskSpec.model_validate(payload))
    return tasks


async def evaluate_candidate(
    candidate: HarnessCandidate,
    split: SplitManifest,
    output_dir: Path,
) -> HarnessEvaluationResult:
    """Evaluate one harness candidate over a split using normal VIGOR archives."""

    adapter_factory = _load_factory(candidate.adapter_factory, candidate.allowed_factory_prefixes)
    backend_factory = _load_factory(candidate.backend_factory, candidate.allowed_factory_prefixes)
    tasks = _load_tasks(split)
    candidate_dir = output_dir / candidate.candidate_id
    candidate_dir.mkdir(parents=True, exist_ok=True)
    archive = RunArchive(candidate_dir / "runs")
    n_succeeded = 0
    composites: list[float] = []
    hard_gate_passes = 0
    for task in tasks:
        # Backend lifecycle is owned per Orchestrator.run(), so instantiate per task.
        adapter = adapter_factory()
        backend = backend_factory()
        if not isinstance(adapter, DomainAdapter):
            raise TypeError("adapter_factory did not return a DomainAdapter")
        if not isinstance(backend, AgentBackend):
            raise TypeError("backend_factory did not return an AgentBackend")
        orchestrator = Orchestrator(adapter=adapter, backend=backend, archive=archive)
        result = await orchestrator.run(task)
        if result.accepted:
            n_succeeded += 1
        frontier_path = archive.run_dir(task.task_id) / "frontier.json"
        if frontier_path.exists():
            frontier = json.loads(frontier_path.read_text(encoding="utf-8"))
            selected = next(
                (c for c in frontier.get("candidates", []) if c.get("status") == "selected"),
                None,
            )
            if selected is not None:
                hard_gate_passes += 1 if selected.get("hardGatePassed") else 0
                composite = selected.get("scores", {}).get("composite")
                if isinstance(composite, int | float):
                    composites.append(float(composite))
    n_tasks = len(tasks)
    report = HarnessEvalReport(
        candidate_id=candidate.candidate_id,
        split_id=split.split_id,
        n_tasks=n_tasks,
        n_succeeded=n_succeeded,
        hard_gate_pass_rate=hard_gate_passes / n_tasks if n_tasks else 0.0,
        accept_rate=n_succeeded / n_tasks if n_tasks else 0.0,
        mean_composite=sum(composites) / len(composites) if composites else None,
    )
    (candidate_dir / "aggregate.json").write_text(
        report.model_dump_json(by_alias=True, indent=2), encoding="utf-8"
    )
    return HarnessEvaluationResult(report=report, output_dir=candidate_dir)
