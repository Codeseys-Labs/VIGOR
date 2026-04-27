# ADR-0011: IR Schema Versioning And Discriminated Unions

Status: Accepted

Date: 2026-04-26

## Context

VIGOR declares many intermediate representations: photo edit recipes, Manim scenes, CAD feature graphs, UI specs, audio graphs, and more. Each will evolve. Without a versioning scheme, new fields break old artifacts, and mismatched schemas cause silent data loss.

Pydantic v2 offers `Literal` fields, strict validation, JSON-Schema export, aliases, and discriminated unions that fit this problem well.

## Decision

VIGOR standardizes IR schema versioning as follows.

1. Every persisted schema has a `schema_version: Literal["<name>.vN"]` field pinned per model class. Example: `schema_version: Literal["photo_edit_recipe.v1"]`.
2. IR payloads carry a `kind: Literal[...]` field so they can participate in discriminated unions later.
3. Persisted runtime records carry a `created_at` timestamp and a stable id.
4. When a field is added, the schema version stays the same only if the field is fully backward compatible. Breaking changes introduce a new version alongside the old one.
5. `vigor-core` provides registry helpers (`register_ir`, `get_ir_model`, `validate_ir_body`, `export_json_schema`, `registered_ir_versions`) so adapters can register their IR models without coupling core to domain packages.
6. Migrations between versions are explicit functions when needed.
7. JSON-Schema is exported per model so IRs are portable to non-Python consumers.

### Field Naming

1. Python fields are `snake_case`.
2. JSON/YAML serialization uses `camelCase` via Pydantic `alias_generator` and `populate_by_name = True`.
3. Serialization calls use `by_alias=True` for on-disk artifacts.

### Strict Mode

All VIGOR Pydantic models set `ConfigDict(strict=True, extra="forbid")`. Adapter-specific extension data lives under declared dictionaries such as `domain`, `metadata`, `metrics`, or domain IR extension fields.

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| Free-form `schema_version` string | Easy to write, but impossible to validate at type level. |
| Untagged unions | Slow, ambiguous, and produce worse error messages. |
| Pydantic v1 | Weaker support for modern validation and schema features. |
| Protobuf or Avro | Too heavy for Python-first v0. |

## Implementation Notes

Example registry use:

```python
from vigor_core.registry import register_ir, validate_ir_body
from vigor_adapter_photo import PhotoEditRecipeV1

register_ir(PhotoEditRecipeV1)
recipe = validate_ir_body("photo_edit_recipe.v1", payload)
```

## Citations

| Source | URL |
| --- | --- |
| Pydantic discriminated unions | https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions |
| Pydantic JSON Schema export | https://docs.pydantic.dev/latest/concepts/json_schema/ |
| Pydantic alias generators | https://docs.pydantic.dev/latest/concepts/alias/ |
