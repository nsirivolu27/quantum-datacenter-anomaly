import random

import pytest

from qdc_anomaly.lab.adapters import SourceResult
from qdc_anomaly.lab.collector import Collector
from qdc_anomaly.lab.config import LabConfig
from qdc_anomaly.lab.detection import normalize_flows
from qdc_anomaly.lab.framework import RulePack, SecurityFramework, TelemetryBatch
from qdc_anomaly.lab.replay import replay
from qdc_anomaly.lab.simulator import gpu_sample
from qdc_anomaly.lab.storage import evidence_id, write_json


def overlapping_batch():
    inventory = {"worker": "172.20.0.2", "api": "172.20.0.3", "canary": "172.20.0.4"}
    gpu = gpu_sample("misuse", random.Random(1), 100, "run")
    raw = {
        "ts": 102,
        "uid": "Ctransfer",
        "id.orig_h": inventory["worker"],
        "id.resp_h": "172.20.0.5",
        "id.resp_p": 8080,
        "orig_bytes": 66000,
    }
    flows, _ = normalize_flows([raw], 0, inventory["worker"])
    return TelemetryBatch([gpu], flows, [], inventory)


def test_correlation_joins_real_flow_evidence_and_simulated_gpu_evidence():
    batch = overlapping_batch()
    findings = SecurityFramework(LabConfig()).analyze(batch)
    (correlation,) = [f for f in findings if f["rule"] == "compute-network-overlap"]
    assert correlation["rule_pack"] == "compute-network-v1"
    assert set(correlation["evidence_ids"]) == {
        batch.flows[0]["id"],
        evidence_id("gpu-simulator", batch.gpu[0]),
    }
    assert "does not prove" in correlation["explanation"]


@pytest.mark.parametrize(
    "mismatch", ["time", "gpu_identity", "network_identity", "approved_peer", "small_transfer"]
)
def test_correlation_does_not_join_unrelated_observations(mismatch):
    batch = overlapping_batch()
    if mismatch == "time":
        batch.flows[0]["ts"] = 200
    elif mismatch == "gpu_identity":
        batch.gpu[0]["node_id"] = "different-worker"
    elif mismatch == "network_identity":
        batch.flows[0]["src"] = "different-ip"
    elif mismatch == "approved_peer":
        batch.flows[0]["dst"] = batch.inventory["api"]
    else:
        batch.flows[0]["bytes"] = 20
    assert not any(
        f["rule"] == "compute-network-overlap"
        for f in SecurityFramework(LabConfig()).analyze(batch)
    )


def test_rule_pack_selection_and_custom_pack_are_actual_execution_boundaries():
    batch = overlapping_batch()
    engine = SecurityFramework(LabConfig(enabled_packs=["datacenter-v1"]))
    assert not any(f["rule"] == "compute-network-overlap" for f in engine.analyze(batch))
    called = []

    def custom_rule(received, config):
        called.append(received)
        return [{"rule": "custom", "first_seen": 1, "evidence_ids": [received.flows[0]["id"]]}]

    custom = RulePack("custom-pack", "Application-specific rule", custom_rule)
    (result,) = SecurityFramework(LabConfig(), (custom,)).analyze(batch)
    assert called == [batch] and result["rule_pack"] == "custom-pack"
    assert SecurityFramework(LabConfig(enabled_packs=[])).analyze(batch) == []
    with pytest.raises(ValueError, match="unique"):
        SecurityFramework(LabConfig(), (custom, custom))
    with pytest.raises(ValueError, match="Unknown"):
        SecurityFramework(LabConfig(enabled_packs=["typo"]))


def test_replacement_source_adapter_runs_without_a_simulator_or_browser(tmp_path):
    write_json(tmp_path / "control.json", {"mode": "baseline", "run_id": "run", "started_at": 0})
    row = gpu_sample("thermal", random.Random(1), 100, "run")

    class MemoryAdapter:
        def __init__(self, records):
            self.records = records

        def read(self, context):
            assert context.run_id == "run"
            return SourceResult(self.records, 0, len(self.records))

    adapters = {
        "gpu": MemoryAdapter([row]),
        "zeek": MemoryAdapter([]),
        "opencanary": MemoryAdapter([]),
    }
    report = Collector(LabConfig(), tmp_path, adapters=adapters).snapshot()
    assert report["findings"][0]["rule"] == "thermal"
    assert report["counts"]["gpu_samples"] == 1
    assert report["schema_version"] == 1


def test_offline_replay_recomputes_from_raw_evidence_instead_of_saved_findings():
    batch = overlapping_batch()
    snapshot = {
        "schema_version": 1,
        "control": {"run_id": "run", "started_at": 0},
        "inventory": batch.inventory,
        "findings": [{"rule": "fabricated"}],
        "evidence": [
            {"source": "gpu-simulator", "raw": batch.gpu[0]},
            {"source": "zeek", "raw": batch.flows[0]["raw"]},
        ],
    }
    result = replay(snapshot, LabConfig())
    assert result["findings"] == SecurityFramework(LabConfig()).analyze(batch)
    assert result["bad_records"] == 0
    assert result["mode"] == "offline-replay"
    with pytest.raises(ValueError, match="schema"):
        replay({**snapshot, "schema_version": 9}, LabConfig())
