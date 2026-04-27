# Security Policy

## Scope

VIGOR is an early-stage research framework. It has no authenticated endpoints and ships no binaries, but it executes user-supplied agent/tool code and writes artifacts to disk. Security work focuses on:

1. Path containment for the run archive and adapter output.
2. Untrusted input handling in compilers, renderers, and reviewers.
3. Supply-chain hygiene for optional agent SDKs.

## Reporting A Vulnerability

Please use GitHub private vulnerability reporting on this repository. Do not open public issues for security-sensitive findings.

When reporting, include:

1. The VIGOR package and version you reproduced against.
2. A minimal reproduction (ideally a unit test).
3. The expected vs observed behavior.
4. Any suggested mitigation.

We aim to acknowledge within 3 business days and to ship a fix or mitigation plan within 30 days.

## Supported Versions

VIGOR is pre-1.0. Only the latest tagged minor line on `main` is supported.

## Hardening Expectations For Adapters And Backends

1. Adapters MUST treat IR bodies, artifact URIs, and reference URIs as untrusted input. Use `vigor_core.util.safe_relative` and `RunArchive.write_raw`'s containment check rather than direct `Path` operations.
2. Adapters SHOULD run blocking compute (Pillow, NumPy, CAD kernels, simulators) inside `asyncio.to_thread`.
3. Backends MUST NOT write artifact state directly; always return data through the declared schemas.
4. Optional dependencies (`strands-agents`, `claude-agent-sdk`) MUST be imported lazily so users can install the runtime without these extras.
