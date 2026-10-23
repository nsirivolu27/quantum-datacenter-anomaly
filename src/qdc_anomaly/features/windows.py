"""Turn per rack time series into fixed length feature vectors.

Anomaly detectors in this repo are point based: they score one vector at a
time.  Telemetry faults, however, are temporal (a temperature ramp, a memory
leak).  Sliding windows bridge the gap.  For each window of ``window_size``
steps and each metric we compute three summaries:

    mean    the level
    std     the volatility
    slope   last value minus first value, the trend

So with 7 metrics a window becomes a 21 dimensional vector.  A window is labeled anomalous when at least half of its steps fall inside a
fault, normal when none do.  Windows that only clip the first few steps of a
fault are ambiguous (the signal has barely started) and carry
``ambiguous=True`` so the benchmark can exclude them from scoring without
pretending they are clean.  ``fault_type`` is the most common fault inside
the window, so every anomalous window names the fault it belongs to.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from qdc_anomaly.config import FeatureConfig


@dataclass
class WindowedDataset:
    X: np.ndarray  # shape (n_windows, n_metrics * 3)
    y: np.ndarray  # shape (n_windows,), 1 = anomalous
    fault_type: np.ndarray  # shape (n_windows,), string per window
    rack_id: np.ndarray  # shape (n_windows,)
    end_time: np.ndarray  # timestamp of the final step in each window
    ambiguous: np.ndarray  # True when 0 < fault coverage < 0.5
    feature_names: list[str]

    def __len__(self) -> int:
        return len(self.y)

    def subset(self, mask: np.ndarray) -> WindowedDataset:
        return WindowedDataset(
            X=self.X[mask],
            y=self.y[mask],
            fault_type=self.fault_type[mask],
            rack_id=self.rack_id[mask],
            end_time=self.end_time[mask],
            ambiguous=self.ambiguous[mask],
            feature_names=self.feature_names,
        )


def _window_features(block: np.ndarray) -> np.ndarray:
    """block has shape (window_size, n_metrics). Returns (n_metrics * 3,)."""
    mean = block.mean(axis=0)
    std = block.std(axis=0)
    slope = block[-1] - block[0]
    return np.concatenate([mean, std, slope])


def _dominant_fault(step_faults: np.ndarray) -> str:
    """Most frequent fault inside the window, or 'none' if every step is normal."""
    faults = [f for f in step_faults if f not in ("none", "unknown")]
    if not faults:
        return str(step_faults[-1])
    values, counts = np.unique(np.asarray(faults), return_counts=True)
    return str(values[np.argmax(counts)])


def make_windows(
    frame: pd.DataFrame,
    config: FeatureConfig,
    metric_columns: list[str],
) -> WindowedDataset:
    """Slide a window over each rack independently and stack the results."""
    missing = [c for c in metric_columns if c not in frame.columns]
    if missing:
        raise KeyError(f"Telemetry frame is missing metric columns: {missing}")
    has_labels = "label" in frame.columns

    features, labels, faults, racks, ends, ambiguous = [], [], [], [], [], []
    for rack_id, group in frame.groupby("rack_id", sort=True):
        group = group.sort_values("timestamp")
        values = group[metric_columns].to_numpy(dtype=float)
        step_labels = (
            group["label"].to_numpy(dtype=int) if has_labels else np.zeros(len(group), dtype=int)
        )
        step_faults = (
            group["fault_type"].to_numpy(dtype=str)
            if has_labels
            else np.full(len(group), "unknown")
        )
        timestamps = group["timestamp"].to_numpy()
        n = len(values)
        if n < config.window_size:
            raise ValueError(
                f"Rack {rack_id} has only {n} steps, fewer than window_size={config.window_size}."
            )
        for end in range(config.window_size, n + 1, config.stride):
            start = end - config.window_size
            block = values[start:end]
            coverage = step_labels[start:end].mean()
            features.append(_window_features(block))
            labels.append(int(coverage >= 0.5))
            ambiguous.append(bool(0 < coverage < 0.5))
            faults.append(_dominant_fault(step_faults[start:end]))
            racks.append(rack_id)
            ends.append(timestamps[end - 1])

    names = (
        [f"{m}_mean" for m in metric_columns]
        + [f"{m}_std" for m in metric_columns]
        + [f"{m}_slope" for m in metric_columns]
    )
    return WindowedDataset(
        X=np.asarray(features),
        y=np.asarray(labels, dtype=int),
        fault_type=np.asarray(faults),
        rack_id=np.asarray(racks),
        end_time=np.asarray(ends),
        ambiguous=np.asarray(ambiguous, dtype=bool),
        feature_names=names,
    )
