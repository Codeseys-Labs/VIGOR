"""Schema registry tests."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict
from vigor_core.registry import (
    export_json_schema,
    get_ir_model,
    register_ir,
    registered_ir_versions,
    validate_ir_body,
)


class TinyIR(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    schema_version: str = "tiny_ir.v1"
    kind: str = "tiny"
    value: str


def test_register_and_validate_ir_body() -> None:
    register_ir(TinyIR)
    assert get_ir_model("tiny_ir.v1") is TinyIR
    assert "tiny_ir.v1" in registered_ir_versions()
    obj = validate_ir_body("tiny_ir.v1", {"value": "ok"})
    assert isinstance(obj, TinyIR)
    schema = export_json_schema("tiny_ir.v1")
    assert schema["title"] == "TinyIR"


def test_unknown_ir_version_raises() -> None:
    with pytest.raises(KeyError):
        get_ir_model("missing.v1")
