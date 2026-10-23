"""qdc_anomaly: quantum and classical anomaly detection for data center telemetry.

Study path (each module is written to be read top to bottom):

1. ``data.synthetic``            how telemetry is simulated and faults are injected
2. ``features.windows``          turning a time series into fixed length vectors
3. ``features.reduce``           scaling and PCA down to "one feature per qubit"
4. ``detectors.classical``       the baselines every quantum method must beat
5. ``detectors.quantum_kernel``  quantum kernel + one class SVM
6. ``detectors.quantum_autoencoder``  variational quantum autoencoder
7. ``evaluation.benchmark``      how the comparison is run and reported
"""

from qdc_anomaly.config import ExperimentConfig, load_config

__all__ = ["ExperimentConfig", "load_config", "__version__"]
__version__ = "0.1.0"
