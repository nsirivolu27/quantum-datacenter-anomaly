"""Turn audit records into observations and evaluate the data-security rule pack.

Three findings stay separate on purpose:

- ``access-policy-violation``: a request the guarded store denied. The store blocked
  it, so this is a policy violation, not a confirmed incident.
- ``integrity-failure``: an asset or manifest did not verify against the approved
  baseline. Something changed; who changed it is not established.
- ``evidence-verification-failure``: a sealed bundle did not verify.

Two correlation rules join these with other sources only when identity and timing
agree: ``compute-policy-overlap`` (denied or failing asset event beside unapproved
GPU activity on the same node) and ``asset-read-then-transfer`` (an allowed read of
a dataset or model followed by a large transfer from the same node to an
unapproved peer). Successful reads are kept as observations for that second rule
and never produce a finding on their own.
"""

from __future__ import annotations

import math
from pathlib import Path

from qdc_anomaly.lab.storage import evidence_id, read_events

SOURCE = "audit"
VIOLATION_OUTCOMES = {"denied"}
INTEGRITY_OUTCOMES = {"modified", "missing", "unexpected", "escaped", "unapproved", "auth-failed"}


def normalize_security(records: list[dict], start: float) -> tuple[list[dict], int]:
    """Keep audit rows that describe a denial or a failed verification."""
    observations, bad, seen = [], 0, set()
    for raw in records:
        try:
            ts = float(raw["ts"])
            if not math.isfinite(ts):
                raise ValueError("Non-finite timestamp")
            outcome, operation = str(raw["outcome"]), str(raw["operation"])
            actor = str(raw["actor"])
        except (KeyError, ValueError, TypeError):
            bad += 1
            continue
        if ts < start or (outcome == "ok" and operation != "read"):
            continue
        identifier = evidence_id(SOURCE, raw)
        if identifier in seen:
            continue
        seen.add(identifier)
        observations.append(
            {
                "id": identifier,
                "ts": ts,
                "source": SOURCE,
                "actor": actor,
                "operation": operation,
                "outcome": outcome,
                "asset_id": raw.get("asset_id"),
                "node_id": raw.get("node_id"),
                "baseline_version": raw.get("baseline_version"),
                "raw": raw,
            }
        )
    return sorted(observations, key=lambda o: o["ts"]), bad


def _finding(rule, category, title, explanation, records):
    return {
        "rule": rule,
        "category": category,
        "title": title,
        "explanation": explanation,
        "first_seen": min(r["ts"] for r in records),
        "last_seen": max(r["ts"] for r in records),
        "count": len(records),
        "source": SOURCE,
        "evidence_ids": [r["id"] for r in records[-12:]],
    }


