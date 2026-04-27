"""Schemas for VIGOR harness candidates and aggregate reports."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from vigor_core.util import utcnow_iso


class _HarnessBase(BaseModel):
    model_config = ConfigDict(
        strict=True,
        extra="forbid",
        populate_by_name=True,
        alias_generator=to_camel,
    )


class HarnessCandidate(_HarnessBase):
    schema_version: Literal["vigor.harness_candidate.v1"] = "vigor.harness_candidate.v1"
    candidate_id: str
    created_at: str = Field(default_factory=utcnow_iso)
    parent_candidate_id: str | None = None
    status: Literal["pending", "validated", "evaluated", "promoted", "rejected"] = "pending"
    hypothesis: str
    adapter_factory: str
    backend_factory: str
    policy_id: str = "default.v1"
    config: dict[str, str] = Field(default_factory=dict)
    allowed_factory_prefixes: list[str] = Field(default_factory=lambda: ["vigor_"])


class SplitManifest(_HarnessBase):
    schema_version: Literal["vigor.split_manifest.v1"] = "vigor.split_manifest.v1"
    split_id: str
    role: Literal["search", "validation", "heldout"]
    task_uris: list[str]


class HarnessEvalReport(_HarnessBase):
    schema_version: Literal["vigor.harness_eval_report.v1"] = "vigor.harness_eval_report.v1"
    candidate_id: str
    split_id: str
    n_tasks: int
    n_succeeded: int
    hard_gate_pass_rate: float
    accept_rate: float
    mean_composite: float | None = None
    regressions: list[str] = Field(default_factory=list)
