"""Quantum autoencoder for anomaly detection.

A classical autoencoder compresses data and scores anomalies by how badly
the compression went.  The quantum version does the same with qubits:

    1. load the window onto n_qubits qubits
    2. apply a trainable circuit
    3. split the qubits into "latent" (keep) and "trash" (should read 0)

Training adjusts the circuit so that on normal data the trash qubits read 0
as often as possible.  The anomaly score for a new window is how often a
trash qubit reads 1: if the circuit cannot squeeze the window into the
latent qubits, it has not seen anything like it before.

There is no decoder.  Quantum circuits run backwards exactly, so a perfect
encoder is automatically a perfect decoder.

See docs/06-quantum-autoencoder.md for the full walkthrough.
"""

from __future__ import annotations

import numpy as np

from qdc_anomaly.config import QuantumConfig
from qdc_anomaly.detectors.base import AnomalyDetector


def _require_pennylane():
    try:
        import pennylane as qml
        from pennylane import numpy as pnp
    except ImportError as exc:
        raise ImportError(
            "PennyLane is required for quantum detectors. Install with: pip install pennylane"
        ) from exc
    return qml, pnp


class QuantumAutoencoderDetector(AnomalyDetector):
    name = "quantum_autoencoder"

    def __init__(self, config: QuantumConfig, seed: int = 0, verbose: bool = False):
        qml, pnp = _require_pennylane()
        self.config = config
        self.seed = seed
        self.verbose = verbose
        self.wires = list(range(config.n_qubits))
        self.trash_wires = self.wires[config.n_latent :]
        self.device = qml.device(config.device, wires=config.n_qubits)
        self.weights = None
        self.history: list[float] = []

        weight_shape = qml.StronglyEntanglingLayers.shape(
            n_layers=config.n_layers, n_wires=config.n_qubits
        )
        self._weight_shape = weight_shape

        @qml.qnode(self.device)
        def trash_expectations(weights, x):
            # x may be a single vector (n_qubits,) or a batch (batch, n_qubits).
            # PennyLane broadcasts the batch dimension through the circuit.
            qml.AngleEmbedding(x, wires=self.wires, rotation="Y")
            qml.StronglyEntanglingLayers(weights, wires=self.wires)
            return [qml.expval(qml.PauliZ(w)) for w in self.trash_wires]

        self._trash_expectations = trash_expectations

    def _trash_probability(self, weights, X):
        """Mean probability over trash qubits of measuring |1>, per sample."""
        _, pnp = _require_pennylane()
        z = pnp.stack(self._trash_expectations(weights, X))  # shape (n_trash, batch) or (n_trash,)
        return pnp.mean((1 - z) / 2, axis=0)

    def fit(self, X_normal: np.ndarray) -> QuantumAutoencoderDetector:
        qml, pnp = _require_pennylane()
        self._validate(X_normal)
        rng = np.random.default_rng(self.seed)
        X_normal = np.asarray(X_normal, dtype=float)

        weights = pnp.array(rng.uniform(0, 2 * np.pi, self._weight_shape), requires_grad=True)
        optimizer = qml.AdamOptimizer(stepsize=self.config.learning_rate)
        n = len(X_normal)
        batch = min(self.config.batch_size, n)

        def loss(w, batch_X):
            return pnp.mean(self._trash_probability(w, batch_X))

        self.history = []
        for epoch in range(self.config.epochs):
            order = rng.permutation(n)
            epoch_losses = []
            for start in range(0, n, batch):
                idx = order[start : start + batch]
                batch_X = pnp.array(X_normal[idx], requires_grad=False)
                weights, value = optimizer.step_and_cost(loss, weights, batch_X)
                # step_and_cost passes every positional arg; only weights is trainable
                weights = weights[0] if isinstance(weights, (list, tuple)) else weights
                epoch_losses.append(float(value))
            self.history.append(float(np.mean(epoch_losses)))
            if self.verbose and (epoch % 10 == 0 or epoch == self.config.epochs - 1):
                print(f"[{self.name}] epoch {epoch:3d}  trash prob {self.history[-1]:.4f}")

        self.weights = weights
        return self

    def score(self, X: np.ndarray) -> np.ndarray:
        self._check_fitted("weights")
        self._validate(X)
        _, pnp = _require_pennylane()
        X = pnp.array(np.asarray(X, dtype=float), requires_grad=False)
        scores = self._trash_probability(self.weights, X)
        return np.asarray(scores, dtype=float).reshape(-1)

    def _validate(self, X: np.ndarray) -> None:
        if X.ndim != 2 or X.shape[1] != self.config.n_qubits:
            raise ValueError(
                f"{self.name} expects shape (n, {self.config.n_qubits}); got {X.shape}. "
                "Run the features through QubitReducer first."
            )
