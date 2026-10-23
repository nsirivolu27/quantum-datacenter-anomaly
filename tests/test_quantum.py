"""Quantum detector tests. Skipped cleanly when PennyLane is not installed."""

import numpy as np
import pytest

pennylane = pytest.importorskip(
    "pennylane", reason="PennyLane not installed; pip install pennylane"
)

from qdc_anomaly.detectors.quantum_autoencoder import QuantumAutoencoderDetector  # noqa: E402
from qdc_anomaly.detectors.quantum_kernel import QuantumKernelSVMDetector  # noqa: E402
from qdc_anomaly.evaluation.metrics import compute_metrics  # noqa: E402

pytestmark = pytest.mark.slow


def test_kernel_is_one_on_identical_inputs(quantum_config):
    detector = QuantumKernelSVMDetector(quantum_config)
    x = np.array([0.3, 1.2, 2.0, 0.7])
    assert detector.kernel(x, x) == pytest.approx(1.0, abs=1e-6)


def test_kernel_is_symmetric_and_bounded(quantum_config):
    detector = QuantumKernelSVMDetector(quantum_config)
    rng = np.random.default_rng(0)
    a, b = rng.uniform(0, np.pi, 4), rng.uniform(0, np.pi, 4)
    kab, kba = detector.kernel(a, b), detector.kernel(b, a)
    assert kab == pytest.approx(kba, abs=1e-6)
    assert 0.0 <= kab <= 1.0


def test_kernel_matrix_matches_pairwise(quantum_config):
    detector = QuantumKernelSVMDetector(quantum_config)
    rng = np.random.default_rng(1)
    A = rng.uniform(0, np.pi, (3, 4))
    K = detector.kernel_matrix(A, A)
    for i in range(3):
        for j in range(3):
            assert K[i, j] == pytest.approx(detector.kernel(A[i], A[j]), abs=1e-6)


def test_quantum_kernel_svm_fits_and_scores(reduced, quantum_config):
    detector = QuantumKernelSVMDetector(quantum_config).fit(reduced["X_fit"])
    scores = detector.score(reduced["X_test"])
    assert scores.shape == (len(reduced["y_test"]),)
    assert np.all(np.isfinite(scores))
    assert compute_metrics(reduced["y_test"], scores).roc_auc > 0.5


def test_quantum_autoencoder_loss_decreases(reduced, quantum_config):
    quantum_config.epochs = 6
    detector = QuantumAutoencoderDetector(quantum_config, seed=0).fit(reduced["X_fit"])
    assert len(detector.history) == 6
    assert detector.history[-1] < detector.history[0]


def test_quantum_autoencoder_scores_are_probabilities(reduced, quantum_config):
    detector = QuantumAutoencoderDetector(quantum_config, seed=0).fit(reduced["X_fit"])
    scores = detector.score(reduced["X_test"])
    assert scores.shape == (len(reduced["y_test"]),)
    assert np.all((scores >= 0) & (scores <= 1))


def test_wrong_dimension_is_rejected(quantum_config):
    with pytest.raises(ValueError, match="expects shape"):
        QuantumKernelSVMDetector(quantum_config).fit(np.zeros((5, 3)))
    with pytest.raises(ValueError, match="expects shape"):
        QuantumAutoencoderDetector(quantum_config).fit(np.zeros((5, 3)))
