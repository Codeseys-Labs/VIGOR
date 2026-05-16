"""VIGOR async orchestrator.

Runs the generate-compile-review-adjudicate-patch loop described in
``docs/vigor-framework.md``. The runtime supports patch refinement and
best-of-N candidate evaluation.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
import uuid
from dataclasses import dataclass, field

from vigor_core.archive import RunArchive
from vigor_core.errors import VigorError
from vigor_core.interfaces import (
    AgentBackend,
    DomainAdapter,
    GenerationRequest,
    PatchProposalRequest,
    RepresentationPlan,
    ReviewRequest,
    RunContext,
    ToolBackend,
)
from vigor_core.observability import RuntimeObserver
from vigor_core.schemas import (
    AdjudicationReport,
    ArtifactIR,
    CompileResult,
    ExportBundle,
    IterationCheckpoint,
    ObservableArtifact,
    ProvenanceActivity,
    ProvenanceRecord,
    ReviewReport,
    RuntimeErrorRecord,
    StopReason,
    TaskSpec,
    Usage,
)
from vigor_core.scoring import (
    AdjudicationInputs,
    ScoringPolicy,
    adjudicate,
    build_frontier,
    select_best,
)
from vigor_core.util import utcnow_iso

from vigor_runtime.budget import RunBudgetTracker

# Orthogonal Python logging seam — independent of the observer Protocol.
# Library users configure handlers as they would for any library; the
# deployment-layer vigor-server configures structured JSON output.
_logger = logging.getLogger("vigor.runtime")


@dataclass(slots=True)
class CandidateOutcome:
    ir: ArtifactIR
    compile_result: CompileResult
    artifact: ObservableArtifact | None
    reviews: list[ReviewReport]
    adjudication: AdjudicationReport


@dataclass(slots=True)
class RunResult:
    run_id: str
    accepted: bool
    stop_reason: StopReason
    selected_candidate_id: str | None
    export_bundle: ExportBundle | None
    provenance: ProvenanceRecord
    usage: Usage = field(default_factory=Usage)


class Orchestrator:
    """Async orchestrator for a single domain adapter + agent backend pairing."""

    def __init__(
        self,
        *,
        adapter: DomainAdapter,
        backend: AgentBackend,
        archive: RunArchive,
        policy: ScoringPolicy | None = None,
        tools: ToolBackend | None = None,
        tool_capabilities: frozenset[str] | None = None,
        observer: RuntimeObserver | None = None,
    ) -> None:
        self._adapter = adapter
        self._backend = backend
        self._archive = archive
        self._policy = policy or ScoringPolicy(policy_id="default.v1")
        self._tools = tools
        # Per ADR-0016 §3.2: orchestrator issues mutator capabilities
        # for the run. Default-empty means observer-only access; a
        # configuration / policy layer is responsible for granting
        # mutator tool ids when they are required for the task.
        self._tool_capabilities: frozenset[str] = (
            frozenset(tool_capabilities) if tool_capabilities is not None else frozenset()
        )
        # ADR-0037: opt-in observer Protocol. ``runtime_checkable`` validation
        # at construction time fails fast on misconfigured observers (object
        # missing one of the seven lifecycle methods) — a single isinstance
        # check that is *not* repeated at the per-emission hot path.
        if observer is not None and not isinstance(observer, RuntimeObserver):
            raise TypeError(
                "observer does not satisfy RuntimeObserver Protocol — must "
                "implement on_run_start, on_iteration_start, on_candidate_start, "
                "on_candidate_end, on_iteration_end, on_run_end, on_event"
            )
        self._observer: RuntimeObserver | None = observer

    def _emit(self, method_name: str, /, *args: object, **kwargs: object) -> None:
        """Best-effort observer dispatch (ADR-0037 §Decision Outcome).

        Observer bugs must not break runs: every observer call is wrapped
        in ``try / except Exception`` and logged at WARNING. The fast-path
        ``is None`` check matches the "zero overhead when no observer"
        promise — when no observer is attached the method simply returns
        before any attribute lookup.
        """

        observer = self._observer
        if observer is None:
            return
        try:
            getattr(observer, method_name)(*args, **kwargs)
        except Exception:
            _logger.warning("RuntimeObserver.%s raised; ignoring", method_name, exc_info=True)

    async def run(self, task: TaskSpec) -> RunResult:
        self._archive.write_task(task)
        return await self._execute(
            task=task,
            start_iteration=0,
            seed_prior=[],
            seed_current_ir=None,
            seed_activities=[],
            seed_adjudications=[],
            seed_last_candidate_id=None,
        )

    async def resume(self, run_id: str) -> RunResult:
        """Resume a partial run from its most recent iteration checkpoint.

        Per ADR-0036: reads ``runs/<run_id>/iteration_checkpoint.json``,
        rehydrates ``prior`` IRs from per-candidate archive entries plus
        ``adjudications`` from each candidate's ``adjudication.json``, and
        re-enters the loop at ``checkpoint.next_iteration``. Raises
        :class:`vigor_core.errors.NoCheckpointError` if no checkpoint
        exists. The resumed run gets a fresh wall-clock and cost counter
        — operators who care about end-to-end budgets must tighten
        ``max_cost_usd`` / ``max_wall_clock_s`` on the rehydrated task
        themselves (ADR-0036 §Negative §3).
        """

        task = self._archive.read_task(run_id)
        checkpoint = self._archive.read_checkpoint(run_id)
        prior = [self._archive.read_ir(run_id, cid) for cid in checkpoint.prior_candidate_ids]
        current_ir = (
            self._archive.read_ir(run_id, checkpoint.current_candidate_id)
            if checkpoint.current_candidate_id is not None
            else None
        )
        adjudications = [
            self._archive.read_adjudication(run_id, cid) for cid in checkpoint.adjudication_ids
        ]
        return await self._execute(
            task=task,
            start_iteration=checkpoint.next_iteration,
            seed_prior=prior,
            seed_current_ir=current_ir,
            seed_activities=list(checkpoint.activities),
            seed_adjudications=adjudications,
            seed_last_candidate_id=checkpoint.last_candidate_id,
        )

    async def _execute(
        self,
        *,
        task: TaskSpec,
        start_iteration: int,
        seed_prior: list[ArtifactIR],
        seed_current_ir: ArtifactIR | None,
        seed_activities: list[ProvenanceActivity],
        seed_adjudications: list[AdjudicationReport],
        seed_last_candidate_id: str | None,
    ) -> RunResult:
        run_id = task.task_id
        started = time.monotonic()
        # ADR-0036 + ADR-0037: write_task moved up to ``run()`` so resume()
        # does not redundantly persist a task it just read from the archive.
        # Observer + log emissions are run-scoped and apply equally to
        # fresh runs and resumed runs.
        _logger.info("run start run_id=%s task_id=%s", run_id, task.task_id)
        self._emit("on_run_start", run_id, task)

        activities: list[ProvenanceActivity] = list(seed_activities)
        adjudications: list[AdjudicationReport] = list(seed_adjudications)
        last_candidate_id: str | None = seed_last_candidate_id
        last_export: ExportBundle | None = None
        stop_reason: StopReason = "accepted"
        accepted = False
        fatal_error: RuntimeErrorRecord | None = None

        budget_tracker = RunBudgetTracker(self._backend, task.budgets)

        try:
            manifest = await self._adapter.describe_capabilities()
            self._archive.write_manifest(run_id, manifest)
            context = RunContext(
                run_id=run_id,
                run_dir=str(self._archive.run_dir(run_id)),
                task=task,
                tools=self._tools,
                tool_capabilities=self._tool_capabilities,
            )
            plan = await self._adapter.plan_representation(task)
            prior: list[ArtifactIR] = list(seed_prior)
            current_ir: ArtifactIR | None = seed_current_ir

            for iteration in range(start_iteration, task.budgets.max_iterations):
                context.iteration = iteration
                if time.monotonic() - started > task.budgets.max_wall_clock_s:
                    stop_reason = "budget_exhausted"
                    break
                if await budget_tracker.check():
                    stop_reason = "cost_exceeded"
                    break

                _logger.info("iteration start run_id=%s iteration=%d", run_id, iteration)
                self._emit("on_iteration_start", run_id, iteration)

                candidates = await self._candidate_batch(task, plan, prior, current_ir, activities)
                current_ir = None
                outcomes: list[CandidateOutcome] = []
                # ADR-0034: chunked asyncio.gather fanout. Default
                # parallel_candidates=1 → chunks of size 1 (byte-identical to
                # the legacy serial loop); operators raise the cap to opt in.
                eval_chunk = min(max(1, task.budgets.parallel_candidates), max(1, len(candidates)))
                for chunk_start in range(0, len(candidates), eval_chunk):
                    chunk = candidates[chunk_start : chunk_start + eval_chunk]
                    # ADR-0037 §Negative §1: parallel batches emit one
                    # ``on_candidate_start`` / ``on_candidate_end`` per
                    # candidate concurrently. Observers are documented as
                    # async-safe.
                    for ir in chunk:
                        self._emit("on_candidate_start", run_id, iteration, ir.candidate_id)
                        _logger.debug(
                            "candidate start run_id=%s iteration=%d candidate_id=%s",
                            run_id,
                            iteration,
                            ir.candidate_id,
                        )
                    gathered = await asyncio.gather(
                        *(self._evaluate_candidate(ir, context, activities) for ir in chunk),
                        return_exceptions=True,
                    )
                    for ir, item in zip(chunk, gathered, strict=True):
                        outcome = self._coerce_outcome(ir, item, run_id)
                        outcomes.append(outcome)
                        adjudications.append(outcome.adjudication)
                        prior.append(ir)
                        last_candidate_id = ir.candidate_id
                        self._emit(
                            "on_candidate_end",
                            run_id,
                            iteration,
                            ir.candidate_id,
                            outcome.compile_result,
                            outcome.reviews,
                            outcome.adjudication,
                        )
                        _logger.debug(
                            "candidate end run_id=%s iteration=%d candidate_id=%s decision=%s",
                            run_id,
                            iteration,
                            ir.candidate_id,
                            outcome.adjudication.decision,
                        )

                accepted_outcome = self._select_accepted_outcome(outcomes)
                if accepted_outcome is not None:
                    assert accepted_outcome.artifact is not None
                    export = await self._safe_export(
                        accepted_outcome.ir, accepted_outcome.artifact, context
                    )
                    if export is None:
                        accepted = False
                        stop_reason = "failed"
                        self._emit(
                            "on_event",
                            "export_failed",
                            {
                                "run_id": run_id,
                                "iteration": iteration,
                                "candidate_id": accepted_outcome.ir.candidate_id,
                            },
                        )
                    else:
                        accepted = True
                        last_export = export
                        last_candidate_id = accepted_outcome.ir.candidate_id
                        activities.append(
                            ProvenanceActivity(activity_id=export.export_id, type="export")
                        )
                        stop_reason = "accepted"
                    accepted_id = accepted_outcome.ir.candidate_id if accepted else None
                    self._emit(
                        "on_iteration_end",
                        run_id,
                        iteration,
                        len(outcomes),
                        accepted_id,
                    )
                    _logger.info(
                        "iteration end run_id=%s iteration=%d candidates=%d accepted=%s",
                        run_id,
                        iteration,
                        len(outcomes),
                        accepted_id,
                    )
                    # ADR-0036: write checkpoint at iteration boundary even
                    # on success-break so a crash before the final
                    # provenance.json still has a recovery point.
                    self._write_iteration_checkpoint(
                        run_id=run_id,
                        next_iteration=iteration + 1,
                        prior=prior,
                        current_ir=None,
                        activities=activities,
                        adjudications=adjudications,
                        last_candidate_id=last_candidate_id,
                    )
                    break

                patch_source = self._select_patch_source(outcomes)
                if patch_source is None:
                    stop_reason = (
                        "escalated"
                        if any(out.adjudication.decision == "escalate" for out in outcomes)
                        else "failed"
                    )
                    self._emit("on_iteration_end", run_id, iteration, len(outcomes), None)
                    _logger.info(
                        "iteration end run_id=%s iteration=%d candidates=%d "
                        "no_patchable_candidate stop_reason=%s",
                        run_id,
                        iteration,
                        len(outcomes),
                        stop_reason,
                    )
                    break

                proposal = await self._backend.propose_patch(
                    PatchProposalRequest(
                        ir=patch_source.ir, reviews=patch_source.reviews, context=context
                    )
                )
                self._archive.write_patch(run_id, proposal.patch)
                activities.append(
                    ProvenanceActivity(activity_id=proposal.patch.patch_id, type="patch")
                )
                self._emit(
                    "on_event",
                    "patch_applied",
                    {
                        "run_id": run_id,
                        "iteration": iteration,
                        "patch_id": proposal.patch.patch_id,
                        "source_candidate_id": patch_source.ir.candidate_id,
                    },
                )

                patched_ir = await self._adapter.apply_patch(patch_source.ir, proposal.patch)
                patched_validation = await self._adapter.validate_ir(patched_ir)
                if not patched_validation.ok:
                    fatal_error = RuntimeErrorRecord(
                        error_id=f"err_patch_{patch_source.ir.candidate_id}",
                        type="adapter_contract",
                        severity="high",
                        message=(
                            "apply_patch produced invalid IR: "
                            + "; ".join(patched_validation.errors)
                        ),
                        retryable=False,
                    )
                    self._archive.write_error(run_id, fatal_error)
                    stop_reason = "failed"
                    self._emit("on_iteration_end", run_id, iteration, len(outcomes), None)
                    _logger.info(
                        "iteration end run_id=%s iteration=%d candidates=%d patched_ir_invalid",
                        run_id,
                        iteration,
                        len(outcomes),
                    )
                    break
                # ADR-0036: persist the patched IR so resume can rehydrate
                # ``current_ir`` from disk via ``read_ir(run_id, cid)``. Without
                # this, ``current_candidate_id`` would point at a candidate
                # whose ir.json doesn't exist until the next iteration's
                # ``_evaluate_candidate`` writes it — fatal for resume across
                # the iteration boundary.
                self._archive.write_ir(run_id, patched_ir)
                current_ir = patched_ir
                self._emit("on_iteration_end", run_id, iteration, len(outcomes), None)
                _logger.info(
                    "iteration end run_id=%s iteration=%d candidates=%d patch_applied continuing",
                    run_id,
                    iteration,
                    len(outcomes),
                )
                # ADR-0036: end-of-iteration checkpoint after all candidate
                # JSONs are durable. A crash before the next iteration
                # starts resumes here with rehydrated prior + current_ir.
                self._write_iteration_checkpoint(
                    run_id=run_id,
                    next_iteration=iteration + 1,
                    prior=prior,
                    current_ir=current_ir,
                    activities=activities,
                    adjudications=adjudications,
                    last_candidate_id=last_candidate_id,
                )
            else:
                stop_reason = "budget_exhausted"

        except VigorError as exc:
            kind = exc.kind if exc.kind in _ERROR_KINDS else "generic"
            fatal_error = RuntimeErrorRecord.model_validate(
                {
                    "error_id": f"err_{uuid.uuid4().hex[:8]}",
                    "type": kind,
                    "severity": "high",
                    "message": exc.message,
                    "retryable": exc.retryable,
                    "evidence_uri": exc.evidence_uri,
                }
            )
            self._archive.write_error(run_id, fatal_error)
            stop_reason = "failed"
        except Exception as exc:
            fatal_error = RuntimeErrorRecord(
                error_id=f"err_{uuid.uuid4().hex[:8]}",
                type="generic",
                severity="high",
                message=f"{type(exc).__name__}: {exc}",
                retryable=False,
            )
            self._archive.write_error(run_id, fatal_error)
            stop_reason = "failed"
        finally:
            with contextlib.suppress(Exception):
                await budget_tracker.snapshot()
            with contextlib.suppress(Exception):
                await self._backend.aclose()

        frontier = build_frontier(
            run_id=run_id,
            frontier_id=f"frontier_{run_id}",
            adjudications=adjudications,
            policy=self._policy,
        )
        self._archive.write_frontier(run_id, frontier)
        best = select_best(frontier)
        selected_candidate_id = (
            last_candidate_id if accepted else (best.candidate_id if best else None)
        )

        provenance = ProvenanceRecord(
            provenance_id=f"prov_{run_id}_{uuid.uuid4().hex[:8]}",
            created_at=utcnow_iso(),
            run_id=run_id,
            task_id=task.task_id,
            selected_candidate_id=selected_candidate_id,
            inputs=[ref.artifact_id for ref in task.references],
            activities=activities,
            derived_artifacts=[last_candidate_id] if last_candidate_id else [],
            stop_reason=stop_reason,
            residual_risks=[fatal_error.message] if fatal_error is not None else [],
        )
        if last_export is not None and accepted:
            self._archive.write_final(run_id, last_export, provenance)

        _logger.info(
            "run end run_id=%s accepted=%s stop_reason=%s selected=%s",
            run_id,
            accepted,
            stop_reason,
            selected_candidate_id,
        )
        self._emit("on_run_end", run_id, accepted, stop_reason, selected_candidate_id)

        return RunResult(
            run_id=run_id,
            accepted=accepted,
            stop_reason=stop_reason,
            selected_candidate_id=selected_candidate_id,
            export_bundle=last_export,
            provenance=provenance,
            usage=budget_tracker.latest,
        )

    def _write_iteration_checkpoint(
        self,
        *,
        run_id: str,
        next_iteration: int,
        prior: list[ArtifactIR],
        current_ir: ArtifactIR | None,
        activities: list[ProvenanceActivity],
        adjudications: list[AdjudicationReport],
        last_candidate_id: str | None,
    ) -> None:
        checkpoint = IterationCheckpoint(
            checkpoint_id=f"ckpt_{run_id}_{next_iteration:04d}",
            run_id=run_id,
            next_iteration=next_iteration,
            prior_candidate_ids=[ir.candidate_id for ir in prior],
            current_candidate_id=(current_ir.candidate_id if current_ir is not None else None),
            activities=list(activities),
            adjudication_ids=[adj.candidate_id for adj in adjudications],
            last_candidate_id=last_candidate_id,
        )
        self._archive.write_checkpoint(run_id, checkpoint)

    async def _candidate_batch(
        self,
        task: TaskSpec,
        plan: RepresentationPlan,
        prior: list[ArtifactIR],
        current_ir: ArtifactIR | None,
        activities: list[ProvenanceActivity],
    ) -> list[ArtifactIR]:
        if current_ir is not None:
            return [current_ir]
        total = max(1, task.budgets.max_candidates)
        # ADR-0034: chunked fanout under parallel_candidates cap. Default
        # cap=1 reproduces the legacy serial loop (one-at-a-time generate
        # with a growing prior_candidates list). Higher caps fan out a
        # batch under asyncio.gather; the per-call ``prior_candidates``
        # snapshot is the same for every member of a batch, so we re-stamp
        # candidate IDs by global slot index *after* the gather returns.
        gen_chunk = min(max(1, task.budgets.parallel_candidates), total)
        generated: list[ArtifactIR] = []
        for chunk_start in range(0, total, gen_chunk):
            chunk_size = min(gen_chunk, total - chunk_start)
            snapshot = [*prior, *generated]
            requests = [
                GenerationRequest(task=task, plan=plan, prior_candidates=snapshot)
                for _ in range(chunk_size)
            ]
            results = await asyncio.gather(
                *(self._backend.generate(req) for req in requests),
                return_exceptions=True,
            )
            for slot_offset, item in enumerate(results):
                slot = chunk_start + slot_offset
                if isinstance(item, BaseException):
                    self._archive.write_error(
                        task.task_id,
                        RuntimeErrorRecord(
                            error_id=f"err_generate_{task.task_id}_{slot:04d}",
                            type="generic",
                            severity="high",
                            message=f"backend.generate raised {type(item).__name__}: {item}",
                            retryable=False,
                        ),
                    )
                    continue
                ir = item.ir
                # Re-stamp IDs by global slot to preserve sequential
                # determinism even under parallel fanout (ADR-0034
                # §Negative §2: "stable IDs, the index is computed before
                # fanout"). Backends compute `cand_<task>_<NNNN>` from
                # `len(prior_candidates)` which is constant within a
                # chunk — without this rewrite a chunk of 4 would all
                # claim slot 0000 and collide on archive paths.
                expected_id = f"cand_{task.task_id}_{slot:04d}"
                if ir.candidate_id != expected_id:
                    ir = ir.model_copy(update={"candidate_id": expected_id})
                generated.append(ir)
                activities.append(
                    ProvenanceActivity(
                        activity_id=f"generate_{ir.candidate_id}",
                        type="generation",
                        agent="backend",
                    )
                )
        return generated

    async def _evaluate_candidate(
        self,
        ir: ArtifactIR,
        context: RunContext,
        activities: list[ProvenanceActivity],
    ) -> CandidateOutcome:
        validation = await self._adapter.validate_ir(ir)
        if not validation.ok:
            self._archive.write_ir(context.run_id, ir)
            err = RuntimeErrorRecord(
                error_id=f"err_validate_{ir.candidate_id}",
                type="schema_validation",
                severity="high",
                message="; ".join(validation.errors),
                retryable=False,
            )
            compile_result = CompileResult(
                compile_id=f"compile_validate_{ir.candidate_id}",
                candidate_id=ir.candidate_id,
                tool_id="orchestrator.validate",
                status="failure",
                errors=[err],
            )
            self._archive.write_compile_result(context.run_id, compile_result)
            adj = self._failure_adjudication(ir.candidate_id, err.message)
            self._archive.write_adjudication(context.run_id, adj)
            return CandidateOutcome(ir, compile_result, None, [], adj)

        self._archive.write_ir(context.run_id, ir)
        compile_result = await self._safe_compile(ir, context)
        self._archive.write_compile_result(context.run_id, compile_result)
        activities.append(
            ProvenanceActivity(
                activity_id=compile_result.compile_id,
                type="compile",
                tool_id=compile_result.tool_id,
            )
        )

        if compile_result.status != "success" or not compile_result.outputs:
            reason = (
                "compile failed: " + "; ".join(e.message for e in compile_result.errors)
                if compile_result.errors
                else "compile failed"
            )
            adj = self._failure_adjudication(ir.candidate_id, reason)
            self._archive.write_adjudication(context.run_id, adj)
            return CandidateOutcome(ir, compile_result, None, [], adj)

        artifact = compile_result.outputs[0]
        reviews = await self._run_reviewers(
            ir=ir,
            artifact=artifact,
            context=context,
            compile_result=compile_result,
        )
        for review in reviews:
            self._archive.write_review(context.run_id, review)
            activities.append(
                ProvenanceActivity(
                    activity_id=review.review_id,
                    type="review",
                    reviewer_id=review.reviewer_id,
                )
            )

        adj = adjudicate(
            AdjudicationInputs(
                candidate_id=ir.candidate_id,
                reviews=reviews,
                hard_gate_signals={"compile_success": True, "render_success": True},
            ),
            self._policy,
            f"adj_{ir.candidate_id}",
        )
        self._archive.write_adjudication(context.run_id, adj)
        activities.append(ProvenanceActivity(activity_id=adj.adjudication_id, type="adjudication"))
        return CandidateOutcome(ir, compile_result, artifact, reviews, adj)

    def _select_accepted_outcome(self, outcomes: list[CandidateOutcome]) -> CandidateOutcome | None:
        accepted = [
            outcome
            for outcome in outcomes
            if outcome.adjudication.decision == "accept" and outcome.artifact is not None
        ]
        if not accepted:
            return None
        return max(
            accepted,
            key=lambda outcome: (
                outcome.adjudication.composite
                if outcome.adjudication.composite is not None
                else 0.0
            ),
        )

    def _select_patch_source(self, outcomes: list[CandidateOutcome]) -> CandidateOutcome | None:
        patchable = [
            outcome
            for outcome in outcomes
            if outcome.artifact is not None
            and outcome.adjudication.decision in {"patch", "branch", "pivot"}
        ]
        if not patchable:
            return None
        return max(
            patchable,
            key=lambda outcome: (
                outcome.adjudication.composite
                if outcome.adjudication.composite is not None
                else 0.0
            ),
        )

    async def _safe_compile(self, ir: ArtifactIR, context: RunContext) -> CompileResult:
        try:
            return await self._adapter.compile(ir, context)
        except VigorError as exc:
            kind = exc.kind if exc.kind in _ERROR_KINDS else "compile_error"
            err = RuntimeErrorRecord.model_validate(
                {
                    "error_id": f"err_compile_{ir.candidate_id}",
                    "type": kind,
                    "severity": "high",
                    "message": exc.message,
                    "retryable": exc.retryable,
                }
            )
            return CompileResult(
                compile_id=f"compile_{ir.candidate_id}_error",
                candidate_id=ir.candidate_id,
                tool_id="orchestrator.compile",
                status="failure",
                errors=[err],
            )

    async def _safe_export(
        self, ir: ArtifactIR, artifact: ObservableArtifact, context: RunContext
    ) -> ExportBundle | None:
        try:
            return await self._adapter.export(ir, artifact, context)
        except VigorError as exc:
            self._archive.write_error(
                context.run_id,
                RuntimeErrorRecord(
                    error_id=f"err_export_{ir.candidate_id}",
                    type="export_error",
                    severity="medium",
                    message=f"export raised VigorError: {exc.message}",
                    retryable=False,
                ),
            )
            return None
        except Exception as exc:
            self._archive.write_error(
                context.run_id,
                RuntimeErrorRecord(
                    error_id=f"err_export_{ir.candidate_id}",
                    type="export_error",
                    severity="medium",
                    message=f"export raised {type(exc).__name__}: {exc}",
                    retryable=False,
                ),
            )
            return None

    async def _run_reviewers(
        self,
        *,
        ir: ArtifactIR,
        artifact: ObservableArtifact,
        context: RunContext,
        compile_result: CompileResult,
    ) -> list[ReviewReport]:
        async def adapter_reviews() -> list[ReviewReport]:
            try:
                return await self._adapter.review(artifact, ir, context)
            except VigorError as exc:
                return [
                    _reviewer_error_report(
                        ir.candidate_id,
                        artifact.artifact_id,
                        reviewer_id="adapter",
                        reviewer_type="objective_metric",
                        exc=exc,
                    )
                ]
            except Exception as exc:
                return [
                    _reviewer_error_report(
                        ir.candidate_id,
                        artifact.artifact_id,
                        reviewer_id="adapter",
                        reviewer_type="objective_metric",
                        exc=VigorError(str(exc), kind="generic"),
                    )
                ]

        async def backend_review() -> list[ReviewReport]:
            try:
                result = await self._backend.review(
                    ReviewRequest(
                        ir=ir,
                        artifact=artifact,
                        context=context,
                        reviewer_id="backend.default",
                    )
                )
                return [result.report]
            except VigorError as exc:
                return [
                    _reviewer_error_report(
                        ir.candidate_id,
                        artifact.artifact_id,
                        reviewer_id="backend.default",
                        reviewer_type="model_critic",
                        exc=exc,
                    )
                ]
            except Exception as exc:
                return [
                    _reviewer_error_report(
                        ir.candidate_id,
                        artifact.artifact_id,
                        reviewer_id="backend.default",
                        reviewer_type="model_critic",
                        exc=VigorError(str(exc), kind="generic"),
                    )
                ]

        adapter_reviews_result, backend_reviews_result = await asyncio.gather(
            adapter_reviews(), backend_review()
        )
        _ = compile_result
        return adapter_reviews_result + backend_reviews_result

    def _coerce_outcome(
        self,
        ir: ArtifactIR,
        item: CandidateOutcome | BaseException,
        run_id: str,
    ) -> CandidateOutcome:
        """Wrap an escaped exception from gather() into a failure outcome.

        ``_evaluate_candidate`` already converts every documented per-
        candidate error into a failure-shaped ``CandidateOutcome`` (see
        ADR-0034 §Decision Outcome). ``return_exceptions=True`` is the
        defense-in-depth net for *anything* that escapes — runtime
        regressions, unexpected ``BaseException`` subclasses, etc.
        """

        if not isinstance(item, BaseException):
            return item
        message = f"_evaluate_candidate raised {type(item).__name__}: {item}"
        err = RuntimeErrorRecord(
            error_id=f"err_evaluate_{ir.candidate_id}",
            type="generic",
            severity="high",
            message=message,
            retryable=False,
        )
        self._archive.write_error(run_id, err)
        compile_result = CompileResult(
            compile_id=f"compile_evaluate_{ir.candidate_id}_error",
            candidate_id=ir.candidate_id,
            tool_id="orchestrator.evaluate",
            status="failure",
            errors=[err],
        )
        self._archive.write_compile_result(run_id, compile_result)
        adj = self._failure_adjudication(ir.candidate_id, message)
        self._archive.write_adjudication(run_id, adj)
        return CandidateOutcome(ir, compile_result, None, [], adj)

    def _failure_adjudication(self, candidate_id: str, reason: str) -> AdjudicationReport:
        return AdjudicationReport(
            adjudication_id=f"adj_{candidate_id}_fail",
            candidate_id=candidate_id,
            policy_id=self._policy.policy_id,
            hard_gate_passed=False,
            decision="fail",
            selection_reason=reason,
        )


_ERROR_KINDS = {
    "schema_validation",
    "compile_error",
    "render_error",
    "tool_timeout",
    "reviewer_error",
    "export_error",
    "budget_exceeded",
    "adapter_contract",
    "generic",
}


def _reviewer_error_report(
    candidate_id: str,
    artifact_id: str,
    *,
    reviewer_id: str,
    reviewer_type: str,
    exc: VigorError,
) -> ReviewReport:
    action = "patch" if exc.retryable else "fail"
    return ReviewReport.model_validate(
        {
            "review_id": f"rev_error_{candidate_id}_{reviewer_id}",
            "candidate_id": candidate_id,
            "artifact_id": artifact_id,
            "reviewer_id": f"orchestrator.reviewer_error.{reviewer_id}",
            "reviewer_type": reviewer_type,
            "summary": f"reviewer raised {exc.kind}: {exc.message}",
            "scores": {"quality": 0.0},
            "passed": False,
            "recommended_action": action,
        }
    )