def data_security_rules(batch, config) -> list[dict]:
    observations = list(getattr(batch, "security", []))
    findings = []
    reads = [o for o in observations if o["outcome"] == "ok" and o["operation"] == "read"]
    observations = [o for o in observations if o not in reads]
    denied = [o for o in observations if o["outcome"] in VIOLATION_OUTCOMES]
    if denied:
        assets = sorted({str(o["asset_id"]) for o in denied})
        findings.append(
            _finding(
                "access-policy-violation",
                "investigate",
                "Request denied by the access policy",
                f"The guarded store denied {len(denied)} request(s) on {', '.join(assets)}. "
                "The actor label is simulated and the request was blocked, so this is a policy "
                "violation to review, not a confirmed incident.",
                denied,
            )
        )
    integrity = [
        o
        for o in observations
        if o["outcome"] in INTEGRITY_OUTCOMES and o["operation"] != "verify-evidence"
    ]
    if integrity:
        outcomes = sorted({o["outcome"] for o in integrity})
        findings.append(
            _finding(
                "integrity-failure",
                "security",
                "Asset or baseline failed integrity verification",
                f"Verification against the approved baseline reported {', '.join(outcomes)}. "
                "Content differs from what was approved; this does not identify who changed it "
                "or whether the change was malicious.",
                integrity,
            )
        )
    evidence = [o for o in observations if o["operation"] == "verify-evidence"]
    if evidence:
        findings.append(
            _finding(
                "evidence-verification-failure",
                "security",
                "Exported evidence failed authentication",
                "A sealed evidence bundle did not verify. Treat its contents as unverified; "
                "verification cannot say whether the original sensors reported truthfully.",
                evidence,
            )
        )
    # Correlation: same simulated node, unapproved GPU use, within the configured window.
    unapproved = [
        g
        for g in batch.gpu
        if g["gpu_util_percent"] >= config.unapproved_gpu_percent and not g["job_approved"]
    ]
    joined = []
    for observation in denied + integrity:
        if not observation.get("node_id"):
            continue
        nearby = [
            g
            for g in unapproved
            if g.get("node_id") == observation["node_id"]
            and abs(g["ts"] - observation["ts"]) <= config.correlation_seconds
        ]
        if nearby:
            joined.append(
                (observation, min(nearby, key=lambda g: abs(g["ts"] - observation["ts"])))
            )
    if joined:
        records = [o for o, _ in joined]
        finding = _finding(
            "compute-policy-overlap",
            "investigate",
            "Asset event overlaps unapproved compute on the same node",
            f"A denied or failing asset request carrying node identity occurred within "
            f"{config.correlation_seconds:g}s of unapproved simulated GPU activity on that node. "
            "Node identity and time overlap; this does not prove the same process did both.",
            records,
        )
        finding["source"] = "audit + gpu-simulator"
        for _, sample in joined[-6:]:
            finding["evidence_ids"].append(evidence_id("gpu-simulator", sample))
        finding["evidence_ids"] = list(dict.fromkeys(finding["evidence_ids"]))
        findings.append(finding)
    findings.extend(read_then_transfer(reads, batch, config))
    return findings


def read_then_transfer(reads: list[dict], batch, config) -> list[dict]:
    """An allowed dataset or model read, then a large transfer from the same node."""
    worker_ip = batch.inventory.get("worker")
    approved = {batch.inventory.get("api"), batch.inventory.get("canary")}
    sensitive = [
        r
        for r in reads
        if r.get("node_id") == config.worker_node_id
        and str(r.get("asset_id", "")).split(":")[0] in {"dataset", "model"}
    ]
    if not sensitive or not worker_ip:
        return []
    pairs = []
    for flow in batch.flows:
        if (
            flow["src"] != worker_ip
            or flow["dst"] in approved
            or flow["bytes"] < config.transfer_bytes
        ):
            continue
        before = [r for r in sensitive if 0 <= flow["ts"] - r["ts"] <= config.exfil_window_seconds]
        if before:
            pairs.append((max(before, key=lambda r: r["ts"]), flow))
    if not pairs:
        return []
    records = [r for r, _ in pairs]
    assets = sorted({str(r["asset_id"]) for r in records})
    finding = _finding(
        "asset-read-then-transfer",
        "investigate",
        "Asset read followed by a large transfer from the same node",
        f"An allowed read of {', '.join(assets)} by a workload on {config.worker_node_id} was "
        f"followed within {config.exfil_window_seconds:g}s by a connection carrying at least "
        f"{config.transfer_bytes} combined bytes to an unapproved peer. This is an ordered pair in "
        "time and node identity; it does not show that the asset's content was what moved.",
        records,
    )
    finding["source"] = "audit + zeek"
    finding["evidence_ids"].extend(flow["id"] for _, flow in pairs[-6:])
    finding["evidence_ids"] = list(dict.fromkeys(finding["evidence_ids"]))
    return [finding]


def audit_source(path):
    """Build a Collector ``security_source`` that reads a local audit log each snapshot."""
    path = Path(path)

    def read(started_at: float) -> tuple[list[dict], int]:
        raw, bad = read_events(path)
        observations, rejected = normalize_security(raw, started_at)
        return observations, bad + rejected

    return read
