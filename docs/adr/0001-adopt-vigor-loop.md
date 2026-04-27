# ADR-0001: Adopt Generate-Compile-Review As The Core VIGOR Loop

Status: Accepted

Date: 2026-04-26

## Context

One-shot AI generation is brittle for assets that must satisfy spatial, semantic, aesthetic, physical, or engineering constraints. VIGA demonstrates a successful domain-specific loop for inverse graphics: generate executable scene code, render it, inspect visual mismatch, and revise. Anthropic's evaluator-optimizer pattern similarly recommends a generator plus evaluator loop when criteria are clear and iteration improves quality.

VIGOR needs to generalize this pattern across modalities.

## Decision

VIGOR will use **generate-compile-review** as the core runtime loop.

The loop is:

```text
goal -> representation plan -> generate IR -> compile/render/simulate -> review -> adjudicate -> patch or accept
```

Every domain adapter must define how its IR is generated, compiled or rendered, reviewed, patched, exported, and stopped.

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| One-shot generation | Does not produce enough evidence, editability, or reliability for downstream domains. |
| Pure chat-based refinement | Lacks durable artifact state and objective tool feedback. |
| Fully differentiable optimization | Useful for some modalities but not universal across code, CAD, documents, and editor workflows. |
| Domain-specific standalone systems | Powerful locally but does not create a universal framework. |

## Consequences

Positive:

1. VIGOR can unify photo editing, video generation, CAD, code, UI, audio, robotics, and simulation under one orchestration model.
2. Compilers and reviewers provide evidence for refinement.
3. Artifacts remain editable and reproducible.

Negative:

1. Iteration increases latency and cost.
2. Domain adapters must be built carefully.
3. Reviewers can be biased or noisy and require calibration.

## Citations

| Source | URL |
| --- | --- |
| VIGA paper | https://arxiv.org/abs/2601.11109 |
| VIGA repository | https://github.com/Fugtemypt123/VIGA |
| Anthropic evaluator-optimizer pattern | https://www.anthropic.com/engineering/building-effective-agents |
| Long-running generator/evaluator harness | https://www.anthropic.com/engineering/harness-design-long-running-apps |
