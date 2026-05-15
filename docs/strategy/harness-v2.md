<!-- written-by: builder-harness-strategy -->
# Harness v2: From Minimal Evaluator To Real Eval Framework

Status: Draft for review
Date: 2026-05-15
Audience: VIGOR architecture lead, harness owners, ML/eval methodology reviewers, downstream operators evaluating VIGOR for adapter selection.
Parent task: VIGOR-455f (strategic deep-dive on harness v2)
Companion deliverables: ADR-0031 (harness v2 architecture), ADR-0032 (benchmark methodology and reproducibility), ADR-0033 (promotion gate logic), `docs/strategy/harness-backlog.md`.

---

## Executive Summary

VIGOR shipped a **minimal harness evaluator** in Phase 6 (`packages/vigor-harness/src/vigor_harness/evaluator.py`, ADR-0006). It runs one named `HarnessCandidate` over a `SplitManifest`, executes each task through the normal `Orchestrator`, and writes a `HarnessEvalReport` with five aggregate metrics. It does not propose harness candidates, does not compare two candidates, does not detect regressions, does not gate promotion automatically, does not control for non-determinism, does not bound eval cost, and treats its result schema as a single immutable shape. Phase 6's roadmap entry already names six of these as "future enhancement" / "documented, not automated".

Eight questions inherited from the parent seed (VIGOR-455f) decompose cleanly into three architectural concern groups:

- **System architecture** (Q1 self-proposing optimizer, Q3 promotion gates, Q4 A/B comparison, Q5 regression suite). What does the outer loop *do* and what new artifacts does it produce?
- **Evaluation methodology** (Q2 benchmark splits, Q6 reproducibility, Q7 cost-aware sampling). Where do tasks come from, how do we know the score is real, and how do we keep the bill bounded?
- **Schema and protocol evolution** (Q8 result-schema versioning). How does `vigor.harness_eval_report.vN` evolve without breaking the prior consumers that read it?

Each group becomes one ADR draft (ADR-0031, 0032, 0033). The strategy doc you're reading is the synthesis they hang off; it commits to the architectural posture and defers code shapes to the ADRs.

The recommended posture is: **(1)** treat harness v2 as four cooperating but separately-shipped capabilities — Proposer, Comparator, RegressionDetector, PromotionGate — each layering on the existing evaluator; **(2)** make non-determinism control (seed pinning, N-runs averaging, bootstrap CIs) a first-class part of every report rather than an opt-in; **(3)** keep the `HarnessEvalReport` shape additive-only and version any breaking change as `vigor.harness_eval_report.v2` per ADR-0011; **(4)** ship Phase 1 of the self-proposing optimizer (deterministic, search-split-only, human-gated) before any RL-style exploratory proposer; **(5)** treat benchmark splits as **owned, versioned artifacts** with provenance and contamination guards, not loose JSON files. The backlog (`docs/strategy/harness-backlog.md`) sequences the work so each layer can be merged independently and the optimizer is the *last* piece, not the first.

---

## Current Harness Surface

This section anchors every recommendation in the present-day code. All `path:line` citations are against the 2026-05-15 worktree cutoff.

### Evaluator

`packages/vigor-harness/src/vigor_harness/evaluator.py:42-100` is the entire evaluation runner. The shape:

- **`_load_factory`** (`evaluator.py:21`) imports `module:attr` and asserts the module name starts with one of `allowed_factory_prefixes` — a namespace allowlist with the same posture as `vigor_core.factory.load_factory` (`agent_config.py:30`). The check uses prefix-with-dot rather than `startswith` to defeat typo-squat names like `vigor_harness_evil` (covered by `tests/test_harness.py:test_evaluate_candidate_rejects_typosquat_prefix`).
- **`_load_tasks`** (`evaluator.py:39`) reads each `SplitManifest.task_uris[i]` as a JSON file and validates it as `TaskSpec`. Task URIs are file paths, not URIs in the RFC sense — there is no S3 / HTTP loader.
- **`evaluate_candidate`** (`evaluator.py:48`) instantiates `adapter_factory()` and `backend_factory()` **per task** (the comment at `evaluator.py:64` calls this out: *"Backend lifecycle is owned per Orchestrator.run(), so instantiate per task"*), runs each task through `Orchestrator.run`, reads `frontier.json` from the run archive to find the selected candidate, and tallies five metrics: `n_tasks`, `n_succeeded`, `hard_gate_pass_rate`, `accept_rate`, `mean_composite`. Aggregate JSON is written to `{output_dir}/{candidate_id}/aggregate.json`.

