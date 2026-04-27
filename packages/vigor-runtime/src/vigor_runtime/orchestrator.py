"""VIGOR async orchestrator.

Runs the eight-stage generate-compile-review-adjudicate-patch loop described
in ``docs/vigor-framework.md``:

    route -> plan -> generate -> compile -> review -> adjudicate -> patch -> finalize

Key contracts:

* Adapters raise ``VigorError`` subclasses on structured failure. The
  orchestrator catches ``VigorError`` *and* other ``Exception`` types at the
  boundary and records a ``RuntimeErrorRecord`` plus a failure
  ``AdjudicationReport`` instead of crashing.
* After a ``patch`` decision, the backend proposes a ``PatchPlan`` and the
  **adapter** applies it via ``apply_patch``. The patched IR is validated,
  archived, and fed into the next iteration (the generator is only called on
  the very first iteration unless the patched IR fails validation).
* A successful run writes a ``final/`` directory with ``export_bundle.json``
  and ``provenance.json``. A failed run writes ``errors/`` plus the partial
  frontier so the archive is still replay-able.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from dataclasses import dataclass

from vigor_core.archive import RunArchive
from vigor_core.errors import AdapterContractError, VigorError
from vigor_core.interfaces import (
    AgentBackend,
    DomainAdapter,
    GenerationRequest,
    PatchProposalRequest,
    ReviewRequest,
    RunContext,
)
from vigor_core.schemas import (
    AdjudicationReport,
    ArtifactIR,
    CompileResult,
    ExportBundle,
    ObservableArtifact,
    ProvenanceActivity,
    ProvenanceRecord,
    ReviewReport,
    RuntimeErrorRecord,
    StopReason,
    TaskSpec,
)
from vigor_core.scoring import (
    AdjudicationInputs,
    ScoringPolicy,
    adjudicate,
    build_frontier,
    select_best,
)
from vigor_core.util import utcnow_iso


@dataclass(slots=True)
class RunResult:
    run_id: str
    accepted: bool
    stop_reason: StopReason
    selected_candidate_id: str | None
    export_bundle: ExportBundle | None
    provenance: ProvenanceRecord


class Orchestrator:
    """Async orchestrator for a single domain adapter + agent backend pairing."""

    def __init__(
        self,
        *,
        adapter: DomainAdapter,
        backend: AgentBackend,
        archive: RunArchive,
        policy: ScoringPolicy | None = None,
    ) -> None:
        self._adapter = adapter
        self._backend = backend
        self._archive = archive
        self._policy = policy or ScoringPolicy(policy_id="default.v1")

    async def run(self, task: TaskSpec) -> RunResult:
        run_id = task.task_id
        started = time.monotonic()
        self._archive.write_task(task)

        activities: list[ProvenanceActivity] = []
        adjudications: list[AdjudicationReport] = []
        last_candidate_id: str | None = None
        last_export: ExportBundle | None = None
        stop_reason: StopReason = "accepted"
        accepted = False
        fatal_error: RuntimeErrorRecord | None = None

        try:
            manifest = await self._adapter.describe_capabilities()
            self._archive.write_manifest(run_id, manifest)

            context = RunContext(
                run_id=run_id,
                run_dir=str(self._archive.run_dir(run_id)),
                task=task,
            )
            plan = await self._adapter.plan_representation(task)
            prior: list[ArtifactIR] = []
            current_ir: ArtifactIR | None = None

            for iteration in range(task.budgets.max_iterations):
                context.iteration = iteration
                if time.monotonic() - started > task.budgets.max_wall_clock_s:
                    stop_reason = "budget_exhausted"
                    break

                # Stage 1: generate (or reuse patched IR from previous iteration).
                if current_ir is None:
                    gen_result = await self._backend.generate(
                        GenerationRequest(task=task, plan=plan, prior_candidates=list(prior))
                    )
                    ir = gen_result.ir
                    activities.append(
                        ProvenanceActivity(
                            activity_id=f"generate_{ir.candidate_id}",
                            type="generation",
                            agent="backend",
                        )
                    )
                else:
                    ir = current_ir
                    current_ir = None  # consumed

                validation = await self._adapter.validate_ir(ir)
                if not validation.ok:
                    raise AdapterContractError(
                        "generated IR failed adapter validation: " + "; ".join(validation.errors)
                    )
                self._archive.write_ir(run_id, ir)
                prior.append(ir)
                last_candidate_id = ir.candidate_id

                # Stage 2: compile.
                compile_result = await self._safe_compile(ir, context)
                self._archive.write_compile_result(run_id, compile_result)
                activities.append(
                    ProvenanceActivity(
                        activity_id=compile_result.compile_id,
                        type="compile",
                        tool_id=compile_result.tool_id,
                    )
                )

                if compile_result.status != "success" or not compile_result.outputs:
                    adj = self._failure_adjudication(
                        ir.candidate_id,
                        "compile failed: " + "; ".join(e.message for e in compile_result.errors)
                        if compile_result.errors
                        else "compile failed",
                    )
                    self._archive.write_adjudication(run_id, adj)
                    adjudications.append(adj)
                    stop_reason = "failed"
                    break

                primary_artifact = compile_result.outputs[0]

                # Stage 3: review.
                reviews = await self._run_reviewers(
                    ir=ir,
                    artifact=primary_artifact,
                    context=context,
                    compile_result=compile_result,
                )
                for review in reviews:
                    self._archive.write_review(run_id, review)
                    activities.append(
                        ProvenanceActivity(
                            activity_id=review.review_id,
                            type="review",
                            reviewer_id=review.reviewer_id,
                        )
                    )

                # Stage 4: adjudicate.
                adj = adjudicate(
                    AdjudicationInputs(
                        candidate_id=ir.candidate_id,
                        reviews=reviews,
                        hard_gate_signals={
                            "compile_success": True,
                            "render_success": True,
                        },
                    ),
                    self._policy,
                    f"adj_{ir.candidate_id}",
                )
                self._archive.write_adjudication(run_id, adj)
                adjudications.append(adj)
                activities.append(
                    ProvenanceActivity(
                        activity_id=adj.adjudication_id,
                        type="adjudication",
                    )
                )

                if adj.decision == "accept":
                    accepted = True
                    last_export = await self._safe_export(ir, primary_artifact, context)
                    if last_export is not None:
                        activities.append(
                            ProvenanceActivity(
                                activity_id=last_export.export_id,
                                type="export",
                            )
                        )
                    stop_reason = "accepted"
                    break
                if adj.decision in {"fail", "escalate"}:
                    stop_reason = "failed" if adj.decision == "fail" else "escalated"
                    break

                # Stage 5: patch (only when decision is patch/branch/pivot).
                proposal = await self._backend.propose_patch(
                    PatchProposalRequest(ir=ir, reviews=reviews, context=context)
                )
                self._archive.write_patch(run_id, proposal.patch)
                activities.append(
                    ProvenanceActivity(
                        activity_id=proposal.patch.patch_id,
                        type="patch",
                    )
                )

                # Adapter deterministically applies the patch. The patched IR
                # becomes the seed for the next iteration.
                patched_ir = await self._adapter.apply_patch(ir, proposal.patch)
                patched_validation = await self._adapter.validate_ir(patched_ir)
                if not patched_validation.ok:
                    # Adapter produced an invalid patched IR. Record and stop.
                    fatal_error = RuntimeErrorRecord(
                        error_id=f"err_patch_{ir.candidate_id}",
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
                    break
                current_ir = patched_ir
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
                await self._backend.aclose()

        # Finalize: frontier + provenance.
        frontier = build_frontier(
            run_id=run_id,
            frontier_id=f"frontier_{run_id}",
            adjudications=adjudications,
            policy=self._policy,
        )
        self._archive.write_frontier(run_id, frontier)
        best = select_best(frontier)
        selected_candidate_id = best.candidate_id if best is not None else None

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

        return RunResult(
            run_id=run_id,
            accepted=accepted,
            stop_reason=stop_reason,
            selected_candidate_id=selected_candidate_id,
            export_bundle=last_export,
            provenance=provenance,
        )

    async def _safe_compile(self, ir: ArtifactIR, context: RunContext) -> CompileResult:
        """Run the adapter compile, converting raised errors to a failure result."""

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
        """Run domain reviewers and the backend reviewer in parallel.

        Any exception raised by either side is converted into a synthetic
        `reviewer_error` report so adjudication always has something to work
        with.
        """

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
        _ = compile_result  # reserved for future per-tool signals
        return adapter_reviews_result + backend_reviews_result

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
