# ADR-0032: Benchmark Methodology, Contamination Controls, And Reproducibility

Status: Proposed

Date: 2026-05-15

## Context

ADR-0006 names "benchmark search split" and "validation split" as required
inputs to the outer loop without specifying their provenance, format, or
contamination posture. The minimal evaluator at
`packages/vigor-harness/src/vigor_harness/evaluator.py:42-100` accepts a
`SplitManifest` whose `task_uris: list[str]` are file paths to JSON
`TaskSpec` files (`models.py:35-37`). Today this means: any operator can
write any JSON file, point a manifest at it, and call it a benchmark.
There is no provenance record, no canary discipline, no reproducibility
guarantee, no notion of which split is for what.

The `SplitManifest.role` literal already discriminates `"search"` vs.
`"validation"` vs. `"heldout"` (`models.py:37`), but the discrimination is
schema-level only — the evaluator treats all three roles identically at
`evaluator.py:42-100`. The discipline that the search split is what the
proposer optimizes against and the validation/heldout splits are what
gates check on is **not enforced anywhere in code**; it is, today, a
documentation commitment with no runtime consequence.

Three problems follow:

1. **Contamination risk.** A benchmark task whose goal text or expected
   output appears verbatim (or as a near-paraphrase) in the training corpus
   of the model under evaluation will overstate the candidate's score.
   2026 LLMs have ingested most public eval datasets; this is the dominant
   source of inflated public-leaderboard scores. VIGOR has no canary
   discipline, no dataset-provenance record, and no public-dataset
   admission policy.

2. **Non-determinism.** A single run is a single sample of a noisy
   process. Per ADR-0004 the reviewer ensemble may include LLM/VLM
   critics, which are non-deterministic at any temperature > 0. The
   `mean_composite` metric in `HarnessEvalReport.v1`
   (`packages/vigor-harness/src/vigor_harness/models.py:47`) is reported
   without a standard deviation, without a confidence interval, and
   without a sample count. Two evaluations of the same candidate over the
   same split produce different numbers and the operator has no way to
   tell whether the difference is signal or noise.

3. **Schema fragility.** `HarnessEvalReport.v1` is the only result shape
   in the package. ADR-0011 commits VIGOR to additive-when-possible /
   bumped-when-necessary schema evolution, but the harness package does
   not have a single migration function or a single test asserting v1 ↔
   v2 round-trip behavior. Adding fields safely requires the conventions
   to be written down.

The strategic deep-dive in `docs/strategy/harness-v2.md` decomposes these
into one ADR per concern group; this is the methodology + reproducibility
+ schema-evolution ADR. ADR-0031 owns the architectural components
(proposer, comparator, regression detector); ADR-0033 owns the promotion
gate pipeline.

The constraints this ADR must respect:

1. **ADR-0011 schema versioning.** Additive evolution preserves the
   `vigor.harness_eval_report.v1` literal; breaking change forces v2 with
   a migration function.
2. **ADR-0006's three-way split discipline.** Search ≠ validation ≠
   heldout, and the proposer never sees validation or heldout scores.
3. **`SplitManifest.task_uris: list[str]` as file paths.** The shape is
   already shipped; this ADR adds discipline around the file paths
   without changing the schema field's type.
4. **`docs/strategy/harness-v2.md` Q2 commitment.** Public datasets are
   out of scope for v2.0; hand-curated is the only supported source.

## Decision

VIGOR will adopt a benchmark methodology with explicit provenance,
canary-string contamination discipline, three-way split governance, and
reproducibility controls reported alongside every metric.

The change has four parts.

### 1. Benchmark Layout And Provenance

Each adapter ships its benchmark splits as a directory tree under
`packages/vigor-harness/benchmarks/<adapter>/<split-name>/v<N>/`:

```
packages/vigor-harness/benchmarks/
└── photo/
    └── exposure-recovery/
        └── v1/
            ├── manifest.json           # SplitManifest, with manifest_sha256
            ├── canary.txt              # one UUID-shaped canary string
            ├── dataset_provenance.json # source, license, redaction policy
            └── tasks/
                ├── task_0001.json
                ├── task_0002.json
                └── ...
```

