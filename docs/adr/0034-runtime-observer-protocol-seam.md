---
status: proposed
date: 2026-05-15
deciders: [VIGOR architecture team]
consulted: [builder-runtime-strategy]
informed: [coordinator]
---

# ADR-0034: Runtime Observability Via A `RuntimeObserver` Protocol Seam, No Hard SDK Dependency

## Context and Problem Statement

VIGOR-7724 Q5 asks: *OpenTelemetry traces? Structured logging conventions? Prometheus metrics? What's the minimal viable instrumentation?*

The runtime today emits **no telemetry**. There are no `logging` calls, no metric counters, no spans, no progress hooks. A library user wanting to know "iteration 3 just finished" must wrap the orchestrator and poll the archive directory for filesystem changes. A `vigor-server` (deferred per ADR-0030) wanting to surface progress to an HTTP client must do the same. This is hostile to every consumer except the post-hoc archive reader.

The deployment-and-ops sibling document (`docs/strategy/deployment-and-ops.md`, §"Observability And Telemetry", lines 484-499) commits the **deployment layer** to OpenTelemetry traces, Prometheus metrics, structured JSON logs, and `/healthz` `/readyz` endpoints. That commitment is for the eventual `vigor-server`, not for the library. The question for this ADR is: *what observability primitive does the library expose, such that a downstream `vigor-server` can adapt it to OpenTelemetry/Prometheus, while a library-only user gets useful debugging information without a heavyweight dependency?*

Three constraints frame the answer:

- **ADR-0007 (SDK-agnostic core).** `vigor-core` and `vigor-runtime` cannot hard-import `opentelemetry`. Operators using a different telemetry backend (Datadog, Honeycomb, plain stderr logging, no telemetry at all) must not pay the import cost or the dependency-graph cost of an SDK they do not use.
- **ADR-0030 (library-first).** Telemetry sinks are deployment-time choices. The library exposes a *seam*; the deployment chooses the *implementation*. Pre-baking a sink into the library overcommits.
- **Default-off.** Existing operators who today get no telemetry must continue to get no telemetry by default. A change that suddenly emits OpenTelemetry spans (with the security implications of trace-context exfiltration to an unconfigured backend) would be a regression.

The shape every successful library-instrumentation pattern uses for this is a **callback protocol**: the library calls user-provided functions at well-known instrumentation points, and the user supplies the implementation. Python's `typing.Protocol` is the natural primitive — duck-typed (any object with the right methods works), no inheritance required, no runtime cost when no observer is attached.

The complementary question is **what events the protocol exposes**. Too few, and consumers cannot reconstruct the run shape. Too many, and the protocol becomes a churning surface that every observer implementation has to chase. The right cut is **lifecycle events at the same boundaries the orchestrator already has natural seams**: run start/end, iteration start/end, candidate start/end, plus an `on_event(name, attributes)` escape hatch for one-off events that don't fit the lifecycle (errors, patch decisions, stop reasons).

## Decision Drivers

- **Zero-dependency for the default case.** A library user who never attaches an observer pays nothing.
- **Composable with downstream sinks.** A `vigor-observability-otel` package (out-of-tree, not part of this ADR) can implement `RuntimeObserver` against OpenTelemetry. A `vigor-observability-prometheus` package can implement it against Prometheus. Both are downstream from the library — no library-side coupling.
- **Stable lifecycle events.** Adding events later is fine; renaming or removing existing events is a breaking change. The initial cut should cover the canonical orchestrator lifecycle and resist temptation to instrument every internal call.
- **No log-level commitment.** A library that emits at INFO by default pollutes consumers' logs; one that emits at DEBUG is invisible. The right default is **no emission unless an observer is attached**, with a separate (orthogonal) `logging.getLogger("vigor.runtime")` for traditional Python logging that consumers configure as they would for any library.
- **Sampling and aggregation are observer concerns.** The library does not pre-sample, pre-aggregate, or pre-redact. Observers do. The library emits *every* lifecycle event; observers downsample as they need.
- **Audit vs operational telemetry.** Per `docs/strategy/deployment-and-ops.md`, audit (`AuditEvent.v1`) is a separate concern with different retention and integrity requirements. The `RuntimeObserver` is operational telemetry — sampled, lossy, advisory. Audit is filed separately under VIGOR-a171 (sibling backlog) and uses a different code path.

