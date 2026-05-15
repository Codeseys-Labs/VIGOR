# ADR-0016: Adopt Official MCP Servers And Security Posture For Reviewer Tools

Status: Proposed

Date: 2026-05-15

## Context

ADR-0004 commits VIGOR to reviewer ensembles spanning objective validators, learned scorers, model critics, and tool-backed inspectors. ADR-0010 pins the `ToolBackend` async ABC (`vigor-core/src/vigor_core/interfaces.py:136-143`) as the seam through which reviewers consume external tools, and the readiness work flagged "MCP integration policy" as the load-bearing 2026 follow-up because Anthropic's Claude Agent SDK and the Strands SDK both speak Model Context Protocol natively.

The 2026 MCP reviewer survey (`docs/research/2026-mcp-reviewer-survey.md`, verification cutoff 2026-05-14) maps the ecosystem onto VIGOR's four reviewer categories across photo, video, and CAD. Three load-bearing facts from the survey drive this ADR:

1. **No public 2026 MCP server wraps VIGOR's `ReviewReport` shape.** Every pick requires a thin coercion shim in the relevant `vigor-adapter-*` package (survey §4 "Native MCP vs wrap").
2. **No public MCP server exposes VideoScore2** or any post-2025 learned video scorer (survey §5). VIGOR must wrap one to keep the `learned_scorer` slot for video populated.
3. **CAD MCP servers ship destructive tools by default.** `neka-nat/freecad-mcp` exposes `execute_code` (arbitrary Python in the FreeCAD process) and `delete_object`; `jhacksman/OpenSCAD-MCP-Server` exposes `print_model` and `discover_printers`. Allowlist discipline is therefore not optional — it is the authorization layer (survey §8 "Security Posture").

VIGOR's first MCP-backed `ToolBackend` is being scoped under VIGOR-ca0f (sibling Phase-4 architect task). This ADR fixes which servers that backend is officially allowed to talk to, what "official" means as a maintenance contract, and the security posture every adapter must enforce when it instantiates one.

## Decision

VIGOR officially supports the following MCP servers per modality, with the security posture and support contract spelled out below. "Official" means tested in CI and pinned to a version range; anything else is "experimental — adapter-internal only."

### Officially supported servers (Phase A–C)

| Modality | Reviewer category | Server | Repo / canonical URL | Transport | Auth | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| Photo | model_critic | **Claude Vision (in-process)** | https://platform.claude.com/docs/en/docs/build-with-claude/vision | n/a (in-process) | Anthropic API key (from agent env) | A |
| Photo | model_critic + objective_metric (hybrid) | **`tan-yong-sheng/ai-vision-mcp`** | https://github.com/tan-yong-sheng/ai-vision-mcp | stdio | `GEMINI_API_KEY` or Vertex SA | A |
| Photo | model_critic (diversity hedge) | **`JochenYang/luma-mcp`** | https://github.com/JochenYang/luma-mcp | stdio | Per-provider env (`ZHIPU_API_KEY`, `SILICONFLOW_API_KEY`, `DASHSCOPE_API_KEY`) | A (optional) |
| CAD | tool_inspector + objective_metric | **`neka-nat/freecad-mcp`** (allowlist-restricted) | https://github.com/neka-nat/freecad-mcp | stdio (XML-RPC to FreeCAD addon, loopback only) | IP allowlist `127.0.0.1`; MCP layer is the authz point | B |
| CAD | tool_inspector | **`quellant/openscad-mcp`** | https://github.com/quellant/openscad-mcp | stdio | none (local-only) | B |
| CAD | objective_metric (mesh validity) | **In-adapter `trimesh` wrap** (custom, single-tool) | https://github.com/mikedh/trimesh | stdio | none (local-only) | B |
| Video | objective_metric | **`hlpsxc/video-quality-mcp`** | https://github.com/hlpsxc/video-quality-mcp | stdio | none (local-only) | C |
| Video | learned_scorer | **VIGOR-built VideoScore2 wrap** (`packages/vigor-tool-mcp-videoscore2`) | wraps https://huggingface.co/TIGER-Lab/VideoScore2 | http/sse | API key (`Authorization: Bearer …`); mTLS optional for VPC | C |

