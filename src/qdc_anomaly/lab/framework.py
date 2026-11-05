"""Reusable analysis pipeline. The browser and scenario runner are optional clients."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from qdc_anomaly.lab.config import LabConfig
from qdc_anomaly.lab.detection import detect
from qdc_anomaly.lab.storage import evidence_id
from qdc_anomaly.security.findings import data_security_rules


@dataclass(frozen=True)
class TelemetryBatch:
    """Normalized inputs supplied by collectors, replay files, or another application."""

    gpu: list[dict] = field(default_factory=list)
    flows: list[dict] = field(default_factory=list)
    honeypot: list[dict] = field(default_factory=list)
    inventory: dict = field(default_factory=dict)
    security: list[dict] = field(default_factory=list)  # audit-derived observations


@dataclass(frozen=True)
class RulePack:
    id: str
    description: str
    evaluate: Callable[[TelemetryBatch, LabConfig], list[dict]]


def local_rules(batch: TelemetryBatch, config: LabConfig) -> list[dict]:
    return detect(batch.gpu, batch.flows, batch.honeypot, batch.inventory, config)


DEFAULT_PACK = RulePack(
    "datacenter-v1",
    "Thermal threshold, job attribution, decoy contact, port diversity, periodic connections, and outbound volume",
    local_rules,
)


def correlate_compute(batch: TelemetryBatch, config: LabConfig) -> list[dict]:
    """Join unexpected GPU use and outbound transfers within a bounded time window."""
    gpu = [
        g
        for g in batch.gpu
        if g["gpu_util_percent"] >= config.unapproved_gpu_percent
        and not g["job_approved"]
        and g.get("node_id") == config.worker_node_id
    ]
    allowed = {batch.inventory.get("api"), batch.inventory.get("canary")}
    matches = []
    for flow in batch.flows:
        if (
            flow["src"] != batch.inventory.get("worker")
            or flow["dst"] in allowed
            or flow["bytes"] < config.transfer_bytes
        ):
            continue
        nearby = [g for g in gpu if abs(g["ts"] - flow["ts"]) <= config.correlation_seconds]
        if nearby:
            matches.append((flow, min(nearby, key=lambda g: abs(g["ts"] - flow["ts"]))))
    if not matches:
        return []
    ids = []
    for flow, sample in matches[-6:]:
        ids.extend([flow["id"], evidence_id("gpu-simulator", sample)])
    return [
        {
            "rule": "compute-network-overlap",
            "category": "investigate",
            "title": "Unapproved compute overlaps an unusual transfer",
            "explanation": f"Unapproved simulated GPU activity occurred within {config.correlation_seconds:g}s "
            f"of a Zeek connection carrying at least {config.transfer_bytes} combined bytes to an unapproved peer. "
            "This joins independent sources in time; it does not prove exfiltration or causation.",
            "first_seen": min(f["ts"] for f, _ in matches),
            "last_seen": max(f["ts"] for f, _ in matches),
            "count": len(matches),
            "source": "gpu-simulator + zeek",
            "evidence_ids": list(dict.fromkeys(ids)),
        }
    ]


CORRELATION_PACK = RulePack(
    "compute-network-v1",
    "Correlate unapproved GPU activity and unusual transfers within a time window",
    correlate_compute,
)


DATA_SECURITY_PACK = RulePack(
    "data-security-v1",
    "Access-policy denials, integrity failures, node/time overlap with unapproved compute, and asset reads followed by transfers",
    data_security_rules,
)


class SecurityFramework:
    """Compose explicit rule packs without importing a web server or running traffic."""

    def __init__(self, config: LabConfig, packs: tuple[RulePack, ...] | None = None):
        if packs is None:
            available = {p.id: p for p in (DEFAULT_PACK, CORRELATION_PACK, DATA_SECURITY_PACK)}
            names = list(available) if config.enabled_packs is None else config.enabled_packs
            if not isinstance(names, list) or any(name not in available for name in names):
                raise ValueError("Unknown built-in rule pack")
            packs = tuple(available[name] for name in names)
        identifiers = [pack.id for pack in packs]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Rule pack identifiers must be unique")
        self.config, self.packs = config, packs

    def analyze(self, batch: TelemetryBatch) -> list[dict]:
        findings = []
        for pack in self.packs:
            for result in pack.evaluate(batch, self.config):
                findings.append({**result, "rule_pack": pack.id})
        return sorted(findings, key=lambda finding: finding["first_seen"])

    def describe(self) -> dict:
        return {
            "name": "Sentinel",
            "version": 1,
            "stages": [
                {
                    "id": "sources",
                    "name": "Collect",
                    "contract": "Source JSON records",
                    "detail": "Zeek connection logs, OpenCanary service events, simulated GPU observations, and local audit records.",
                },
                {
                    "id": "normalize",
                    "name": "Normalize",
                    "contract": "TelemetryBatch",
                    "detail": "Filter by time and worker identity, validate fields, deduplicate, and preserve raw evidence.",
                },
                {
                    "id": "analyze",
                    "name": "Analyze",
                    "contract": "RulePack → findings",
                    "detail": "Run explicit rule packs and the existing QDC window model. Scenario names are excluded.",
                },
                {
                    "id": "evidence",
                    "name": "Investigate",
                    "contract": "Finding + evidence IDs",
                    "detail": "Trace a finding to original observations and export the run for review.",
                },
                {
                    "id": "response",
                    "name": "Respond",
                    "contract": "Manual review boundary",
                    "detail": "Review evidence and choose next steps. Automated containment is not implemented.",
                },
            ],
            "rule_packs": [{"id": p.id, "description": p.description} for p in self.packs],
            "response": {"mode": "observe-only", "automated_containment": False},
            "thresholds": {
                "thermal_c": self.config.thermal_c,
                "unapproved_gpu_percent": self.config.unapproved_gpu_percent,
                "port_threshold": self.config.port_threshold,
                "beacon_min_connections": self.config.beacon_min_connections,
                "beacon_max_cv": self.config.beacon_max_cv,
                "transfer_bytes": self.config.transfer_bytes,
                "correlation_seconds": self.config.correlation_seconds,
                "volume_window_seconds": self.config.volume_window_seconds,
                "volume_bytes": self.config.volume_bytes,
                "exfil_window_seconds": self.config.exfil_window_seconds,
            },
        }
