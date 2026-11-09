"""Metrics that matter for an on call engineer, not just for a leaderboard.

roc_auc            threshold free ranking quality
pr_auc             same, but focused on the rare positive class
f1_at_budget       F1 when we flag exactly the top ``alert_budget`` fraction;
                   this mirrors "how many pages per day can the team absorb"
precision_at_budget, recall_at_budget   the two halves of that F1
per_fault_recall   recall broken down by fault type so a detector that only
                   catches power spikes does not hide behind an average
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from sklearn.metrics import average_precision_score, roc_auc_score


@dataclass
class DetectionMetrics:
    roc_auc: float
    pr_auc: float
    precision_at_budget: float
    recall_at_budget: float
    f1_at_budget: float
    alert_budget: float

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def compute_metrics(
    y_true: np.ndarray, scores: np.ndarray, alert_budget: float = 0.1
) -> DetectionMetrics:
    y_true = np.asarray(y_true).astype(int)
    scores = np.asarray(scores, dtype=float)
    if len(y_true) != len(scores):
        raise ValueError(f"y_true has {len(y_true)} rows, scores has {len(scores)}")
    if y_true.min() == y_true.max():
        raise ValueError("compute_metrics needs both normal and anomalous samples in y_true")
    if not np.all(np.isfinite(scores)):
        raise ValueError("scores contain NaN or inf; the detector produced invalid output")

    n_alerts = max(1, int(round(alert_budget * len(scores))))
    threshold = np.sort(scores)[-n_alerts]
    flagged = scores >= threshold

    tp = int(np.sum(flagged & (y_true == 1)))
    fp = int(np.sum(flagged & (y_true == 0)))
    fn = int(np.sum(~flagged & (y_true == 1)))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0

    return DetectionMetrics(
        roc_auc=float(roc_auc_score(y_true, scores)),
        pr_auc=float(average_precision_score(y_true, scores)),
        precision_at_budget=precision,
        recall_at_budget=recall,
        f1_at_budget=f1,
        alert_budget=alert_budget,
    )


def per_fault_recall(
    y_true: np.ndarray, scores: np.ndarray, fault_type: np.ndarray, alert_budget: float = 0.1
) -> dict[str, float]:
    """Recall at the alert budget, split by fault type (normal rows excluded)."""
    scores = np.asarray(scores, dtype=float)
    n_alerts = max(1, int(round(alert_budget * len(scores))))
    threshold = np.sort(scores)[-n_alerts]
    flagged = scores >= threshold

    result: dict[str, float] = {}
    for fault in sorted(set(fault_type) - {"none", "unknown"}):
        mask = (fault_type == fault) & (np.asarray(y_true) == 1)
        if mask.sum():
            result[fault] = float(flagged[mask].mean())
    return result