### Schemas

`packages/vigor-harness/src/vigor_harness/models.py` declares three IRs at the `vigor.harness_*.v1` schema-version literal pinned per ADR-0011:

- **`HarnessCandidate`** (`models.py:21`) — `candidate_id`, `parent_candidate_id`, `status: Literal["pending","validated","evaluated","promoted","rejected"]`, `hypothesis`, `adapter_factory`, `backend_factory`, `policy_id`, `config: dict[str, str]`, `allowed_factory_prefixes: list[str]` defaulting to `["vigor_"]`. The `status` literal already includes `"promoted"` and `"rejected"` — the field anticipates promotion gate logic that does not yet exist in code.
- **`SplitManifest`** (`models.py:35`) — `split_id`, `role: Literal["search","validation","heldout"]`, `task_uris: list[str]`. The three-way role split is already in the schema and matches the standard ML eval discipline (search ≠ validation ≠ test); this is the single most important existing seam for the v2 work, because every method below distinguishes its behavior by role.
- **`HarnessEvalReport`** (`models.py:43`) — `candidate_id`, `split_id`, `n_tasks`, `n_succeeded`, `hard_gate_pass_rate`, `accept_rate`, `mean_composite: float | None`, `regressions: list[str]` defaulting empty.

### Observed Gaps (Anchored)

The shape is intentionally skeletal. Six observations follow:

1. **`HarnessEvalReport.regressions: list[str]` is populated nowhere.** `evaluate_candidate` never writes to it — the field is forward-looking. Any v2 regression detector therefore has zero existing consumers to coordinate with, which makes adding the producer cheap.
2. **No proposer.** Nothing in the package mutates `HarnessCandidate` config, prompts, or factory references. `parent_candidate_id` is on the schema, never written by any code path.
3. **No comparator.** `evaluate_candidate` runs one candidate at a time; pairing two reports against the same split into a paired diff is not implemented. Operators run the evaluator twice and diff JSON manually.
4. **No reproducibility controls.** A single run is a single sample. There is no seed pinning at the orchestrator level (`Orchestrator.run` does not accept a seed parameter), no N-runs averaging in the harness, and no bootstrap variance computation. `mean_composite: float | None` has no companion `composite_std` or `n_samples_per_task`.
5. **No promotion gate enforcement.** ADR-0006 lists eight promotion gates as a table; **none** are checked in code. `HarnessCandidate.status` can be set to `"promoted"` by any caller; no gate sequence is enforced by the harness.
6. **No cost telemetry.** The harness inherits VIGOR's run-archive shape, which doesn't track tokens or USD (per the deployment scout, `Budgets.max_cost_usd` is paper). A "cost-aware" eval can't yet read its inputs.

### What Already Works

The current evaluator is not a placeholder. It is correctly:

- **Sandboxing factory imports** at the namespace boundary (`evaluator.py:23-32`).
- **Honoring per-task lifecycle** (instantiate factories per task to avoid cross-task state bleed; `evaluator.py:64`).
- **Persisting per-task run archives** under `{output_dir}/{candidate_id}/runs/` so any v2 layer can read frontier.json and re-derive metrics without re-running.
- **Producing typed Pydantic-strict aggregate output** (`models.py:43-48`, `model_config = ConfigDict(strict=True, extra="forbid")` via `_HarnessBase`).
- **Tested under three threat shapes** (untrusted factory, typo-squat prefix, happy path).

The v2 work below **layers onto** these seams rather than replacing them.

---

## 2026 External Posture: Eval Frameworks Worth Stealing From

This section synthesizes a methodology scout across the production-grade 2026 LLM eval frameworks. Citations are by framework name and known shape; exact line references and URLs are out of scope for a strategy doc and are not fabricated. ADR-0032 contains the per-citation breakdown.

### lm-evaluation-harness (EleutherAI)

The dominant 2026 reference for *single-task per-row* LLM scoring. Three patterns transfer directly:

