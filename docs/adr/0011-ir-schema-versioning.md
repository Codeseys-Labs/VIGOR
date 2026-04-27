# ADR-0011: IR Schema Versioning And Discriminated Unions

Status: Accepted

Date: 2026-04-26

## Context

VIGOR declares many intermediate representations: photo edit recipes, educational video storyboards, CAD feature graphs, UI specs, audio graphs, and more. Each will evolve. Without a versioning scheme, new fields break old artifacts, and mismatched schemas cause silent data loss.

Pydantic v2 offers two features that fit this problem:

1. `Literal` type hints pinned per model so the version becomes part of the type, not a free-form string.
2. Discriminated unions with `Field(discriminator=...)` on tagged fields so validation routes input to the correct model.

## Decision

VIGOR standardizes IR schema versioning as follows.

1. Every persisted schema has a `schema_version: Literal["<name>.vN"]` field pinned per model class. Example: `schema_version: Literal["photo_edit_recipe.v1"]`.
2. Discriminated unions carry a `kind: Literal[...]` field and use `Field(discriminator="kind")`.
3. Persisted runtime records also carry a `created_at` timestamp and a stable id. See `docs/schemas/runtime-schemas.md` for the required-field invariants.
4. When a field is added, the schema version stays the same only if the field is fully backward compatible (optional with a default, no change in meaning of existing fields). Otherwise a new version is introduced (`photo_edit_recipe.v2`) alongside the old one.
5. `vigor-core` provides a `SchemaRegistry` that maps version strings to Pydantic model classes and knows how to load either version from a persisted artifact.
6. Migrations between versions are explicit functions. They are composable, pure, and tested.
7. JSON-Schema is exported per model so IRs are portable to non-Python consumers.

### Field Naming

1. Python fields are `snake_case`.
2. JSON/YAML serialization uses `camelCase` via Pydantic `alias_generator` and `populate_by_name = True`.
3. Serialization calls use `by_alias=True` for on-disk artifacts.

### Strict Mode

All VIGOR Pydantic models set `ConfigDict(strict=True, extra="forbid")`. This prevents silent string-to-int coercion and refuses unknown fields. Adapter-specific extension data goes under a declared `domain` dict so extensions stay explicit.

### Archive Round-Trip

Every persisted artifact must round-trip: load, re-serialize, diff. Round-trip tests live in `vigor-core/tests/test_schemas.py` and cover every top-level persisted type.

## Alternatives Considered

| Alternative | Reason Rejected |
| --- | --- |
| Free-form `schema_version` string | Easy to write, but impossible to validate at type level. |
| Untagged unions | Slow, ambiguous, and produce worse error messages. |
| Pydantic v1 | Fewer validation primitives and weaker discriminated union support. |
| Protobuf or Avro | Too heavy for a Python-first v0. |

## Consequences

Positive:

1. Old and new IRs can be opened at the same time via the registry.
2. Pydantic validation errors are precise because of discriminated unions.
3. Adapter teams get a ready-made versioning pattern.
4. JSON-Schema exports make IRs consumable by non-Python tools.

Negative:

1. Migration functions must be written and maintained.
2. Bumping versions is a small amount of ceremony.
3. Adapters must stay disciplined about what counts as a breaking change.

## Implementation Notes

Example discriminated union:

```python
from typing import Annotated, Literal, Union
from pydantic import BaseModel, ConfigDict, Field

class _VigorBase(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        populate_by_name=True,
        from_attributes=False,
    )

class PhotoEditRecipeV1(_VigorBase):
    schema_version: Literal["photo_edit_recipe.v1"] = "photo_edit_recipe.v1"
    kind: Literal["photo_edit_recipe"] = "photo_edit_recipe"
    intent: str
    global_adjustments: "PhotoGlobalAdjustments"
    local_adjustments: list["PhotoLocalAdjustment"] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)

SomeIR = Annotated[
    Union[PhotoEditRecipeV1, "EducationalVideoIRV1"],
    Field(discriminator="kind"),
]
```

Example schema registry entry:

```python
from vigor_core.schemas import register_ir

register_ir(PhotoEditRecipeV1)
```

## Citations

| Source | URL |
| --- | --- |
| Pydantic discriminated unions | https://docs.pydantic.dev/latest/concepts/unions/#discriminated-unions |
| Pydantic JSON Schema export | https://docs.pydantic.dev/latest/concepts/json_schema/ |
| Pydantic alias generators | https://docs.pydantic.dev/latest/concepts/alias/ |
| VIGOR runtime schemas | `../schemas/runtime-schemas.md` |
