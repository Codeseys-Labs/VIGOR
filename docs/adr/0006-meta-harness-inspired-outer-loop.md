# ADR-0006: Add A Meta-Harness-Inspired Outer Loop For Harness Optimization

Status: Accepted

Date: 2026-04-26

## Context

VIGOR will initially improve individual artifacts through an inner generate-compile-review loop. Over time, the framework should also improve the harness itself: prompts, adapters, reviewer weights, memory policies, observation tools, stop criteria, and candidate selection rules.

Meta-Harness demonstrates an outer-loop approach that searches over harness code using prior candidates, execution traces, and scores stored in a filesystem.

## Decision

VIGOR will support a second-level optimization loop for harness evolution.

The inner loop improves artifacts:

```text
artifact candidate -> compile -> review -> patch -> final artifact
```

The outer loop improves the VIGOR harness:

```text
harness candidate -> run benchmark tasks -> score traces -> propose harness patch -> frontier update
```

Outer-loop candidates may change:

1. Prompt templates.
2. Adapter code.
3. IR schema mappings.
4. Reviewer selection and weights.
5. Memory policy.
6. Compiler preprocessing.
7. Stop conditions.
8. Human escalation policy.

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| Manual harness tuning only | Slow and hard to scale across domains. |
| Optimize prompts only | Underpowered because tool use, memory, and review policies matter. |
| Use same task outputs for search and reporting | Risks leakage and overfitting. |

## Consequences

Positive:

1. VIGOR can improve adapter quality over benchmark suites.
2. Trace archives become useful training and optimization data.
3. Harness tradeoffs can be tracked as Pareto frontiers.

Negative:

1. Requires benchmark suites and held-out evaluation per domain.
2. Outer-loop search can be expensive.
3. Harness patches need stronger review because they affect many future runs.

## Citations

| Source | URL |
| --- | --- |
| Meta-Harness paper | https://arxiv.org/abs/2603.28052 |
| Meta-Harness reference repo | https://github.com/stanford-iris-lab/meta-harness |
| Meta-Harness project page | https://yoonholee.com/meta-harness/ |
