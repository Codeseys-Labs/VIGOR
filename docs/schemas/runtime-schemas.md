# VIGOR Runtime Schemas

This document summarizes the runtime schemas implemented in `packages/vigor-core/src/vigor_core/schemas.py`.

## Invariants

1. Pydantic v2 strict mode and `extra="forbid"` are enabled for all core runtime models.
2. On-disk JSON uses `camelCase` (`by_alias=True`). Python uses `snake_case`.
3. Filesystem-derived IDs use the pattern `^[A-Za-z0-9_.-]{1,128}$`.
4. Top-level persisted records include `schemaVersion`, a stable id, and `createdAt` unless they are small nested objects.
5. `ArtifactIR.bodySha256` is populated automatically from deterministic JSON of `body`.

## Key Records

### `TaskSpec`

```json
{
  "schemaVersion": "vigor.task.v1",
  "taskId": "task_001",
  "createdAt": "2026-04-26T00:00:00Z",
  "goal": "Create a warm cinematic photo edit",
  "modalities": ["image", "photo_edit_recipe"],
  "references": [
    {
      "artifactId": "input_001",
      "uri": "inputs/photo.jpg",
      "mediaType": "image/jpeg",
      "sha256": "..."
    }
  ],
  "constraints": [],
  "targetOutputs": ["preview.jpg", "recipe.json", "lightroom.xmp"],
  "budgets": {
    "maxIterations": 5,
    "maxCandidates": 4,
    "maxWallClockS": 1800,
    "maxCostUsd": null,
    "maxToolRetries": 2
  },
  "humanMode": "automatic",
  "domain": {}
}
```

### `AdapterManifest`

```json
{
  "schemaVersion": "vigor.adapter_manifest.v1",
  "adapterId": "photo.editing.v1",
  "createdAt": "2026-04-26T00:00:00Z",
  "domain": "photo_editing",
  "version": "0.2.0",
  "supportedIr": ["photo_edit_recipe.v1"],
  "tools": [
    {
      "toolId": "photo.renderer.v1",
      "capability": "render",
      "mutability": "mutator",
      "inputs": ["photo_edit_recipe.v1", "image/jpeg"],
      "outputs": ["image/jpeg", "image/png"],
      "timeoutS": null,
      "retryPolicy": {},
      "description": "Preview renderer and mask generator"
    }
  ],
  "reviewers": ["photo.histogram.v1"],
  "exports": ["recipe.json", "lightroom.xmp", "mask.png"]
}
```

### `ArtifactIR`

```json
{
  "schemaVersion": "vigor.artifact_ir.v1",
  "candidateId": "cand_0001",
  "createdAt": "2026-04-26T00:00:00Z",
  "irType": "photo_edit_recipe.v1",
  "parentCandidateId": null,
  "hypothesis": "warm grade with protected highlights",
  "body": {
    "schemaVersion": "photo_edit_recipe.v1",
    "kind": "photo_edit_recipe",
    "intent": "warm cinematic",
    "globalAdjustments": {}
  },
  "bodySha256": "...",
  "generator": {}
}
```

### `CompileResult`

```json
{
  "schemaVersion": "vigor.compile_result.v1",
  "compileId": "compile_cand_0001",
  "createdAt": "2026-04-26T00:00:00Z",
  "candidateId": "cand_0001",
  "toolId": "photo.renderer.v1",
  "status": "success",
  "inputs": [],
  "outputs": [
    {
      "artifactId": "photo_preview_cand_0001",
      "uri": "run_001/candidates/cand_0001/artifacts/preview.jpg",
      "mediaType": "image/jpeg",
      "sha256": "...",
      "summary": "preview"
    }
  ],
  "metrics": {},
  "warnings": [],
  "errors": []
}
```

### `ReviewReport`

```json
{
  "schemaVersion": "vigor.review_report.v1",
  "reviewId": "rev_histogram_cand_0001",
  "createdAt": "2026-04-26T00:00:00Z",
  "candidateId": "cand_0001",
  "artifactId": "photo_preview_cand_0001",
  "reviewerId": "photo.histogram.v1",
  "reviewerType": "objective_metric",
  "summary": "highlight clipping within tolerance",
  "scores": {"quality": 0.9},
  "thresholds": {"quality": 0.5},
  "passed": true,
  "confidence": 0.9,
  "findings": [],
  "recommendedAction": "accept",
  "metadata": {}
}
```

### `AdjudicationReport`

```json
{
  "schemaVersion": "vigor.adjudication_report.v1",
  "adjudicationId": "adj_cand_0001",
  "createdAt": "2026-04-26T00:00:00Z",
  "candidateId": "cand_0001",
  "policyId": "photo.default.v1",
  "hardGatePassed": true,
  "normalizedScores": {"quality": 0.9},
  "composite": 0.9,
  "reviewerDisagreement": 0.0,
  "decision": "accept",
  "basis": ["rev_histogram_cand_0001"],
  "selectionReason": "passes gates and minimums",
  "residualRisks": []
}
```

### `PatchPlan`

```json
{
  "schemaVersion": "vigor.patch_plan.v1",
  "patchId": "patch_cand_0001",
  "createdAt": "2026-04-26T00:00:00Z",
  "sourceCandidateId": "cand_0001",
  "basis": ["rev_histogram_cand_0001"],
  "objectives": ["lower highlights"],
  "doNotChange": [],
  "allowedOperations": [],
  "riskLevel": "low",
  "expectedValidation": []
}
```

### `ExportBundle`

```json
{
  "schemaVersion": "vigor.export_bundle.v1",
  "exportId": "export_cand_0001",
  "createdAt": "2026-04-26T00:00:00Z",
  "candidateId": "cand_0001",
  "exports": [
    {
      "type": "final_artifact",
      "uri": "run_001/candidates/cand_0001/artifacts/preview.jpg",
      "mediaType": "image/jpeg",
      "sha256": "..."
    }
  ],
  "lossiness": []
}
```

### `Frontier`

```json
{
  "schemaVersion": "vigor.frontier.v1",
  "frontierId": "frontier_run_001",
  "createdAt": "2026-04-26T00:00:00Z",
  "runId": "run_001",
  "selectionPolicy": "photo.default.v1",
  "candidates": [
    {
      "candidateId": "cand_0001",
      "status": "selected",
      "decision": "accept",
      "scores": {"quality": 0.9, "composite": 0.9},
      "hardGatePassed": true,
      "rank": 1,
      "selectionReason": "top-ranked accepted candidate passing hard gates"
    }
  ]
}
```

### `ProvenanceRecord`

```json
{
  "schemaVersion": "vigor.provenance.v1",
  "provenanceId": "prov_run_001",
  "createdAt": "2026-04-26T00:00:00Z",
  "runId": "run_001",
  "taskId": "run_001",
  "selectedCandidateId": "cand_0001",
  "inputs": ["input_001"],
  "activities": [],
  "derivedArtifacts": ["cand_0001"],
  "stopReason": "accepted",
  "residualRisks": []
}
```

## Schema Registry

`vigor-core` exposes a lightweight registry for domain IR bodies:

```python
from vigor_core.registry import register_ir, validate_ir_body
from vigor_adapter_photo import PhotoEditRecipeV1

register_ir(PhotoEditRecipeV1)
recipe = validate_ir_body("photo_edit_recipe.v1", payload)
```
