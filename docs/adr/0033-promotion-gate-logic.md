# ADR-0033: Promotion Gate Pipeline And Cost-Aware Sampling

Status: Proposed

Date: 2026-05-15

## Context

ADR-0006 declares an eight-row promotion-gate table — interface
validation, smoke test, search-split improvement, validation-split
no-regression, diff review, safety-sensitive approval, rollback
availability, release provenance — as the policy for promoting a harness
candidate to production use. The table is documentation; **none** of the
gates are enforced in code today. `HarnessCandidate.status` already
includes `"promoted"` as a literal value (`packages/vigor-harness/src/vigor_harness/models.py:25`), but
nothing in the package decides when that flip is legal.

Three gaps follow:

1. **No automated enforcement.** Any caller that can write a
   `HarnessCandidate` JSON file can set `status="promoted"` and there is
   no runtime check that the gate sequence ran. The status field is
   guidance; the code does not consult it.
2. **No `PromotionDecision` artifact.** ADR-0006's "release provenance"
   row says "Promoted harness has version, diff, benchmark report, and
   reviewer signoff". There is no schema for this, no producer, and no
   on-disk shape.
3. **No cost-aware sampling.** The strategic deep-dive
   (`docs/strategy/harness-v2.md` Q7) commits to an adaptive sampling
   mode that reads `Budgets.max_cost_usd`. ADR-0028 enforces that field
   at the orchestrator level; the harness layer's adaptive-sampling
   driver has no specification.

ADR-0031 owns the architectural components (proposer, comparator,
regression detector) and ADR-0032 owns the methodology / reproducibility
/ schema-evolution rules. This ADR owns the promotion pipeline that
composes those pieces into a single `promote_candidate` entry point and
the cost-aware sampling driver that intersects with budget enforcement.
The split is operationally motivated: promotion gates intersect with
safety-sensitive adapter classification and with cost ceilings, both of
which have their own ADR dependencies; ADR-0031 and ADR-0032 stay clean
of those dependencies by punting the integration here.

The constraints this ADR must respect:

1. **ADR-0006 gate table.** The eight rows are the spec. This ADR makes
   them executable; it does not relax any of them.
2. **ADR-0028 cost-ceiling enforcement.** Cost-aware sampling reads
   `Budgets.max_cost_usd` once that field is enforced (Seeds VIGOR-344f).
   The adaptive driver is documented but blocked-in-implementation until
   the cost-ceiling work lands.
3. **ADR-0011 schema-versioning.** New artifacts (`PromotionDecision`)
   ship as `vigor.<name>.v1`.
4. **ADR-0031 component contracts.** The pipeline composes the comparator
   and regression detector defined there; those contracts are inputs to
   this ADR.

## Decision

VIGOR will ship promotion as a single typed pipeline with one entry
point and a typed audit artifact, plus a cost-aware sampling driver that
intersects with `Budgets.max_cost_usd`.

### 1. Pipeline Entry Point

A new function in
`packages/vigor-harness/src/vigor_harness/promotion.py`:

```python
async def promote_candidate(
    candidate: HarnessCandidate,
    *,
    search_report: HarnessEvalReport,
    validation_report: HarnessEvalReport,
    candidate_archive: Path,
    parent_archive: Path | None,
    safety_signoff: SafetySignoff | None,
    diff_review: DiffReview,
    archive_root: Path,
) -> PromotionDecision:
    """Run the eight gates in order; emit a typed decision artifact."""
```

The pipeline runs the gates in order, **fail-fast**: the first gate
that returns a non-pass result determines the outcome. Each gate is a
typed function with a typed input and a typed output:

```
1. validate_interface     -> InterfaceCheck
2. run_smoke_test         -> SmokeResult
3. check_search_improve   -> SearchGate
4. check_validation       -> ValidationGate
5. check_diff_review      -> DiffReviewGate
6. check_safety_signoff   -> SafetyGate
7. check_rollback_avail   -> RollbackGate
8. record_provenance      -> PromotionDecision
```