AIECF integration is **deferred to Phase D** (see survey §7) and explicitly out of scope here: no public MCP server exists, and the integration is gated on external repository access per `docs/adoption/aiecf.md`.

### Transport policy

1. **stdio is the default for local validators and local model critics.** Lower latency, no network exposure, simpler sandboxing.
2. **http/sse is used only for hosted critics that are GPU-resident or stateful**, where colocating the server with each agent over stdio would waste model-load cost. VideoScore2 is the canonical example.
3. **Mixed-transport servers** (e.g. `quellant/openscad-mcp` ships stdio + http + sse) MUST be configured to stdio in VIGOR's official `ToolBackend` registration.

### Security posture (mandatory for every official server)

1. **Default-deny tool surface.** The `ToolBackend` configuration MUST declare an explicit `tool_allowlist`. Tools not on the allowlist are unreachable from VIGOR. The list is closed by default, opened item-by-item.
2. **Mutators require capability grants.** ADR-0010 already pins `mutability: Literal["observer", "mutator"]` on `ToolManifest`. Every officially-supported server's allowlist MUST contain only `observer` tools unless the calling adapter holds an orchestrator-issued mutator capability for the run.
3. **Per-server allowlists** (the only ones officially blessed; anything else is experimental):

| Server | Officially-allowed tools | Explicitly-denied (rationale) |
| --- | --- | --- |
| `tan-yong-sheng/ai-vision-mcp` | `analyze_image`, `compare_images`, `detect_objects_in_image`, `audit_design`, `analyze_video` | none — surface is small and read-only |
| `JochenYang/luma-mcp` | `image_understand` | n/a (only one tool) |
| `neka-nat/freecad-mcp` | `run_fem_analysis`, `get_object`, `get_objects`, `get_view`, `get_parts_list` | `execute_code` (shell-equivalent), `create_object`, `edit_object`, `delete_object`, `insert_part_from_library` |
| `quellant/openscad-mcp` | `render_single`, `render_perspectives`, `compare_renders`, `export_model`, `validate_scad`, `analyze_model`, `get_libraries`, `check_openscad` | `create_model`, `update_model`, `delete_model` (model-management mutators) |
| `hlpsxc/video-quality-mcp` | `analyze_video_metadata`, `analyze_gop_structure`, `compare_quality_metrics`, `analyze_artifacts`, `summarize_transcode_comparison` | none — fully read-only |
| In-adapter `trimesh` wrap | `validate_mesh` | n/a (single-tool) |
| VIGOR VideoScore2 wrap | `score_video` | n/a (single-tool) |

4. **Default timeouts (wall-clock).** Adapter-level timeouts apply on top of any server-internal timeout:

| Reviewer category | Default per-call timeout | Rationale |
| --- | --- | --- |
| Objective validator (stdio, local) | 30 s | Trimesh, OpenSCAD analyze, ffmpeg/ffprobe metadata |
| Objective validator (heavy compute, e.g. PSNR/VMAF on long video) | 300 s | libvmaf is CPU-bound but bounded |
| Tool inspector — render/simulate | 600 s | OpenSCAD render, FreeCAD geometry ops |
| Tool inspector — FEM | 1800 s | CalculiX runs are job-scale; per-run wallclock budget enforced separately |
| Model critic (stdio + vendor egress) | 90 s | Single VLM round-trip including network |
| Learned scorer (http/sse, GPU) | 120 s | Single VideoScore2 inference |

Timeouts are enforced via `asyncio.wait_for` at the `ToolBackend.call_tool` boundary; cancellation propagates to the underlying MCP session per the existing async-cancellation contract. A timeout returns `ToolResult(status="timeout", …)` rather than raising — the adjudicator treats timeout as a failed reviewer signal, not an exception.

