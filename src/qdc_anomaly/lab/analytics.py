"""Reuse the existing window features and Isolation Forest on GPU observations."""

from __future__ import annotations

import random

import numpy as np
import pandas as pd

from qdc_anomaly.config import FeatureConfig
from qdc_anomaly.detectors.classical import IsolationForestDetector
from qdc_anomaly.features.windows import make_windows
from qdc_anomaly.lab.simulator import GPU_COLUMNS, gpu_sample


def reference_features(seed: int, window_size: int) -> np.ndarray:
    rng = random.Random(seed)
    samples = []
    for phase in ("baseline", "approved_load"):
        for i in range(250):
            row = gpu_sample(phase, rng, i, "reference")
            row.update(timestamp=i, rack_id=f"reference-{phase}")
            samples.append(row)
    return make_windows(
        pd.DataFrame(samples), FeatureConfig(window_size, window_size, 4), GPU_COLUMNS
    ).X


class GPUAnalytics:
    def __init__(self, window_size: int):
        self.window_size = window_size
        self.detector = IsolationForestDetector(seed=41)
        self.detector.fit(reference_features(41, window_size))
        calibration = self.detector.score(reference_features(72, window_size))
        self.threshold = float(np.quantile(calibration, 0.99))

    def score(self, gpu: list[dict]) -> dict:
        result = {
            "detector": "qdc_anomaly.detectors.classical.IsolationForestDetector",
            "features": "Existing make_windows: mean, standard deviation, trend",
            "window_samples": self.window_size,
            "threshold": round(self.threshold, 4),
            "score": None,
            "above_reference": None,
            "reference": "Independent synthetic baseline and approved-load runs; not a security probability",
        }
        if len(gpu) < self.window_size:
            return result
        frame = pd.DataFrame(gpu[-self.window_size :])
        frame["timestamp"] = frame["ts"]
        frame["rack_id"] = frame["node_id"]
        window = make_windows(frame, FeatureConfig(self.window_size, 1, 4), GPU_COLUMNS)
        score = float(self.detector.score(window.X)[-1])
        result.update(score=round(score, 4), above_reference=score > self.threshold)
        return result