A pass at every gate flips `candidate.status` to `"promoted"` and
writes the candidate's id into the baseline registry (per ADR-0031 §3),
atomically. Any failure flips `candidate.status` to `"rejected"` with
the failing-gate name and reason recorded in the `PromotionDecision`.

### 2. Gate Specifications

**Gate 1 — Interface validation.** Re-runs `_load_factory` on the
candidate's `adapter_factory` and `backend_factory` against the
candidate's `allowed_factory_prefixes` (the same check as
`evaluator.py:21-32`). Confirms each factory returns the expected ABC
instance. No I/O beyond the import.

**Gate 2 — Smoke test.** Runs the candidate over a tiny fixed split
(`packages/vigor-harness/benchmarks/_smoke/<adapter>/v1/`) of 1-2 trivial
tasks. The smoke split is hand-curated, never auto-updated, intended
purely as "does this candidate run end-to-end without crashing".

**Gate 3 — Search-split improvement.** Reads the search-split
`HarnessEvalReport` and runs `compare_candidates` (ADR-0031 §2) against
the parent's search report. Pass criterion:
`comparison.delta_composite >= delta_search` AND
`comparison.delta_composite_ci_low > 0` (i.e., the lower bound of the
paired-bootstrap 95% CI strictly exceeds zero). `delta_search` defaults
to 0.02; configurable per `policy_id` in a per-adapter promotion-policy
file. If `n_paired_tasks < 10`, the gate fails closed — the search
split is too small for a defensible significance call.

**Gate 4 — Validation no-regress.** Reads the validation-split
`HarnessEvalReport` and runs `compare_candidates` against the parent's
validation report. Pass criterion:
`comparison.delta_composite_ci_low > -delta_validation`. `delta_validation`
defaults to 0.005 (one-quarter of `delta_search`); configurable. The
asymmetry — wider improvement bar on search, narrower regression bar on
validation — is the structural guard against search-split overfitting.

**Gate 5 — Diff review.** A `DiffReview` artifact (input to the
pipeline) carries the reviewer agent name, the timestamp, the diff hash
(SHA-256 of canonical-JSON of the candidate vs. parent), and an
`approved: bool`. Phase-1 implementation accepts a human-signed
`DiffReview` written to disk. Phase-2 (per ADR-0017 plugin policy) may
admit an automated code-review agent producing the same artifact.

**Gate 6 — Safety-sensitive approval.** Runs the safety-sensitive
adapter classifier:

```python
SAFETY_SENSITIVE_ADAPTERS: frozenset[str] = frozenset({
    "vigor_adapter_cad",
    # CAD outputs encode geometry that may be load-bearing.
    # Future safety-sensitive adapters are added here as they ship.
})
```

If the candidate's `adapter_factory`'s module name resolves to a
safety-sensitive adapter, this gate requires a `SafetySignoff` artifact
(input to the pipeline) carrying a human reviewer's name, timestamp,
and `approved: bool`. If the adapter is not safety-sensitive, the gate
auto-passes. Future adapters that need safety classification should be
added to the frozenset by an ADR (this ADR's amendment-via-supersession
shape; ADR-0014 / ADR-0018 set the precedent).

**Gate 7 — Rollback availability.** Confirms the parent candidate's
archive still exists and that the parent's `status` is `"promoted"`.
The invariant is: every `"promoted"` candidate's parent (if any) is
also `"promoted"` and is rollback-available. A candidate whose parent
chain includes an archived (deleted-archive) candidate fails this gate —
rollback to a deleted parent is undefined.

**Gate 8 — Record provenance.** Writes the `PromotionDecision`
artifact (next subsection), updates the baseline registry atomically,
and flips `candidate.status` to `"promoted"`. This gate cannot fail
unless the filesystem write fails, in which case the pipeline aborts
without flipping status (no partial promotion).

