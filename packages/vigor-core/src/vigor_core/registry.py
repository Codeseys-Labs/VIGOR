"""Schema registry utilities for VIGOR IR bodies.

Core cannot import adapter packages, so adapters register their IR models at
import time or application startup. The registry provides the hook promised by
ADR-0011 without coupling core to any domain package.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=type[BaseModel])

_REGISTRY: dict[str, type[BaseModel]] = {}


def register_ir(model: T, *, schema_version: str | None = None) -> T:
    """Register a Pydantic IR model by schema version and return the model.

    The function can be used as a decorator or directly:

    ```python
    register_ir(PhotoEditRecipeV1)
    ```
    """

    version = schema_version or _schema_version_from_model(model)
    _REGISTRY[version] = model
    return model


def get_ir_model(schema_version: str) -> type[BaseModel]:
    try:
        return _REGISTRY[schema_version]
    except KeyError as exc:
        raise KeyError(f"unknown IR schema version: {schema_version}") from exc


def validate_ir_body(schema_version: str, payload: object) -> BaseModel:
    """Validate a payload using a registered IR model."""

    return get_ir_model(schema_version).model_validate(payload)


def export_json_schema(schema_version: str) -> dict[str, object]:
    """Export JSON Schema for a registered IR model."""

    return get_ir_model(schema_version).model_json_schema()


def registered_ir_versions() -> list[str]:
    return sorted(_REGISTRY)


def _schema_version_from_model(model: type[BaseModel]) -> str:
    field = model.model_fields.get("schema_version")
    default = getattr(field, "default", None)
    if not isinstance(default, str):
        raise ValueError(f"{model.__name__} must define a string default for schema_version")
    return default
