"""Run archive tests."""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from vigor_core.archive import RunArchive
from vigor_core.errors import ArchiveLockedError, NoCheckpointError
from vigor_core.schemas import (
    AdapterManifest,
    AdjudicationReport,
    ArtifactIR,
    CompileResult,
    ExportBundle,
    Frontier,
    FrontierCandidate,
    IterationCheckpoint,
    ObservableArtifact,
    PatchPlan,
    ProvenanceActivity,
    ProvenanceRecord,
    ReviewReport,
    TaskSpec,
)


def _demo_task() -> TaskSpec:
    return TaskSpec(task_id="run_001", goal="demo", modalities=["toy"])


def test_write_and_read_task(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    task = _demo_task()
    archive.write_task(task)
    loaded = archive.read_task("run_001")
    assert loaded.task_id == "run_001"


def test_full_run_write_cycle(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    task = _demo_task()
    archive.write_task(task)

    manifest = AdapterManifest(
        adapter_id="toy.v1",
        domain="toy",
        version="0.1.0",
        supported_ir=["toy.v1"],
    )
    archive.write_manifest(task.task_id, manifest)

    ir = ArtifactIR(
        candidate_id="cand_0001",
        ir_type="toy.v1",
        body={"text": "hello"},
    )
    archive.write_ir(task.task_id, ir)

    artifact = ObservableArtifact(
        artifact_id="art_0001",
        uri="artifacts/hello.txt",
        media_type="text/plain",
    )
    compile_result = CompileResult(
        compile_id="compile_0001",
        candidate_id="cand_0001",
        tool_id="toy.compile",
        status="success",
        outputs=[artifact],
    )
    archive.write_compile_result(task.task_id, compile_result)

    review = ReviewReport(
        review_id="rev_0001",
        candidate_id="cand_0001",
        reviewer_id="toy.reviewer",
        reviewer_type="objective_metric",
        summary="ok",
        passed=True,
    )
    archive.write_review(task.task_id, review)

    reviews = archive.list_reviews(task.task_id, "cand_0001")
    assert len(reviews) == 1
    assert reviews[0].passed is True

    adjudication = AdjudicationReport(
        adjudication_id="adj_0001",
        candidate_id="cand_0001",
        policy_id="toy.default",
        hard_gate_passed=True,
        decision="accept",
    )
    archive.write_adjudication(task.task_id, adjudication)

    patch = PatchPlan(
        patch_id="patch_0001",
        source_candidate_id="cand_0001",
        objectives=["noop"],
    )
    archive.write_patch(task.task_id, patch)

    frontier = Frontier(
        frontier_id="frontier_0001",
        run_id=task.task_id,
        selection_policy="toy.default",
        candidates=[
            FrontierCandidate(
                candidate_id="cand_0001",
                status="selected",
                hard_gate_passed=True,
                rank=1,
                scores={"composite": 1.0},
            )
        ],
    )
    archive.write_frontier(task.task_id, frontier)

    export = ExportBundle(
        export_id="export_0001",
        candidate_id="cand_0001",
    )
    provenance = ProvenanceRecord(
        provenance_id="prov_0001",
        run_id=task.task_id,
        task_id=task.task_id,
        selected_candidate_id="cand_0001",
        stop_reason="accepted",
    )
    archive.write_final(task.task_id, export, provenance)

    assert archive.list_candidates(task.task_id) == ["cand_0001"]
    assert (archive.run_dir(task.task_id) / "frontier.json").exists()
    assert (archive.run_dir(task.task_id) / "final" / "export_bundle.json").exists()
    assert (archive.run_dir(task.task_id) / "final" / "provenance.json").exists()


def test_lock_file_created_on_open(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    try:
        assert (tmp_path / ".archive.lock").exists()
    finally:
        archive.close()


def test_close_is_idempotent(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    archive.close()
    archive.close()  # second close must not raise


def test_context_manager_releases_lock(tmp_path: Path) -> None:
    with RunArchive(tmp_path) as archive:
        archive.write_task(_demo_task())
    # After the context exits, a new archive can be opened.
    second = RunArchive(tmp_path)
    second.close()


def test_same_process_reentry_shares_lock(tmp_path: Path) -> None:
    """Adapter `export()` paths construct a transient RunArchive on the same
    root the orchestrator already holds. The refcount registry must allow
    this; otherwise normal happy-path runs would raise ArchiveLockedError.
    """

    primary = RunArchive(tmp_path)
    try:
        secondary = RunArchive(tmp_path)
        # Both should be usable.
        primary.write_task(_demo_task())
        # secondary points at the same root; reading what primary wrote
        # exercises that the refcounted re-entry produces a working archive.
        assert secondary.read_task("run_001").task_id == "run_001"
        secondary.close()
        # Primary still holds the lock — re-opening from the same process is
        # fine (refcount), and after primary closes it should also release.
    finally:
        primary.close()
    # After all in-process holders close, a fresh archive opens cleanly.
    third = RunArchive(tmp_path)
    third.close()


def _spawn_child_holding_lock(
    archive_dir: Path,
    ready_file: Path,
    exit_file: Path,
) -> subprocess.Popen[bytes]:
    """Spawn a child process that opens RunArchive and holds the lock until told to exit."""

    script = textwrap.dedent(
        f"""
        import sys
        import time
        from pathlib import Path

        from vigor_core.archive import RunArchive

        archive = RunArchive(Path({str(archive_dir)!r}))
        Path({str(ready_file)!r}).write_text("ready", encoding="utf-8")
        # Hold the lock until the test signals exit.
        deadline = time.monotonic() + 30.0
        while time.monotonic() < deadline:
            if Path({str(exit_file)!r}).exists():
                break
            time.sleep(0.05)
        archive.close()
        """
    )
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def test_second_process_raises_archive_locked_error(tmp_path: Path) -> None:
    archive_dir = tmp_path / "shared"
    archive_dir.mkdir()
    ready = tmp_path / "ready"
    exit_signal = tmp_path / "exit"
    proc = _spawn_child_holding_lock(archive_dir, ready, exit_signal)
    try:
        # Wait for child to acquire the lock.
        deadline_loops = 200  # 200 * 0.05s = 10s
        for _ in range(deadline_loops):
            if ready.exists():
                break
            if proc.poll() is not None:
                stdout, stderr = proc.communicate(timeout=1)
                raise AssertionError(
                    f"child exited early: rc={proc.returncode} stdout={stdout!r} stderr={stderr!r}"
                )
            time.sleep(0.05)
        else:
            raise AssertionError("child never reported ready")

        with pytest.raises(ArchiveLockedError):
            RunArchive(archive_dir)
    finally:
        exit_signal.write_text("go", encoding="utf-8")
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


def _checkpoint(run_id: str, *, next_iteration: int = 1) -> IterationCheckpoint:
    return IterationCheckpoint(
        checkpoint_id=f"ckpt_{run_id}_{next_iteration:04d}",
        run_id=run_id,
        next_iteration=next_iteration,
        prior_candidate_ids=[f"cand_{run_id}_0000"],
        adjudication_ids=[f"cand_{run_id}_0000"],
        last_candidate_id=f"cand_{run_id}_0000",
        activities=[ProvenanceActivity(activity_id="generate_x", type="generation")],
    )


def test_write_and_read_checkpoint_roundtrip(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    try:
        archive.write_task(_demo_task())
        ckpt = _checkpoint("run_001")
        path = archive.write_checkpoint("run_001", ckpt)
        assert path == archive.run_dir("run_001") / "iteration_checkpoint.json"
        loaded = archive.read_checkpoint("run_001")
        assert loaded.checkpoint_id == ckpt.checkpoint_id
        assert loaded.next_iteration == 1
        assert loaded.prior_candidate_ids == ckpt.prior_candidate_ids
    finally:
        archive.close()


def test_read_checkpoint_raises_when_absent(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    try:
        archive.write_task(_demo_task())
        with pytest.raises(NoCheckpointError):
            archive.read_checkpoint("run_001")
    finally:
        archive.close()


def test_write_checkpoint_overwrites_via_atomic_rename(tmp_path: Path) -> None:
    archive = RunArchive(tmp_path)
    try:
        archive.write_task(_demo_task())
        archive.write_checkpoint("run_001", _checkpoint("run_001", next_iteration=1))
        archive.write_checkpoint("run_001", _checkpoint("run_001", next_iteration=2))
        loaded = archive.read_checkpoint("run_001")
        assert loaded.next_iteration == 2
        # Atomic write must clean up its tmp file via os.replace.
        assert not (archive.run_dir("run_001") / "iteration_checkpoint.json.tmp").exists()
    finally:
        archive.close()


def test_lock_released_after_close_allows_reopen_from_other_process(tmp_path: Path) -> None:
    archive_dir = tmp_path / "shared"
    archive_dir.mkdir()
    first = RunArchive(archive_dir)
    first.close()
    # A subprocess should now be able to acquire the lock.
    rc = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                f"""
                from pathlib import Path
                from vigor_core.archive import RunArchive
                archive = RunArchive(Path({str(archive_dir)!r}))
                archive.close()
                """
            ),
        ],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert rc.returncode == 0, (rc.stdout, rc.stderr)
