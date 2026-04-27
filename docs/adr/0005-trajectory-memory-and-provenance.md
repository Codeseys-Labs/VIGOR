# ADR-0005: Store Trajectory Memory And Artifact Provenance As Core State

Status: Accepted

Date: 2026-04-26

## Context

Long-running iterative systems fail when state lives only in chat history. Context windows fill, summaries lose details, and later reviewers cannot reconstruct what happened. VIGA stores plans, code diffs, and render history. Meta-Harness gives its proposer access to prior source code, scores, and execution traces through a filesystem. W3C PROV provides a general model for provenance over entities, activities, and agents.

## Decision

VIGOR will persist trajectory memory and provenance as first-class state.

Each run should archive:

1. Task spec and constraints.
2. Adapter manifest.
3. Candidate IRs.
4. Compile/render/simulation outputs.
5. Review reports.
6. Adjudication decisions.
7. Patch plans.
8. Final artifact and export bundle.
9. Stop reason.

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| Chat transcript as memory | Not structured, not robust, and hard to resume or audit. |
| Final artifact only | Loses evidence and cannot explain decisions. |
| Metrics-only archive | Cannot diagnose why candidates failed or improved. |

## Consequences

Positive:

1. Runs become auditable and resumable.
2. Reviewers and future agents can inspect prior evidence.
3. Meta-Harness-style harness optimization becomes possible.
4. Human users can compare candidates and understand revisions.

Negative:

1. Artifact storage may become large.
2. Privacy and retention policies are required for media and user data.
3. Hashing, versioning, and schema migration are needed.

## Citations

| Source | URL |
| --- | --- |
| VIGA architecture doc | https://raw.githubusercontent.com/Fugtemypt123/VIGA/main/docs/architecture.md |
| Meta-Harness paper | https://arxiv.org/abs/2603.28052 |
| Meta-Harness repo | https://github.com/stanford-iris-lab/meta-harness |
| W3C PROV overview | https://www.w3.org/TR/prov-overview/ |
