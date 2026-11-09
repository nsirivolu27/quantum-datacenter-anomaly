"""Entrypoint for Compose services and the local collector."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from pathlib import Path

from qdc_anomaly.lab.config import LabConfig
from qdc_anomaly.lab.storage import write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "role",
        choices=["init", "worker", "api", "receiver", "dashboard", "inspect", "describe", "replay"],
    )
    parser.add_argument(
        "--config",
        default="/app/lab/settings.json"
        if Path("/app/lab/settings.json").exists()
        else "lab/settings.json",
    )
    parser.add_argument(
        "--evidence", default="/evidence" if Path("/evidence").exists() else "lab/runtime"
    )
    parser.add_argument("--input", help="Exported JSON snapshot to replay")
    parser.add_argument(
        "--security-audit",
        help="Audit JSONL from qdc_anomaly.security to include in inspect (default: none)",
    )
    parser.add_argument("--out", help="Write replay JSON to this file instead of stdout")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    config, root = LabConfig.load(args.config), Path(args.evidence)
    if args.role == "replay":
        from qdc_anomaly.lab.replay import replay

        if not args.input:
            parser.error("replay requires --input")
        result = replay(json.loads(Path(args.input).read_text(encoding="utf-8")), config)
        payload = json.dumps(result, indent=2, allow_nan=False)
        if args.out:
            Path(args.out).write_text(payload, encoding="utf-8")
        else:
            print(payload)
        return
    if args.role == "describe":
        from qdc_anomaly.lab.framework import SecurityFramework

        print(json.dumps(SecurityFramework(config).describe(), indent=2))
        return
    if args.role == "inspect":
        from qdc_anomaly.lab.collector import Collector

        source = None
        if args.security_audit:
            from qdc_anomaly.security.findings import audit_source

            source = audit_source(args.security_audit)
        snapshot = Collector(config, root, security_source=source).snapshot()
        print(json.dumps(snapshot, indent=2, allow_nan=False))
        return
    if args.role == "init":
        root.mkdir(parents=True, exist_ok=True)
        for name in ("zeek", "canary"):
            (root / name).mkdir(exist_ok=True)
        (root / "canary").chmod(0o777)
        # A new stack start creates a new run; old append-only evidence is retained.
        write_json(
            root / "control.json",
            {"run_id": str(uuid.uuid4()), "started_at": time.time(), "mode": "baseline"},
        )
    elif args.role == "worker":
        from qdc_anomaly.lab.worker import run_worker

        run_worker(config, root)
    elif args.role in {"api", "receiver"}:
        from qdc_anomaly.lab.services import serve_peer

        serve_peer(root, args.role, config.service_port)
    else:
        from qdc_anomaly.lab.server import serve_dashboard

        serve_dashboard(config, root, args.port, args.host)


if __name__ == "__main__":
    main()