`manifest.json` is the existing `SplitManifest`, extended additively
(see §4 below) with `manifest_sha256: str | None` and `canary_string: str
| None`. The manifest's `task_uris` are repository-relative paths to
`tasks/*.json`. The directory shape is stable across adapters; tools
discover splits by walking the tree.

`dataset_provenance.json` is a new artifact:

```python
class DatasetProvenance(_HarnessBase):
    schema_version: Literal["vigor.dataset_provenance.v1"] = (
        "vigor.dataset_provenance.v1"
    )
    split_id: str
    source: Literal["hand_curated", "synthetic_template", "public_dataset"]
    template_id: str | None = None      # required if source == synthetic_template
    template_seed: int | None = None    # required if source == synthetic_template
    public_dataset_id: str | None = None  # required if source == public_dataset
    license: str                         # SPDX id
    redaction_policy: str                # short freeform; e.g., "no PII; no IP"
    created_at: str = Field(default_factory=utcnow_iso)
    notes: str | None = None
```

`canary.txt` contains a single UUIDv4-shaped string. Splits intended to
detect future contamination by inclusion of this exact string in any
training corpus carry a canary; splits exempt (e.g., synthetic-template
search splits) may set `canary_string = None`.

### 2. Three-Way Split Governance

The role discipline already in `SplitManifest.role` becomes enforced
behavior:

- **`search`** splits are the only role the Phase 1 proposer (ADR-0031
  §1) is allowed to read scores from. The proposer's `propose()`
  signature accepts only reports whose `split_id` corresponds to a
  `role="search"` manifest; this is enforced at the proposer's input
  validator.
- **`validation`** splits are the only role the validation-no-regress
  promotion gate (ADR-0033 §2) reads. Promotion gates that read
  validation scores never feed those scores back into the proposer.
- **`heldout`** splits exist for a final pre-release sanity check. They
  are evaluated **at most once per candidate**. The harness records every
  heldout-split run in a per-candidate ledger
  (`packages/vigor-harness/.heldout_ledger/<candidate_id>.json`); a
  second invocation against the same candidate fails closed.

The "at most once" rule for heldout is enforced by the harness, not by
operator discipline. The heldout ledger is the single source of truth;
deletion is auditable (the file is committed to the repo or to a
separate audit store, the choice deferred to the Seeds backlog).

### 3. Reproducibility

Every `HarnessEvalReport.v1` produced by v2 will carry the additive
fields:

- `n_samples_per_task: int = 1` — how many times each task was run.
- `composite_std: float | None = None` — sample standard deviation of
  the per-run mean_composite across samples.
- `composite_ci_low: float | None = None` and `composite_ci_high: float |
  None = None` — paired-bootstrap 95% CI on mean_composite. 1000 default
  resamples; configurable.
- `seed_honored: bool | None = None` — `True` when every backend used
  during the run accepted and honored the task's seed; `False` when at
  least one backend silently ignored it; `None` when the harness could
  not introspect the backend's seed-handling.
- `manifest_sha256: str | None = None` — SHA-256 of the canonical-JSON
  serialization of the `SplitManifest` used for the run.

The harness's reference invocation does N-runs averaging by default with
N=3. Operators can pass `--n-samples 1` to reproduce v1 behavior or
`--n-samples 5` for tighter CIs. The default is N=3 because:

- N=1 is too brittle for LLM-judge-driven scores.
- N=5 is 5× the cost; the marginal CI tightening from N=3 to N=5 is
  modest (about 1/√(5/3) ≈ 0.77× CI width).
