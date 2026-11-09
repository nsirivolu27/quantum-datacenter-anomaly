import numpy as np
import pytest

from qdc_anomaly.config import DataConfig, ExperimentConfig, FeatureConfig, QuantumConfig
from qdc_anomaly.data.synthetic import METRIC_COLUMNS, generate_telemetry
from qdc_anomaly.features.reduce import QubitReducer
from qdc_anomaly.features.windows import make_windows


@pytest.fixture(scope="session")
def small_data_config() -> DataConfig:
    return DataConfig(n_racks=3, n_steps=400, step_minutes=1, anomaly_fraction=0.1, seed=1)


@pytest.fixture(scope="session")
def telemetry(small_data_config):
    return generate_telemetry(small_data_config)


@pytest.fixture(scope="session")
def windows(telemetry):
    return make_windows(
        telemetry, FeatureConfig(window_size=10, stride=2, n_components=4), METRIC_COLUMNS
    )


@pytest.fixture(scope="session")
def reduced(windows):
    """Normal fit set and mixed test set already reduced to 4 angles."""
    rng = np.random.default_rng(0)
    normal_idx = np.flatnonzero((windows.y == 0) & ~windows.ambiguous)
    anom_idx = np.flatnonzero(windows.y == 1)
    fit_idx = rng.choice(normal_idx, 40, replace=False)
    rest_normal = np.setdiff1d(normal_idx, fit_idx)
    test_idx = np.concatenate([rng.choice(rest_normal, 60, replace=False), anom_idx[:20]])
    reducer = QubitReducer(n_components=4).fit(windows.X[fit_idx])
    return {
        "X_fit": reducer.transform(windows.X[fit_idx]),
        "X_test": reducer.transform(windows.X[test_idx]),
        "y_test": windows.y[test_idx],
    }


@pytest.fixture
def quantum_config() -> QuantumConfig:
    return QuantumConfig(
        n_qubits=4, n_layers=1, n_latent=2, epochs=3, batch_size=16, learning_rate=0.1
    )


@pytest.fixture
def tiny_experiment() -> ExperimentConfig:
    config = ExperimentConfig()
    config.data = DataConfig(n_racks=3, n_steps=400, anomaly_fraction=0.1, seed=1)
    config.features = FeatureConfig(window_size=10, stride=2, n_components=4)
    config.quantum = QuantumConfig(n_qubits=4, n_layers=1, n_latent=2, epochs=2, batch_size=16)
    config.benchmark.n_train = 40
    config.benchmark.n_test = 80
    config.benchmark.seeds = [0]
    return config