- **Task taxonomy as YAML.** Each benchmark is one YAML file declaring `dataset_path`, `dataset_name`, `metric_list`, `output_type` (loglikelihood / multiple_choice / generate_until), and a `validation_split` / `test_split` selector. VIGOR's analog is `SplitManifest` plus a per-adapter scoring policy; the lesson is that **the manifest is the unit of versioning**, not the per-task JSON.
- **Few-shot context discipline.** lm-eval-harness pins `num_fewshot`, `fewshot_seed`, and the exact tokenization. VIGOR's reproducibility story currently has no equivalent — `task.budgets.max_iterations` is the closest thing, and it controls *budget*, not determinism.
- **Stratified results table.** The default report is `<task, metric, value, stderr, n_samples>` per row. VIGOR's `HarnessEvalReport` lacks `stderr` and `n_samples`. The fix is small (additive fields) and ADR-0032 commits to it.

### Anthropic Inspect

The 2026-emergent framework that gets agent-style eval right. The key transferable patterns:

- **Solver/Scorer/Task separation.** Inspect cleanly separates the agent (solver) from the scorer (`accuracy`, `match`, `model_graded_qa`, etc.). VIGOR has the same structural separation — `Orchestrator` is the solver, the reviewer ensemble (per ADR-0004) is the scorer — but the harness layer doesn't yet treat them as substitutable. Phase-2 work should expose `scorer_factory: FactoryRef` on `HarnessCandidate` so the same adapter can be re-scored without re-running.
- **Logs as primary artifact.** Inspect's `.eval` log file is *the* unit of comparison — A/B isn't running two configs, it's running one config and reading two logs. VIGOR's run archive is structurally similar; the missing piece is a log-anchored comparator (Q4) rather than a re-run-and-diff comparator.
- **Sandboxed tool execution as default.** Inspect runs tool calls in subprocess sandboxes. VIGOR's MCP backend (per ADR-0016) gets there for tool calls but not for the `_load_factory` path; harness v2 should preserve the namespace allowlist and add an opt-in subprocess-per-candidate mode for promoted candidates from untrusted authors.

### HELM (Stanford CRFM)

The dominant 2026 shape for **transparent multi-metric reporting**. The transferable patterns:

- **Scenario × adaptation × metric matrix.** HELM treats every cell as independently reproducible. VIGOR's analog is `(SplitManifest, HarnessCandidate, scoring_policy)`; the lesson is that the *triple* is the run identity, not just the candidate.
- **Required disclosures.** HELM mandates that every reported number include the prompt, the seed, the temperature, the date, and the model version. VIGOR's `ProvenanceRecord` already covers most of this; the harness layer needs to surface it into the report.
- **Calibration as first-class.** HELM treats LLM-judge scores as calibrated against human raters with a published agreement rate. VIGOR's `docs/scoring-adjudication.md` already names this in its "Confidence And Calibration" section but the calibration data path is unimplemented.

### BIG-Bench / BIG-Bench Hard

Two patterns worth borrowing, two to reject:

- **Borrow:** task-level metadata (`canary string`, `keywords`, `task_url`, `authors`). The `canary string` pattern (a known UUID-shaped phrase embedded in test data so that contamination by a future training corpus is trivially detectable) is high-leverage and has no VIGOR equivalent. ADR-0032 adopts it.
- **Borrow:** human-vs-model parity reporting where applicable.
- **Reject:** the open-submission task-suite shape. VIGOR's adapters are domain-internal; an open submissions process is not appropriate at v0.
- **Reject:** task aggregation by simple averaging across heterogeneous tasks. The 2026 consensus (BIG-Bench Hard explicitly) is that aggregate "BIG-Bench score" hides task-level signal and rewards eval gaming.

### openai/evals

The 2026 lessons here are more cautionary:

- **Borrow:** the `eval` registry pattern — a string id resolves to a versioned eval. VIGOR's registry shape (`vigor_core.registry.register_ir`) is structurally compatible.
- **Reject:** the runner-and-eval-class coupling. openai/evals' `Eval` base class mixes the runner (compute outputs) with the metric (score outputs). Inspect-style separation is cleaner and is what VIGOR already has.
- **Reject:** YAML-only task declarations without strict schemas. VIGOR's Pydantic-strict posture (ADR-0011) is a strict win; don't loosen it.

### Meta-Harness (already cited by ADR-0006)

The proposer architecture is the centerpiece of harness v2 Phase 1. The transferable patterns:

