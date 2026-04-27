# Domain Adapter Specification Template

Use this template to define a new VIGOR modality adapter.

## Adapter Metadata

```json
{
  "adapter_id": "example.adapter.v1",
  "domain": "photo_editing | video_generation | cad | code | audio | ui | robotics | data | other",
  "owner": "team-or-person",
  "status": "draft | experimental | production",
  "version": "0.1.0"
}
```

## Scope

What does this adapter generate or refine?

| Field | Value |
| --- | --- |
| Domain |  |
| Primary users |  |
| Supported inputs |  |
| Supported outputs |  |
| Out of scope |  |

## Intermediate Representation

Describe the canonical editable IR.

| Field | Value |
| --- | --- |
| IR name |  |
| IR version |  |
| Format | JSON, YAML, Python, DSL, graph, native file, mixed |
| Schema location |  |
| Native editor mappings |  |
| Lossy export risks |  |

Example IR:

```json
{
  "ir_type": "domain_ir.v1",
  "intent": "",
  "parameters": {},
  "operations": [],
  "constraints": []
}
```

## Compiler / Renderer / Simulator

| Tool | Capability | Input | Output | Failure Modes | Timeout |
| --- | --- | --- | --- | --- | --- |
|  | compile |  |  |  |  |
|  | render |  |  |  |  |
|  | simulate |  |  |  |  |

## Reviewers

| Reviewer | Type | Input | Output | Hard Gate? | Calibration Data |
| --- | --- | --- | --- | --- | --- |
|  | objective |  |  | yes/no |  |
|  | model critic |  |  | yes/no |  |
|  | human |  |  | yes/no |  |

## Acceptance Criteria

List objective pass/fail criteria.

1. 
2. 
3. 

## Patch Operations

What can be changed automatically?

| Finding | Patch Operation | Risk |
| --- | --- | --- |
|  |  |  |

## Export Bundle

| Export | Purpose | Required? |
| --- | --- | --- |
| Final artifact | User-facing output | yes |
| Final IR | Editable source of truth | yes |
| Review report | Scores and findings | yes |
| Provenance | Audit trail | yes |
| Native editor file | Downstream workflow | optional |

## Budgets

| Budget | Default |
| --- | --- |
| Max iterations |  |
| Max candidates |  |
| Max wall-clock time |  |
| Max cost |  |
| Max tool retries |  |

## Safety And Escalation

| Risk | Gate | Escalation |
| --- | --- | --- |
|  |  |  |

## Benchmark Plan

| Split | Description |
| --- | --- |
| Search set |  |
| Validation set |  |
| Held-out test set |  |

## Open Questions

1. 
2. 
3. 
