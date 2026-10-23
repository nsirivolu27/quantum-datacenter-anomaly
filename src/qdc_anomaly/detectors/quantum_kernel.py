"""Quantum kernel one class SVM.

The idea in one paragraph.  A kernel method never looks at raw features;
it only needs a similarity function k(x, x') between pairs of points.  A
quantum computer gives us a natural similarity: encode x into a quantum
state |phi(x)>, encode x' into |phi(x')>, and measure how much they overlap,

    k(x, x') = |<phi(x') | phi(x)>|^2

That overlap is estimated with the "adjoint trick": run the encoding circuit
for x, then run the *inverse* of the encoding circuit for x', and read out
the probability of landing back on the all zero state.  If x == x' the
circuits cancel exactly and the probability is 1.

Once we have k we hand the kernel matrix to an ordinary one class SVM.  The
SVM does the anomaly detection; the quantum computer only computes
similarities.  This split is why kernel methods are the most practical
near term QML approach: the optimisation stays classical and convex.

Cost: fitting on n points needs n(n-1)/2 circuit evaluations, scoring m
points needs m*n.  That is why the benchmark keeps n_train small.
"""

from __future__ import annotations

import numpy as np
from sklearn.svm import OneClassSVM

from qdc_anomaly.config import QuantumConfig
from qdc_anomaly.detectors.base import AnomalyDetector


def _require_pennylane():
    try:
        import pennylane as qml
    except ImportError as exc:
        raise ImportError(
            "PennyLane is required for quantum detectors. Install with: pip install pennylane"
        ) from exc
    return qml


def feature_map(x, wires: list[int], n_layers: int) -> None:
    """Encode one feature vector ``x`` (length = len(wires)) into a quantum state.

    Each layer: rotate every qubit by its feature (RY), entangle neighbours in
    a ring with CNOTs, then rotate again by the feature (RZ).  Repeating the
    data in several layers is called data re-uploading and makes the kernel
    more expressive than a single rotation per qubit.
    """
    qml = _require_pennylane()
    n = len(wires)
    for _ in range(n_layers):
        for i, wire in enumerate(wires):
            qml.RY(x[i], wires=wire)
        for i in range(n):
            qml.CNOT(wires=[wires[i], wires[(i + 1) % n]])
        for i, wire in enumerate(wires):
            qml.RZ(x[i], wires=wire)


class QuantumKernelSVMDetector(AnomalyDetector):
    name = "quantum_kernel_svm"

    def __init__(self, config: QuantumConfig, nu: float = 0.05):
        qml = _require_pennylane()
        self.config = config
        self.nu = nu
        self.wires = list(range(config.n_qubits))
        self.device = qml.device(config.device, wires=config.n_qubits)
        self.svm = OneClassSVM(kernel="precomputed", nu=nu)
        self.X_train: np.ndarray | None = None

        @qml.qnode(self.device)
        def overlap_circuit(x1, x2):
            feature_map(x1, self.wires, config.n_layers)
            qml.adjoint(feature_map)(x2, self.wires, config.n_layers)
            return qml.probs(wires=self.wires)

        self._overlap_circuit = overlap_circuit

    def kernel(self, x1: np.ndarray, x2: np.ndarray) -> float:
        """k(x1, x2) = probability of measuring |00...0> after the adjoint trick."""
        return float(self._overlap_circuit(x1, x2)[0])

    def kernel_matrix(self, A: np.ndarray, B: np.ndarray) -> np.ndarray:
        """Dense kernel matrix between rows of A and rows of B."""
        qml = _require_pennylane()
        if A is B or (A.shape == B.shape and np.shares_memory(A, B)):
            # Symmetric case: PennyLane fills only the upper triangle and
            # sets the diagonal to 1, halving the number of circuit runs.
            return np.asarray(
                qml.kernels.square_kernel_matrix(A, self.kernel, assume_normalized_kernel=True)
            )
        return np.asarray(qml.kernels.kernel_matrix(A, B, self.kernel))

    def fit(self, X_normal: np.ndarray) -> QuantumKernelSVMDetector:
        self._validate(X_normal)
        self.X_train = np.asarray(X_normal, dtype=float)
        K = self.kernel_matrix(self.X_train, self.X_train)
        self.svm.fit(K)
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        self._check_fitted("X_train")
        assert self.X_train is not None
        self._validate(X)
        K = self.kernel_matrix(np.asarray(X, dtype=float), self.X_train)
        return -self.svm.decision_function(K)

    def _validate(self, X: np.ndarray) -> None:
        if X.ndim != 2 or X.shape[1] != self.config.n_qubits:
            raise ValueError(
                f"{self.name} expects shape (n, {self.config.n_qubits}); got {X.shape}. "
                "Run the features through QubitReducer first."
            )
