"""Fixed-field JSONL audit records.

This is an ordinary append-only file. Anyone who can write to it can edit it, so it
is a record of what the guarded store decided, not tamper-proof evidence. Records
never contain asset contents, key material, or credentials: the dataclass below is
the whole schema, and ``detail`` is a short free-text reason.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from qdc_anomaly.lab.storage import append_event, read_events

OUTCOMES = (
    "ok",
    "denied",
    "modified",
    "missing",
    "unexpected",
    "escaped",
    "unapproved",
    "auth-failed",
    "error",
)
DETAIL_LIMIT = 300


@dataclass(frozen=True)
class AuditRecord:
    actor: str
    operation: str  # read, write, approve, verify, seal, verify-evidence
    decision: str  # allow, deny, n/a
    outcome: str  # one of OUTCOMES
    asset_id: str | None = None
    baseline_version: int | None = None
    evidence_ids: list[str] = field(default_factory=list)
    detail: str = ""
    node_id: str | None = None  # simulated workload identity, when the caller supplies one
    job_id: str | None = None
    ts: float = field(default_factory=time.time)
    source: str = "audit"

    def __post_init__(self):
        if self.outcome not in OUTCOMES:
            raise ValueError(f"Unknown audit outcome {self.outcome!r}")
        if self.decision not in {"allow", "deny", "n/a"}:
            raise ValueError(f"Unknown audit decision {self.decision!r}")
        if len(self.detail) > DETAIL_LIMIT:
            object.__setattr__(self, "detail", self.detail[:DETAIL_LIMIT])


class AuditLog:
    def __init__(self, path: Path):
        self.path = Path(path)

    def record(self, entry: AuditRecord) -> dict:
        row = asdict(entry)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        append_event(self.path, row)
        return row

    def read(self, limit: int = 4000) -> list[dict]:
        records, _ = read_events(self.path, limit)
        return records
