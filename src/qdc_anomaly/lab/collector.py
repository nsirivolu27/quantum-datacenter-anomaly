"""Join independent observations by time and identity; keep raw evidence accessible."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from qdc_anomaly.lab.adapters import CollectionContext, SourceAdapter, default_adapters
from qdc_anomaly.lab.analytics import GPUAnalytics
from qdc_anomaly.lab.config import LabConfig, current_phase
from qdc_anomaly.lab.framework import SecurityFramework, TelemetryBatch
from qdc_anomaly.lab.storage import evidence_id, read_events, read_json


class Collector:
    def __init__(
        self,
        config: LabConfig,
        root: Path,
        adapters: dict[str, SourceAdapter] | None = None,
        framework: SecurityFramework | None = None,
        security_source: Callable[[float], tuple[list[dict], int]] | None = None,
    ):
        self.config, self.root = config, root
        # Optional: a callable returning (audit-derived observations, bad record count)
        # for this run. Without one the data-security pack simply sees no observations.
        self.security_source = security_source
        self.analytics = GPUAnalytics(config.window_samples)
        self.framework = framework or SecurityFramework(config)
        self.adapters = default_adapters() if adapters is None else adapters
        if set(self.adapters) != {"gpu", "zeek", "opencanary"}:
            raise ValueError("Supply adapters for the gpu, zeek, and opencanary contracts")

    def snapshot(self) -> dict:
        now = time.time()
        control = read_json(self.root / "control.json")
        inventory_path = self.root / "inventory.json"
        inventory = read_json(inventory_path) if inventory_path.exists() else {}
        context = CollectionContext(
            self.root, control["run_id"], control["started_at"], inventory.get("worker", "")
        )
        sources = {name: adapter.read(context) for name, adapter in self.adapters.items()}
        gpu, flows, hits = (sources[name].records for name in ("gpu", "zeek", "opencanary"))
        markers, _ = read_events(self.root / "presenter.jsonl")
        markers = [m for m in markers if m.get("run_id") == control["run_id"]]
        clients, _ = read_events(self.root / "worker.jsonl")
        clients = [c for c in clients if c.get("run_id") == control["run_id"]]
        phase, complete = current_phase(control, now, self.config)
        security, security_bad = [], 0
        if self.security_source is not None:
            security, security_bad = self.security_source(control["started_at"])
        findings = self.framework.analyze(TelemetryBatch(gpu, flows, hits, inventory, security))
        evidence = [
            {
                "id": evidence_id("gpu-simulator", g),
                "ts": g["ts"],
                "source": "gpu-simulator",
                "raw": g,
            }
            for g in gpu
        ]
        evidence += flows + hits + security
        evidence.sort(key=lambda e: e["ts"])
        recent_flows = [f for f in flows if f["ts"] >= now - 8]
        return {
            "schema_version": 1,
            "generated_at": now,
            "framework": self.framework.describe(),
            "control": control,
            "phase": phase,
            "complete": complete,
            "inventory": inventory,
            "gpu": gpu[-120:],
            "model": self.analytics.score(gpu),
            "findings": findings,
            "flows": flows[-120:],
            "honeypot_hits": hits[-40:],
            "security": {
                "observations": security[-40:],
                "source": "audit log" if self.security_source is not None else "none",
                "bad_records": security_bad,
            },
            "markers": markers,
            "evidence": evidence[-1500:],
            "counts": {
                "flows": len(flows),
                "canary": len(hits),
                "gpu_samples": len(gpu),
                "bytes": sum(f["bytes"] for f in flows),
            },
            "activity": {
                name: sum(f["dst"] == ip for f in recent_flows)
                for name, ip in inventory.items()
                if name != "worker"
            },
            "worker_requests": clients[-15:],
            "health": {
                "gpu": {
                    "state": "live"
                    if gpu and now - gpu[-1]["ts"] < self.config.stale_seconds
                    else "waiting / stale",
                    "bad_records": sources["gpu"].bad_records,
                    "kind": "simulated",
                },
                "zeek": {
                    "state": "live" if flows and now - flows[-1]["ts"] < 15 else "waiting / stale",
                    "bad_records": sources["zeek"].bad_records,
                    "kind": "real packet capture",
                },
                "opencanary": {
                    "state": "log available"
                    if sources["opencanary"].raw_count
                    else "waiting for log",
                    "bad_records": sources["opencanary"].bad_records,
                    "kind": "real decoy events",
                },
            },
        }