## Considered Options

- **Option A — `RuntimeObserver` `Protocol` with lifecycle methods + `on_event` escape hatch.** No hard `opentelemetry` dependency. Default observer is a no-op. Downstream packages implement the Protocol against their preferred sink.
- **Option B — Direct OpenTelemetry instrumentation in the runtime.** Add `from opentelemetry import trace` and `tracer.start_as_current_span(...)` calls at every lifecycle point. OpenTelemetry's no-op default tracer means consumers without OTel configured pay no overhead.
- **Option C — Abstract Base Class (`RuntimeObserver(abc.ABC)`).** Same lifecycle methods but as an ABC. Consumers must inherit.
- **Option D — Event bus / pub-sub (`Orchestrator.on(event_name, callback)`).** Event-emitter style. Callbacks register against named events.
- **Option E — Defer.** Document observability as a future enhancement; ship v1.0 without instrumentation hooks.

## Decision Outcome

Chosen: **Option A** — `RuntimeObserver` Protocol with lifecycle methods + `on_event` escape hatch.

The rationale: Protocol is the right Python primitive for opt-in seams (PEP 544 structural typing). It avoids forcing inheritance, avoids forcing import order, avoids forcing a base-class dependency. Downstream sinks (OpenTelemetry, Prometheus, Datadog, plain print-statements) implement the Protocol without importing anything from `vigor-core` or `vigor-runtime` beyond the Protocol definition itself. Default-off (no observer attached → no events emitted) preserves existing behavior.

The Protocol surface:

```python
from typing import Protocol, runtime_checkable
from vigor_core.schemas import (
    AdjudicationReport, ArtifactIR, CompileResult, ReviewReport, TaskSpec,
)


@runtime_checkable
class RuntimeObserver(Protocol):
    """Opt-in seam for emitting runtime lifecycle events.

    Implementations live downstream of vigor-runtime; the library never
    imports a specific telemetry SDK. Methods are best-effort: the
    runtime catches and discards exceptions raised inside any observer
    method to prevent observer bugs from breaking runs.
    """

    def on_run_start(self, run_id: str, task: TaskSpec) -> None: ...

    def on_iteration_start(self, run_id: str, iteration: int) -> None: ...

    def on_candidate_start(
        self, run_id: str, iteration: int, candidate_id: str
    ) -> None: ...

    def on_candidate_end(
        self,
        run_id: str,
        iteration: int,
        candidate_id: str,
        compile_result: CompileResult,
        reviews: list[ReviewReport],
        adjudication: AdjudicationReport,
    ) -> None: ...

    def on_iteration_end(
        self,
        run_id: str,
        iteration: int,
        candidate_count: int,
        accepted_candidate_id: str | None,
    ) -> None: ...

    def on_run_end(
        self,
        run_id: str,
        accepted: bool,
        stop_reason: str,
        selected_candidate_id: str | None,
    ) -> None: ...

    def on_event(self, name: str, attributes: dict[str, object]) -> None: ...
```

The `Orchestrator` accepts an optional `observer: RuntimeObserver | None = None` constructor argument. When `None` (the default), every method call is skipped via a fast-path check at each emission site (`if self._observer is not None: self._observer.on_iteration_start(...)`). When set, the method is called inside a `try / except Exception` block that logs the exception (to `logging.getLogger("vigor.runtime")` at WARNING) and continues — observer bugs cannot break runs.

The lifecycle is mapped to the orchestrator's existing seams:

- `on_run_start` — top of `Orchestrator.run`, after `archive.write_task` (`orchestrator.py:91`).
- `on_iteration_start` — top of the iteration loop, after the wall-clock budget check (`orchestrator.py:115-118`).
- `on_candidate_start` — start of `_evaluate_candidate` (`orchestrator.py:277-282`).
- `on_candidate_end` — end of `_evaluate_candidate`, just before the return (`orchestrator.py:354`). Three positions for the three early-return paths (validation failure, compile failure, success); all three call `on_candidate_end` with the appropriate result.
- `on_iteration_end` — bottom of the iteration body, alongside the new checkpoint write from ADR-0033.
- `on_run_end` — bottom of `Orchestrator.run`, just before the `return RunResult(...)` (`orchestrator.py:243-250`).
- `on_event` — open-ended; the runtime emits a few canonical events (e.g. `name="patch_applied"`, `name="export_failed"`) but the surface is intentionally extensible. Observers receive any event the runtime decides to emit.

The `vigor-agent` `AgentOrchestrator` accepts an `observer` kwarg in its constructor and threads it down to `Orchestrator`. The CLI exposes `--observer-factory <module:func>` (analogous to the existing factory-ref pattern from ADR-0014) that, when provided, calls the factory to construct an observer; without the flag, no observer is attached.

**Logging is orthogonal**. The runtime calls `logging.getLogger("vigor.runtime")` for traditional Python logging at INFO (lifecycle events) and DEBUG (per-call timing). Library users configure log handlers as they would for any library; the deployment-layer `vigor-server` configures structured JSON output. Logs and observer events are independent — observers see structured Python objects (Pydantic models); logs see formatted strings.

**Metrics are out of scope**. Per `docs/strategy/deployment-and-ops.md` §"Observability And Telemetry", Prometheus-shaped metrics are a `vigor-server` (deployment layer) concern. An observer implementation in the deployment layer aggregates the lifecycle events into metric counters / histograms; the library does not pre-aggregate.

### Alt-A: Protocol seam (chosen) vs direct OTel vs ABC vs event bus vs defer

| Alternative | Reason Rejected |
| --- | --- |
| Direct OpenTelemetry instrumentation | Forces an `opentelemetry` dependency on every consumer, even ones with no telemetry needs. ADR-0007 forbids SDK coupling in core packages. OpenTelemetry's "no-op default" makes the runtime overhead negligible, but the dependency-graph cost (import time, package install size) is real. Downstream consumers using a non-OTel sink (Datadog's auto-instrumentation, Honeycomb's beeline, plain logging) inherit unwanted code. The Protocol seam keeps OTel as one of many possible implementations, owned by a downstream package that opts in. |
| ABC (`class RuntimeObserver(abc.ABC)`) | Forces inheritance. Downstream packages must `from vigor_core.observability import RuntimeObserver` and inherit, creating a one-way dependency from the observer package to the core package. Protocol is structurally typed: an observer package can define its own type that happens to satisfy the Protocol without importing it (though importing for type-checking is convenient). Better composition, lower coupling. |
| Event bus / pub-sub style (`Orchestrator.on("iteration_start", callback)`) | String-keyed event names mean every callback site is unchecked at type-check time. A typo in the event name silently no-ops. The Protocol approach gets full type checking on lifecycle methods; the `on_event` escape hatch is the controlled exception for non-lifecycle events. |
| Defer to v2 | Library users today have no progress visibility into runs. A 60-minute run is a 60-minute black box. Even the simplest debugging workflow ("which iteration are we in?") requires hand-rolled archive-polling. The cost of shipping the seam is one Protocol class plus 6 emission sites in the orchestrator; the value is unblocking every downstream consumer. Deferring this is an ADR-shaped commitment to keep VIGOR runs opaque. |
| (Chosen) `RuntimeObserver` Protocol with lifecycle methods + `on_event` escape hatch | Smallest possible seam. Zero dependency cost for non-users. Type-checked lifecycle methods. Escape hatch for non-lifecycle events. Default-off preserves existing behavior. Composable with any downstream telemetry choice. |

### Alt-B: Event surface — comprehensive (instrument every internal call) vs lifecycle-only (chosen) vs minimal (run-level only)

