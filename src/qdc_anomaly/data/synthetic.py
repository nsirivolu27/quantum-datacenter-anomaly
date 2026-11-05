"""Reconstructed synthetic input, following docs/02-telemetry-simulation.md.

The original repository referenced this module but did not track it. This is
a new implementation, not a reproduction of the historical benchmark dataset.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from qdc_anomaly.config import DataConfig

METRIC_COLUMNS = [
    "cpu_util",
    "mem_util",
    "power_kw",
    "inlet_temp_c",
    "fan_rpm",
    "net_mbps",
    "disk_iops",
]
FAULT_TYPES = ("thermal_runaway", "memory_leak", "fan_failure", "network_saturation", "power_spike")


def _inject_fault(frame: pd.DataFrame, start: int, end: int, fault: str) -> None:
    index = frame.index[start:end]
    ramp = np.linspace(0.2, 1.0, len(index))
    if fault == "thermal_runaway":
        frame.loc[index, "inlet_temp_c"] += 8 * ramp
        frame.loc[index, "fan_rpm"] += 250 * ramp
    elif fault == "memory_leak":
        initial = frame.loc[index[0], "mem_util"]
        frame.loc[index, "mem_util"] = initial + (99 - initial) * ramp
    elif fault == "fan_failure":
        frame.loc[index, "fan_rpm"] *= 0.4
        frame.loc[index, "inlet_temp_c"] += 6 * ramp
    elif fault == "network_saturation":
        frame.loc[index, "net_mbps"] = 980
        frame.loc[index, "cpu_util"] = np.minimum(frame.loc[index, "cpu_util"] + 8, 100)
    elif fault == "power_spike":
        frame.loc[index, "power_kw"] += 2.5
    else:
        raise ValueError(f"Unknown fault: {fault}")
    frame.loc[index, "label"] = 1
    frame.loc[index, "fault_type"] = fault


def generate_telemetry(config: DataConfig) -> pd.DataFrame:
    if config.n_racks < 1 or config.n_steps < 40 or config.step_minutes <= 0:
        raise ValueError("Use at least one rack, 40 samples, and a positive sampling interval.")
    if not 0 < config.anomaly_fraction < 0.5:
        raise ValueError("anomaly_fraction must be between zero and 0.5.")
    rng = np.random.default_rng(config.seed)
    racks = []
    for rack in range(config.n_racks):
        phase = np.arange(config.n_steps) * config.step_minutes / 1440 * 2 * np.pi
        load = np.clip(0.45 + 0.18 * np.sin(phase + rack) + rng.normal(0, 0.025, len(phase)), 0, 1)
        power = 2 + 6 * load + rng.normal(0, 0.06, len(load))
        temp = 19 + 0.7 * pd.Series(power).ewm(span=8).mean().to_numpy()
        frame = pd.DataFrame(
            {
                "timestamp": pd.date_range(
                    "2026-01-01", periods=len(load), freq=f"{config.step_minutes}min", tz="UTC"
                ),
                "rack_id": f"rack-{rack:02d}",
                "cpu_util": np.clip(100 * load + rng.normal(0, 1, len(load)), 0, 100),
                "mem_util": 40 + 30 * pd.Series(load).ewm(span=12).mean().to_numpy(),
                "power_kw": power,
                "inlet_temp_c": temp + rng.normal(0, 0.12, len(load)),
                "fan_rpm": 2000 + 160 * (temp - 20) + rng.normal(0, 35, len(load)),
                "net_mbps": np.maximum(0, 400 * load + rng.normal(0, 20, len(load))),
                "disk_iops": np.maximum(0, 8000 * load + rng.normal(0, 150, len(load))),
                "label": 0,
                "fault_type": "none",
            }
        )
        budget = max(1, int(config.n_steps * config.anomaly_fraction))
        segments = max(1, budget // 40)
        sizes = [budget // segments + (i < budget % segments) for i in range(segments)]
        gap = (config.n_steps - budget) // (segments + 1)
        start = gap
        for segment, size in enumerate(sizes):
            _inject_fault(
                frame, start, start + size, FAULT_TYPES[(rack + segment) % len(FAULT_TYPES)]
            )
            start += size + gap
        racks.append(frame)
    return pd.concat(racks, ignore_index=True)


def summarize(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.groupby("fault_type", as_index=False).size().rename(columns={"size": "samples"})