### 3. `PromotionDecision` Artifact

```python
class PromotionDecision(_HarnessBase):
    schema_version: Literal["vigor.promotion_decision.v1"] = (
        "vigor.promotion_decision.v1"
    )
    decision_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    candidate_id: str
    parent_candidate_id: str | None
    outcome: Literal["promoted", "rejected"]
    failing_gate: str | None = None  # set when outcome == rejected
    failing_reason: str | None = None
    search_report_id: str | None = None
    validation_report_id: str | None = None
    diff_sha256: str | None = None
    diff_reviewer: str | None = None
    safety_reviewer: str | None = None
    delta_composite_search: float | None = None
    delta_composite_validation: float | None = None
    n_samples_search: int | None = None
    n_samples_validation: int | None = None
```

Promotion decisions are append-only: each `decision_id` is unique, and
a rejected candidate may be re-promoted (with a new `decision_id`)
after the rejecting gate's input changes (e.g., a re-run, a fresh
diff-review). The append-only ledger is the audit record for
promotion.

### 4. Cost-Aware Sampling Driver

A new function in
`packages/vigor-harness/src/vigor_harness/sampling.py`:

```python
async def evaluate_candidate_adaptive(
    candidate: HarnessCandidate,
    split: SplitManifest,
    output_dir: Path,
    *,
    sample_budget_usd: float,
    min_samples_per_task: int = 1,
    max_samples_per_task: int = 5,
) -> HarnessEvaluationResult:
    """N-runs averaging with adaptive sampling under a USD budget."""
```

The algorithm:

1. Run `min_samples_per_task` samples over every task. Record the
   running USD spend (read from the orchestrator's `RunBudgetTracker`,
   per ADR-0028). Build the per-task `composite_std` from the
   accumulated samples.
2. While running USD spend < `sample_budget_usd` and at least one task
   has `samples_taken < max_samples_per_task`:
   - Pick the task with the highest `composite_std` (ties broken by
     lowest sample count).
   - Run one more sample for that task.
   - Update `composite_std` and the running spend.
3. Stop when either the budget is exhausted or every task is at
   `max_samples_per_task`.
4. Emit `HarnessEvalReport` with `n_samples_per_task` per-task (which
   means the v2 reproducibility fields per ADR-0032 must be enriched
   to optionally accept a per-task histogram; this is a v2.1 schema
   bump named in §Consequences).

The driver is **opt-in**. The default `evaluate_candidate` (per
ADR-0031 §1) does N=3 uniform sampling with a flat cost profile.
Adaptive mode is invoked via `vigor harness eval --adaptive-sampling
--sample-budget 10.00`.

The driver is **structurally blocked on ADR-0028**: until
`Budgets.max_cost_usd` is enforced and `RunBudgetTracker` exposes the
running USD tally, the driver cannot read its inputs. ADR-0028 is
listed as a hard prerequisite in the backlog
(`docs/strategy/harness-backlog.md`).

### 5. Rollback Semantics

`status="promoted"` is **monotone** for a given `candidate_id`. A
promoted candidate is never reverted to an earlier status; rollback is
implemented by promoting a previously-promoted candidate forward in
time as the new baseline.

Concretely, rollback works via the baseline registry (ADR-0031 §3):