| Alternative | Reason Rejected |
| --- | --- |
| Comprehensive — instrument every adapter call, every backend call, every archive write, every scoring computation | The Protocol becomes a moving target as internals change. Every refactor that adds a method becomes an observer-protocol bump. Worse, observers that depend on internal events are coupled to internal structure — refactoring the runtime breaks observer implementations. Lifecycle-level instrumentation is stable across internal refactors. |
| Minimal — only `on_run_start` and `on_run_end` | Insufficient for the canonical use case ("show me iteration progress"). Operators want per-iteration granularity; observer implementations want per-candidate granularity to map to OpenTelemetry spans. Run-level only forces every observer to do internal polling against the archive, which is the failure mode this ADR exists to fix. |
| (Chosen) Lifecycle-only — run / iteration / candidate boundaries plus `on_event` escape hatch | Covers the canonical use cases (progress, span hierarchy, per-candidate cost). Stable across internal refactors (the lifecycle is the contract; internal helpers are not). Open-ended via `on_event` for runtime-emitted non-lifecycle events. |

### Alt-C: Observer attachment — constructor arg (chosen) vs global default vs context-var

| Alternative | Reason Rejected |
| --- | --- |
| Global default (`vigor_runtime.set_default_observer(observer)`) | Action-at-a-distance. Two `Orchestrator`s in the same process get the same observer whether they want it or not. Composability disaster for the harness use case (Phase 6) where each task may want different observation. |
| Context-var (`with attached_observer(observer): await orchestrator.run(...)`) | Clean for the request-scoped case (one HTTP request, one observer) but more involved than the constructor arg for the canonical library case (one `Orchestrator`, one observer for life). The deployment-layer `vigor-server` can wrap the call site in a context-var if it wants per-request scoping; the library does not pre-bake that. |
| (Chosen) Constructor arg (`Orchestrator(adapter=..., backend=..., observer=...)`) | Same shape as every other extensibility point in the runtime (`tools=` ToolBackend, `archive=` RunArchive, `policy=` ScoringPolicy). Consistent. Per-orchestrator scoping. Trivial to test (pass a `MagicMock` as the observer in fixtures). |

## Consequences

### Positive

1. **Zero-dependency default.** Library users who never attach an observer pay nothing. No new packages installed, no import-time cost, no runtime overhead beyond the `if self._observer is not None` check at each emission site.
2. **Composable with any downstream sink.** A `vigor-observability-otel` package implements the Protocol against OpenTelemetry; a `vigor-observability-prometheus` package implements it against `prometheus_client`; a `vigor-server` deployment composes both. None of those choices touch the library.
3. **Type-checked lifecycle.** Pydantic models flow through the lifecycle methods (`TaskSpec`, `CompileResult`, `ReviewReport`, `AdjudicationReport`). Observer implementations get full type information, which is what enables clean OpenTelemetry span attribution and clean Prometheus label sets.
4. **Sibling-ADR consistency.** ADR-0028's `Usage` becomes a natural attribute on `on_candidate_end` (via the per-candidate usage extension to ADR-0028's Seeds). ADR-0033's iteration-checkpoint write fits naturally alongside `on_iteration_end`. ADR-0031's parallel batches still emit one `on_candidate_end` per candidate (concurrent emission; observers must be thread-safe — documented).
5. **Observer bugs don't break runs.** The `try / except Exception` wrapper around every observer call catches misbehaving observers and continues. Errors are logged but don't propagate.

### Negative

