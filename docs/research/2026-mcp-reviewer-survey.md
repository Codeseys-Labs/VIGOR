# 2026 MCP Reviewer Server Survey

This document surveys the 2026 Model Context Protocol (MCP) server ecosystem for VIGOR's reviewer architecture (ADR-0004). It maps available servers onto VIGOR's reviewer categories — objective validators, learned scorers, model critics, tool-backed inspectors — across three modalities (photo, video, CAD) and the AIECF educational-video integration ask. The doc feeds ADR-0016 (VIGOR-ff1c).

Verification cutoff: **2026-05-14**. Every recommendation cites a canonical URL.

## Executive Summary

The 2026 MCP ecosystem is mature for general-purpose tool servers but **uneven for the typed reviewer contract VIGOR needs**. Strongest fit is CAD: `neka-nat/freecad-mcp` and `quellant/openscad-mcp` cover parametric, FEM, and rendering surfaces with active maintenance. Photo critique has multiple credible third-party MCP servers (`tan-yong-sheng/ai-vision-mcp`, `JochenYang/luma-mcp`, `GongRzhe/opencv-mcp-server`), but none produces the structured `ReviewReport` shape natively — every photo pick requires a thin wrapping reviewer in `vigor-adapter-photo` to coerce free-text or per-tool JSON into `scores` + `findings`. Video is the weakest modality: the only purpose-built quality MCP server is `hlpsxc/video-quality-mcp` (PSNR/SSIM/VMAF, no learned scorers); **no public 2026 MCP server exposes VideoScore2 or any learned video scorer**, so VIGOR must wrap VideoScore2 itself. AIECF has no MCP server at all, so the integration is a wrap-cost question, not a survey question.

Top-3 picks per modality and the AIECF wrap path are summarized in §9. Native MCP exposure exists for FreeCAD, OpenSCAD, OpenCV, and FFmpeg-backed video tooling; **all VLM aesthetic critique, all video learned scoring, and all AIECF integration require wrapping work**.

## Methodology

**Sources surveyed**:

| Source | URL | Used For |
| --- | --- | --- |
| Official MCP servers repo | https://github.com/modelcontextprotocol/servers | Reference servers; confirmed none cover photo/video/CAD review |
| MCP examples page | https://modelcontextprotocol.io/examples | Cross-check on reference set |
| GitHub repo search | `github.com/search?q=mcp-server+<modality>` | Third-party server discovery |
| Vendor docs | Anthropic, Google AI Studio, FreeCAD, OpenSCAD, CadQuery | Tool surface / auth verification |
| TIGER-Lab VideoScore2 | https://huggingface.co/TIGER-Lab/VideoScore2 | Learned scorer wrap-cost analysis |

