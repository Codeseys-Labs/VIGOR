"""VIGOR async orchestrator.

Runs the generate-compile-review-adjudicate-patch loop described in
``docs/vigor-framework.md``. The runtime supports patch refinement and
best-of-N candidate evaluation.
"""

from __future__ import annotations

import asyncio
import contextlib
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
            prior: list[ArtifactIR] = []
            current_ir: ArtifactIR | None = None

            for iteration in range(task.budgets.max_iterations):
                context.iteration = iteration
                if time.monotonic() - started > task.budgets.max_wall_clock_s:
                    stop_reason = "budget_exhausted"
                    break
                if await budget_tracker.check():
                    stop_reason = "cost_exceeded"
                    break

                candidates = await self._candidate_batch(task, plan, prior, current_ir, activities)
                current_ir = None
                outcomes: list[CandidateOutcome] = []
                for ir in candidates:
                    outcome = await self._evaluate_candidate(ir, context, activities)
                    outcomes.append(outcome)
                    adjudications.append(outcome.adjudication)
                    prior.append(ir)
                    last_candidate_id = ir.candidate_id

                accepted_outcome = self._select_accepted_outcome(outcomes)
                if accepted_outcome is not None:
                    assert accepted_outcome.artifact is not None
                    export = await self._safe_export(
                        accepted_outcome.ir, accepted_outcome.artifact, context
                    )
                    if export is None:
                        accepted = False
                        stop_reason = "failed"
                    else:
                        accepted = True
                        last_export = export
                        last_candidate_id = accepted_outcome.ir.candidate_id
                        activities.append(
                            ProvenanceActivity(activity_id=export.export_id, type="export")
                        )
                        stop_reason = "accepted"
                    break

                patch_source = self._select_patch_source(outcomes)
                if patch_source is None:
                    stop_reason = (
                        "escalated"
                        if any(out.adjudication.decision == "escalate" for out in outcomes)
                        else "failed"
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

        return RunResult(
            run_id=run_id,
            accepted=accepted,
            stop_reason=stop_reason,
            selected_candidate_id=selected_candidate_id,
            export_bundle=last_export,
            provenance=provenance,
            usage=budget_tracker.latest,
        )

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
        generated: list[ArtifactIR] = []
        for _ in range(max(1, task.budgets.max_candidates)):
            result = await self._backend.generate(
                GenerationRequest(task=task, plan=plan, prior_candidates=[*prior, *generated])
            )
            generated.append(result.ir)
            activities.append(
                ProvenanceActivity(
                    activity_id=f"generate_{result.ir.candidate_id}",
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
