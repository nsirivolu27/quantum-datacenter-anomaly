"""Classical baselines.

A quantum method is only interesting if it is compared against the tools an
engineer would actually reach for today.  These three cover the main
families:

    IsolationForest     tree ensemble, the default choice in most monitoring stacks
    OneClassSVM (RBF)   kernel method, the direct classical twin of the quantum kernel SVM
    PCA reconstruction  linear autoencoder, the direct classical twin of the quantum autoencoder

Keeping the twins in the table lets a reader see what, if anything, the
quantum feature map adds beyond the classical version of the same idea.
"""

from __future__ import annotations

import numpy as np
from sklearn.decomposition import PCA
from sklearn.ensemble import IsolationForest
from sklearn.svm import OneClassSVM

from qdc_anomaly.detectors.base import AnomalyDetector


class IsolationForestDetector(AnomalyDetector):
    name = "isolation_forest"

    def __init__(self, n_estimators: int = 200, seed: int = 0):
        self.model = IsolationForest(
            n_estimators=n_estimators, random_state=seed, contamination="auto"
        )
        self._fitted = None

    def fit(self, X_normal: np.ndarray) -> IsolationForestDetector:
        self.model.fit(X_normal)
        self._fitted = True
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        self._check_fitted("_fitted")
        # sklearn returns higher = more normal; flip the sign.
        return -self.model.score_samples(X)


class OneClassSVMDetector(AnomalyDetector):
    name = "one_class_svm"

    def __init__(self, nu: float = 0.05, gamma: str | float = "scale"):
        self.model = OneClassSVM(kernel="rbf", nu=nu, gamma=gamma)
        self._fitted = None

    def fit(self, X_normal: np.ndarray) -> OneClassSVMDetector:
        self.model.fit(X_normal)
        self._fitted = True
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        self._check_fitted("_fitted")
        # decision_function is positive inside the learned region.
        return -self.model.decision_function(X)


class PCAReconstructionDetector(AnomalyDetector):
    """Project onto the top ``n_latent`` directions and measure what is lost."""

    name = "pca_reconstruction"

    def __init__(self, n_latent: int = 2):
        self.n_latent = n_latent
        self.model: PCA | None = None

    def fit(self, X_normal: np.ndarray) -> PCAReconstructionDetector:
        if self.n_latent >= X_normal.shape[1]:
            raise ValueError(
                f"n_latent={self.n_latent} must be smaller than the feature dimension {X_normal.shape[1]}"
            )
        self.model = PCA(n_components=self.n_latent).fit(X_normal)
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        self._check_fitted("model")
        assert self.model is not None
        reconstructed = self.model.inverse_transform(self.model.transform(X))
        return np.sum((X - reconstructed) ** 2, axis=1)
