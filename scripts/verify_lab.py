"""Verify a running default lab using only the Python standard library (~130 seconds)."""

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8765"


def state():
    with urllib.request.urlopen(BASE + "/api/state", timeout=5) as response:
        value = json.load(response)
    assert value.get("control") and not value.get("error"), value.get("error")
    return value


def control(mode, new_run=False, token=None):
    request = urllib.request.Request(
        BASE + "/api/control",
        data=json.dumps({"mode": mode, "new_run": new_run}).encode(),
        headers={
            "Content-Type": "application/json",
            "X-Lab-Token": token or state()["control_token"],
        },
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        assert response.status == 200


def main():
    try:
        control("recon", token="invalid")
        raise AssertionError("An invalid control token was accepted")
    except urllib.error.HTTPError as error:
        assert error.code == 403
    before = state()["control"]["run_id"]
    control("guided", new_run=True)
    deadline, observed, baseline_clear, approved_clear = time.time() + 150, set(), False, False
    while time.time() < deadline:
        current = state()
        if current["control"]["run_id"] == before:
            time.sleep(1)
            continue
        phase = current["phase"]
        if phase not in observed:
            print(f"Observed {phase}: {current['counts']}", flush=True)
            observed.add(phase)
        if phase == "baseline" and current["counts"]["flows"] >= 3 and not current["complete"]:
            assert not current["findings"], "Baseline created an unexpected finding"
            baseline_clear = True
        if phase == "approved_load" and current["gpu"] and current["gpu"][-1]["job_approved"]:
            assert not current["findings"], "Approved work created an unexpected finding"
            approved_clear = True
        if current["complete"]:
            break
        time.sleep(2)
    else:
        raise AssertionError("The guided cycle did not finish in 150 seconds")

    assert baseline_clear and approved_clear
    expected = {
        "thermal",
        "port-spread",
        "honeypot-contact",
        "periodic-connection",
        "unapproved-compute",
        "compute-network-overlap",
        "outbound-volume",
    }
    assert expected <= {f["rule"] for f in current["findings"]}, current["findings"]
    assert len(observed) == 7, observed
    assert current["health"]["zeek"]["state"] == "live", current["health"]
    assert all(h["bad_records"] == 0 for h in current["health"].values())
    assert current["model"]["score"] is not None
    ids = {e["id"] for e in current["evidence"]}
    assert all(set(f["evidence_ids"]) <= ids for f in current["findings"])
    assert current["honeypot_hits"] and all(h["raw"]["logtype"] for h in current["honeypot_hits"])
    assert any(f["bytes"] > 60000 for f in current["flows"]), "Dummy transfer not captured"
    receiver = current["inventory"]["receiver"]
    assert not any(f["dst"] == receiver and f["ts"] > time.time() - 10 for f in current["flows"])
    assert current["worker_requests"][-1]["ok"], "Ordinary API traffic did not recover"
    with urllib.request.urlopen(BASE + "/api/export", timeout=5) as response:
        exported = json.load(response)
    assert "control_token" not in exported

    # The worker probes the asset mount from inside its container. Read its answers from
    # the shared evidence folder and require that the operating system, not just the
    # Python policy, denied the write and that the key was never reachable.
    runtime = Path(__file__).resolve().parents[1] / "lab/runtime"
    run_id = current["control"]["run_id"]
    probes = [
        json.loads(line)
        for line in (runtime / "boundary.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    probes = [p for p in probes if p.get("run_id") == run_id]
    assert probes, "No boundary probe recorded for this run"
    results = {c["action"]: c["result"] for c in probes[-1]["checks"]}
    assert results == {
        "read-dataset": "allowed",
        "write-model-dir": "denied",
        "open-key": "absent",
    }, results
    assert all(p["enforced"] for p in probes), probes
    assert "misuse" in {p["phase"] for p in probes}, "Misuse phase did not probe the mount"
    destination = runtime / "verification.json"
    destination.write_text(
        json.dumps(
            {
                "passed": True,
                "checked_at": time.time(),
                "observed_phases": sorted(observed),
                "boundary": probes[-1],
                "snapshot": exported,
            },
            indent=2,
        )
    )
    print(
        "PASS: real sensor evidence, seven findings, approved load, recovery, export, "
        f"read-only asset boundary.\n{destination}"
    )


if __name__ == "__main__":
    main()
