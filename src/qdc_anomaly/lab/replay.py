"""Replay an exported evidence snapshot through the same framework without Docker."""

from __future__ import annotations

from pathlib import Path

from qdc_anomaly.lab.adapters import CollectionContext, normalize_gpu
from qdc_anomaly.lab.config import LabConfig
from qdc_anomaly.lab.detection import normalize_canary, normalize_flows
from qdc_anomaly.lab.framework import SecurityFramework, TelemetryBatch
from qdc_anomaly.security.findings import normalize_security


def replay(snapshot: dict, config: LabConfig) -> dict:
    if snapshot.get("schema_version", 1) != 1:
        raise ValueError("Unsupported evidence schema")
    control, inventory = snapshot["control"], snapshot["inventory"]
    context = CollectionContext(
        Path("."), control["run_id"], control["started_at"], inventory["worker"]
    )
    records = snapshot["evidence"]
    gpu, gpu_bad = normalize_gpu(
        [e["raw"] for e in records if e["source"] == "gpu-simulator"], context
    )
    flows, flow_bad = normalize_flows(
        [e["raw"] for e in records if e["source"] == "zeek"], context.started_at, context.worker_ip
    )
    hits, canary_bad = normalize_canary(
        [e["raw"] for e in records if e["source"] == "opencanary"],
        context.started_at,
        context.worker_ip,
    )
    security, security_bad = normalize_security(
        [e["raw"] for e in records if e["source"] == "audit"], context.started_at
    )
    framework = SecurityFramework(config)
    return {
        "schema_version": 1,
        "mode": "offline-replay",
        "run_id": context.run_id,
        "framework": framework.describe(),
        "counts": {
            "gpu": len(gpu),
            "flows": len(flows),
            "honeypot": len(hits),
            "security": len(security),
        },
        "bad_records": gpu_bad + flow_bad + canary_bad + security_bad,
        "findings": framework.analyze(TelemetryBatch(gpu, flows, hits, inventory, security)),
        "scope": "Only the records retained in the exported snapshot are replayed.",
    }
