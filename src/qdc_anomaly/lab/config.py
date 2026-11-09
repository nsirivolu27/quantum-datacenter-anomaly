"""A separate configuration for the demo, leaving benchmark settings unchanged."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class LabConfig:
    sample_seconds: float = 1.0
    phase_seconds: int = 15
    beacon_seconds: int = 3
    window_samples: int = 10
    stale_seconds: int = 10
    port_threshold: int = 6
    beacon_min_connections: int = 6
    beacon_max_cv: float = 0.25
    thermal_c: float = 85
    unapproved_gpu_percent: float = 70
    transfer_bytes: int = 50000
    correlation_seconds: float = 5
    # Sustained outbound volume to one unapproved peer, and how long after an allowed
    # asset read a large transfer still counts as "following" it.
    volume_window_seconds: float = 60
    volume_bytes: int = 150000
    exfil_window_seconds: float = 30
    worker_node_id: str = "compute-01"
    enabled_packs: list[str] | None = None
    api_host: str = "api"
    receiver_host: str = "receiver"
    canary_host: str = "canary"
    service_port: int = 8080
    probe_ports: list[int] = field(default_factory=lambda: [21, 22, 23, 80, 443, 445, 3389])
    # Where the worker container sees the declared assets (read-only mount) and where the
    # integrity key would be if it were mounted. The worker probes both to show the boundary.
    asset_root: str = "/assets"
    key_probe_path: str = "/app/security/local/integrity.key"

    @classmethod
    def load(cls, path: str | Path) -> LabConfig:
        config = cls(**json.loads(Path(path).read_text()))
        if config.sample_seconds <= 0 or config.phase_seconds < 10 or config.window_samples < 2:
            raise ValueError("Invalid sampling interval, phase duration, or window size")
        if config.beacon_seconds < 1 or config.beacon_min_connections < 3:
            raise ValueError(
                "Beacon interval must be positive and require at least three connections"
            )
        if config.port_threshold < 2 or not 0 <= config.beacon_max_cv <= 1:
            raise ValueError("Invalid network thresholds")
        if config.transfer_bytes <= 0 or config.correlation_seconds <= 0:
            raise ValueError("Invalid correlation thresholds")
        if config.volume_window_seconds <= 0 or config.volume_bytes <= 0:
            raise ValueError("Invalid outbound volume thresholds")
        if config.exfil_window_seconds <= 0:
            raise ValueError("Invalid read-then-transfer window")
        return config


PHASES = ("baseline", "approved_load", "thermal", "recon", "beacon", "misuse", "recovery")


def current_phase(control: dict, now: float, config: LabConfig) -> tuple[str, bool]:
    mode = control.get("mode", "baseline")
    if mode != "guided":
        return mode, False
    elapsed = max(0, now - control["started_at"])
    for phase in PHASES:
        duration = config.phase_seconds * (2 if phase == "beacon" else 1)
        if elapsed < duration:
            return phase, False
        elapsed -= duration
    return "baseline", True
