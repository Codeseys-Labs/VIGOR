"""Small shared helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utcnow_iso() -> str:
    """ISO-8601 UTC timestamp with seconds precision and `Z` suffix."""

    return datetime.now(tz=UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    """SHA-256 hex digest of a byte string."""

    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    """SHA-256 hex digest of a text string (UTF-8)."""

    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    """SHA-256 hex digest of a file on disk, streamed."""

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def stable_json(obj: Any) -> str:
    """Deterministic JSON serialization useful for hashing."""

    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def safe_relative(path: Path, base: Path) -> str:
    """Return ``path`` expressed relative to ``base`` in POSIX form.

    If ``path`` is not inside ``base`` the absolute POSIX path is returned.
    Callers should treat absolute results as a signal that the artifact was
    produced outside the run archive and handle accordingly.
    """

    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()
