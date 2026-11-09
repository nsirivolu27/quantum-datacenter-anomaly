from pathlib import Path

import pytest

from qdc_anomaly.config import ExperimentConfig, apply_overrides, load_config

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_yaml_loads_and_validates():
    config = load_config(REPO_ROOT / "configs" / "default.yaml")
    assert config.features.n_components == config.quantum.n_qubits
    assert "quantum_kernel_svm" in config.detectors


def test_unknown_key_is_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("quantum:\n  n_qubit: 4\n")
    with pytest.raises(KeyError, match="n_qubit"):
        load_config(bad)


def test_qubit_component_mismatch_is_rejected(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("features:\n  n_components: 3\nquantum:\n  n_qubits: 4\n")
    with pytest.raises(ValueError, match="n_components"):
        load_config(bad)


def test_override_parses_types():
    config = apply_overrides(ExperimentConfig(), ["quantum.epochs=5", "benchmark.seeds=[3,4]"])
    assert config.quantum.epochs == 5
    assert config.benchmark.seeds == [3, 4]


def test_override_rejects_bad_field():
    with pytest.raises(KeyError):
        apply_overrides(ExperimentConfig(), ["quantum.nope=1"])