- N=3 is the standard ML-eval compromise (e.g., HELM's default).

Seed propagation: a new optional field `TaskSpec.seed: int | None = None`
is added to `vigor-core`'s schemas (additive; v1 stays at v1). The
harness threads `task.seed` into the orchestrator's nondeterministic
seams: best-of-N candidate index ordering, reviewer sampling
temperature, retry jitter. The harness does **not** control the LLM
provider's sampling seed unless the `AgentBackend` exposes one; backends
that accept a seed report `seed_honored=True`, others report
`seed_honored=False`.

### 4. Schema Evolution

`HarnessEvalReport` evolves additively for the v2.0 deliverables —
every reproducibility field above is `Optional` with a default that
preserves the v1 read shape. The `schema_version` literal stays at
`"vigor.harness_eval_report.v1"`.

A future change forces a v2 bump if and only if one of the following
holds:

- a required (non-default) field is added,
- a field's type changes,
- a field is removed,
- the metric semantics of an existing field change.

When v2 is required, ship a `migrate_v1_to_v2(report_dict: dict) ->
dict` function in `vigor_harness.migrations` and a v1-input acceptance
contract on every v2 reader. Per ADR-0011, every persisted schema bump
is paired with a JSON-Schema export (a future Seeds task tracks the
export pipeline).

`HarnessCandidate.status` is a `Literal[...]` (`models.py:25`) and any
new state is a Pydantic strict-mode breaking change. The schema bump
cost is the right deterrent against state-space sprawl. ADR-0033's
PromotionGate adds new gate states only when no existing state captures
the semantics; a v2 schema bump for that ADR is named in its
Consequences section.

### 5. Public-Dataset Admission Policy

Public datasets are **explicitly disallowed** as benchmark sources for
v2.0 (`source = "public_dataset"` triggers a fail-closed at the
manifest validator). Reasons:

- Contamination of 2026 LLM training corpora with public eval datasets
  is the rule, not the exception. Every score reported against a public
  dataset is an upper bound, not a real measurement.
- License posture is per-dataset and exceeds the scope of v2.0
  diligence.
- The strategic deep-dive (`docs/strategy/harness-v2.md` Q2) explicitly
  defers this.

A future ADR may admit a specific public dataset by superseding this
rule; that ADR records the dataset id, the canary discipline (if any),
the license, and the split mapping.

## Alternatives Considered

### Alt-A: Benchmark layout — flat directory vs. nested vs. external repo

| Alternative | Reason Rejected |
| --- | --- |
| Flat: all task JSON files in one `benchmarks/` directory with adapter and split encoded into filenames | Conflates two namespaces (adapter, split) into one filesystem dimension. Tooling that walks the tree to discover splits has to parse filenames; the directory pattern is the right primitive. |
| Nested per adapter, flat within (`benchmarks/<adapter>/*.json`) | Loses per-split versioning. The `v<N>` directory is what makes "this split, evaluated at this point in time" a stable reference. |
| External repo: ship benchmarks in `vigor-benchmarks` separate from `vigor-harness` | Defensible long-term but adds release-cycle coupling with no v2.0 payoff. The current monorepo posture (ADR-0009) keeps benchmark + harness in lockstep, which is the correct v2.0 trade. |
| (Chosen) `packages/vigor-harness/benchmarks/<adapter>/<split-name>/v<N>/` with `manifest.json + canary.txt + dataset_provenance.json + tasks/*.json` | One directory == one split version. Discoverable by walking. Provenance lives next to the data. Canary is conspicuous. |

### Alt-B: Contamination posture — canary string vs. hash-only vs. nothing

| Alternative | Reason Rejected |
| --- | --- |
| Hash-only: store the SHA-256 of the manifest and trust that nobody redistributes the tasks | Useful for tamper detection but useless for contamination detection — a model trained on the tasks themselves doesn't care about the manifest hash. |
| Nothing (status quo) | Accepts that every public-dataset-derived benchmark is contaminated and that there's no way to check in the future. Untenable for any adapter that ever accepts a public-dataset import. |
| (Chosen) Canary strings (BIG-Bench pattern) — one UUID-shaped phrase per split, embedded in tasks | Trivially detectable in any future training corpus by string search; the standard 2026 contamination guard. The cost is tiny (one extra string per split); the leverage is exactly the leverage BIG-Bench named. Optional for synthetic-template splits because they are regenerable. |

### Alt-C: Reproducibility — N-runs default vs. operator-opt-in vs. operator-required

| Alternative | Reason Rejected |
| --- | --- |
| Operator-opt-in (N=1 default; --n-samples to enable): preserves v1 cost behavior | N=1 is brittle enough that "the default report shape lies about its uncertainty" is a real failure mode. The reproducibility commitment exists exactly because operators were already running into this. |
| Operator-required (no default; explicit --n-samples is required): forces a decision | Friction without commensurate value — the right default for almost everyone is 3, and forcing every invocation to specify it is busywork. |
| (Chosen) Default N=3 with --n-samples to override | Standard ML-eval default. Cost is 3× v1; the operator who needs v1 cost passes --n-samples 1 and accepts the brittleness. |

### Alt-D: Schema evolution — additive-first vs. v2-now vs. unversioned

| Alternative | Reason Rejected |
| --- | --- |
| Bump to `harness_eval_report.v2` immediately for the reproducibility fields | Bumping the schema for fields that have safe defaults forces every existing consumer to migrate without benefit. ADR-0011's additive-first rule exists exactly to avoid this. |
| Drop the `schema_version` literal and treat the schema as freeform | Defeats ADR-0011. Not seriously considered. |
| (Chosen) Stay at v1, all reproducibility fields are `Optional` with defaults that preserve v1 read shape | Composes with ADR-0011's rules. Forces a v2 bump only when the additive headroom runs out. |

### Alt-E: Public-dataset admission policy — open vs. closed vs. case-by-case

| Alternative | Reason Rejected |
| --- | --- |
| Open admission: any public dataset declared in `dataset_provenance.json` is admissible | Ignores the contamination problem and the license-diligence problem. Documents the wrong commitment. |
| Case-by-case: an ADR per dataset | Eventually right; for v2.0, there is no case to be made for any specific dataset, so committing to the case-by-case process implies the case-by-case process exists. It does not. |
| (Chosen) Closed: no public datasets in v2.0; future ADRs may supersede with a specific admission | Honest about what's tractable in v2.0. Names the supersession path explicitly. |

## Consequences

### Positive

1. **Provenance becomes a first-class artifact.** Every score has a
   manifest sha and a dataset provenance record. Reproducing a score
   later is a matter of checking out the same `v<N>/` directory and
   running.
2. **Contamination detection becomes possible.** Canary strings are
   trivially detectable in any future training corpus by string search.
   Splits without canaries are explicitly synthetic-template, which is
   the only justification for canary exemption.
3. **The three-way split discipline is enforced rather than documented.**
   The proposer cannot leak validation scores into its inputs; the
   heldout ledger prevents accidental heldout reuse.
4. **Reproducibility metrics ship with every report.** No more
   "mean_composite went up by 0.02, is that signal?" — the CI is in
   the report.
5. **Schema bumps are deferred.** The reproducibility commitment is
   shipped without a v2 schema bump, preserving every v1 reader.

### Negative

1. **Default cost is 3× v1.** N=3 averaging triples the bill at v2
   default settings. Operators who opt out (`--n-samples 1`) accept the
   noise; operators who keep the default accept the cost. The cost is
   the right default for science, not the right default for budget.
2. **The benchmark directory tree is repository-resident and growing.**
   Each adapter's split files contribute to repo size; large
   `tasks/*.json` files add up. The mitigation is per-split
   versioning — old versions can be pruned on a deprecation cycle when
   a v<N+1> is shipped.
3. **The heldout ledger is a small new piece of operational state.**
   A corrupted ledger blocks heldout invocations until the operator
   intervenes. The blast radius is small (per-candidate JSON file with
   a single timestamp); recovery is manual but mechanical.
4. **The "no public datasets" commitment will become controversial.**
   At some point an operator will want HumanEval or MMLU-style
   evaluation. The commitment is honest about v2.0; the supersession
   path is documented.

## Citations

| Source | Anchor |
| --- | --- |
| `SplitManifest` schema | `packages/vigor-harness/src/vigor_harness/models.py:35-37` |
| `HarnessEvalReport` schema | `packages/vigor-harness/src/vigor_harness/models.py:43-48` |
| `evaluator.py:42-100` (the evaluator we extend) | inline |
| Schema-versioning rules | ADR-0011 (Accepted) |
| Outer-loop policy | ADR-0006 (Accepted) |
| Sibling ADRs | ADR-0031 (architecture), ADR-0033 (promotion gates) |
| Strategic context | `docs/strategy/harness-v2.md` |
| BIG-Bench canary-string pattern | (industry pattern; see strategy doc §"2026 External Posture") |
| HELM disclosure / N=3 default | (industry pattern; see strategy doc §"2026 External Posture") |
