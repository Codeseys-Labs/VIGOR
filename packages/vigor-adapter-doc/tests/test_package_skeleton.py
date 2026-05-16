"""Smoke tests for the vigor-adapter-doc package skeleton.

The IR schemas, adapter, compile path, and reviewers are filled in by
follow-up Seeds tasks rooted at VIGOR-c916. These tests only assert
that the package is importable, advertises a version, and ships a
``py.typed`` marker so PEP 561 consumers see the type hints once they
exist.
"""

from __future__ import annotations

import importlib.resources

import vigor_adapter_doc


def test_version_is_published() -> None:
    assert vigor_adapter_doc.__version__ == "0.1.0"


def test_public_api_is_empty_until_ir_lands() -> None:
    assert vigor_adapter_doc.__all__ == []


def test_ships_py_typed_marker() -> None:
    marker = importlib.resources.files(vigor_adapter_doc).joinpath("py.typed")
    assert marker.is_file()
