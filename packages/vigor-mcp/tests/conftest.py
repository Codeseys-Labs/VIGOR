"""Per-package pytest configuration for ``vigor-mcp`` tests.

Why: the root ``pyproject.toml`` declares ``filterwarnings = ["error",
"ignore::ResourceWarning", ...]`` so the whole repo silences
ResourceWarnings. We lift that suppression *only here* so that any
unclosed subprocess, socket, or file handle in the MCP backend's
teardown path fails the test loudly. Scoping this via ``conftest.py``
(rather than ``[tool.pytest.ini_options]`` in this package's
``pyproject.toml``) is robust under uv-workspace + root-invocation:
pytest's per-package config discovery requires the package's
``pyproject.toml`` to be the closest ancestor of the test files, which
is fragile under root invocation.

The lift is applied per-item via the ``filterwarnings`` marker. Two
alternatives were ruled out:

* Module-level ``warnings.filterwarnings("error", ...)`` is silently
  shadowed by pytest's per-test ``catch_warnings`` block, which only
  re-applies ini filters and item-level markers.
* ``pytest_configure`` + ``addinivalue_line`` mutates the
  *session-global* filter list, which would leak the lift to every
  package's tests under default ``uv run pytest`` invocation -- the
  exact scope-creep we are trying to avoid.

Attaching the marker in ``pytest_collection_modifyitems`` keeps the
lift confined to test items collected from this directory tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(
    config: pytest.Config,
    items: list[pytest.Item],
) -> None:
    """Promote ResourceWarning to error for items under this directory only.

    The marker is reapplied inside pytest's per-test ``catch_warnings``
    block, so it survives the warning-state reset that shadows
    ``warnings.filterwarnings`` calls made at module import time.
    Items collected from sibling packages keep the root ini policy
    (``ignore::ResourceWarning``) untouched.
    """

    marker = pytest.mark.filterwarnings("error::ResourceWarning")
    for item in items:
        try:
            item_path = Path(str(item.fspath)).resolve()
        except (OSError, ValueError):
            continue
        if _THIS_DIR in item_path.parents or item_path == _THIS_DIR:
            item.add_marker(marker)
