"""Local-only dashboard. No Docker socket, shell execution, or arbitrary targets."""

from __future__ import annotations

import json
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from qdc_anomaly.lab.collector import Collector
from qdc_anomaly.lab.config import PHASES, LabConfig
from qdc_anomaly.lab.storage import read_json, write_json


def serve_dashboard(config: LabConfig, root: Path, port: int, host: str = "127.0.0.1") -> None:
    collector = Collector(config, root)
    token = secrets.token_urlsafe(24)
    lock = threading.Lock()
    state = {"snapshot": {}, "error": "Starting collectors"}
    assets = Path(__file__).parent / "static"

    def collect():
        while True:
            try:
                snapshot = collector.snapshot()
                with lock:
                    state.update(snapshot=snapshot, error=None)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                with lock:
                    state["error"] = f"Collector error: {exc}"
            time.sleep(1)

    threading.Thread(target=collect, daemon=True).start()

    class Handler(BaseHTTPRequestHandler):
        def send(self, payload: bytes, mime: str, status: int = 200, download=False):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
            )
            if download:
                self.send_header(
                    "Content-Disposition", 'attachment; filename="sentinel-evidence.json"'
                )
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path == "/api/framework":
                self.send(json.dumps(collector.framework.describe()).encode(), "application/json")
                return
            if self.path == "/api/health":
                with lock:
                    error = state["error"]
                self.send(
                    json.dumps({"ok": error is None, "error": error}).encode(),
                    "application/json",
                    503 if error else 200,
                )
                return
            if self.path in {"/api/state", "/api/export"}:
                with lock:
                    result = {**state["snapshot"], "error": state["error"]}
                if self.path == "/api/state":
                    result["control_token"] = token
                self.send(
                    json.dumps(result, allow_nan=False).encode(),
                    "application/json",
                    download=self.path == "/api/export",
                )
                return
            files = {
                "/": ("index.html", "text/html"),
                "/app.js": ("app.js", "text/javascript"),
                "/style.css": ("style.css", "text/css"),
            }
            if self.path not in files:
                self.send_error(404)
                return
            filename, mime = files[self.path]
            self.send((assets / filename).read_bytes(), mime + "; charset=utf-8")

        def do_POST(self):
            host = self.headers.get("Host", "")
            origin = self.headers.get("Origin")
            if (
                self.path != "/api/control"
                or self.headers.get("X-Lab-Token") != token
                or (origin and origin != f"http://{host}")
                or self.headers.get("Content-Type") != "application/json"
            ):
                self.send_error(403)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1024:
                    raise ValueError("Invalid payload size")
                request = json.loads(self.rfile.read(size))
                mode = request["mode"]
                if mode not in {*PHASES, "guided"}:
                    raise ValueError("Unknown scenario")
                with lock:
                    control = read_json(root / "control.json")
                    if request.get("new_run") is True:
                        control = {"run_id": str(uuid.uuid4()), "started_at": time.time()}
                    elif mode == "guided":
                        raise ValueError("A guided cycle must start a new run")
                    control.update(mode=mode, changed_at=time.time())
                    write_json(root / "control.json", control)
                self.send(b'{"ok":true}', "application/json")
            except (ValueError, KeyError, TypeError):
                self.send(b'{"error":"Invalid control request"}', "application/json", 400)

        def log_message(self, *args):
            pass

    print(f"Local dashboard listening on port {port}", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()
