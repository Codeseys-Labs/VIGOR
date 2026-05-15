# ADR-0031: Harness v2 Architecture — Proposer, Comparator, RegressionDetector

Status: Proposed

Date: 2026-05-15

## Context

ADR-0006 commits VIGOR to a Meta-Harness-inspired outer loop for harness
optimization, lists eight promotion gates as a table, and names a
`harness candidate -> run benchmark tasks -> score candidate outputs ->
store traces/scores -> propose harness patch -> update search history/frontier`
flow. Phase 6 of the roadmap (`docs/roadmap.md` "Phase 6: Meta-Harness-Style
Harness Optimization") shipped only the middle three boxes: the minimal
evaluator at `packages/vigor-harness/src/vigor_harness/evaluator.py:42-100`,
the `HarnessCandidate` / `SplitManifest` / `HarnessEvalReport` schemas at
`packages/vigor-harness/src/vigor_harness/models.py:21-48`, and the per-task
RunArchive plumbing inherited from `vigor-runtime`.

What the minimal evaluator does **not** do, and what this ADR commits to
shipping in v2:

- It does not propose new `HarnessCandidate` records — `parent_candidate_id`
  is a schema field that no code path writes
  (`packages/vigor-harness/src/vigor_harness/models.py:26`).
- It does not compare two reports — operators run `evaluate_candidate` twice
  and diff the resulting JSON manually.
- It does not detect regressions — `HarnessEvalReport.regressions: list[str]`
  is populated nowhere in the package
  (`packages/vigor-harness/src/vigor_harness/models.py:48`).
- It does not enforce promotion gates — `HarnessCandidate.status` literal
  already includes `"promoted"` and `"rejected"`
  (`packages/vigor-harness/src/vigor_harness/models.py:25`) but no gate
  sequence is enforced; any caller can flip the field.

The strategic deep-dive in `docs/strategy/harness-v2.md` decomposes harness
v2 into four cooperating capabilities — Proposer, Comparator,
RegressionDetector, PromotionGate. This ADR specifies the first three;
ADR-0033 specifies the PromotionGate. The split is deliberate: PromotionGate
intersects with the cost-ceiling work (ADR-0028) and the safety-sensitive
adapter classification, which are operationally distinct from the evaluator
extensions.

ADR-0006 explicitly defers the proposer/optimizer to "future enhancement".
This ADR replaces that deferral with a concrete Phase 1 / Phase 2 split.
Phase 1 is the smallest commitment that delivers signal; Phase 2 is named
but not specified. The Phase 1 proposer is intentionally lower-novelty than
the Meta-Harness reference: it varies prompt/policy fields only, never
mutates code or factory references.

The constraints this ADR must respect:

1. **ADR-0011 schema versioning.** Any new artifact carries a
   `schema_version: Literal["vigor.<name>.v1"]` field. Additive evolution
   stays at v1; breaking change forces v2.
2. **ADR-0007 SDK-agnostic core.** New components must not introduce a new
   `AgentBackend`-style coupling to a single SDK. The proposer accepts an
   `AgentBackend` reference (whatever flavor) and produces a typed
   `HarnessCandidate`.
3. **`evaluator.py:21-32` factory namespace allowlist.** New components
   must preserve the allowlist when accepting factory references — no
   bypass via the proposer.
4. **No re-run on the comparator side.** An archive-anchored design (per
   the Inspect 2026 pattern) keeps cost where the operator can see it.

## Decision

VIGOR will ship harness v2 as three new components in `packages/vigor-harness`,
each layering on the existing `evaluate_candidate` rather than replacing it.

### 1. `HarnessProposer` ABC + `LLMHarnessProposer` (Phase 1 reference impl)

A new abstract base class in `packages/vigor-harness/src/vigor_harness/proposer.py`:

```python
class HarnessProposer(ABC):
    """Generate a new HarnessCandidate from prior history."""

    @abstractmethod
    async def propose(
        self,
        history: Sequence[HarnessCandidate],
        reports: Sequence[HarnessEvalReport],
    ) -> HarnessCandidate:
        """Return a new candidate. parent_candidate_id MUST be set."""
```

The reference implementation `LLMHarnessProposer(backend: AgentBackend)`
in the same file implements `propose` by:

1. Selecting the highest-`mean_composite` candidate from `history` whose
   reports show no validation regressions as the `parent`.
2. Asking the backend to vary one of `policy_id` or `config["prompt_template_id"]`
   or `config["reviewer_weights"]` (and only these — a closed allowlist
   enforced by the proposer post-validation).
3. Setting `parent_candidate_id = parent.candidate_id`,
   `allowed_factory_prefixes = parent.allowed_factory_prefixes` (inherited),
   `adapter_factory = parent.adapter_factory` (inherited),
   `backend_factory = parent.backend_factory` (inherited).
4. Returning the new `HarnessCandidate`.

**Phase 1 ↔ Phase 2 boundary.** The Phase 1 proposer never returns a
candidate whose `adapter_factory` or `backend_factory` differs from its
parent. Any backend response that proposes such a change is rejected by
the proposer (the proposer post-validates the LLM output). Phase 2 is
explicitly out of scope for this ADR; it requires (a) a sandbox boundary
beyond the namespace allowlist, (b) a separate code-review path, and
(c) a threat-model amendment.

### 2. `HarnessComparator` + `vigor.harness_comparison.v1`

A new function in `packages/vigor-harness/src/vigor_harness/comparator.py`:

```python
async def compare_candidates(
    a: HarnessEvalReport,
    b: HarnessEvalReport,
    a_archive: Path,
    b_archive: Path,
    *,
    bootstrap_resamples: int = 1000,
) -> HarnessComparison:
```

The function:

1. Asserts `a.split_id == b.split_id` and (when v2 schema lands) the
   `manifest_sha256` matches.
2. Reads each per-task `frontier.json` from the two archives.
3. For each task id common to both, classifies `win` / `loss` / `tie`
   on the per-task selected-candidate composite score.
4. Computes a paired-bootstrap CI on Δ mean_composite over the per-task
   pairs (default 1000 resamples).
5. Computes McNemar's test on accept_rate (treating "accepted vs not
   accepted" as the binary outcome).
6. Emits `HarnessComparison` (new schema):

   ```python
   class HarnessComparison(_HarnessBase):
       schema_version: Literal["vigor.harness_comparison.v1"] = (
           "vigor.harness_comparison.v1"
       )
       comparison_id: str
       created_at: str = Field(default_factory=utcnow_iso)
       a_candidate_id: str
       b_candidate_id: str
       split_id: str
       n_paired_tasks: int
       wins: int   # B beats A
       losses: int # B regresses against A
       ties: int
       delta_composite: float | None
       delta_composite_ci_low: float | None
       delta_composite_ci_high: float | None
       mcnemar_p: float | None
       regressed_task_ids: list[str] = Field(default_factory=list)
   ```

The comparator is **archive-anchored** — it does not run candidates. If
either archive is missing, the comparator fails closed with a typed
error (`ComparisonInputError`); operators must run the evaluator first.

### 3. `RegressionDetector` + Baseline Registry

A new function in `packages/vigor-harness/src/vigor_harness/regression.py`:

```python
async def detect_regressions(
    candidate_report: HarnessEvalReport,
    candidate_archive: Path,
    baselines: Sequence[BaselineEntry],
    *,
    archive_root: Path,
) -> list[str]:
    """Return the list of regressed task_ids across all baselines."""
```

Where `BaselineEntry`:

```python
class BaselineEntry(_HarnessBase):
    schema_version: Literal["vigor.baseline_entry.v1"] = "vigor.baseline_entry.v1"
    split_id: str
    baseline_candidate_id: str
    delta_threshold: float = 0.005  # validation no-regress default
```

The detector calls `compare_candidates` for each baseline whose
`split_id` matches the report's `split_id`, collects the
`regressed_task_ids` from each comparison, deduplicates them, and
returns the union. The detector's caller writes the result into
`HarnessEvalReport.regressions` — repurposing the existing v1 field
that is currently always empty (`models.py:48`).

The **baseline registry** is a per-adapter JSON file at
`packages/vigor-harness/baselines/<adapter>.json` containing a list of
`BaselineEntry`. Updates are atomic and are owned exclusively by the
PromotionGate pipeline (ADR-0033); manual edits are a smell. The
registry is read-only from the perspective of the detector.

### 4. CLI Entry Points

`vigor-harness` gains a small CLI surface (a new module
`packages/vigor-harness/src/vigor_harness/cli.py`) exposing four
subcommands, each composable with the others:

- `vigor harness eval --candidate <path> --split <path> --output <dir>`
  (existing, but moved from a Python-API-only invocation to an explicit CLI).
- `vigor harness propose --history <dir> --output <path>` runs the Phase 1
  proposer; it does not run the resulting candidate.
- `vigor harness compare --a <report> --b <report> --output <path>` runs
  the comparator; archive paths are inferred from the report's
  `output_dir` convention.
- `vigor harness regress --candidate-report <path> --baselines <adapter>`
  runs the regression detector and prints regressed task ids.

The CLI is intentionally composable rather than monolithic — operators
chain the four steps in shell. A "do everything" wrapper is explicitly
not introduced in v2.0; ADR-0033's `promote_candidate` entry point is
the closest thing, and it exists for the promotion-gate orchestration,
not as a generic wrapper.

## Alternatives Considered

### Alt-A: Proposer scope — prompt/policy only vs. factory mutation vs. arbitrary code

| Alternative | Reason Rejected |
| --- | --- |
| Phase 1 permits `adapter_factory` / `backend_factory` mutation under the existing namespace allowlist | The namespace allowlist is a coarse boundary — it gates which Python module is imported, not what the imported code does. A proposer that swaps `adapter_factory` from a known-good module to a different module within the same allowed prefix can introduce arbitrary behavior change without triggering any code-review path. The Phase 2 design that admits this requires a sandbox boundary beyond the namespace allowlist (subprocess isolation, capability tags, or both); shipping that boundary is itself a separate ADR. |
| Phase 1 permits arbitrary code generation (the proposer writes new Python files) | This is the Meta-Harness reference shape and is a known threat surface even in research contexts. It also implies a code-review agent that VIGOR has not yet committed to ship. Out of scope for v2.0 entirely; this ADR explicitly does not foreclose Phase 2 admitting it via a separate ADR. |
| (Chosen) Phase 1 permits prompt template id and policy id and reviewer-weight variation only | Six of the eight axes ADR-0006 names as outer-loop targets are addressable via prompts, policies, reviewer weights, memory policy, stop conditions, and escalation policy — and each is a string-keyed config field rather than executable code. The remaining two (adapter code, IR mappings) are exactly the dangerous ones. Phase 1 covers the cheap wins; Phase 2 admits the dangerous wins under a separate ADR. |

### Alt-B: Comparator semantics — re-run vs. archive-anchored vs. caching layer

| Alternative | Reason Rejected |
| --- | --- |
| Comparator re-runs both candidates inside the comparator entry point | Doubles the operator's bill in the comparator surface, hides cost from `vigor harness eval`, and reproduces the determinism question from Q6 inside a different code path. If the operator wants a re-run, they can run the evaluator twice and pass the new reports to the comparator — the composability is a strict win. |
| Comparator caches per-task scores in a side database | Adds a hard runtime dependency (sqlite or similar) for a cache that the file-system archive already implements. Over-engineering for v2.0. |
| (Chosen) Archive-anchored: comparator reads two existing run archives | Matches the Inspect 2026 pattern and keeps the cost in the upstream evaluator invocation where the operator can budget it. Fails closed on missing archive — the operator must explicitly run the evaluator before comparing. |

### Alt-C: Regression-suite shape — baselines on disk vs. baselines in code vs. baselines in seeds

| Alternative | Reason Rejected |
| --- | --- |
| Baselines hard-coded as Python literals in `vigor-harness` source | Updating the baseline requires a code change + release. The whole point of the registry is that promotion atomically updates baselines; coupling that to a release cycle defeats the v2 commitment to automated promotion. |
| Baselines tracked in seeds (one Seed per baseline entry) | Misuses the seeds tracker for runtime configuration. Seeds tracks issues; the baseline is operational data. Wrong primitive. |
| Baselines stored in `RunArchive` next to per-run frontier.json | Plausible but couples the registry's shape to the archive's, which is unnecessary indirection. The registry is per-adapter, not per-run; the per-adapter file is the natural unit. |
| (Chosen) Per-adapter JSON file at `packages/vigor-harness/baselines/<adapter>.json`, owned by the PromotionGate pipeline | One writer, fail-closed reads, atomic updates via temp-file-rename. The shape composes cleanly with the existing namespace boundary (one file per adapter). |

### Alt-D: New artifact `HarnessComparison` vs. extending `HarnessEvalReport`

| Alternative | Reason Rejected |
| --- | --- |
| Embed the comparison fields inside `HarnessEvalReport.v2` (carrying a "compared_to" reference) | Conflates the per-candidate report with a pairwise artifact. A v2 report would carry comparison fields that are meaningful only when populated, which violates ADR-0011's strict-mode posture (`extra="forbid"` plus `Optional` fields proliferating). |
| Use a free-form JSON file with no schema | Defeats the typed-pipeline discipline ADR-0011 codifies. |
| (Chosen) New schema `vigor.harness_comparison.v1` | One artifact, one shape. Operators reading a comparison file know exactly what to expect; the type system enforces the v1 contract. |

## Consequences

### Positive

1. **Phase 6 of the roadmap moves from "minimal evaluator" to "real eval framework"** in three independently-shippable steps. Each of the three components above can land separately and provide value alone — comparator without proposer is useful for human-authored candidates; regression detector without comparator is meaningless, so the order is forced.
2. **The unused `HarnessEvalReport.regressions` field gets a producer.** Repurposing the existing v1 field rather than adding a new one preserves additive evolution (Q8 commitment).
3. **The proposer's Phase 1 / Phase 2 split surfaces the threat boundary explicitly.** A future operator reading this ADR understands why prompt-only is the v2.0 commitment and what shipping Phase 2 would require (a separate ADR with a sandbox decision).
4. **Archive-anchored comparison composes with `ml-eval-harness` / `Inspect`-style usage.** Operators who want to compare results from a third-party tool can in principle wrap them as a `HarnessEvalReport` + a frontier-shaped archive and feed them to the comparator. The shape is portable.
5. **CLI composability matches the unix-pipeline aesthetic of the rest of `vigor-agent`.** No new monolithic entry point.

### Negative

1. **Phase 1 proposer misses the highest-leverage variation axes.** Adapter mutation, IR-mapping mutation, and arbitrary code generation are precisely where Meta-Harness reports the largest gains. VIGOR's v2.0 deliberately leaves these on the table. Operators who need them will be frustrated; the answer is "Phase 2, after the threat boundary is named in its own ADR".
2. **The baseline registry is a small new piece of operational state.** It is one JSON file per adapter, atomically updated, with one writer (the PromotionGate). The blast radius is small but nonzero — corruption requires manual intervention. Mitigated by atomic temp-file-rename and a `vigor harness baselines verify` health check (P1 backlog).
3. **Paired-bootstrap is more compute than t-tests.** 1000 resamples × per-task pair count is on the order of 50k-100k arithmetic operations per comparison. Trivial in absolute terms; mentioned only to set the expectation that v2 reports take milliseconds longer to produce than v1.
4. **CLI surface widens by four subcommands.** Maintenance cost grows linearly with the surface; a future deprecation of any subcommand requires the standard CLI deprecation cycle.
5. **The Phase 2 deferral is a known unknown.** A future ADR that admits factory mutation will need to reconcile its sandbox boundary with the existing namespace allowlist. The work is named, not started.

## Citations

| Source | Anchor |
| --- | --- |
| Phase 6 minimal evaluator | `packages/vigor-harness/src/vigor_harness/evaluator.py:42-100` |
| `HarnessEvalReport.regressions` (currently unused) | `packages/vigor-harness/src/vigor_harness/models.py:48` |
| Factory namespace allowlist | `packages/vigor-harness/src/vigor_harness/evaluator.py:21-32` |
| Meta-Harness outer-loop policy | ADR-0006 (Accepted) |
| Schema-versioning rules | ADR-0011 (Accepted) |
| Sibling ADRs | ADR-0032 (benchmark methodology), ADR-0033 (promotion gates) |
| Strategic context | `docs/strategy/harness-v2.md` |
