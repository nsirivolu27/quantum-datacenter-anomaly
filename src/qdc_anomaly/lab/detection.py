"""Explainable findings derived from sensor records, never presenter phase labels."""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, pstdev

from qdc_anomaly.lab.config import LabConfig
from qdc_anomaly.lab.storage import evidence_id


def timestamp(value) -> float:
    if isinstance(value, str):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=result.tzinfo or timezone.utc).timestamp()
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite timestamp")
    return result


def normalize_flows(records: list[dict], start: float, worker_ip: str) -> tuple[list[dict], int]:
    flows, bad, seen = [], 0, set()
    for raw in records:
        try:
            ts = timestamp(raw["ts"])
            port = int(raw["id.resp_p"])
            if not 0 <= port <= 65535:
                raise ValueError("Invalid port")
            uid = str(raw["uid"])
            if ts < start or raw["id.orig_h"] != worker_ip or uid in seen:
                continue
            byte_count = int(raw.get("orig_bytes", 0)) + int(raw.get("resp_bytes", 0))
            if byte_count < 0:
                raise ValueError("Negative bytes")
            flows.append(
                {
                    "id": evidence_id("zeek", raw),
                    "ts": ts,
                    "source": "zeek",
                    "src": raw["id.orig_h"],
                    "dst": str(raw["id.resp_h"]),
                    "port": port,
                    "bytes": byte_count,
                    "state": str(raw.get("conn_state", "unknown")),
                    "raw": raw,
                }
            )
            seen.add(uid)
        except (KeyError, ValueError, TypeError, OverflowError):
            bad += 1
    return sorted(flows, key=lambda f: f["ts"]), bad


def normalize_canary(records: list[dict], start: float, worker_ip: str) -> tuple[list[dict], int]:
    hits, bad, seen = [], 0, set()
    for raw in records:
        if not raw.get("src_host") or raw.get("src_host") != worker_ip:
            continue  # OpenCanary startup events are not intrusions
        try:
            ts = timestamp(raw.get("utc_time") or raw["local_time"])
            identifier = evidence_id("opencanary", raw)
            if ts < start or identifier in seen:
                continue
            hits.append(
                {
                    "id": identifier,
                    "ts": ts,
                    "source": "opencanary",
                    "src": raw["src_host"],
                    "port": int(raw["dst_port"]),
                    "logtype": int(raw["logtype"]),
                    "raw": raw,
                }
            )
            seen.add(identifier)
        except (KeyError, ValueError, TypeError, OverflowError):
            bad += 1
    return sorted(hits, key=lambda h: h["ts"]), bad


def detect(
    gpu: list[dict], flows: list[dict], hits: list[dict], inventory: dict, config: LabConfig
) -> list[dict]:
    findings = []

    def add(rule, category, title, explanation, records, source):
        findings.append(
            {
                "rule": rule,
                "category": category,
                "title": title,
                "explanation": explanation,
                "first_seen": min(r["ts"] for r in records),
                "last_seen": max(r["ts"] for r in records),
                "count": len(records),
                "source": source,
                "evidence_ids": [r.get("id") or evidence_id(source, r) for r in records[-12:]],
            }
        )

    hot = [g for g in gpu if g["gpu_temp_c"] >= config.thermal_c]
    if hot:
        add(
            "thermal",
            "operational",
            "Thermal anomaly",
            f"Simulated GPU temperature reached {max(g['gpu_temp_c'] for g in hot):.1f} °C; "
            f"the operational threshold is {config.thermal_c:g} °C. This is not proof of an attack.",
            hot,
            "gpu-simulator",
        )
    unexpected = [
        g
        for g in gpu
        if g["gpu_util_percent"] >= config.unapproved_gpu_percent and not g["job_approved"]
    ]
    if unexpected:
        add(
            "unapproved-compute",
            "investigate",
            "Compute activity without an approved job",
            f"GPU use exceeded {config.unapproved_gpu_percent:g}% without an approved job in the simulated registry. "
            "Check job attribution before concluding misuse.",
            unexpected,
            "gpu-simulator",
        )
    if hits:
        add(
            "honeypot-contact",
            "security",
            "Internal decoy accessed",
            "OpenCanary recorded traffic from the worker. The declared workload policy has no reason "
            "to contact this decoy; inspect the original service event.",
            hits,
            "opencanary",
        )

    # Find port diversity in a real 20-second event-time window, not across the entire run.
    for i, flow in enumerate(flows):
        window = [
            f for f in flows[: i + 1] if f["dst"] == flow["dst"] and f["ts"] >= flow["ts"] - 20
        ]
        ports = {f["port"] for f in window}
        if len(ports) >= config.port_threshold:
            add(
                "port-spread",
                "security",
                "Multiple destination ports probed",
                f"Zeek observed {len(ports)} distinct ports on {flow['dst']} in 20 seconds. "
                "Connection attempts do not imply successful access.",
                window,
                "zeek",
            )
            break

    # Sustained volume: combined bytes to one unapproved peer inside a sliding window.
    approved = {inventory.get("api"), inventory.get("canary")}
    by_destination = defaultdict(list)
    for flow in flows:
        if flow["dst"] not in approved:
            by_destination[flow["dst"]].append(flow)
    for destination, group in by_destination.items():
        for end, flow in enumerate(group):
            window = [
                f for f in group[: end + 1] if f["ts"] >= flow["ts"] - config.volume_window_seconds
            ]
            total = sum(f["bytes"] for f in window)
            if total >= config.volume_bytes:
                add(
                    "outbound-volume",
                    "investigate",
                    "Sustained transfer volume to an unapproved peer",
                    f"{total} combined bytes moved between the worker and {destination} across "
                    f"{len(window)} connections within {config.volume_window_seconds:g}s; the threshold "
                    f"is {config.volume_bytes}. Bytes count both directions and the content is "
                    "unknown, so this is volume to review, not confirmed exfiltration.",
                    window,
                    "zeek",
                )
                break

    groups = defaultdict(list)
    for flow in flows:
        if flow["dst"] not in approved:
            groups[(flow["dst"], flow["port"])].append(flow)
    for (destination, port), group in groups.items():
        for end in range(config.beacon_min_connections, len(group) + 1):
            window = group[max(0, end - 10) : end]
            intervals = [b["ts"] - a["ts"] for a, b in zip(window, window[1:], strict=False)]
            if min(intervals) <= 0 or mean(intervals) > 30:
                continue
            variation = pstdev(intervals) / mean(intervals)
            if variation <= config.beacon_max_cv:
                add(
                    "periodic-connection",
                    "investigate",
                    "Beacon-like connection pattern",
                    f"{len(window)} connections to {destination}:{port}; mean spacing {mean(intervals):.1f}s, "
                    f"variation {variation:.2f}. Destination is outside the approved API policy. "
                    "Regular traffic can be benign; this is a candidate, not confirmed C2.",
                    window,
                    "zeek",
                )
                break
    return sorted(findings, key=lambda finding: finding["first_seen"])
