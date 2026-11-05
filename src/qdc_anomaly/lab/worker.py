"""Generate ordinary and suspicious-looking traffic only to fixed Compose peers."""

from __future__ import annotations

import random
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path

from qdc_anomaly.lab.boundary import probe_boundary
from qdc_anomaly.lab.config import LabConfig, current_phase
from qdc_anomaly.lab.simulator import gpu_sample
from qdc_anomaly.lab.storage import append_event, read_json, write_json


def request(host: str, port: int, path: str, body: bytes | None = None) -> dict:
    started = time.time()
    try:
        req = urllib.request.Request(f"http://{host}:{port}{path}", data=body)
        with urllib.request.urlopen(req, timeout=1) as response:
            response.read()
            return {"ok": True, "status": response.status, "seconds": time.time() - started}
    except (OSError, urllib.error.URLError) as exc:
        return {"ok": False, "error": str(exc), "seconds": time.time() - started}


def run_worker(config: LabConfig, root: Path) -> None:
    rng = random.Random(17)
    inventory = {
        name: socket.gethostbyname(host)
        for name, host in {
            "worker": socket.gethostname(),
            "api": config.api_host,
            "receiver": config.receiver_host,
            "canary": config.canary_host,
        }.items()
    }
    write_json(root / "inventory.json", inventory)

    def record_boundary(run_id, phase):
        result = probe_boundary(config.asset_root, config.key_probe_path)
        append_event(root / "boundary.jsonl", {**result, "run_id": run_id, "phase": phase})

    record_boundary(read_json(root / "control.json")["run_id"], "startup")
    last_phase, last_run, last_beacon, last_normal = "", "", 0.0, 0.0
    while True:
        control = read_json(root / "control.json")
        now = time.time()
        phase, complete = current_phase(control, now, config)
        run_id = control["run_id"]
        if (last_phase, last_run) != (phase, run_id):
            append_event(
                root / "presenter.jsonl",
                {
                    "ts": now,
                    "run_id": run_id,
                    "phase": phase,
                    "complete": complete,
                    "source": "scenario-runner",
                    "note": "Presenter marker; excluded from detection",
                },
            )
            if phase == "recon":
                for port in config.probe_ports:
                    try:
                        with socket.create_connection((config.canary_host, port), timeout=0.15):
                            pass
                    except OSError:
                        pass  # expected closed ports; Zeek independently observes attempts
                request(
                    config.canary_host,
                    config.service_port,
                    "/index.html",
                    b"username=lab-user&password=demo-only",
                )
            if phase == "misuse":
                # The misuse scenario also tries to touch protected assets directly,
                # so the read-only mount is exercised, not just described.
                record_boundary(run_id, phase)
            last_phase, last_run = phase, run_id
        append_event(root / "gpu.jsonl", gpu_sample(phase, rng, now, run_id, config.worker_node_id))
        if now - last_normal >= 2:
            result = request(config.api_host, config.service_port, "/health")
            append_event(
                root / "worker.jsonl",
                {
                    "ts": now,
                    "run_id": run_id,
                    "source": "worker-client",
                    "destination": "approved-api",
                    **result,
                },
            )
            last_normal = now
        if phase in {"beacon", "misuse"} and now - last_beacon >= config.beacon_seconds:
            body = b"lab-heartbeat" if phase == "beacon" else b"DUMMY-DATA-" * 6000
            result = request(config.receiver_host, config.service_port, "/lab-heartbeat", body)
            append_event(
                root / "worker.jsonl",
                {
                    "ts": now,
                    "run_id": run_id,
                    "source": "worker-client",
                    "destination": "test-receiver",
                    "sent_bytes": len(body),
                    **result,
                },
            )
            last_beacon = now
        write_json(
            root / "worker-status.json",
            {
                "ts": time.time(),
                "run_id": run_id,
                "phase": phase,
                "complete": complete,
            },
        )
        time.sleep(config.sample_seconds)