- **Filesystem as system of record.** Meta-Harness's proposer reads `prior_candidates/`, `traces/`, and `scores/` from a flat directory. VIGOR's `RunArchive` is already this shape; `evaluator.py:71-76` already reads frontier.json the way Meta-Harness reads scores.json.
- **Prior-candidate inspection.** The proposer is given access to prior candidate source files. VIGOR's `HarnessCandidate.parent_candidate_id` is the latch; the unwritten producer is what fills it.
- **Score-as-feedback.** Proposer prompts include `aggregate_score` per candidate. VIGOR's `mean_composite` is the analog.

### Synthesis: Where 2026 Meets VIGOR

| 2026 pattern | VIGOR seam | v2 commitment |
| --- | --- | --- |
| Task-as-versioned-YAML (lm-eval-harness) | `SplitManifest` is JSON-backed today | Keep JSON but add `manifest_sha256` + `dataset_provenance` per ADR-0032 |
| stderr / n_samples in every row (lm-eval-harness) | `HarnessEvalReport` v1 has neither | Add `composite_std`, `composite_ci_low`, `composite_ci_high`, `n_samples_per_task` in v2 (ADR-0032 §Reproducibility) |
| Solver / scorer separation (Inspect) | `Orchestrator` is solver; reviewer ensemble is scorer; harness conflates them | Add `scorer_factory: FactoryRef` to `HarnessCandidate` v2 (ADR-0031 §Comparator) |
| Log-anchored A/B (Inspect) | RunArchive per candidate already exists | Comparator reads two archives + emits paired diff (ADR-0031 §Comparator) |
| Calibration as first-class (HELM) | `scoring-adjudication.md` names it; unimplemented | Defer to harness v2.1; out of v2.0 scope |
| Canary strings for contamination (BIG-Bench) | No equivalent | Add `canary_string` to `SplitManifest` v2 (ADR-0032 §Contamination) |
| Filesystem proposer (Meta-Harness) | `RunArchive` is the right shape | Phase 1 deterministic proposer (ADR-0031 §Proposer) |

---

## Strategic Recommendations: The Eight Questions Answered

Each subsection answers one question from VIGOR-455f, names the architectural commitment, and points at the ADR / Seeds task that owns it.

### Q1: Self-Proposing Optimizer Architecture

**Commitment:** Phase 1 of the self-proposing optimizer is **deterministic, search-split-only, human-gated, prompt-and-policy-only**. No code mutation, no factory swapping, no RL-style exploration. The proposer is a `HarnessProposer` ABC with one method, `propose(history: list[HarnessCandidate], reports: list[HarnessEvalReport]) -> HarnessCandidate`. The reference implementation is a `LLMHarnessProposer` that reads prior candidate hypotheses + their `mean_composite` from disk and asks an `AgentBackend` for a new `HarnessCandidate` that varies one of `policy_id` / `config["prompt_template_id"]` / `config["reviewer_weights"]` (and *only* these). All other fields (`adapter_factory`, `backend_factory`, `allowed_factory_prefixes`) are inherited from the parent unchanged.

The Phase 1 scope is narrow on purpose. Three reasons:

1. **Code-mutation proposers are a different threat surface.** Letting a backend write to `adapter_factory: str` reintroduces the `_load_factory` allowlist as the only barrier to arbitrary code execution. Phase 2 may permit this with an additional sandbox boundary; Phase 1 does not.
2. **Prompt and policy variation already covers the highest-leverage axes.** ADR-0006 lists eight things outer-loop candidates may change; six of them are addressable through `policy_id` + `config` (prompts, reviewer weights, memory policy, stop conditions, escalation policy, compiler preprocessing). The remaining two (adapter code, IR mappings) are exactly the dangerous ones.
3. **A search-split-only proposer cannot overfit the validation/test sets.** The proposer never sees validation scores; promotion gates do, and they are run separately (Q3). This preserves the two-split discipline that ADR-0006 already commits to.

The Phase 1 deliverable is `HarnessProposer` + `LLMHarnessProposer` + a runnable `vigor harness propose` CLI that:
1. Reads a history dir of prior candidates + reports.
2. Calls `propose()` with the parent's allowed_factory_prefixes preserved.
3. Writes the new candidate JSON to disk.
4. **Does not run it.** The operator runs `vigor harness eval` separately. This composability is non-negotiable for Phase 1.

ADR-0031 §Proposer specifies the interface and the Phase 1 / Phase 2 boundary.

### Q2: Real Benchmark Splits — Where They Come From

