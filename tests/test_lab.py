"""Evidence boundaries: load is not an attack and missing sensors never invent traffic."""

import random
import time

import pandas as pd
import pytest

from qdc_anomaly.config import FeatureConfig
from qdc_anomaly.features.windows import make_windows
from qdc_anomaly.lab.analytics import GPUAnalytics
from qdc_anomaly.lab.collector import Collector
from qdc_anomaly.lab.config import LabConfig, current_phase
from qdc_anomaly.lab.detection import detect, normalize_canary, normalize_flows
from qdc_anomaly.lab.simulator import GPU_COLUMNS, gpu_sample
from qdc_anomaly.lab.storage import append_event, read_events, write_json

INVENTORY = {"worker": "172.20.0.2", "api": "172.20.0.3", "canary": "172.20.0.4"}


def connection(index, port=8080, destination="172.20.0.5", ts=None):
    return {
        "ts": index * 3 if ts is None else ts,
        "uid": f"C{index}",
        "id.orig_h": INVENTORY["worker"],
        "id.resp_h": destination,
        "id.resp_p": port,
        "orig_bytes": 50,
        "resp_bytes": 100,
        "conn_state": "SF",
    }


def test_approved_busy_gpu_is_not_a_security_finding():
    rows = [gpu_sample("approved_load", random.Random(i), i, "run") for i in range(12)]
    assert all(g["gpu_util_percent"] >= 80 for g in rows)
    assert detect(rows, [], [], INVENTORY, LabConfig()) == []


def test_heat_is_operational_and_job_attribution_changes_interpretation():
    hot = gpu_sample("thermal", random.Random(1), 1, "run")
    (finding,) = detect([hot], [], [], INVENTORY, LabConfig())
    assert (finding["rule"], finding["category"]) == ("thermal", "operational")
    misuse = gpu_sample("misuse", random.Random(1), 2, "run")
    (finding,) = detect([misuse], [], [], INVENTORY, LabConfig())
    assert finding["rule"] == "unapproved-compute"
    assert finding["category"] == "investigate"


def test_port_spread_requires_a_time_window():
    raw = [connection(i, port=20 + i, ts=i) for i in range(7)]
    flows, bad = normalize_flows(raw, 0, INVENTORY["worker"])
    assert bad == 0
    assert "port-spread" in {f["rule"] for f in detect([], flows, [], INVENTORY, LabConfig())}
    for record in raw:
        record["ts"] *= 30
    flows, _ = normalize_flows(raw, 0, INVENTORY["worker"])
    assert not detect([], flows, [], INVENTORY, LabConfig())


def test_periodic_traffic_requires_samples_and_excludes_approved_api():
    flows, _ = normalize_flows([connection(i) for i in range(6)], 0, INVENTORY["worker"])
    assert not detect([], flows[:5], [], INVENTORY, LabConfig())
    (finding,) = detect([], flows, [], INVENTORY, LabConfig())
    assert finding["rule"] == "periodic-connection"
    assert "not confirmed C2" in finding["explanation"]
    for flow in flows:
        flow["dst"] = INVENTORY["api"]
    assert not detect([], flows, [], INVENTORY, LabConfig())


def test_sensor_normalization_excludes_other_hosts_old_data_duplicates_and_bad_records():
    good = connection(2)
    other = {**connection(3), "id.orig_h": "127.0.0.1"}
    raw = [good, good, connection(0), other, {**connection(4), "ts": float("nan")}]
    flows, bad = normalize_flows(raw, 3, INVENTORY["worker"])
    assert len(flows) == 1 and bad == 1
    assert flows[0]["raw"] == good


def test_canary_startup_is_not_an_intrusion_and_raw_event_is_preserved():
    raw = {
        "utc_time": "2026-11-05 01:00:00.000000",
        "src_host": INVENTORY["worker"],
        "dst_port": 8080,
        "logtype": 3001,
        "logdata": {"USERNAME": "lab-user"},
    }
    hits, bad = normalize_canary([{"logtype": 1001}, raw, raw], 0, INVENTORY["worker"])
    assert len(hits) == 1 and bad == 0
    (finding,) = detect([], [], hits, INVENTORY, LabConfig())
    assert finding["rule"] == "honeypot-contact"
    assert hits[0]["raw"] == raw


