"""Replaceable source adapters, keeping collection separate from rule evaluation."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from qdc_anomaly.lab.detection import normalize_canary, normalize_flows
from qdc_anomaly.lab.simulator import GPU_COLUMNS
from qdc_anomaly.lab.storage import read_events


@dataclass(frozen=True)
class CollectionContext:
    root: Path
    run_id: str
    started_at: float
    worker_ip: str


@dataclass
class SourceResult:
    records: list[dict]
    bad_records: int
    raw_count: int


class SourceAdapter(Protocol):
    def read(self, context: CollectionContext) -> SourceResult: ...


@dataclass(frozen=True)
class JsonlAdapter:
    path: str
    normalize: Callable[[list[dict], CollectionContext], tuple[list[dict], int]]

    def read(self, context: CollectionContext) -> SourceResult:
        raw, bad = read_events(context.root / self.path)
        records, rejected = self.normalize(raw, context)
        return SourceResult(records, bad + rejected, len(raw))


def normalize_gpu(records: list[dict], context: CollectionContext) -> tuple[list[dict], int]:
    gpu, bad = [], 0
    for row in records:
        if row.get("run_id") != context.run_id:
            continue
        try:
            if not all(
                type(row[c]) in (int, float) and math.isfinite(row[c]) for c in ["ts", *GPU_COLUMNS]
            ):
                raise ValueError("Invalid numeric observation")
            if type(row["job_approved"]) is not bool or not row.get("node_id"):
                raise ValueError("Invalid workload attribution")
            gpu.append(row)
        except (ValueError, TypeError, KeyError):
            bad += 1
    return sorted(gpu, key=lambda row: row["ts"]), bad


def zeek_records(records, context):
    return normalize_flows(records, context.started_at, context.worker_ip)


def canary_records(records, context):
    return normalize_canary(records, context.started_at, context.worker_ip)


def default_adapters() -> dict[str, SourceAdapter]:
    return {
        "gpu": JsonlAdapter("gpu.jsonl", normalize_gpu),
        "zeek": JsonlAdapter("zeek/conn.log", zeek_records),
        "opencanary": JsonlAdapter("canary/events.jsonl", canary_records),
    }