**Commitment:** Benchmark splits are **owned, versioned, hand-curated artifacts**, stored under `packages/vigor-harness/benchmarks/<adapter>/<split-name>/v<N>/`, with `manifest.json` (a `SplitManifest`), `tasks/*.json` (per-task `TaskSpec` files), `dataset_provenance.json` (sources, license, redaction policy), and a top-level `canary.txt`.

The framework supports two source shapes:

- **Hand-curated** (the v2 default). Tasks are written by humans, reviewed, and merged via PR. Each adapter ships a search split (≥20 tasks) and a validation split (≥10 tasks); test splits are optional and start empty. This is the only source shape blessed for **promotion** (Q3).
- **Synthetic-from-template** (v2.1 follow-on). A generator produces tasks from templated parameters; provenance records the template id and seed. Synthetic tasks may **only** appear in search splits, never in validation or test, to avoid the "model trained on output of model that generated tasks" loop.

Public datasets (HumanEval, GSM8K, MMLU, etc.) are **explicitly out of scope** for the v2 commitment. Reasons:

- VIGOR's adapters are modality-specific (photo, video, CAD); no public benchmark exactly matches.
- Public-dataset contamination is a known 2026 problem (training corpora include them by default). The canary-string discipline (Q-adjacent) cannot retro-fit a contaminated source.
- License posture is bespoke per dataset; the strategic deep-dive does not commit VIGOR maintainers to per-dataset license diligence.

If a future ADR supersedes this commitment to admit a specific public dataset, that ADR records the license, the canary, and the split mapping. ADR-0032 §Datasets and §Contamination specify the rules.

### Q3: Promotion Gate Logic

**Commitment:** Promotion gates are an **explicit ordered pipeline**: `validate → smoke → search-improve → validation-no-regress → diff-review → safety-approve → record-provenance → flip-status`. Each step is a typed function with a typed input and a typed output; the pipeline composes them. The pipeline runs in a single `promote_candidate(candidate, evidence)` entry point in `vigor-harness`. Each step that fails sets `HarnessCandidate.status = "rejected"` and records the failing step + reason in a new `vigor.promotion_decision.v1` artifact.

ADR-0006's eight-row table is the *spec*; this ADR makes it executable.

Concrete commitments:

- **Score thresholds vs. statistical significance.** The default promotion criterion on the search split is *mean_composite improves by ≥ Δ AND the improvement is significant at α=0.05 by paired-bootstrap*. Δ defaults to 0.02 normalized score (configurable per `policy_id`). Statistical significance requires ≥10 paired observations. If `n_tasks < 10`, the gate fails closed — the caller must either grow the search split or promote with explicit `--manual-override`.
- **Validation no-regress.** On the validation split, the criterion is *mean_composite does not regress beyond Δ_validation by paired-bootstrap*. Δ_validation defaults to 0.005 (one-quarter of the search-split improvement gate). This is the asymmetric guard against search-split overfitting.
- **Manual review.** Diff review is a hash check + human gate by default — the candidate's `parent_candidate_id` chain must yield a clean diff against an `Accepted` parent. Phase 2 introduces an optional independent code-review agent, gated by ADR-0017 plugin policy.
- **Safety approval.** The gate is **adapter-keyed**: any adapter declaring `safety_sensitive: true` in its manifest (a new field; ADR-0014 amendment-via-supersession territory) requires a human signoff event before status flips to `"promoted"`. Until that field exists, the gate fails closed for any candidate whose adapter is in the safety-sensitive set hard-coded in ADR-0033.
- **Rollback.** Every promotion is a one-way commit at the schema level (`status` flips `evaluated → promoted`); rollback is a *new candidate* whose `parent_candidate_id` points at the previous-good version, not a status reversion. The invariant is that `status="promoted"` is monotone for a given `candidate_id`.
- **Release provenance.** Promotion writes a `PromotionDecision` artifact with the candidate id, the parent id, the search/validation report ids, the gate sequence trace, the reviewer signoff event id, and the timestamp. This artifact is the audit log for promotion; ADR-0033 specifies the schema.

ADR-0033 §Gate Specification, §Rollback Semantics, §Provenance specify the implementation.

### Q4: A/B Comparison

