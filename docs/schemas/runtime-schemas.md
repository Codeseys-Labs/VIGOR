# VIGOR Runtime Schemas

This document defines the core runtime objects named by the VIGOR architecture. Schemas are intentionally JSON-shaped so they can be stored as files, database records, or event payloads.

## Design Rules

1. Every persisted runtime record should include a stable object identifier, `schema_version`, and creation timestamp unless it is embedded as a small child object inside another record.
2. Every artifact reference should include a URI and a content hash when feasible.
3. Runtime failures are structured data, not only logs.
4. Domain-specific fields live under `domain` or adapter-specific extension blocks.
5. Required fields should be small and portable; large media stays in artifact storage.

## TaskSpec

```json
{
  "schema_version": "vigor.task.v1",
  "task_id": "task_001",
  "created_at": "2026-04-26T00:00:00Z",
  "goal": "Create a warm cinematic photo edit",
  "modalities": ["image", "photo_edit_recipe"],
  "references": [
    {
      "artifact_id": "input_001",
      "uri": "inputs/photo.raw",
      "media_type": "image/raw",
      "sha256": "..."
    }
  ],
  "constraints": [
    {"id": "c1", "type": "style", "text": "warm but natural"},
    {"id": "c2", "type": "technical", "text": "avoid clipped highlights"}
  ],
  "target_outputs": ["preview.jpg", "recipe.json", "lightroom.xmp"],
  "budgets": {
    "max_iterations": 5,
    "max_candidates": 4,
    "max_wall_clock_s": 1800,
    "max_cost_usd": 10.0
  },
  "human_mode": "automatic | checkpoint | interactive",
  "domain": {}
}
```

## AdapterManifest

```json
{
  "schema_version": "vigor.adapter_manifest.v1",
  "adapter_id": "photo.editing.v1",
  "created_at": "2026-04-26T00:00:00Z",
  "domain": "photo_editing",
  "version": "0.1.0",
  "supported_ir": ["photo_edit_recipe.v1"],
  "tools": [
    {
      "tool_id": "photo.rawpy_renderer.v1",
      "capability": "render",
      "mutability": "state_mutating",
      "inputs": ["photo_edit_recipe.v1", "image/raw"],
      "outputs": ["image/jpeg", "metrics.histogram.v1"],
      "timeout_s": 60,
      "retry_policy": {"max_retries": 1}
    }
  ],
  "reviewers": ["photo.histogram.v1", "photo.aesthetic_vlm.v1"],
  "exports": ["recipe.json", "xmp", "tiff"]
}
```

## ArtifactIR

```json
{
  "schema_version": "vigor.artifact_ir.v1",
  "candidate_id": "cand_0001",
  "created_at": "2026-04-26T00:00:00Z",
  "ir_type": "photo_edit_recipe.v1",
  "ir_uri": "runs/run_001/candidates/cand_0001/ir.json",
  "ir_sha256": "...",
  "parent_candidate_id": null,
  "hypothesis": "Lift the subject while preserving moody shadows",
  "generator": {
    "model": "example-model",
    "prompt_uri": "runs/run_001/candidates/cand_0001/generator_prompt.md",
    "tool_ids": []
  },
  "domain": {}
}
```

## CompileResult

```json
{
  "schema_version": "vigor.compile_result.v1",
  "compile_id": "compile_0001",
  "created_at": "2026-04-26T00:00:00Z",
  "candidate_id": "cand_0001",
  "tool_id": "photo.rawpy_renderer.v1",
  "status": "success | failure | timeout | cancelled",
  "inputs": [
    {"uri": "ir.json", "sha256": "..."}
  ],
  "outputs": [
    {"artifact_id": "preview_0001", "uri": "preview.jpg", "media_type": "image/jpeg", "sha256": "..."}
  ],
  "metrics": {
    "runtime_ms": 842,
    "peak_memory_mb": 512
  },
  "warnings": [],
  "errors": []
}
```

