"""YAML/JSON loader for `AgentConfig`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from vigor_core.agent_config import AgentConfig


def load_agent_config(path: str | Path) -> AgentConfig:
    """Load an `AgentConfig` from a ``.yaml``/``.yml``/``.json`` file."""

    p = Path(path)
    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()
    payload: Any
    if suffix in {".yaml", ".yml"}:
        payload = yaml.safe_load(text)
    elif suffix == ".json":
        payload = json.loads(text)
    else:
        raise ValueError(
            f"unsupported config file extension {suffix!r}; expected .yaml, .yml, or .json"
        )
    if not isinstance(payload, dict):
        raise ValueError(f"agent config root must be a mapping, got {type(payload).__name__}")
    return AgentConfig.model_validate(payload)
