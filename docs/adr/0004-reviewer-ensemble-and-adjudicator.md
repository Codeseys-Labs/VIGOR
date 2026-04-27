# ADR-0004: Use Reviewer Ensembles And An Adjudicator Instead Of Self-Review

Status: Accepted

Date: 2026-04-26

## Context

Generator self-review is unreliable, especially for subjective domains such as visual design, photo editing, video quality, and aesthetics. Anthropic's long-running harness article explicitly identifies self-evaluation as a failure mode and describes better results with a separate evaluator agent.

VIGOR domains also require different kinds of evidence: objective metrics, learned scorers, VLM critique, domain simulators, and human preference.

## Decision

VIGOR will use reviewer ensembles plus an adjudicator.

Reviewers produce structured findings. The adjudicator merges results, handles disagreement, decides whether to accept/refine/branch/escalate, and writes patch objectives.

Reviewer categories:

| Category | Examples |
| --- | --- |
| Objective validators | Tests, constraints, clipping, contrast, mesh validity, LUFS |
| Learned scorers | VideoScore2, aesthetic models, reward models, TRIBE-like encoders where applicable |
| Model critics | VLM/LLM critique, semantic alignment, design review |
| Tool-backed inspectors | Playwright, CAD solvers, physics simulators, slicers |
| Humans | A/B preference, inline comments, accept/reject, evaluator calibration |

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| Generator self-review only | Too lenient and correlated with generation blind spots. |
| Single LLM judge | Useful but biased and insufficient for objective correctness. |
| Objective metrics only | Many target qualities are subjective or semantic. |
| Human review only | High quality but not scalable for automatic refinement. |

## Consequences

Positive:

1. Review is more robust and evidence-grounded.
2. Subjective and objective criteria can be combined.
3. Review disagreement can be surfaced as uncertainty.

Negative:

1. Ensembles increase cost and latency.
2. Scoring requires calibration.
3. Adjudication policy can become complex.

## Citations

| Source | URL |
| --- | --- |
| Long-running generator/evaluator harness | https://www.anthropic.com/engineering/harness-design-long-running-apps |
| Anthropic parallelization and evaluator-optimizer patterns | https://www.anthropic.com/engineering/building-effective-agents |
| LLM-as-judge bias discussion | https://arxiv.org/abs/2306.05685 |
| TRIBE v2 demo | https://aidemos.atmeta.com/tribev2 |
