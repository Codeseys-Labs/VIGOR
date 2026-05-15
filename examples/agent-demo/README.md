# agent-demo

End-to-end demo of one configurable VIGOR agent serving three modalities.
The example exercises the full Phase 6 wiring: a single `AgentConfig`
loads three adapters (photo editing, Manim video, OpenSCAD CAD), an
echo agent backend, and one MCP server. Tasks are dispatched to the
matching adapter via `routing.strategy: modality_match`.

## Layout

```
agent-demo/
  agent.yaml                # AgentConfig declaring 3 adapters + 1 MCP server
  assets/sample.jpg         # tiny synthetic JPEG used by the photo task
  tasks/
    photo.json              # photo_editing TaskSpec
    video.json              # video_manim TaskSpec
    cad.json                # cad_openscad TaskSpec
  src/agent_demo/
    factories.py            # adapter + backend factories referenced by agent.yaml
```

## Run it

```bash
# from the workspace root
uv run vigor-agent run --config examples/agent-demo/agent.yaml \
  examples/agent-demo/tasks/photo.json

uv run vigor-agent run --config examples/agent-demo/agent.yaml \
  examples/agent-demo/tasks/video.json

uv run vigor-agent run --config examples/agent-demo/agent.yaml \
  examples/agent-demo/tasks/cad.json
```

Each command produces a run directory under `examples/agent-demo/runs/`
containing the task spec, adapter manifest, candidate IR + compile
result, frontier, adjudication, and final export bundle.

## What's deterministic, what's faked, and why

The demo is meant to run on a clean checkout with **no external CLIs
installed**. Two adapters need a small assist for that:

- **Echo backend** (`make_demo_echo_backend`) — synthesizes a per-modality
  IR body from the task goal so the orchestrator's generate path
  doesn't need an LLM.
- **Manim adapter** (`make_manim_adapter`) — Manim normally shells out
  to the `manim` CLI. The demo injects a deterministic fake `Runner`
  that writes a placeholder MP4 to the path the adapter expects
  (`expected_output_path(...)`), so the *adapter* code path runs
  unchanged but no untrusted Python is ever executed and no `manim`
  install is required. Operators with a real Manim install can swap
  the factory.

Photo and CAD adapters are run **as-is**: the photo task uses the
shipped sample JPEG, the CAD adapter generates real OpenSCAD source.

## MCP wiring

`agent.yaml` declares one stdio MCP server that points at
`@modelcontextprotocol/server-filesystem`. Operators with that
package on `npx` get a working filesystem tool surface; tests
substitute a fake `SessionOpener` (see
`packages/vigor-agent/tests/test_e2e_demo.py`) so CI never spawns a
subprocess. This mirrors the production injection point —
`MCPToolBackend(specs, session_opener=...)` — and is the recommended
pattern for testing any agent that depends on MCP servers.

## Integration test

`packages/vigor-agent/tests/test_e2e_demo.py` boots this same
`agent.yaml` with a fake `SessionOpener` and runs all three modalities
under `pytest.mark.parametrize`. It is the canonical "this demo still
works" smoke test.

```bash
uv run pytest packages/vigor-agent/tests/test_e2e_demo.py -v
```