**Recency cutoff**: Today is 2026-05-14. Repos with no commits in the trailing 18 months are flagged as "pre-2026 baseline" and de-prioritized. The VideoScore2 paper (https://arxiv.org/abs/2509.22799) is the most recent learned-scorer reference.

**Fitness criteria** (applied uniformly):
1. **Tool-surface clarity** — the server names its tools and documents inputs/outputs.
2. **Transport** — stdio for local validators, http/sse for hosted critics.
3. **Auth model** — explicit (env var, OAuth, mTLS) or explicit "none + local-only".
4. **Repo liveness** — commits in the last 12 months; no archived-by-owner status.
5. **Output mappability** — can the response be coerced into `ReviewReport.scores`, `ReviewReport.findings`, `recommended_action`?
6. **Allowlist viability** — can dangerous tools (`execute_code`, `delete_object`, `print_model`) be denied while keeping the read/score surface?

**Coverage gaps acknowledged up front**:
- Smithery.ai listings were not exhaustively crawled; for any specific pick, a smithery cross-check before adoption is recommended but does not change the conclusions below.
- Closed-source vendor MCP servers (Anthropic-internal, OpenAI-internal) are not enumerated — VIGOR's adapter contract should prefer open servers it can audit.
- The ARXiv preprint pipeline for newer learned scorers (post-VideoScore2) was not deeply searched; if the lead has a candidate, treat the wrap-cost section as a template.

## VIGOR Reviewer Contract Recap

ADR-0004 splits reviewers into five categories. Below maps each to the MCP transport / tool shape that fits, anchoring the per-modality tables.

| Reviewer Category (ADR-0004) | Typical MCP Transport | Required Tool Shape | Notes |
| --- | --- | --- | --- |
| Objective validators | stdio (local) | Pure functions: in → metric. No side effects. | Examples: histogram stats (`HistogramCritic`), mesh manifold check, PSNR. Maps cleanly to `reviewer_type: objective_metric`. |
| Learned scorers | http/sse (hosted, GPU) | Single tool: `score(artifact)` → `{dim: float, rationale: str}`. | Examples: VideoScore2, aesthetic models. Stateful loading is expensive; hosted is preferred. Maps to `reviewer_type: learned_scorer`. |
| Model critics | http/sse (vendor-hosted) or stdio (proxy) | Tool: `critique(image, prompt)` → text or JSON. | Claude/Gemini/GLM-4.6V wrappers. Maps to `reviewer_type: model_critic`. Output is free-text by default; coerce client-side. |
| Tool-backed inspectors | stdio (local subprocess) | Multi-tool surface: render, simulate, validate. | Playwright, FreeCAD, OpenSCAD, ffmpeg. Maps to `reviewer_type: tool_inspector`. Tool allowlists are critical because these surfaces include destructive operations. |
| Humans | n/a | Out of scope for this survey. | |

Every recommendation in §4–§7 must slot into one of the first four rows.

## Photo / VLM Aesthetic Critic Survey

VIGOR's existing `HistogramCritic` (`packages/vigor-adapter-photo/src/vigor_adapter_photo/reviewers.py`) demonstrates the objective-metric end of the spectrum. The MCP gap is subjective/semantic critique — i.e. model critics over images. Below are the credible 2026 candidates.

| Server | Repo / URL | Transport | Auth | tool_allowlist coverage | Native MCP? | Wrap effort if not | Fitness for VIGOR | Risks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Claude Vision (direct API, no MCP) | https://platform.claude.com/docs/en/docs/build-with-claude/vision | n/a (in-process) | API key (Anthropic) | n/a — agent calls Claude directly | No | Zero — VIGOR is already a Claude agent | **High** (model_critic) — best critique quality, structured output via prompt | Vendor lock-in; cost per critique; rate-limit shared with main agent |
| `tan-yong-sheng/ai-vision-mcp` | https://github.com/tan-yong-sheng/ai-vision-mcp | stdio | `GEMINI_API_KEY` or Vertex SA | 5 tools: `analyze_image`, `compare_images`, `detect_objects_in_image`, `audit_design`, `analyze_video` — `audit_design` already returns structured (WCAG, palette, edge complexity) | Yes | Low — `audit_design` output → `scores`/`findings` is a 30–80 line shim | **High** (model_critic + objective_metric hybrid) | Gemini-only backend; no Anthropic/OpenAI; v0.0.7 is early |
| `JochenYang/luma-mcp` | https://github.com/JochenYang/luma-mcp | stdio | Per-provider env (`ZHIPU_API_KEY`, `SILICONFLOW_API_KEY`, `DASHSCOPE_API_KEY`, etc.) | Single tool: `image_understand` — 5 model providers (GLM-4.6V, DeepSeek-OCR, Qwen3-VL-Flash, Doubao-Seed-1.6, Hunyuan-Vision-1.5) | Yes | Medium — output is plain text; structured prompt + JSON parse needed | **Medium** (model_critic) — useful for OSS/multi-vendor diversity | Optimized for screenshots/OCR rather than aesthetic critique; geographic auth dependencies (cn vendors) |
| `GongRzhe/opencv-mcp-server` | https://github.com/GongRzhe/opencv-mcp-server | stdio | None (local) | Wide: `get_image_stats_tool`, `detect_edges_tool`, `apply_threshold_tool`, `detect_features_tool`, `detect_objects_tool` (YOLOv3) | Yes | Low — already structured numeric output | **Medium** (objective_metric) — duplicates `HistogramCritic` for histogram stats; adds Canny/Sobel/SIFT | **Archived 2026-03-03 by owner — read-only, no fixes**. Use only if vendoring is acceptable. |
| `mario-andreschak/mcp-image-recognition` | https://github.com/mario-andreschak/mcp-image-recognition | stdio | OpenAI / Anthropic API keys | Single critique tool over OpenAI/Anthropic vision | Yes | Low | Medium (model_critic) — fewer features than `tan-yong-sheng/ai-vision-mcp` | Last updated 2025-04 — pre-2026 baseline; verify before adoption |
| `merterbak/Grok-MCP` | https://github.com/merterbak/Grok-MCP | stdio | xAI API key | Vision + image/video generation + agentic tools | Yes | Low–Medium | Medium (model_critic) — Grok-specific bias/style worth measuring against Claude | xAI rate limits; vendor lock-in |

### Top-3 picks (photo)

1. **Claude Vision (in-process, no MCP)** — VIGOR is already a Claude agent. Calling the messages API with image content directly avoids an MCP hop, halves latency, and produces the same critique quality. Use this as the primary `model_critic` reviewer for `vigor-adapter-photo`. *Rationale:* lowest integration cost, highest critique quality, and the agent's existing auth flows.
2. **`tan-yong-sheng/ai-vision-mcp`** — best second-opinion critic. `audit_design` returns WCAG contrast and palette metrics that the Claude critic does not produce numerically; combine for ensemble diversity. *Rationale:* covers the design-audit niche with structured output that maps cleanly to `Finding`.
3. **`JochenYang/luma-mcp`** — diversity hedge against Anthropic/Google outages or bias. Wrap output with a JSON-schema-coerced prompt. *Rationale:* OSS-friendly; only viable multi-vendor MCP server in the photo space as of 2026-05.

### Native MCP vs wrap

Claude Vision is **not an MCP server**; it is an in-process call from the agent. None of the third-party servers map their output to VIGOR's `ReviewReport` shape — every pick needs a 30–100 line adapter shim in `vigor-adapter-photo` that takes the MCP response and returns a `ReviewReport(reviewer_type='model_critic', scores=..., findings=..., recommended_action=...)`.

## Video Quality Survey (VideoScore2 + alternatives)

The video-MCP space in 2026 is dominated by FFmpeg wrappers for editing rather than scoring. The only purpose-built quality-scoring server found is `hlpsxc/video-quality-mcp`. **No public MCP server exposes VideoScore2** — confirmed by GitHub search returning zero results for `mcp + videoscore`.

| Server | Repo / URL | Transport | Auth | tool_allowlist coverage | Native MCP? | Wrap effort if not | Fitness for VIGOR | Risks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `hlpsxc/video-quality-mcp` | https://github.com/hlpsxc/video-quality-mcp | stdio | None (local) | 5 tools: `analyze_video_metadata`, `analyze_gop_structure`, `compare_quality_metrics` (PSNR Y/U/V, SSIM, VMAF), `analyze_artifacts` (blur/blocking/ringing/banding), `summarize_transcode_comparison` | Yes | Low — already JSON-structured | **High** (objective_metric) — explicit per-channel PSNR + VMAF deltas → `Finding` per artifact | No license file declared — verify before vendoring; explicitly "no deep learning" so cannot replace VideoScore2 |
| `KyaniteLabs/mcp-video` | https://github.com/KyaniteLabs/mcp-video | stdio | None (local) | 87 FFmpeg + Hyperframes tools — broad editing/probing surface | Yes | Medium — needs allowlist to deny mutator tools | **Medium** (tool_inspector) — useful for ffprobe-style metadata, **not** scoring | Wide allowlist surface; many mutator tools that must be denied |
| `video-creator/ffmpeg-mcp` | https://github.com/video-creator/ffmpeg-mcp | stdio | None (local) | FFmpeg command-line wrapper | Yes | Medium | Low–Medium (tool_inspector) — primarily editing-oriented | Pre-2026 baseline (last updated May 2025); verify liveness |
| `misbahsy/video-audio-mcp` | https://github.com/misbahsy/video-audio-mcp | stdio | None (local) | Basic FFmpeg-powered video/audio editing | Yes | Medium | Low (tool_inspector) — editing not scoring | Pre-2026 baseline |
| **VideoScore2 (no MCP server exists)** | https://huggingface.co/TIGER-Lab/VideoScore2 | n/a | n/a | n/a — must be wrapped | **No** | **High** — see "Wrap path" below | **Critical** (learned_scorer) — the canonical 2026 video learned scorer per VIGOR research synthesis | Wrapping is required; GPU-bound |

### Top-1 + Wrap path

1. **`hlpsxc/video-quality-mcp`** for objective video quality (PSNR/SSIM/VMAF + artifact heuristics). Slots into `reviewer_type: objective_metric`. *Rationale:* the only 2026 server purpose-built for video quality scoring.
2. **Wrap VideoScore2 as an MCP server** for the learned-scorer slot. No public MCP server exists for VideoScore2 as of the cutoff. The wrap path:

#### VideoScore2 MCP wrap specification

| Field | Value |
| --- | --- |
| Entry point | `TIGER-Lab/VideoScore2` Hugging Face model card; eval tooling at https://github.com/TIGER-AI-Lab/VideoScore2/tree/main/eval |
| Dependencies | `transformers`, `torch` (GPU recommended), `decord` or `pyav` for frame loading; ~14 GB VRAM at fp16 per the model card class |
| Tool exposed | `score_video(video_path: str, prompt: str) -> {visual_quality: float, alignment: float, common_sense: float, rationale: str}` |
| Transport | **http/sse** — VideoScore2 is GPU-bound and stateful (model load is expensive); colocating it with each agent over stdio is wasteful. Run as a hosted MCP service; agents connect over http. |
| Auth | API key in `Authorization: Bearer` header. mTLS optional for inter-VPC. **Required** because the inference cost is non-trivial. |
| Output schema | Three score floats in [0,1], one rationale string per axis. Map directly: `ReviewReport.scores = {visual_quality, alignment, common_sense}`, `findings` derived per axis where score < threshold, `reviewer_type='learned_scorer'`. |
| Wrap effort | ~250–400 LOC Python (FastAPI/MCP-Python SDK) + Dockerfile + a Hugging Face-Spaces or self-hosted GPU deployment. Existing eval tooling at https://github.com/TIGER-AI-Lab/VideoScore2/tree/main/eval is a starting point but not an MCP server. |
| Allowlist | Single tool `score_video` — no destructive surface, trivial allowlist. |
| Rate-limit | Server-side throttle by candidate-id and by run-id; recommend per-run cap to keep budget enforceable. |
| Sanitization | Validate `video_path` against a per-run sandbox; reject `..`/absolute paths outside the run-archive root. |

This wrap is the highest-leverage MCP investment in the survey because (a) VideoScore2 is the only canonical multi-axis video scorer per the VIGOR research synthesis (`docs/research/vigor-research-synthesis.md`), (b) no equivalent MCP server exists publicly, and (c) the wrap unblocks the `vigor-adapter-video-manim` and future `vigor-adapter-video-aiecf` review pipelines simultaneously.

## CAD Mesh / FEM Validator Survey

CAD is the strongest modality for MCP coverage in 2026 — multiple actively maintained servers exist for FreeCAD, OpenSCAD, and parametric workflows. CadQuery has no MCP wrapper as of the cutoff (canonical repo at https://github.com/CadQuery/cadquery, latest release 2.7.0 on 2026-02-13, no MCP integration referenced).

| Server | Repo / URL | Transport | Auth | tool_allowlist coverage | Native MCP? | Wrap effort if not | Fitness for VIGOR | Risks |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `neka-nat/freecad-mcp` | https://github.com/neka-nat/freecad-mcp | stdio (over local RPC) | IP allowlist (default `127.0.0.1`); **no per-tool auth** | 12 tools incl. `run_fem_analysis` (CalculiX → von Mises stress, displacement), `execute_code`, `create_object`, `delete_object`, `get_view` | Yes | Low — but `execute_code` MUST be denied in allowlist | **High** (tool_inspector + objective_metric for FEM) — only 2026 MCP server with FEM access | `execute_code` is arbitrary Python in FreeCAD; treat as shell-equivalent. Allowlist must scope to `run_fem_analysis`, `get_object`, `get_objects`, `get_view`, `get_parts_list` only. License: MIT. |
| `quellant/openscad-mcp` | https://github.com/quellant/openscad-mcp | stdio / http / sse | None (local-only assumed) | 14 tools: `render_single`, `render_perspectives`, `compare_renders`, `export_model` (STL/3MF/AMF/OFF/DXF/SVG), `validate_scad`, `analyze_model` (bbox, dims, triangle count), `create_model`, etc. | Yes | Low | **High** (tool_inspector) for OpenSCAD validators | **No manifold/watertight checks** — `analyze_model` is shape metrics only. License: MIT. v0.2.0 dated 2026-02-15. |
| `jhacksman/OpenSCAD-MCP-Server` | https://github.com/jhacksman/OpenSCAD-MCP-Server | http (port 8000) | API key for remote CUDA MVS; none for local | Tools include `generate_image_gemini`, `create_3d_model_from_text`, `export_model`, `print_model`, `discover_printers` | Yes | Medium — broad surface includes destructive `print_model` | **Medium** (tool_inspector) — heavier on AI generation than validation | License: MIT. Last commit 2025-03 — pre-2026 baseline. `print_model` and `discover_printers` must be denied. |
| `spkane/freecad-addon-robust-mcp-server` | https://github.com/spkane/freecad-addon-robust-mcp-server | stdio | None documented | "Robust MCP server and MCP Bridge Workbench/Addon" | Yes | Low–Medium | **Medium** (tool_inspector) — alternative FreeCAD if `neka-nat` is unsuitable | 83 stars, active (3 days ago); README depth not verified for FEM coverage |
| `contextform/freecad-mcp` | https://github.com/contextform/freecad-mcp | stdio | None | PartDesign (13 ops), Part (18 ops), View Control (14 ops), Python execution | Yes | Medium | Medium (tool_inspector) — **no FEM, no mesh validity** | License not specified; verify before adoption. |
| **Mesh validity (no dedicated MCP server)** | n/a — must be wrapped | n/a | n/a | n/a | **No** | Low — see below | Critical for `vigor-adapter-cad` reviewers | None of the surveyed CAD MCP servers expose manifold/watertight/self-intersection checks. |
| **CadQuery (no MCP wrapper)** | https://github.com/CadQuery/cadquery | n/a | n/a | n/a | **No** | Low–Medium | n/a | If VIGOR's CAD adapter standardizes on CadQuery IR, a wrap is required. |

### Mesh validity wrap (small)

Mesh validity (manifold, watertightness, self-intersection) is **not exposed** by any 2026 MCP server found. The wrap is small:
- **Library**: `trimesh` (https://github.com/mikedh/trimesh) — `mesh.is_watertight`, `mesh.is_winding_consistent`, `mesh.is_volume`, `mesh.fill_holes()`.
- **Effort**: 80–150 LOC stdio MCP server with a single tool `validate_mesh(stl_path) -> {watertight: bool, winding_consistent: bool, volume: float, defects: [...]}`. Pure Python, no GPU.
- **Transport**: stdio (local, fast).
- **Auth**: none (local).
- **Reviewer type**: `objective_metric`.

This wrap is small enough that `vigor-adapter-cad` should own it directly rather than adopting a third-party MCP server.

### Top-3 picks (CAD)

1. **`neka-nat/freecad-mcp`** with strict allowlist `[run_fem_analysis, get_object, get_objects, get_view, get_parts_list]` — provides FEM (the only 2026 MCP path to it). *Rationale:* FEM is irreplaceable; allowlist neutralizes the `execute_code` risk. Best fit for `vigor-adapter-cad` FEM reviewer.
2. **`quellant/openscad-mcp`** for OpenSCAD render/validate/analyze. *Rationale:* cleanest tool surface, multi-transport support, active 2026 maintenance, MIT license.
3. **In-adapter `trimesh` mesh-validity wrap** (custom). *Rationale:* fills the manifold/watertight gap that no third-party server covers. Trivial to implement and own.

## AIECF Integration

**No public MCP server for AIECF exists** as of the cutoff (GitHub search for "AIECF" returned zero repositories; verified 2026-05-14). AIECF in this project's lexicon refers to "AI Education Content Factory" — scene-based educational video systems described in `docs/adoption/aiecf.md`. The integration is a wrap-cost question.

### Wrapping cost

Per `docs/adoption/aiecf.md` lines 39–46, the AIECF system is assumed to expose:

| Assumed AIECF Entry Point | MCP Tool To Expose | Transport | Auth |
| --- | --- | --- | --- |
| Scene-based generation API | `generate_scene(spec) -> scene_ir` | http | API key (per-tenant) |
| Manim rendering worker | `render_scene(scene_ir) -> mp4_uri` | http (long-running, async) | API key |
| ffmpeg assembly stage | `assemble_video(mp4_list) -> final_uri` | http | API key |
| VLM critique (Gemini-style) | `critique_video(uri) -> finding[]` | http or stdio (depending on AIECF deployment) | API key |
| Quality threshold gate | `evaluate(uri, thresholds) -> pass: bool` | http | API key |

**Transport recommendation**: http/sse. AIECF workflows are long-running (Redis/RQ-backed per the adoption doc), so stdio is unsuitable; the agent should poll or stream over http.

**Auth model**: API key per-tenant, with rate-limits enforced server-side. mTLS optional for VPC-internal deployments.

**Estimated wrap effort**:
- ~400–600 LOC Python (one MCP server wrapping the AIECF HTTP API).
- Plus a `vigor-adapter-video-aiecf` package (already declared as future work, currently blocked on repo URL/access/license per the adoption doc).
- The wrap should map AIECF's storyboard/script objects to VIGOR `ArtifactIR` and AIECF reviewer outputs to `ReviewReport` with `reviewer_type='model_critic'` (for VLM critique) or `objective_metric` (for threshold gates).

**Blocker**: as recorded in `docs/adoption/aiecf.md` and `docs/readiness/implementation-readiness.md`, AIECF integration is currently blocked on access to a concrete AIECF repository. Until that arrives, the wrap is hypothetical. ADR-0016 should treat AIECF as a Phase-C item, not Phase-A.

## Security Posture

For each recommended pick:

### Claude Vision (in-process)
- **tool_allowlist viability**: n/a (in-process). VIGOR's existing model-call gating applies.
- **Auth**: Anthropic API key. Already in agent's env.
- **Rate-limit**: Anthropic-side per-key TPM/RPM. Shares quota with main agent — must budget at the run level.
- **Transport**: in-process HTTPS to Anthropic.
- **Sanitization**: image dimensions validated by Anthropic (max 8000×8000 px, max 600 images per request — see https://platform.claude.com/docs/en/docs/build-with-claude/vision). VIGOR should strip EXIF if privacy-sensitive.

### `tan-yong-sheng/ai-vision-mcp`
- **tool_allowlist viability**: High — 5 tools, none destructive. Recommended allowlist: all 5 (`analyze_image`, `compare_images`, `detect_objects_in_image`, `audit_design`, `analyze_video`).
- **Auth**: `GEMINI_API_KEY` (env) for Google AI Studio, or Vertex SA JSON for production. Rotate monthly.
- **Rate-limit**: Google AI Studio per-project RPM caps; Vertex per-project quota. Server itself does not throttle — VIGOR must throttle client-side per-run.
- **Transport**: stdio. Local subprocess; no network exposure beyond the egress to Google.
- **Sanitization**: paths from agent to MCP must be inside the run-archive sandbox.

### `JochenYang/luma-mcp`
- **tool_allowlist viability**: High — single tool `image_understand`.
- **Auth**: per-provider env vars (`ZHIPU_API_KEY`, `SILICONFLOW_API_KEY`, `DASHSCOPE_API_KEY`). Some providers are PRC-jurisdiction; review data-residency policy before sending sensitive imagery.
- **Rate-limit**: per-provider; server does not throttle.
- **Transport**: stdio.
- **Sanitization**: same path-sandbox discipline as above.

### `hlpsxc/video-quality-mcp`
- **tool_allowlist viability**: High — 5 tools, all read-only quality analysis.
- **Auth**: none (local). Local-only deployment is mandatory because the server has no auth.
- **Rate-limit**: bounded by FFmpeg + libvmaf CPU. Wallclock-bound only.
- **Transport**: stdio.
- **Sanitization**: server reads local files; restrict working dir to run-archive root via OS-level permissions.

### VideoScore2 wrap (planned)
- **tool_allowlist**: single tool `score_video`. Trivial.
- **Auth**: API key (Bearer). mTLS optional for VPC deployment.
- **Rate-limit**: per-key RPS + per-run cap. GPU is the bottleneck — cap concurrent inferences.
- **Transport**: http/sse (hosted, GPU-resident).
- **Sanitization**: validate `video_path` is inside a per-run sandbox; reject path traversal.

### `neka-nat/freecad-mcp`
- **tool_allowlist viability**: **Critical**. The default tool set includes `execute_code` (arbitrary Python in FreeCAD process — shell-equivalent), `delete_object`, and `edit_object`. VIGOR must run with allowlist `[run_fem_analysis, get_object, get_objects, get_view, get_parts_list]` and DENY everything else.
- **Auth**: IP allowlist on the RPC layer (`127.0.0.1` default). No per-tool auth — the MCP layer is the authorization point.
- **Rate-limit**: none server-side; FEM runs can be expensive — VIGOR must enforce per-run wallclock budget.
- **Transport**: stdio between agent and MCP; XML-RPC between MCP and FreeCAD addon. **Do not expose RPC port to network**.
- **Sanitization**: model files passed to FreeCAD must be in run-archive sandbox; refuse external paths.

### `quellant/openscad-mcp`
- **tool_allowlist viability**: High. Recommended allowlist: `[render_single, render_perspectives, compare_renders, export_model, validate_scad, analyze_model, get_libraries, check_openscad]`. Deny model-management mutators (`create_model`, `update_model`, `delete_model`) unless adapter genuinely needs them.
- **Auth**: none (local). Local-only.
- **Rate-limit**: bounded by OpenSCAD subprocess (already bounded server-side by timeouts).
- **Transport**: stdio (preferred), http/sse available. Use stdio for the local validator pattern.
- **Sanitization**: server validates variable names by regex (`^[a-zA-Z_][a-zA-Z0-9_]*$`) and applies file-size limits — good baseline.

### Custom `trimesh` mesh-validity wrap
- **tool_allowlist**: single tool `validate_mesh`.
- **Auth**: none (local).
- **Rate-limit**: trimesh is CPU-fast; no throttling needed.
- **Transport**: stdio.
- **Sanitization**: path sandbox.

### AIECF wrap (planned)
- **tool_allowlist**: scope to read/score tools; deny any AIECF admin/teardown endpoints.
- **Auth**: API key per-tenant. Rotate per environment.
- **Rate-limit**: AIECF-side RPS plus VIGOR-side per-run cap.
- **Transport**: http/sse.
- **Sanitization**: scene specs are user-controlled; validate against `vigor.task.v1` schema before forwarding to AIECF.

## Recommended Sequencing

VIGOR should land MCP integrations in dependency order against adapter readiness and supply risk:

1. **Phase A — Photo critic (low risk, high return)**
   - Use Claude Vision in-process for the primary `model_critic` reviewer in `vigor-adapter-photo`. Zero new infrastructure.
   - Add `tan-yong-sheng/ai-vision-mcp` as the second-opinion design-audit reviewer for ensemble diversity.
   - *Why first*: photo adapter is the most mature in the codebase (`HistogramCritic` is the reference contract); critic addition is purely additive; no new packages or hosting needed.

2. **Phase B — CAD validators (medium risk, immediate value)**
   - Adopt `quellant/openscad-mcp` for OpenSCAD render/validate (low-risk, MIT, active).
   - Adopt `neka-nat/freecad-mcp` for FEM, with strict allowlist (`run_fem_analysis` + read-only getters only).
   - Build the `trimesh` mesh-validity wrap inside `vigor-adapter-cad`.
   - *Why second*: CAD adapter is partially built; FEM access unblocks objective scoring for parametric workflows; supply risk is contained by allowlist discipline.

3. **Phase C — Video objective + VideoScore2 wrap (high effort, gated on infrastructure)**
   - Adopt `hlpsxc/video-quality-mcp` for objective video quality (PSNR/SSIM/VMAF) — trivial integration.
   - Build the VideoScore2 MCP wrap (~250–400 LOC + GPU hosting). Treat as a hosted service shared across runs.
   - *Why third*: GPU hosting is non-trivial; video objective metrics give partial coverage while wrap is built; per the adoption doc, VideoScore2 hard scoring is currently blocked on GPU/shadow-mode policy.

4. **Phase D — AIECF integration (blocked on external repo access)**
   - Build `vigor-adapter-video-aiecf` against the concrete AIECF repository once access is unblocked.
   - Wrap AIECF's HTTP API as MCP per §7.
   - *Why last*: blocked on external dependency outside this team's control.

## Open Questions / Coverage Gaps

| Gap | Why It Matters | Suggested Resolution |
| --- | --- | --- |
| No public MCP server for VideoScore2 or any post-2025 learned video scorer | VIGOR must wrap one to get `learned_scorer` review on video. | Build the VideoScore2 wrap per §5. Track newer learned scorers (post-VideoScore2) via `huggingface-skills:huggingface-papers`. |
| No mesh manifold/watertight MCP server | `vigor-adapter-cad` cannot do objective mesh validity without one. | Trivial in-adapter `trimesh` wrap per §6. |
| No CadQuery MCP server | If VIGOR's CAD IR standardizes on CadQuery, a wrap is required. | Defer until ADR-0016 confirms CAD IR choice. |
| AIECF repository URL / access / license | Blocks `vigor-adapter-video-aiecf` entirely (per `docs/adoption/aiecf.md`). | Out-of-band coordination; not solvable from this survey. |
| Smithery.ai not exhaustively crawled | A long-tail server may exist that this survey missed. | Lead can run one targeted smithery query before ADR finalization. |
| Closed-source vendor MCP servers (Anthropic-internal, OpenAI-internal) | Could outperform OSS picks but are not auditable. | Out of scope for this survey by ADR-0004 transparency principles. |
| `contextform/freecad-mcp` and several smaller FreeCAD/OpenSCAD MCP servers have no declared license | Blocks vendoring or commercial use. | Skip without resolution; `neka-nat` + `quellant` (both MIT) cover the same surface. |
| `mario-andreschak/mcp-image-recognition` last updated 2025-04-12 — pre-2026 baseline | May be unmaintained. | Verify activity before adoption; otherwise skip. |
| `GongRzhe/opencv-mcp-server` archived 2026-03-03 by owner | No upstream fixes possible. | If used, must vendor and fork. Prefer in-adapter OpenCV calls (already viable per `HistogramCritic`). |
| Per-server rate-limit characteristics under load | Not measured; relying on documented vendor limits only. | Smoke-test each pick under expected VIGOR run concurrency before declaring production-ready. |

