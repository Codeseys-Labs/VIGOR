# ADR-0008: Use Python 3.11+ As The Reference VIGOR Language

Status: Accepted

Date: 2026-04-26

## Context

The readiness assessment in `docs/readiness/implementation-readiness.md` flagged cross-cutting prerequisite C1: the language choice was undecided. Every interface sketch in the VIGOR docs is written in Python (framework doc, ADR-0007, comparison doc). The primary libraries the first adapters need — rawpy, OpenCV, Pillow, Manim, FreeCAD, CadQuery, ffmpeg-python, VideoScore2 inference, Pydantic, Strands Agents, the Claude Agent SDK — all have first-class Python support and some of them are Python-only.

The Strands TypeScript SDK and the Claude Agent SDK also offer TypeScript bindings, but those audiences are client-side or web UI use cases, not VIGOR's primary adapter surface.

## Decision

VIGOR v0 is written in Python 3.11 or newer.

1. All core, runtime, backend, and adapter packages target Python 3.11+.
2. All schema objects use Pydantic v2 with strict mode.
3. All framework-level concurrency uses `asyncio`.
4. TypeScript bindings are out of scope for v0. They are not ruled out for v1 and later, but they must not drive the v0 architecture.

Python 3.11 is chosen because it is broadly supported, offers `tomllib` in the standard library, offers performance improvements over 3.10, and is the minimum version required by several modern tools in the stack.

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| Python 3.10 | 3.10 is widely available, but 3.11 gives measurable performance gains and `tomllib` without new dependencies. |
| TypeScript-first | Strong for web/browser cases, but photo, CAD, Manim, and ML scorers are Python-native. |
| Dual Python + TS from day one | Doubles the surface to maintain and blocks delivering a single working adapter. |
| Rust core with Python bindings | Good long-term idea for performance-critical paths, but not needed for v0 correctness. |

## Consequences

Positive:

1. Every downstream project named in ADR-0007 can import VIGOR directly.
2. No duplicated schemas across languages.
3. Straightforward integration with Pydantic, Strands, Claude Agent SDK, rawpy, OpenCV, Pillow, and Manim.

Negative:

1. Browser-only use cases need an additional transport such as HTTP or WebSocket.
2. TypeScript bindings will need to be added separately later.
3. Users without a Python environment need a way to invoke VIGOR through a CLI or service.

## Implementation Notes

1. Each package declares `requires-python = ">=3.11"` in its `pyproject.toml`.
2. Each package depends on Pydantic v2.
3. Each package exposes an async API.
4. Projects that need sync entry points should offer thin sync wrappers, not the other way around.

## Citations

| Source | URL |
| --- | --- |
| Python 3.11 release notes | https://docs.python.org/3/whatsnew/3.11.html |
| Pydantic documentation | https://docs.pydantic.dev/latest/ |
| PEP 621 pyproject.toml metadata | https://packaging.python.org/en/latest/specifications/pyproject-toml/ |
| Strands Agents Python SDK | https://strandsagents.com/ |
| Claude Agent SDK Python reference | https://docs.anthropic.com/en/api/agent-sdk/python |
