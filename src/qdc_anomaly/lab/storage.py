"""Small append-only evidence files and atomic control messages."""

from __future__ import annotations

import hashlib
import json
import os
from collections import deque
from pathlib import Path


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, allow_nan=False), encoding="utf-8")
    os.replace(temporary, path)


def append_event(path: Path, event: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, allow_nan=False) + "\n")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_events(path: Path, limit: int = 4000) -> tuple[list[dict], int]:
    if not path.exists():
        return [], 0
    records, bad = [], 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        lines = deque(handle, maxlen=limit)
    for line in lines:
        if not line.endswith("\n"):
            continue  # writer may still be appending the last line
        if line.startswith("#") or not line.strip():
            continue
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("Expected object")
            records.append(record)
        except (ValueError, TypeError):
            bad += 1
    return records, bad


def evidence_id(source: str, record: dict) -> str:
    digest = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()[:16]
    return f"{source}:{digest}"
