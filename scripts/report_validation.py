"""Offline validation shared by report summaries and the retrieval gate."""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any


def load_report(path: Path) -> dict[str, Any]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def has_context(context: Any) -> bool:
    """Require evidence text, not just a serialized container or metadata.

    Plaintext remains supported. Structured provider responses must contain
    nonblank text in sources, facts or results (Mem0), or a list of entries.
    Unknown structured objects fail closed rather than counting metadata.
    """
    if isinstance(context, str):
        if not context.strip():
            return False
        try:
            payload = json.loads(context)
        except json.JSONDecodeError:
            return True
        if isinstance(payload, str):
            return bool(payload.strip())
        context = payload
    if isinstance(context, dict):
        return any(
            _has_entries(context[key])
            for key in ("sources", "facts", "results") if key in context
        )
    return _has_entries(context)


def _has_entries(entries: Any) -> bool:
    if not isinstance(entries, list):
        return False
    for entry in entries:
        if isinstance(entry, str) and entry.strip():
            return True
        if isinstance(entry, dict) and any(
            isinstance(entry.get(key), str) and entry[key].strip()
            for key in ("text", "content", "memory")
        ):
            return True
    return False
