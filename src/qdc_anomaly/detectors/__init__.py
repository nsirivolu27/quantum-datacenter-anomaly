"""Detector registry. Add a new detector here and it shows up in the CLI and benchmark."""

from __future__ import annotations

from qdc_anomaly.config import QuantumConfig
from qdc_anomaly.detectors.base import AnomalyDetector
from qdc_anomaly.detectors.classical import (
    IsolationForestDetector,
    OneClassSVMDetector,
    PCAReconstructionDetector,
)

CLASSICAL_NAMES = ["isolation_forest", "one_class_svm", "pca_reconstruction"]
QUANTUM_NAMES = ["quantum_kernel_svm", "quantum_autoencoder"]
ALL_NAMES = CLASSICAL_NAMES + QUANTUM_NAMES


def build_detector(name: str, quantum: QuantumConfig, seed: int = 0) -> AnomalyDetector:
    """Create a detector by name. Quantum modules are imported lazily so the
    classical path works without PennyLane installed."""
    if name == "isolation_forest":
        return IsolationForestDetector(seed=seed)
    if name == "one_class_svm":
        return OneClassSVMDetector()
    if name == "pca_reconstruction":
        return PCAReconstructionDetector(n_latent=quantum.n_latent)
    if name == "quantum_kernel_svm":
        from qdc_anomaly.detectors.quantum_kernel import QuantumKernelSVMDetector

        return QuantumKernelSVMDetector(quantum)
    if name == "quantum_autoencoder":
        from qdc_anomaly.detectors.quantum_autoencoder import QuantumAutoencoderDetector

        return QuantumAutoencoderDetector(quantum, seed=seed)
    raise KeyError(f"Unknown detector '{name}'. Available: {ALL_NAMES}")


__all__ = [
    "ALL_NAMES",
    "CLASSICAL_NAMES",
    "QUANTUM_NAMES",
    "AnomalyDetector",
    "IsolationForestDetector",
    "OneClassSVMDetector",
    "PCAReconstructionDetector",
    "build_detector",
]
