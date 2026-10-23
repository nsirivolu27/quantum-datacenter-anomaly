"""Compress window features down to one number per qubit.

Near term quantum devices have few qubits and the simulators used here get
slow past ten or so.  The standard trick in quantum machine learning is:

    1. standardize every feature (zero mean, unit variance on normal data)
    2. PCA down to ``n_components`` = number of qubits
    3. squash each component into a bounded range so it can be used as a
       rotation angle

Step 3 matters more than it looks.  Angle encoding is periodic: a value of
0 and a value of 2*pi produce the same quantum state.  Without bounding, two
very different windows could collide.  We map each component to [0, pi]
using the training set range, with a small margin, then clip anything
outside at inference time (an out of range value is itself a strong hint
of an anomaly, and clipping to the edge keeps that signal).

The same reducer feeds the classical detectors so the comparison is fair:
every method sees the identical low dimensional input.
"""

from __future__ import annotations

import numpy as np
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler


class QubitReducer:
    def __init__(self, n_components: int, angle_max: float = np.pi, margin: float = 0.1):
        self.n_components = n_components
        self.angle_max = angle_max
        self.margin = margin
        self.scaler = StandardScaler()
        self.pca = PCA(n_components=n_components)
        self._low: np.ndarray | None = None
        self._high: np.ndarray | None = None

    def fit(self, X: np.ndarray) -> QubitReducer:
        if X.shape[1] < self.n_components:
            raise ValueError(
                f"Cannot reduce {X.shape[1]} features to {self.n_components} components."
            )
        Z = self.pca.fit_transform(self.scaler.fit_transform(X))
        span = Z.max(axis=0) - Z.min(axis=0)
        self._low = Z.min(axis=0) - self.margin * span
        self._high = Z.max(axis=0) + self.margin * span
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        if self._low is None or self._high is None:
            raise RuntimeError("QubitReducer.transform called before fit.")
        Z = self.pca.transform(self.scaler.transform(X))
        unit = (Z - self._low) / (self._high - self._low)
        return np.clip(unit, 0.0, 1.0) * self.angle_max

    def fit_transform(self, X: np.ndarray) -> np.ndarray:
        return self.fit(X).transform(X)

    @property
    def explained_variance_ratio(self) -> np.ndarray:
        return self.pca.explained_variance_ratio_