## RuntimeError

```json
{
  "schema_version": "vigor.runtime_error.v1",
  "error_id": "err_0001",
  "created_at": "2026-04-26T00:00:00Z",
  "type": "schema_validation | compile_error | render_error | tool_timeout | reviewer_error | export_error",
  "severity": "high | medium | low",
  "message": "Renderer failed to load mask file",
  "tool_id": "photo.rawpy_renderer.v1",
  "retryable": true,
  "evidence_uri": "logs/compile_0001.stderr.txt"
}
```

## PatchPlan

```json
{
  "schema_version": "vigor.patch_plan.v1",
  "patch_id": "patch_0001",
  "created_at": "2026-04-26T00:00:00Z",
  "source_candidate_id": "cand_0001",
  "basis": ["review_0001", "review_0002", "compile_0001"],
  "objectives": [
    "Reduce sky highlight clipping without changing cabin exposure",
    "Preserve foreground mood"
  ],
  "do_not_change": ["overall crop", "subject identity"],
  "allowed_operations": ["modify_global_adjustment", "modify_local_mask"],
  "risk_level": "low | medium | high",
  "expected_validation": ["photo.histogram.v1", "photo.aesthetic_vlm.v1"]
}
```

## ExportBundle

```json
{
  "schema_version": "vigor.export_bundle.v1",
  "export_id": "export_0001",
  "created_at": "2026-04-26T00:00:00Z",
  "candidate_id": "cand_0004",
  "exports": [
    {"type": "final_artifact", "uri": "final/preview.jpg", "media_type": "image/jpeg", "sha256": "..."},
    {"type": "canonical_ir", "uri": "final/recipe.json", "media_type": "application/json", "sha256": "..."},
    {"type": "xmp", "uri": "final/lightroom.xmp", "media_type": "application/xml", "sha256": "..."}
  ],
  "lossiness": [
    {
      "export_type": "xmp",
      "note": "Complex semantic masks are represented as external mask references"
    }
  ]
}
```

## Frontier

```json
{
  "schema_version": "vigor.frontier.v1",
  "run_id": "run_001",
  "frontier_id": "frontier_001",
  "created_at": "2026-04-26T00:00:00Z",
  "selection_policy": "hard_gates_then_weighted_score.v1",
  "candidates": [
    {
      "candidate_id": "cand_0004",
      "status": "selected | kept | rejected",
      "scores": {"quality": 0.82, "cost": 0.31, "editability": 0.91, "safety": 1.0},
      "hard_gate_passed": true,
      "rank": 1,
      "selection_reason": "Best quality among candidates passing all hard gates"
    }
  ]
}
```

## ProvenanceRecord

```json
{
  "schema_version": "vigor.provenance.v1",
  "provenance_id": "prov_001",
  "run_id": "run_001",
  "created_at": "2026-04-26T00:00:00Z",
  "task_id": "task_001",
  "selected_candidate_id": "cand_0004",
  "inputs": ["input_001"],
  "activities": [
    {"activity_id": "generate_0001", "type": "generation", "agent": "generator", "model": "example-model"},
    {"activity_id": "compile_0001", "type": "compile", "tool_id": "photo.rawpy_renderer.v1"},
    {"activity_id": "review_0001", "type": "review", "reviewer_id": "photo.histogram.v1"}
  ],
  "derived_artifacts": ["preview_0004", "recipe_0004"],
  "stop_reason": "accepted | budget_exhausted | plateau | human_selected | failed | escalated",
  "residual_risks": []
}
```

## RunArchive Layout

```text
runs/<run_id>/
  task.json
  adapter_manifest.json
  candidates/
    cand_0001/
      ir.json
      generator_prompt.md
      compile_result.json
      artifacts/
      reviews/
      adjudication.json
      patch_plan.json
    cand_0002/
      ...
  frontier.json
  final/
    export_bundle.json
    provenance.json
```
