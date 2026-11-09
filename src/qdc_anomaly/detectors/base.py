"""The one interface every detector implements.

Semi supervised anomaly detection: ``fit`` only ever sees normal windows,
``score`` returns a real number per window where larger means more anomalous.
Thresholding is left to the evaluation layer so detectors can be compared
with threshold free metrics like ROC AUC.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class AnomalyDetector(ABC):
    name: str = "detector"

    @abstractmethod
    def fit(self, X_normal: np.ndarray) -> AnomalyDetector:
        """Learn what normal looks like. ``X_normal`` has shape (n, d)."""

    @abstractmethod
    def score(self, X: np.ndarray) -> np.ndarray:
        """Return anomaly scores of shape (n,). Higher = more anomalous."""

    def _check_fitted(self, attr: str) -> None:
        if getattr(self, attr, None) is None:
            raise RuntimeError(f"{self.name}.score called before fit.")