5. **Path sandboxing.** Every server that reads filesystem inputs (every officially-supported server here) MUST be invoked with paths inside the per-run archive root. The `ToolBackend` MUST reject path-traversal (`..`, absolute paths outside the archive root, symlinks crossing the boundary).

6. **Network isolation.** Servers without auth (`hlpsxc/video-quality-mcp`, `quellant/openscad-mcp`, `neka-nat/freecad-mcp`'s XML-RPC) MUST be local-only. The `neka-nat` XML-RPC bridge MUST bind to `127.0.0.1`; opening it to a network interface is forbidden.

7. **Vendor auth and rotation.** All API keys (Anthropic, Gemini/Vertex, GLM/Doubao/Hunyuan via `luma-mcp`, the VideoScore2 wrap's API key) live in agent env, never on disk in artifacts. Recommended rotation: monthly for vendor critic keys, per-environment for the VideoScore2 wrap.

### Definition of "official support"

A server is officially supported when, and only when, all five criteria hold:

1. **Pinned version range.** `pyproject.toml` (or wrap-Dockerfile) declares an upper-bounded version constraint. New majors require an ADR-0016 amendment.
2. **CI smoke test.** A nightly job in `.github/workflows/` boots the server, lists tools, calls one read-only tool, and asserts the response shape. Failure breaks the build.
3. **Response-schema validation.** The adapter shim wraps every response in a Pydantic model declared in the adapter package; unrecognized fields are dropped (not `extra="forbid"`, because vendor schemas drift), but required fields are validated strictly.
4. **Allowlist enforced at registration.** The adapter constructs the `ToolBackend` with the allowlist from §3 above. Tests verify denied tools are unreachable.
5. **License audit.** MIT or equivalent permissive only for vendored servers; vendor-hosted services (Claude, Gemini) follow vendor ToS.

Servers not meeting all five remain experimental and cannot be exposed via `vigor-runtime` reviewer ensembles.

### MCP server lifecycle

| Phase | Status field | Implication |
| --- | --- | --- |
| Tracked | survey-only | Listed in the survey; not used in code |
| Experimental | adapter-internal flag | Imported behind `experimental=True`; not exposed to ensembles |
| Officially supported | this ADR | All five definition criteria satisfied; CI smoke green |
| Deprecated | flagged in CI | Pinned version frozen; replacement ADR amendment in progress |
| Removed | gone from registry | Adapter no longer references the server |

Adding or removing an officially supported server requires an ADR amendment (a successor ADR superseding this one's relevant section), not a code-only change.

### Versioning policy for MCP server pins

1. Pin to the latest tag at adoption time, with a `>=X.Y,<X+1` constraint (caret-style).
2. Major bumps (across the upper bound) require: re-running the smoke test, re-confirming the allowlist (tools may have been renamed), and an ADR amendment.
3. For servers with no tagged releases, pin to a commit SHA and lift to a tag once one exists.

## Alternatives Considered

Alternatives are organized per decision point, with at least two real options each, and one rejection reason per alternative.

### Alt-A: Adapter contract — MCP via `ToolBackend` vs custom adapters per provider

| Alternative | Reason Rejected |
| --- | --- |
| Bypass MCP entirely; write a custom Python adapter per vendor (Gemini SDK, OpenSCAD subprocess, FreeCAD XML-RPC, ffmpeg shell) | Forfeits the standardized protocol that Claude Agent SDK and Strands already speak; multiplies maintenance N× by the number of providers; loses the per-tool capability surface that `tool_allowlist` keys off. |
| Sit MCP behind a VIGOR-internal "ReviewerProtocol" wrapper layer | Extra abstraction without payoff: every reviewer would still parse MCP responses; the layer would mostly forward calls and obscure the security posture (allowlists, transport choice) that needs to be visible at the `ToolBackend` boundary. |
| (Chosen) MCP servers consumed via existing `ToolBackend` ABC + adapter-side coercion shim | Reuses the ADR-0010 contract; keeps adapters owning the response coercion (which is where the response shape changes per vendor anyway); allowlists are enforceable at the `ToolBackend` registration site. |

### Alt-B: Photo critic — Claude Vision in-process vs MCP-only photo critics

| Alternative | Reason Rejected |
| --- | --- |
| Use only third-party MCP photo servers (`tan-yong-sheng/ai-vision-mcp`, `JochenYang/luma-mcp`); skip in-process Claude Vision | Survey §4 finds Claude Vision produces the highest critique quality and shares the agent's existing auth flow; excluding it forfeits "best second-opinion against itself" and forces Gemini-only or PRC-vendor hops for the primary critic. |
| Use OpenAI vision through `mario-andreschak/mcp-image-recognition` | Last upstream commit 2025-04-12 — pre-2026 baseline; survey flags as unmaintained. Adding an additional vendor lock-in axis (OpenAI key) without a maintained server is not justified vs Claude Vision in-process. |
| (Chosen) Claude Vision in-process as primary, `tan-yong-sheng/ai-vision-mcp` as second-opinion, `luma-mcp` as optional diversity hedge | Lowest integration cost for the primary; adds genuine ensemble diversity (different vendors, different aesthetic biases) without committing to two MCP hops on every critique. |

### Alt-C: Video learned scorer — wrap VideoScore2 vs adopt unverified third-party

| Alternative | Reason Rejected |
| --- | --- |
| Adopt a third-party MCP server that claims to expose VideoScore2 | None exist as of the 2026-05-14 cutoff (survey §5; GitHub search for `mcp + videoscore` returns zero). Adopting a non-existent server is not an option. |
| Skip the learned-scorer slot for video; use only `hlpsxc/video-quality-mcp` (PSNR/SSIM/VMAF) | PSNR/SSIM/VMAF are reference-based; learned scorers like VideoScore2 evaluate generative quality without a reference. ADR-0004's `learned_scorer` slot would be empty for the video modality, leaving a structural gap that the survey calls out as the highest-leverage MCP investment. |
| Wrap VideoScore2 via direct `transformers`/`torch` import inside the adapter (no MCP) | Pulls 14 GB of VRAM-class dependencies into every adapter process; cannot be shared across runs; precludes hosting on a separate GPU box. |
| (Chosen) Build a dedicated MCP wrap of VideoScore2 over http/sse, hosted on a shared GPU service | Allows pooling GPU across runs; matches transport policy (Decision §"Transport policy"); produces a published artifact that other Claude/Strands agents can consume. Wrap effort estimated at 250–400 LOC + Dockerfile + GPU deployment per survey §5. |

### Alt-D: CAD FEM access — `neka-nat/freecad-mcp` allowlisted vs no FEM in v0

| Alternative | Reason Rejected |
| --- | --- |
| Defer FEM to a later ADR; ship CAD without it | Survey §6 finds `neka-nat/freecad-mcp` is the only 2026 MCP path to FEM. Deferring leaves the CAD adapter without objective scoring for parametric workflows — exactly the case where adjudicators need a numeric anchor. |
| Adopt `contextform/freecad-mcp` instead | License is unspecified (per survey table); blocks vendoring. No FEM coverage. |
| Adopt `spkane/freecad-addon-robust-mcp-server` | Active and starred but README depth not verified for FEM coverage; survey downgrades it to "alternative if `neka-nat` is unsuitable" rather than first pick. |
| (Chosen) `neka-nat/freecad-mcp` with strict allowlist (`run_fem_analysis` + read-only getters); explicitly deny `execute_code`, `create_object`, `edit_object`, `delete_object` | The only MIT-licensed, FEM-capable path. Allowlist discipline neutralizes the destructive surface — `execute_code` is shell-equivalent and is treated as such. The risk profile after allowlist matches the other read-only servers. |

### Alt-E: Mesh validity — third-party MCP server vs in-adapter `trimesh` wrap

| Alternative | Reason Rejected |
| --- | --- |
| Adopt a third-party MCP server for mesh validity | None exist (survey §6) — manifold/watertight/self-intersection checks are not exposed by any 2026 CAD MCP server. |
| Defer mesh validity to a later phase | The existing `vigor-adapter-cad` reviewer cannot do objective scoring without it; the cost of a 80–150 LOC trimesh wrap is far below the cost of leaving the slot empty. |
| (Chosen) In-adapter `trimesh` wrap exposed as a single-tool stdio MCP server inside `vigor-adapter-cad` | Trivial cost, no new external dependency on an unmaintained third party, full ownership of the response schema. |

### Alt-F: Default transport — stdio everywhere vs hybrid stdio/http vs http everywhere

| Alternative | Reason Rejected |
| --- | --- |
| stdio for everything, including hosted GPU services | Forces VideoScore2 (14 GB VRAM, expensive load) to run as a per-agent subprocess; impossible to share GPU; GPU-bound services can't be colocated with agent processes. |
| http/sse for everything, including local validators | Adds network dependency for trivial CPU validators; complicates local development; introduces auth surface for tools that don't need it. |
| (Chosen) stdio default; http/sse only for hosted/GPU/stateful servers (currently VideoScore2) | Matches each reviewer category to its real cost profile; survey-aligned. |

### Alt-G: Default tool surface — opt-in allowlist vs opt-out denylist

| Alternative | Reason Rejected |
| --- | --- |
| Default-allow all tools the server exposes; maintain a denylist of known-dangerous tools | New tool added by upstream ⇒ instantly reachable from VIGOR with no review. `neka-nat/freecad-mcp`'s `execute_code` is the canonical "dangerous tool that exists today"; future upstream tools are unknown. Denylist fails closed only if the maintainer remembers to update it after every upstream release. |
| (Chosen) Default-deny; explicit allowlist per server, declared at `ToolBackend` registration, asserted in tests | Closed by default. New upstream tools require explicit opt-in via ADR amendment. The five-criteria support contract enforces this. |

### Alt-H: AIECF — pre-spec the wrap now vs defer to Phase D

| Alternative | Reason Rejected |
| --- | --- |
| Pre-spec the AIECF MCP wrap and codify it in this ADR | Per `docs/adoption/aiecf.md` and `docs/readiness/implementation-readiness.md`, AIECF integration is blocked on access to a concrete repository. Pre-specifying without a repo to verify against produces speculation, not architecture. |
| (Chosen) Treat AIECF as Phase D; reference the survey's wrap-cost analysis but do not bless any AIECF server in this ADR | Avoids retrospective rationalization once the repo arrives; future ADR can amend §"Officially supported servers" with concrete details. |

## Consequences

### Positive

1. The supported reviewer surface is named, versioned, and CI-verified rather than implicit.
2. Allowlist discipline becomes the single authorization layer for MCP-backed reviewers, matching ADR-0010's mutability rule and giving every adapter a clear template to copy.
3. The transport split (stdio for local, http/sse for hosted) gives operators a predictable network/security profile per server.
4. Building the VideoScore2 MCP wrap as VIGOR-native infrastructure (rather than depending on an unmaintained third party) makes it a publishable artifact that other Claude / Strands agents can consume.
5. The "official support" five-criteria contract makes deprecation/replacement a structured event (ADR amendment), not a silent code change.

### Negative

1. Every officially-supported server adds a CI smoke job. CI runtime grows with each adoption; flaky vendor APIs (especially `JochenYang/luma-mcp`'s PRC providers) will need retry/skip logic that can mask real outages.
2. The VideoScore2 wrap requires GPU hosting that VIGOR does not currently operate. Phase C is gated on that infrastructure; until it exists, VIGOR's `learned_scorer` slot for video stays empty and the adjudicator must tolerate a missing reviewer in that slot.
3. Allowlist-by-default means new useful upstream tools are unreachable until an ADR amendment lands. This is intentional but adds latency to legitimate expansions.
4. The `neka-nat/freecad-mcp` allowlist depends on upstream not renaming `execute_code` — if a future version renames the tool, the denylist string-match in tests will silently pass while leaving the dangerous surface exposed. The smoke-test suite must therefore enumerate the *full* upstream tool list and assert that the allowlist-complement matches.
5. Survey §"Open Questions" notes per-server rate-limit characteristics under load are not measured. The default timeouts above are educated guesses; production runs may need tuning.
6. Three of the photo picks (`tan-yong-sheng/ai-vision-mcp` v0.0.7, `JochenYang/luma-mcp` PRC providers, `mario-andreschak/mcp-image-recognition` if ever revisited) are in early or pre-2026 maintenance state. Adopting them as official means accepting upstream maintenance risk we cannot directly mitigate.

### Neutral

1. AIECF integration remains blocked on external dependency outside this ADR's scope.
2. Closed-source vendor MCP servers (Anthropic-internal, OpenAI-internal) remain out of scope per ADR-0004 transparency principles; they may outperform the picks here but are not auditable.

## Implementation Notes

1. The first MCP-backed `ToolBackend` (currently scoped under VIGOR-ca0f) lands in a new package `vigor-tool-mcp` (or equivalent — naming TBD by that task) that depends only on `vigor-core`. Adapters register it.
2. Each adapter that consumes an MCP server owns a Pydantic response model for that server in the adapter package, plus a coercion function from server-response → `ReviewReport`.
3. The VideoScore2 wrap lives under `packages/vigor-tool-mcp-videoscore2` (final naming subject to VIGOR-ca0f's package layout decision); it is not part of `vigor-adapter-video-manim` so it can be GPU-hosted independently.
4. CI smoke tests live in `.github/workflows/mcp-smoke.yml` (new) and run nightly + on PRs that touch `packages/vigor-tool-mcp*` or any adapter's MCP-coercion shim.
5. Transition to `Status: Accepted` after VIGOR-ca0f's host implementation lands and the smoke test for at least one Phase A server (`tan-yong-sheng/ai-vision-mcp`) is green.

## Citations

| Source | URL |
| --- | --- |
| 2026 MCP reviewer survey (this project) | `../research/2026-mcp-reviewer-survey.md` |
| ADR-0004 (reviewer ensemble) | `0004-reviewer-ensemble-and-adjudicator.md` |
| ADR-0010 (async core interfaces) | `0010-async-core-interfaces.md` |
| Model Context Protocol spec | https://modelcontextprotocol.io/specification |
| Official MCP servers reference | https://github.com/modelcontextprotocol/servers |
| Claude Vision API | https://platform.claude.com/docs/en/docs/build-with-claude/vision |
| `tan-yong-sheng/ai-vision-mcp` | https://github.com/tan-yong-sheng/ai-vision-mcp |
| `JochenYang/luma-mcp` | https://github.com/JochenYang/luma-mcp |
| `neka-nat/freecad-mcp` | https://github.com/neka-nat/freecad-mcp |
| `quellant/openscad-mcp` | https://github.com/quellant/openscad-mcp |
| `hlpsxc/video-quality-mcp` | https://github.com/hlpsxc/video-quality-mcp |
| `trimesh` (mesh validity library) | https://github.com/mikedh/trimesh |
| TIGER-Lab VideoScore2 (model card) | https://huggingface.co/TIGER-Lab/VideoScore2 |
| TIGER-AI-Lab VideoScore2 eval tooling | https://github.com/TIGER-AI-Lab/VideoScore2/tree/main/eval |
| VideoScore2 paper | https://arxiv.org/abs/2509.22799 |
| AIECF adoption assumptions (this project) | `../adoption/aiecf.md` |
| Anthropic Building Effective Agents | https://www.anthropic.com/engineering/building-effective-agents |