**Commitment:** A `HarnessComparator` reads two `HarnessEvalReport` files + their per-task underlying frontiers and emits a `vigor.harness_comparison.v1` artifact with: per-task win/loss/tie classification, paired-bootstrap CI on Δ mean_composite, McNemar test on accept_rate, the per-metric breakdown, and a "regressions" list naming task ids where B regresses against A by more than the per-policy threshold. The comparator is **archive-anchored** (Inspect pattern) — it reads two existing run archives rather than re-running.

Concrete commitments:

- **Pairing discipline.** A and B must have run the same `split_id` *and* the same `manifest_sha256` (per Q2). Comparing across split versions is rejected at the type level.
- **Paired statistic.** Default is the paired-bootstrap CI on Δ mean_composite over the per-task selected-candidate scores. The bootstrap default is 1000 resamples; configurable per call.
- **Reporter shape.** The output is a Pydantic-strict artifact, not a freeform markdown report. A separate `vigor harness compare --to-markdown` renderer produces the human-readable view.
- **No re-running.** A v2 design that re-runs both candidates inside the comparator hides the cost in the comparator surface and double-bills the operator. The archive-anchored discipline keeps the cost where the operator can see it (in the upstream `vigor harness eval` invocations).

ADR-0031 §Comparator specifies the artifact and the algorithm.

### Q5: Regression Suite

