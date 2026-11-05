"""Internal HTTP peers. They acknowledge lab requests, never execute commands."""

from __future__ import annotations

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from qdc_anomaly.lab.storage import append_event


def serve_peer(root: Path, role: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.respond(0)

        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 <= size <= 100_000:
                    raise ValueError("Request too large")
            except ValueError:
                self.send_error(400)
                return
            self.rfile.read(size)
            self.respond(size)

        def respond(self, size):
            append_event(
                root / f"{role}.jsonl",
                {
                    "ts": time.time(),
                    "source": role,
                    "client": self.client_address[0],
                    "path": self.path[:200],
                    "received_bytes": size,
                },
            )
            payload = json.dumps({"service": role, "ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
