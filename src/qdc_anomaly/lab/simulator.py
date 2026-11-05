"""Clearly synthetic GPU signals. No real GPU, mining, or hardware stress."""

from __future__ import annotations

import random

GPU_COLUMNS = ["gpu_util_percent", "gpu_memory_mb", "gpu_temp_c", "gpu_power_w"]


def gpu_sample(
    phase: str, rng: random.Random, timestamp: float, run_id: str, node_id: str = "compute-01"
) -> dict:
    busy = phase in {"approved_load", "misuse"}
    utilization = rng.uniform(80, 94) if busy else rng.uniform(18, 38)
    temperature = 42 + utilization * 0.30 + rng.uniform(-2, 2)
    if phase == "thermal":
        temperature = rng.uniform(89, 95)
    return {
        "ts": timestamp,
        "run_id": run_id,
        "node_id": node_id,
        "gpu_id": "simulated-gpu-0",
        "source": "gpu-simulator",
        "simulated": True,
        "gpu_util_percent": round(utilization, 2),
        "gpu_memory_mb": round(800 + utilization * 85 + rng.uniform(-80, 80), 1),
        "gpu_temp_c": round(temperature, 2),
        "gpu_power_w": round(45 + utilization * 2.4 + rng.uniform(-4, 4), 2),
        "job_id": "approved-training-01" if phase == "approved_load" else None,
        "job_approved": phase == "approved_load",
    }