**Commitment:** A regression suite is a **named set of `(SplitManifest, BaselineHarnessCandidate)` pairs** that any candidate must beat (or at minimum not regress against) before promotion to validation. The mechanism is the `HarnessComparator` (Q4) running over each pair; the regression-suite runner aggregates the results and populates `HarnessEvalReport.regressions` (the v1 field that's currently always empty) with the task ids that fail the no-regress criterion.

This intentionally re-uses the `regressions: list[str]` field that already exists on `HarnessEvalReport.v1` rather than introducing a new schema. The producer changes; the consumer surface does not.

Concrete commitments:

- **Baseline registry.** Each adapter declares its baselines in `packages/vigor-harness/baselines/<adapter>.json`: `[{"split_id": "...", "baseline_candidate_id": "...", "delta_threshold": 0.005}, ...]`. Baselines are the most recently `"promoted"` candidate per split.
- **Auto-update.** When a new candidate is promoted, the baseline registry updates atomically as part of the promotion pipeline (Q3). This is the only writer of the baseline registry; manual edits are a smell.
- **Fail-closed default.** A regression suite that cannot find its baseline (e.g., the candidate id was archived) fails closed, blocking promotion. The operator can `--accept-missing-baseline` only with explicit cause.

ADR-0031 §RegressionDetector specifies the runner.

### Q6: Score Reproducibility

**Commitment:** Every report in v2 carries `n_samples_per_task` (default 3 for new evals; 1 is permitted for cost-bound exploration but flagged), `composite_std`, and a paired-bootstrap CI (`composite_ci_low` / `composite_ci_high`). The harness pins a `seed` field on `TaskSpec` (additive — `task.seed: int | None = None`) and threads it through the orchestrator's nondeterministic seams (best-of-N candidate index, reviewer sampling temperature). The default is to **average across N runs** rather than rely on a single sample, with `n_samples` configurable per `policy_id`.

The non-trivial bits:

- **LLM-judge non-determinism is dominant.** Per ADR-0004, the reviewer ensemble may include LLM/VLM critics with `temperature > 0`. Seeding doesn't fully control these; only repeat-and-average does. The N=3 default is a pragmatic compromise (not 5 = expensive, not 1 = brittle).
- **Bootstrap variance, not classical t-stats.** Paired-bootstrap is robust to the score distribution being skewed or zero-inflated (which the per-task `mean_composite` distribution often is, especially when hard gates fail). t-tests are not the right tool here.
- **Seed propagation is partial.** A `task.seed` does not control the LLM provider's sampling unless the backend exposes a seed; some 2026 backends do (OpenAI), some do not (Anthropic). The harness accepts this partial determinism and reports it in `HarnessEvalReport.v2` as `seed_honored: bool`.

ADR-0032 §Reproducibility specifies the seed-threading rules and the bootstrap algorithm.

### Q7: Cost-Aware Eval — Budget vs. Thoroughness Trade-Off

**Commitment:** The harness layer reads `Budgets.max_cost_usd` (per ADR-0028, once enforced) and supports an **adaptive sampling** mode: `sample_budget_usd` per split, `min_samples_per_task` (default 1), `max_samples_per_task` (default 5). The harness runs `min_samples_per_task` over every task first, then spends the remainder of `sample_budget_usd` on tasks where the per-task `composite_std` is widest (i.e., the highest-uncertainty tasks get the additional samples).

Three guardrails:

- **Cost-aware mode is opt-in.** The default report shape is N samples per task uniformly; adaptive sampling is `--adaptive-sampling --sample-budget 10.00`.
- **Budget under-spend is reported.** If the budget is not exhausted (rare), the report's `n_samples_per_task` is per-task and the policy applied is recorded in `report.metadata`.
- **Budget over-spend is hard-bounded.** Per-iteration cost-ceiling enforcement (ADR-0028) bounds individual run cost; the harness layer simply stops scheduling new samples when its own running tally crosses `sample_budget_usd`. Budget overshoot of one in-flight task is acceptable, matching ADR-0028's per-iteration overshoot semantics.

This commitment is **structurally blocked on ADR-0028 landing** (cost telemetry exists for `Budgets.max_cost_usd` to be readable). Until then, the harness's cost-aware mode is documented but not implementable.

ADR-0033 §Cost-Aware Sampling specifies the algorithm and the budget interaction.

### Q8: Result Schema Versioning

**Commitment:** `HarnessEvalReport` evolves additively as long as the additive shape works, and bumps to `vigor.harness_eval_report.v2` when a non-additive change is unavoidable. Per ADR-0011's rules:

- v1 → v1 (additive): new optional fields (`composite_std`, `composite_ci_low`, `composite_ci_high`, `n_samples_per_task`, `seed_honored`, `manifest_sha256`) are added with defaults that preserve the v1 read shape. The schema_version literal stays `vigor.harness_eval_report.v1`.
- v1 → v2 (breaking): if a v2-required field is added without a default, OR a field's type changes, OR a field is removed, OR the metric semantics of an existing field change. The literal becomes `vigor.harness_eval_report.v2` and a `migrate_v1_to_v2` function ships in `vigor_harness.migrations`.
- A v2 reader must accept v1 inputs through the migration function until v1 is deprecated.

`HarnessCandidate.status` widens additively for new gate states (e.g., `"safety_review_pending"`); `Literal` widening is a breaking schema bump per ADR-0011 strict-mode rules, so any new state forces a v2 — the schema bump cost is the right deterrent against state-space sprawl.

The reproducibility additions (Q6) are **all additive**; no v2 bump is required for v2.0. A v2 bump is named in the backlog as a **deferred** item, scheduled only when the additive headroom runs out.

ADR-0032 §Schema Evolution specifies the additive vs. breaking taxonomy.

---

## Synthesis: What Harness v2 Looks Like

The v2 harness is **four cooperating capabilities** layered on the v1 evaluator:

```
+-------------------+       +-------------------+       +-------------------+
|  HarnessProposer  | ----> | evaluate_candidate| ----> | HarnessComparator |
| (Phase 1: LLM)    |       | (existing v1)     |       | (new in v2)       |
+-------------------+       +-------------------+       +-------------------+
                                     |                            |
                                     v                            v
                            +-------------------+       +-------------------+
                            | RegressionDetector| <---- | PromotionGate     |
                            | (new in v2)       |       | (new in v2)       |
                            +-------------------+       +-------------------+
```

The dataflow:

1. **Proposer** generates a `HarnessCandidate` (Phase 1: prompt/policy variation only).
2. **Evaluator** (existing v1) runs it over the search split, producing a `HarnessEvalReport` and a per-task RunArchive.
3. **Comparator** pairs the new candidate's report with its parent's report on the same split; emits a `HarnessComparison`.
4. **RegressionDetector** runs the comparator over the baseline registry; populates `HarnessEvalReport.regressions`.
5. **PromotionGate** ingests the search report, validation report, regression list, and diff review; emits a `PromotionDecision` and (if accepted) flips `status` to `"promoted"`.

The minimum-viable v2.0 ships steps 2-5 (everything but the proposer). v2.0 is operator-driven: a human writes the candidate JSON, runs evaluator + comparator + regression, and triggers promotion. The proposer is v2.1 because:

- **The other four pieces are independently useful without it.** A human writing candidates by hand still benefits from automated comparison, regression detection, and promotion gates.
- **The proposer is the highest-novelty piece.** Shipping it last lets the lower-novelty pieces stabilize and serve as the proposer's substrate.
- **Proposer evaluation requires the other four.** A meta-question of "is this proposer producing better candidates than humans?" can only be answered once the comparison + promotion machinery exists.

The backlog sequences this explicitly.

---

## Backlog Summary

The full backlog is `docs/strategy/harness-backlog.md`. The summary table:

| Priority | Title | ADR |
| :---: | --- | --- |
| **P0** | Add reproducibility fields to `HarnessEvalReport.v1` (additive) + N-runs averaging | ADR-0032 |
| **P0** | Implement `HarnessComparator` + `vigor.harness_comparison.v1` schema | ADR-0031 |
| **P0** | Implement `PromotionGate` pipeline + `vigor.promotion_decision.v1` schema | ADR-0033 |
| **P1** | Implement `RegressionDetector` + baseline registry; populate `HarnessEvalReport.regressions` | ADR-0031 |
| **P1** | Add `manifest_sha256` + `dataset_provenance.json` + `canary.txt` to split layout | ADR-0032 |
| **P1** | Implement Phase 1 `LLMHarnessProposer` (prompt/policy variation, search-split-only) | ADR-0031 |
| **P2** | Wire cost-aware adaptive sampling (depends on ADR-0028 landing) | ADR-0033 |
| **P2** | Migration function + tests for `harness_eval_report.v1 → v2` (placeholder, scheduled when needed) | ADR-0032 |
| **P3** | Deferred: Phase 2 proposer (factory mutation under sandbox) | ADR-0031 (named, not specified) |

P0 work is unblocked today. P1 work depends on P0 reaching merge or specifically on its schemas being merged. P2 work has explicit external dependencies (ADR-0028 for cost; v2 schema bump triggered by future need).

---

## What Is Intentionally NOT In Scope

The v2 deep-dive intentionally defers:

- **Public-dataset benchmark splits.** No HumanEval, GSM8K, etc. License diligence + contamination guards exceed v2 scope. A future ADR may admit a specific dataset.
- **Code-mutating proposers.** Phase 2 of the proposer (factory swapping, prompt-arbitrary code) is named but not specified; the threat surface justifies a separate ADR.
- **Calibration data path.** HELM-style human-vs-LLM-judge calibration is named in `docs/scoring-adjudication.md` and not implemented; v2 does not change this.
- **Hosted eval service.** No `vigor harness eval` HTTP endpoint, no eval result database. ADR-0030's library-first posture applies.
- **Cross-tenant eval isolation.** ADR-0029 covers tenant scoping at the run-archive level; harness layering on top is identical.
- **Real-time leaderboard.** A v0 commitment to leaderboards forces a hosted-service surface that ADR-0030 forbids.
- **Eval-as-RL-environment.** Some 2026 frameworks (Anthropic's RLAIF tooling) treat the eval harness as an environment for fine-tuning the agent. This is out of v0/v1 scope; VIGOR's outer loop is a *search* loop, not a *training* loop.

Each line above corresponds to a concrete decision in the ADRs or an explicit deferral in the backlog.

---

## Citations

External patterns referenced in §"2026 External Posture":

| Source | Notes |
| --- | --- |
| lm-evaluation-harness (EleutherAI) | YAML task taxonomy, fewshot discipline, stratified results |
| Inspect (Anthropic) | Solver/scorer separation, log-anchored A/B, sandboxed tools |
| HELM (Stanford CRFM) | Scenario × adaptation × metric matrix, required disclosures, calibration |
| BIG-Bench / BIG-Bench Hard | Canary strings, task-level metadata, anti-aggregation |
| openai/evals | Eval registry pattern (borrow); runner-eval coupling (reject) |
| Meta-Harness (per ADR-0006) | Filesystem proposer, prior-candidate inspection, score-as-feedback |

Internal anchors:

| Anchor | Location |
| --- | --- |
| Minimal evaluator | `packages/vigor-harness/src/vigor_harness/evaluator.py:42-100` |
| `HarnessCandidate` / `SplitManifest` / `HarnessEvalReport` | `packages/vigor-harness/src/vigor_harness/models.py:21-48` |
| Factory namespace allowlist | `packages/vigor-harness/src/vigor_harness/evaluator.py:21-32` |
| Cost-ceiling status | ADR-0028 (Proposed) |
| Outer-loop policy | ADR-0006 (Accepted, sets the gate table) |
| Schema versioning rules | ADR-0011 (Accepted) |
| Library-first posture | ADR-0030 (Proposed) |
