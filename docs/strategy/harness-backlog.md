<!-- written-by: builder-harness-strategy -->
# Harness v2 Backlog

**Source:** VIGOR-455f (strategic deep-dive on harness v2)
**Authored:** 2026-05-15
**Status:** Initial backlog created. Items below are open Seeds issues; `sd ready` will surface unblocked work.

This is the single point of reference for the follow-on implementation
work falling out of the harness-v2 strategic deep-dive
(`docs/strategy/harness-v2.md`). The seeds below are the prioritized
backlog; the ADRs they reference are draft proposals (Status: Proposed)
pending coordinator review on the same merge cycle as this file.

## Summary table

| Seed ID | Priority | Title | ADR / strategy reference |
| --- | :---: | --- | --- |
| [VIGOR-e45f](#vigor-e45f) | P0 | Add reproducibility fields to `HarnessEvalReport.v1` (additive) + N-runs averaging | ADR-0032 §3; strategy Q6 |
| [VIGOR-4e5a](#vigor-4e5a) | P0 | Implement `HarnessComparator` + `vigor.harness_comparison.v1` schema | ADR-0031 §2; strategy Q4 |
| [VIGOR-5504](#vigor-5504) | P0 | Implement `PromotionGate` pipeline + `vigor.promotion_decision.v1` schema | ADR-0033 §1-§3; strategy Q3 |
| [VIGOR-fb88](#vigor-fb88) | P1 | Implement `RegressionDetector` + per-adapter baseline registry | ADR-0031 §3; strategy Q5 |
| [VIGOR-81d5](#vigor-81d5) | P1 | Add benchmark layout + 3-way split governance enforcement | ADR-0032 §1-§2; strategy Q2 |
| [VIGOR-5b3b](#vigor-5b3b) | P1 | Implement Phase 1 `LLMHarnessProposer` (prompt/policy variation, search-split-only) | ADR-0031 §1; strategy Q1 |
| [VIGOR-7842](#vigor-7842) | P1 | Add per-adapter smoke splits at `benchmarks/_smoke/<adapter>/v1/` | ADR-0033 §2 Gate 2 |
| [VIGOR-e7ac](#vigor-e7ac) | P2 | Wire cost-aware adaptive sampling driver (depends on ADR-0028 / VIGOR-344f) | ADR-0033 §4; strategy Q7 |
| [VIGOR-4827](#vigor-4827) | P2 | Add migration scaffold + tests for `harness_eval_report.v1 → v2` (placeholder) | ADR-0032 §4; strategy Q8 |
| [VIGOR-a384](#vigor-a384) | P3 | [DEFERRED] Phase 2 proposer — factory mutation under sandbox | ADR-0031 §1, §Alt-A; strategy Q1 |

**Priority breakdown:** 3× P0, 4× P1, 2× P2, 1× P3 (10 total).

## Why P0 vs P1 vs P2 vs P3

- **P0 — the v2.0 core trio.** Reproducibility fields, comparator, and
  promotion gate are the smallest set of changes that materially closes
  ADR-0006's "documented, not automated" gap. Each is independently
  shippable: reproducibility is purely additive (no upstream
  dependency); the comparator unblocks the regression detector and the
  promotion gate; the promotion gate composes them. With these three
  merged, an operator can hand-author a `HarnessCandidate`, run it with
  reproducibility, compare it to a parent, and promote it via a typed
  pipeline — every part of strategy doc Q3-Q6 is exercisable.
- **P1 — completes the v2.0 architectural picture.** Regression
  detector + baseline registry, 3-way split governance, Phase 1
  proposer, smoke splits. Each depends on something at P0 to be useful
  (comparator, schema, pipeline). The Phase 1 proposer is in P1 not
  because it's secondary but because the strategy doc explicitly orders
  it after the comparison/promotion infrastructure (the proposer's
  output is only as valuable as the promotion gate that filters it).
- **P2 — externally-blocked or schedule-dependent.** Cost-aware
  sampling is hard-blocked on ADR-0028 / VIGOR-344f (cost-ceiling
  enforcement); the migration scaffold is scheduled to ship when the
  additive-only headroom of `harness_eval_report.v1` runs out, which
  is a future event, not a current one.
- **P3 — explicitly deferred.** Phase 2 proposer (factory mutation,
  code-gen) is named in the backlog so the deferral is discoverable;
  it is explicitly out of v2.0 scope per ADR-0031 §Alt-A. A future ADR
  must specify the sandbox boundary before this work starts.

## What is intentionally NOT in the backlog

- **Public-dataset benchmark splits.** Per ADR-0032 §5, public
  datasets are disallowed in v2.0. A future ADR may admit a specific
  dataset; that ADR opens the corresponding Seeds work.
- **HELM-style human-vs-LLM-judge calibration data path.** Named in
  `docs/scoring-adjudication.md` "Confidence And Calibration"; not
  implemented today; explicitly deferred to harness v2.1+.
- **Hosted eval service / `vigor harness eval` HTTP endpoint.** Per
  ADR-0030's library-first posture. Not in v2.0.
- **Real-time leaderboard.** Forces a hosted-service surface. Not in
  v2.0 (ADR-0030).
- **Phase 2 proposer implementation.** Listed as a deferral
  ([VIGOR-a384](#vigor-a384)); not opened as an active seed.
- **Eval-as-RL-environment.** Some 2026 frameworks treat the harness
  as an RL environment for fine-tuning; out of v0/v1 scope per the
  strategy doc.

## Dependency Graph

```text
                                                          [VIGOR-2585]
                                                     ADR-0028 cost-ceiling
                                                              ^
                                                              |
[VIGOR-81d5]   ←--depended-on-by--   [VIGOR-e45f]       [VIGOR-e7ac]
split governance                     reproducibility    cost-aware sampling
       ^                                    ^
       |                                    |
[VIGOR-7842]                          [VIGOR-4e5a]
smoke splits                          comparator
                                            ^
                              +-------------+-------------+
                              |                           |
                       [VIGOR-fb88]                [VIGOR-5504]
                       regression                  promotion gate
                       detector                    (also depends on
                                                    [VIGOR-81d5])
                              ^
                              |
                       [VIGOR-5b3b]
                       Phase 1 proposer
                       (depends on comparator)

[VIGOR-4827] (no deps)            [VIGOR-a384] (deferred — no deps)
migration scaffold                Phase 2 proposer
```

External dependencies:

- [VIGOR-e7ac] (cost-aware sampling) is **hard-blocked** on
  [VIGOR-344f] (ADR-0028 cost-ceiling enforcement) landing.
- [VIGOR-5504] (promotion gate) takes [VIGOR-2585]'s retry-loop work
  as a soft dependency for Gate 1 reliability under transient errors.

## Seed details

### VIGOR-e45f

**P0 — Reproducibility fields + N-runs averaging.** Per ADR-0032 §3.
Additive evolution of `HarnessEvalReport.v1`: add
`n_samples_per_task`, `composite_std`, `composite_ci_low`,
`composite_ci_high`, `seed_honored`, `manifest_sha256` — all
`Optional` with defaults that preserve v1 read shape. Default N=3
sampling in `evaluate_candidate`; `--n-samples` CLI override. Bootstrap
CI with 1000 default resamples. Adds `TaskSpec.seed: int | None = None`
to `vigor-core` (additive). Anchors:
`packages/vigor-harness/src/vigor_harness/models.py:43-48`,
`evaluator.py:48-100`. Depends on [VIGOR-81d5] (manifest_sha256
populated from the SplitManifest defined there).

### VIGOR-4e5a

**P0 — `HarnessComparator` + `vigor.harness_comparison.v1`.** Per
ADR-0031 §2. New module
`packages/vigor-harness/src/vigor_harness/comparator.py` exposing
`compare_candidates(a, b, a_archive, b_archive, *, bootstrap_resamples=1000) -> HarnessComparison`.
New schema `vigor.harness_comparison.v1` in `models.py`. Reads two
existing run archives — does **not** re-run candidates (Inspect
2026 pattern). Paired-bootstrap CI on Δ mean_composite, McNemar test
on accept_rate, per-task win/loss/tie classification. Asserts
`split_id` and `manifest_sha256` match; fail-closed on missing
archive or split mismatch. Tests: bootstrap correctness on toy data,
McNemar on toy data, fail-closed paths.

### VIGOR-5504

**P0 — `PromotionGate` pipeline + `vigor.promotion_decision.v1`.**
Per ADR-0033 §1-§3. New module
`packages/vigor-harness/src/vigor_harness/promotion.py` exposing
`promote_candidate(...)`. Eight gates in order, fail-fast:
`validate_interface`, `run_smoke_test`, `check_search_improve`,
`check_validation`, `check_diff_review`, `check_safety_signoff`,
`check_rollback_avail`, `record_provenance`. `SAFETY_SENSITIVE_ADAPTERS`
frozenset starts with `vigor_adapter_cad`. Append-only
`PromotionDecision` ledger. Depends on [VIGOR-4e5a] (gates 3-4 use
the comparator) and [VIGOR-81d5] (smoke + benchmark layout). Soft
dependency on [VIGOR-2585] (retry-loop work for Gate 1 reliability).

### VIGOR-fb88

**P1 — `RegressionDetector` + baseline registry.** Per ADR-0031 §3.
New module `packages/vigor-harness/src/vigor_harness/regression.py`
exposing `detect_regressions(...)`. New `BaselineEntry` schema
(`vigor.baseline_entry.v1`). Per-adapter registry at
`packages/vigor-harness/baselines/<adapter>.json`. Detector runs
[VIGOR-4e5a]'s comparator for each baseline. Caller writes returned
list into `HarnessEvalReport.regressions` — repurposing the existing
v1 field that is currently always empty
(`packages/vigor-harness/src/vigor_harness/models.py:48`). Atomic
registry updates owned by [VIGOR-5504]'s promotion gate.

### VIGOR-81d5

**P1 — Benchmark layout + 3-way split governance.** Per ADR-0032 §1,
§2. New directory tree
`packages/vigor-harness/benchmarks/<adapter>/<split-name>/v<N>/` with
`manifest.json` + `canary.txt` + `dataset_provenance.json` +
`tasks/*.json`. Add `manifest_sha256` and `canary_string` to
`SplitManifest` (additive). New `DatasetProvenance` schema
(`vigor.dataset_provenance.v1`). Public-dataset admission fail-closed
at validator. Heldout "at most once" ledger at
`packages/vigor-harness/.heldout_ledger/<candidate_id>.json`.
Proposer enforces `role="search"` input.

### VIGOR-5b3b

**P1 — Phase 1 `LLMHarnessProposer`.** Per ADR-0031 §1. New module
`packages/vigor-harness/src/vigor_harness/proposer.py` with
`HarnessProposer` ABC and `LLMHarnessProposer(backend: AgentBackend)`.
Phase 1 scope: vary `policy_id`, `config["prompt_template_id"]`,
`config["reviewer_weights"]` only — closed allowlist, post-validated.
`adapter_factory` / `backend_factory` / `allowed_factory_prefixes`
inherited from parent unchanged. Reads search-split reports only.
CLI: `vigor harness propose --history <dir> --output <path>`. Does
**not** run the resulting candidate — composability discipline
(ADR-0031 §4). Phase 2 (factory mutation, code-gen) explicitly
deferred to [VIGOR-a384].

### VIGOR-7842

**P1 — Per-adapter smoke splits.** Per ADR-0033 §2 Gate 2. Create
hand-curated 1-2 task smoke splits for each shipping adapter
(`vigor-runtime/toy_text`, `vigor-adapter-photo`,
`vigor-adapter-video-manim`, `vigor-adapter-cad`). Tasks should
exercise end-to-end adapter behavior cheaply. Splits are never
auto-updated — a smoke split mutation is a code review. Anchored
under the same benchmark layout as [VIGOR-81d5].

### VIGOR-e7ac

**P2 — Cost-aware adaptive sampling.** Per ADR-0033 §4. New module
`packages/vigor-harness/src/vigor_harness/sampling.py` exposing
`evaluate_candidate_adaptive(candidate, split, output_dir, *,
sample_budget_usd, min_samples_per_task=1, max_samples_per_task=5)`.
Greedy variance-driven allocation: floor uniform pass, then highest
`composite_std` task gets next sample until budget exhausted or
every task at max. Reads `RunBudgetTracker` USD tally per ADR-0028.
CLI flag `--adaptive-sampling --sample-budget`. **Hard-blocked on
[VIGOR-344f] landing** (the ADR-0028 cost-ceiling enforcement work);
this seed is opened to mark the dependency explicitly, not because
implementation can start today.

### VIGOR-4827

**P2 — Migration scaffold for `harness_eval_report.v1 → v2`.** Per
ADR-0032 §4. Create
`packages/vigor-harness/src/vigor_harness/migrations.py` with a
`migrate_v1_to_v2(report_dict: dict) -> dict` skeleton + a
v2-reader-accepts-v1 contract. The actual v2 bump is scheduled only
when additive headroom runs out (a future event, not a current one).
Document the additive-vs-breaking taxonomy from ADR-0032 in the
module docstring. Test scaffold: round-trip identity + property-based
check that v1 documents pass v2 readers without modification once a
v2 is defined. This seed exists to make the deferred work
discoverable.

### VIGOR-a384

**P3 — [DEFERRED] Phase 2 proposer.** Per ADR-0031 §1 and §Alt-A.
A future ADR must specify the sandbox boundary (subprocess
isolation, capability tags, or both) before the proposer is allowed
to mutate `adapter_factory` / `backend_factory` /
`allowed_factory_prefixes`. Requirements before opening this seed
for active work:

1. Sandbox boundary beyond namespace allowlist.
2. Automated code-review path (composes with ADR-0017 plugin policy).
3. Threat-model amendment to `docs/security/threat-model.md`.

Out of scope for v2.0; this seed exists to make the deferral
discoverable to a future operator surveying the backlog.
