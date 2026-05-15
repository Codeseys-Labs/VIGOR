# Architecture Decision Records

VIGOR records architectural decisions as ADRs in this directory. New ADRs (ADR-0017 onward) follow [MADR 3.0](https://github.com/adr/madr); ADR-0001–0015 use the project's earlier inline `Status:` / `Date:` style and are preserved as-is. Per the ADR methodology, accepted ADRs are immutable: changes are recorded by writing a new ADR that supersedes the old one.

| # | Title | Status | Date |
| --- | --- | --- | --- |
| [ADR-0001](0001-adopt-vigor-loop.md) | Adopt Generate-Compile-Review As The Core VIGOR Loop | accepted | 2026-04-26 |
| [ADR-0002](0002-use-editable-intermediate-representations.md) | Use Editable Intermediate Representations As First-Class Outputs | accepted | 2026-04-26 |
| [ADR-0003](0003-separate-adapters-from-orchestration.md) | Separate Domain Adapters From The Orchestration Runtime | accepted | 2026-04-26 |
| [ADR-0004](0004-reviewer-ensemble-and-adjudicator.md) | Use Reviewer Ensembles And An Adjudicator Instead Of Self-Review | accepted | 2026-04-26 |
| [ADR-0005](0005-trajectory-memory-and-provenance.md) | Store Trajectory Memory And Artifact Provenance As Core State | accepted | 2026-04-26 |
| [ADR-0006](0006-meta-harness-inspired-outer-loop.md) | Add A Meta-Harness-Inspired Outer Loop For Harness Optimization | accepted | 2026-04-26 |
| [ADR-0007](0007-sdk-agnostic-core-with-optional-agent-backends.md) | Build VIGOR As An SDK-Agnostic Core With Optional Agent Backends | accepted | 2026-04-26 |
| [ADR-0008](0008-python-as-reference-language.md) | Use Python 3.11+ As The Reference VIGOR Language | accepted | 2026-04-26 |
| [ADR-0009](0009-monorepo-layout.md) | Use A Single UV Monorepo With `packages/` And `examples/` | accepted | 2026-04-26 |
| [ADR-0010](0010-async-core-interfaces.md) | Async Core Interfaces For Adapters, Backends, And Patches | accepted | 2026-04-26 |
| [ADR-0011](0011-ir-schema-versioning.md) | IR Schema Versioning And Discriminated Unions | accepted | 2026-04-26 |
| [ADR-0017](0017-pure-mcp-plugin-support.md) | Admit Pure-MCP Plugins As Ambient Tool Sources | proposed | 2026-05-15 |
| [ADR-0018](0018-vendor-manifest-dual-publishing.md) | Dual-Publish Vendor Manifests From The Adapter Generator For Open-Plugin-Spec Host Compatibility | proposed | 2026-05-15 |
| [ADR-0028](0028-cost-ceiling-enforcement.md) | Enforce Cost Ceilings Via AgentBackend Usage Telemetry And A RunBudgetTracker | proposed | 2026-05-15 |
| [ADR-0029](0029-multi-tenant-subprocess-env-hardening.md) | Default-Drop Subprocess Environment For MCP Stdio And Per-Tenant Run Archive Scoping | proposed | 2026-05-15 |
| [ADR-0030](0030-library-first-deployment-posture.md) | Ship VIGOR As Library + CLI; Defer Hosted vigor-server As Downstream Concern | proposed | 2026-05-15 |
| [ADR-0034](0034-parallel-best-of-n-via-asyncio-gather.md) | Parallel Best-of-N Via `asyncio.gather` Gated By `Budgets.parallel_candidates` | proposed | 2026-05-15 |
| [ADR-0035](0035-single-node-orchestrator-posture.md) | VIGOR-The-Library Is Single-Node By Contract; Defer Distributed Orchestration | proposed | 2026-05-15 |
| [ADR-0036](0036-iteration-checkpoint-resume.md) | Iteration-Boundary Checkpoint And Opt-In Resume Via `Orchestrator.resume(run_id)` | proposed | 2026-05-15 |
| [ADR-0037](0037-runtime-observer-protocol-seam.md) | Runtime Observability Via A `RuntimeObserver` Protocol Seam, No Hard SDK Dependency | proposed | 2026-05-15 |

ADR-0014 (Generalized Agent Configuration) and ADR-0015 (Open Plugin Spec v1 Compatibility) were authored on the unmerged `claude/agent-adapter-framework-1KOmV` feature branch and will appear in this index when that branch lands. ADR-0017 and ADR-0018 are written to land alongside them; ADR-0018 amends a single deferral row in ADR-0015's Alternatives table, all four are mutually referencing.