def test_partial_json_line_does_not_crash_or_appear_as_evidence(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('#fields\n{"ok":1}\nnot-json\n[]\n{"unfinished":', encoding="utf-8")
    assert read_events(path) == ([{"ok": 1}], 2)


def test_collector_reports_missing_sensors_without_fabricating_flows(tmp_path):
    write_json(tmp_path / "control.json", {"run_id": "run", "started_at": 0, "mode": "recon"})
    # A presenter label must never become a security finding.
    append_event(tmp_path / "presenter.jsonl", {"run_id": "run", "phase": "recon"})
    state = Collector(LabConfig(), tmp_path).snapshot()
    assert state["flows"] == state["findings"] == []
    assert state["health"]["zeek"]["state"] == "waiting / stale"
    assert state["model"]["score"] is None


def test_collector_skips_malformed_gpu_and_marks_old_samples_stale(tmp_path):
    write_json(tmp_path / "control.json", {"run_id": "run", "started_at": 0, "mode": "baseline"})
    row = gpu_sample("baseline", random.Random(1), time.time() - 100, "run")
    append_event(tmp_path / "gpu.jsonl", row)
    append_event(tmp_path / "gpu.jsonl", {**row, "job_approved": "false"})
    state = Collector(LabConfig(), tmp_path).snapshot()
    assert len(state["gpu"]) == 1
    assert state["health"]["gpu"]["bad_records"] == 1
    assert state["health"]["gpu"]["state"] == "waiting / stale"


def test_existing_model_is_used_after_a_complete_window():
    model = GPUAnalytics(10)
    rows = [gpu_sample("thermal", random.Random(i), i, "run") for i in range(10)]
    assert model.score(rows[:9])["score"] is None
    result = model.score(rows)
    assert result["score"] is not None
    frame = pd.DataFrame(rows).assign(timestamp=lambda f: f.ts, rack_id="compute-01")
    features = make_windows(frame, FeatureConfig(10, 1, 4), GPU_COLUMNS)
    expected = float(model.detector.score(features.X)[-1])
    assert result["score"] == round(expected, 4)
    assert result["above_reference"] == (expected > model.threshold)
    assert "qdc_anomaly.detectors.classical" in result["detector"]


@pytest.mark.parametrize(
    ("elapsed", "phase", "complete"),
    [
        (0, "baseline", False),
        (15, "approved_load", False),
        (60, "beacon", False),
        (89, "beacon", False),
        (90, "misuse", False),
        (105, "recovery", False),
        (120, "baseline", True),
    ],
)
def test_guided_cycle_returns_to_baseline(elapsed, phase, complete):
    assert current_phase({"mode": "guided", "started_at": 100}, 100 + elapsed, LabConfig()) == (
        phase,
        complete,
    )


def test_boundary_probe_reports_os_answers_and_cleans_up(tmp_path):
    from qdc_anomaly.lab.boundary import PROBE_NAME, probe_boundary

    root = tmp_path / "assets"
    (root / "datasets").mkdir(parents=True)
    (root / "models").mkdir()
    (root / "datasets" / "telemetry-sample.csv").write_bytes(b"a,b\n")
    result = probe_boundary(root, tmp_path / "missing.key")
    results = {c["action"]: c["result"] for c in result["checks"]}
    # A writable folder is reported as a gap, never hidden, and the probe file is removed.
    assert results == {
        "read-dataset": "allowed",
        "write-model-dir": "allowed",
        "open-key": "absent",
    }
    assert not (root / "models" / PROBE_NAME).exists()
    assert result["enforced"] is False and result["source"] == "os-boundary"
    # A missing root fails loudly instead of raising, so the worker keeps running.
    empty = probe_boundary(tmp_path / "nowhere", tmp_path / "missing.key")
    assert {c["result"] for c in empty["checks"]} == {"failed", "absent"}
    assert empty["enforced"] is False


def test_outbound_volume_needs_sustained_bytes_to_one_unapproved_peer():
    config = LabConfig()
    big = [{**connection(i, ts=i * 3), "orig_bytes": 40000, "resp_bytes": 0} for i in range(4)]
    flows, _ = normalize_flows(big, 0, INVENTORY["worker"])
    (finding,) = [
        f for f in detect([], flows, [], INVENTORY, config) if f["rule"] == "outbound-volume"
    ]
    assert finding["count"] == 4 and "not confirmed exfiltration" in finding["explanation"]
    # Same bytes spread beyond the window, or sent to the approved API, do not qualify.
    spread, _ = normalize_flows(
        [{**c, "ts": i * 100} for i, c in enumerate(big)], 0, INVENTORY["worker"]
    )
    assert not [
        f for f in detect([], spread, [], INVENTORY, config) if f["rule"] == "outbound-volume"
    ]
    to_api, _ = normalize_flows(
        [{**c, "id.resp_h": INVENTORY["api"]} for c in big], 0, INVENTORY["worker"]
    )
    assert not [
        f for f in detect([], to_api, [], INVENTORY, config) if f["rule"] == "outbound-volume"
    ]
    assert not [
        f for f in detect([], flows[:3], [], INVENTORY, config) if f["rule"] == "outbound-volume"
    ]