1. **Concurrent emission under parallel best-of-N.** ADR-0031's batched fanout means multiple `on_candidate_start` and `on_candidate_end` calls fire concurrently. Observer implementations must be thread-safe (or, more accurately, async-safe — they run inside the event loop). The Protocol documentation will say so explicitly. OpenTelemetry's tracer is async-safe; `prometheus_client` is thread-safe via its internal locks; naive observers (a custom one with shared mutable state) need to use `asyncio.Lock` or be careful. This is a documented constraint, not a runtime guarantee.
2. **No standardized attribute schema.** `on_event(name, attributes)` accepts any `dict[str, object]`. Observers expecting OpenTelemetry semantic conventions (HTTP, gen-ai, etc.) need to map VIGOR's events to those conventions themselves. The runtime does not commit to an attribute taxonomy beyond the lifecycle method signatures. The implementing builder will document the attribute keys for the canonical events the runtime emits (`patch_applied`, `export_failed`, etc.).
3. **Observer methods are sync, not async.** Calling `await` inside an observer method would require awaiting in the runtime, which means observers can block the event loop indefinitely. The Protocol declares sync methods to make this constraint visible. Observers that need to do async work (e.g. ship spans to a remote OTel collector) must spawn a background task themselves; the runtime will not. This is a known constraint of OpenTelemetry's Python tracer too — span recording is sync; export is async behind the scenes.
4. **No built-in trace-context propagation.** OpenTelemetry expects `traceparent` to flow into downstream calls (MCP servers, agent backends). The library does not propagate it — that is an observer-implementation concern. The deployment-and-ops sibling doc commits the `vigor-server` layer to header propagation; the library exposes the seam (`on_event` with `traceparent` as an attribute) but does not wire it.
5. **Open-ended `on_event` is a typing escape hatch.** Lifecycle-method calls are typed; `on_event(name, attributes)` is not. The cost is that misnamed events silently fall through. The mitigation is documentation: the runtime emits a small fixed set of events (`patch_applied`, `export_failed`, `cancelled`), and observers should pattern-match on `name` defensively.

### Neutral

1. The `logging.getLogger("vigor.runtime")` story is independent of the observer Protocol. Operators who want plain Python logging configure handlers as they would for any library; operators who want structured telemetry attach an observer; both can be active simultaneously.
2. The `runtime_checkable` decorator on the Protocol allows `isinstance(my_observer, RuntimeObserver)` checks at construction time; this is cheap (Python checks for the named methods) and useful for misconfiguration detection. The runtime does this once in the `Orchestrator` constructor and raises a clear error if the supplied object lacks any of the lifecycle methods.
3. The Protocol's location is `vigor_core.observability` (new module). Sibling code can import the Protocol type without importing `vigor-runtime`. This matters for downstream observer packages that may not need the runtime as a dep.

## References

| Source | Path / URL |
| --- | --- |
| Run-loop top (target site for `on_run_start`) | `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:88-100` |
| Iteration-loop top (target site for `on_iteration_start`) | `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:114-118` |
| `_evaluate_candidate` (target site for `on_candidate_start` and `on_candidate_end`) | `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:277-354` |
| Run-loop bottom (target site for `on_run_end`) | `packages/vigor-runtime/src/vigor_runtime/orchestrator.py:243-250` |
| Schema config (`_VigorBase`) for any new observer-related schemas | `packages/vigor-core/src/vigor_core/schemas.py:21-32` |
| ADR-0007 (SDK-agnostic core — forbids hard-importing OpenTelemetry) | `0007-sdk-agnostic-core-with-optional-agent-backends.md` |
| ADR-0010 (async core interfaces — pattern for protocol-shaped extension points) | `0010-async-core-interfaces.md` |
| ADR-0028 (cost ceilings — `Usage` as a `on_candidate_end` attribute) | `0028-cost-ceiling-enforcement.md` |
| ADR-0030 (library-first — telemetry sinks are deployment-layer choices) | `0030-library-first-deployment-posture.md` |
| ADR-0031 (parallel best-of-N — observer must be async-safe) | `0031-parallel-best-of-n-via-asyncio-gather.md` |
| ADR-0033 (checkpoint/resume — `on_iteration_end` fires alongside checkpoint write) | `0033-iteration-checkpoint-resume.md` |
| Strategic summary | `docs/strategy/runtime-completeness.md` §Q5 |
| Deployment observability commitment (sibling layer) | `docs/strategy/deployment-and-ops.md` §"Observability And Telemetry" |
| PEP 544 (Python `Protocol`) | https://peps.python.org/pep-0544/ |
| OpenTelemetry Python SDK | https://opentelemetry.io/docs/languages/python/ |