- The baseline registry's per-adapter file maps `split_id ->
  baseline_candidate_id`. Promotion atomically updates this mapping.
- Rollback is a `vigor harness rollback --adapter <a> --split <s>
  --to <prior_candidate_id>` command that flips the registry's mapping
  back to a prior promoted candidate. The prior candidate's `status`
  is unchanged (it was, and remains, `"promoted"`); only the registry's
  `baseline_candidate_id` changes.
- The rollback writes a `PromotionDecision` with `outcome="promoted"`
  and `notes="rollback to prior baseline"`. The append-only ledger
  preserves the rollback as a first-class event.

This shape avoids the "what does it mean to demote a promoted
candidate" question by never asking it. A candidate that was once
promoted stays promoted; the registry decides what runs in production.

## Alternatives Considered

### Alt-A: Pipeline shape — single entry point vs. composable subcommands vs. event bus

| Alternative | Reason Rejected |
| --- | --- |
| Composable subcommands: each gate is its own CLI invocation, the operator chains them | Plausible aesthetically but loses the **fail-fast** discipline. An operator who runs gate 4 without gate 3 silently bypasses the search-improve check. The single-entry-point shape enforces ordering. |
| Event bus: each gate emits an event, a coordinator subscribes | Over-engineered for a sequential pipeline. The fan-out structure isn't needed; the gates are inherently serial. |
| (Chosen) Single typed entry point `promote_candidate(...)` with one typed `PromotionDecision` artifact | Composable inside Python (the function is callable from any code path), composable on the CLI (one subcommand wraps it), and enforces ordering by construction. |

### Alt-B: Significance criterion — paired-bootstrap CI vs. paired t-test vs. raw threshold

| Alternative | Reason Rejected |
| --- | --- |
| Paired t-test on the per-task delta | Assumes the per-task delta is approximately normal. Per the strategy doc Q6 discussion, the per-task `mean_composite` distribution is often skewed or zero-inflated (especially when hard gates fail); the t-test is the wrong tool. |
| Raw threshold: "delta_composite >= 0.02 wins" with no significance check | Rewards lucky runs. A run with N=1 and a delta of 0.02 driven by one outlier task is indistinguishable from a real gain. The CI lower-bound check is what makes the gate honest. |
| (Chosen) Paired-bootstrap CI lower bound > 0 (search) and lower bound > -delta_validation (validation) | Robust to skewed distributions, doesn't require parametric assumptions, scales to any sample count, and naturally handles the asymmetric search-vs-validation criteria. The asymmetry — improvement strictly required on search, no-regress on validation — is the standard ML-eval discipline. |

### Alt-C: Safety-sensitive classification — frozenset in code vs. per-adapter manifest field vs. ADR-keyed registry

| Alternative | Reason Rejected |
| --- | --- |
| Per-adapter manifest field `safety_sensitive: bool` on `AdapterManifest` | Plausible long-term but requires an ADR-0014 amendment (the AdapterManifest schema is settled) and a migration. For v2.0 a code-resident frozenset is faster and reversible — the cost is one ADR amendment when the next safety-sensitive adapter ships. |
| Untyped policy file: `safety_sensitive_adapters: ["vigor_adapter_cad"]` in YAML | Loose, easy to misspell, no type check. |
| (Chosen) Frozenset in `vigor_harness.promotion`, additions made by superseding ADRs | Type-checked, atomic, version-controlled with the code. The ADR cost per addition is the right deterrent — adding a safety-sensitive adapter is a load-bearing decision and should be ADR'd. |

### Alt-D: Rollback semantics — status reversion vs. baseline-registry redirect vs. dedicated `RollbackDecision`

| Alternative | Reason Rejected |
| --- | --- |
| Status reversion: a rollback flips `status` from `"promoted"` to `"rejected"` | Defeats the monotonicity invariant. A promoted candidate that is rolled back may need to be re-promoted later; reverting status creates ambiguity about what the field means. |
| Dedicated `RollbackDecision` artifact distinct from `PromotionDecision` | Two near-identical schemas with one bit of difference. The PromotionDecision shape already carries `outcome` and `notes`; a rollback is just a promotion of a prior candidate forward in time. |
| (Chosen) Rollback redirects the baseline registry; a rollback is a `PromotionDecision` with `notes="rollback to prior baseline"` | Single artifact, monotone status, append-only ledger. The registry decides what runs in production; the candidate's `status` is its own monotone history. |

### Alt-E: Cost-aware sampling — adaptive vs. uniform vs. operator-specified

| Alternative | Reason Rejected |
| --- | --- |
| Uniform-only with a higher default N (e.g., N=5) | Wastes budget on tasks with low variance. The strategy doc Q7 commitment is that the budget should buy more samples where the variance is highest. |
| Operator-specified per-task sample counts | Defeats automation. The whole point of cost-aware mode is that the operator declares a budget and the harness figures out the allocation. |
| (Chosen) Adaptive: `min_samples_per_task` floor + greedy variance-driven allocation up to `max_samples_per_task` and `sample_budget_usd` | Standard approach in 2026 ML-eval ("ARP-style" adaptive allocation). Bounded by per-task cap (no single task hogging the budget) and by total budget (no global overshoot). |

## Consequences

### Positive

1. **ADR-0006's gate table becomes executable.** Eight gates, eight typed
   functions, one typed audit artifact per promotion attempt.
2. **Promotion provenance is auditable.** `PromotionDecision` is
   append-only and fully typed; reconstructing why a candidate was
   promoted is a single file read.
3. **Rollback works without contradicting the monotonic-status
   invariant.** A promoted candidate stays promoted; the registry
   decides what runs.
4. **Cost-aware sampling has a specification operators can plan around.**
   The driver's blockedness on ADR-0028 is named explicitly; nothing
   "starts ticking" until the prerequisite lands.
5. **Safety-sensitive adapters require human signoff at promotion
   time.** The frozenset is small today (CAD only) and grows by ADR; the
   per-addition deliberation is the right discipline.

### Negative

1. **Adding a safety-sensitive adapter is now an ADR step.** Smaller
   adapter changes that don't touch the safety classification are
   unaffected; adding the *first* safety classification for a new
   adapter needs an ADR. The cost is ~1 person-hour of writing per
   addition, which is the right deterrent against careless
   classification.
2. **Promotion is no longer a status field set; it's a pipeline run.**
   Operators who previously hand-edited `status="promoted"` will be
   rejected by the schema's status flip path. The migration is to
   document the previous behavior as a migration tool (one-shot script)
   that constructs a `PromotionDecision` for previously-promoted
   candidates retroactively. Listed in the backlog.
3. **The cost-aware driver imposes a `HarnessEvalReport` schema bump
   eventually.** Per-task sample counts (when `n_samples_per_task`
   varies across tasks) need a new optional `samples_per_task: dict[str,
   int] | None` field. Additive per ADR-0032's rules; named in the
   backlog as a v2.1 follow-on.
4. **Diff review is human-only at v2.0.** Phase 2 admits an automated
   code-review agent, but that requires ADR-0017 plugin-policy
   integration. Operators bottlenecked on humans is a known cost; the
   plug-in admission criteria are not negotiated in this ADR.
5. **The smoke-test split is operational state that ships in the repo.**
   It's tiny (1-2 tasks per adapter) but it's still a benchmark
   directory the harness owns. Listed under §Citations of ADR-0032 and
   in the Seeds backlog.

## Citations

| Source | Anchor |
| --- | --- |
| ADR-0006 gate table (the spec this ADR makes executable) | ADR-0006 (Accepted) §"Decision" |
| `HarnessCandidate.status` literal incl. `"promoted"`, `"rejected"` | `packages/vigor-harness/src/vigor_harness/models.py:25` |
| Factory namespace allowlist (used by Gate 1) | `packages/vigor-harness/src/vigor_harness/evaluator.py:21-32` |
| Cost-ceiling enforcement (Gate 4 / cost-aware sampling prerequisite) | ADR-0028 (Proposed) |
| Schema-versioning rules | ADR-0011 (Accepted) |
| Sibling ADRs | ADR-0031 (architecture: comparator, regression detector), ADR-0032 (methodology: 3-way splits, reproducibility) |
| Strategic context | `docs/strategy/harness-v2.md` §Q3, §Q5, §Q7 |
