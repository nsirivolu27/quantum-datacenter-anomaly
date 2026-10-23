"""Typed configuration for the whole project.

The YAML file in ``configs/`` is the single source of truth for an experiment.
This module turns it into plain dataclasses so the rest of the code never
touches raw dictionaries and typos fail loudly at load time.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml


@dataclass
class DataConfig:
    n_racks: int = 8
    n_steps: int = 1440
    step_minutes: int = 1
    anomaly_fraction: float = 0.08
    seed: int = 7


@dataclass
class FeatureConfig:
    window_size: int = 10
    stride: int = 2
    n_components: int = 4


@dataclass
class QuantumConfig:
    n_qubits: int = 4
    n_layers: int = 2
    n_latent: int = 2
    epochs: int = 60
    batch_size: int = 32
    learning_rate: float = 0.05
    device: str = "default.qubit"


@dataclass
class BenchmarkConfig:
    n_train: int = 160
    n_test: int = 400
    seeds: list[int] = field(default_factory=lambda: [0, 1, 2])
    output_dir: str = "results"


@dataclass
class ExperimentConfig:
    data: DataConfig = field(default_factory=DataConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    quantum: QuantumConfig = field(default_factory=QuantumConfig)
    benchmark: BenchmarkConfig = field(default_factory=BenchmarkConfig)
    detectors: list[str] = field(
        default_factory=lambda: [
            "isolation_forest",
            "one_class_svm",
            "pca_reconstruction",
            "quantum_kernel_svm",
            "quantum_autoencoder",
        ]
    )

    def validate(self) -> None:
        """Catch combinations that would fail deep inside a detector."""
        if self.features.n_components != self.quantum.n_qubits:
            raise ValueError(
                f"features.n_components ({self.features.n_components}) must equal "
                f"quantum.n_qubits ({self.quantum.n_qubits}); each PCA component is "
                "encoded onto one qubit."
            )
        if not 0 < self.quantum.n_latent < self.quantum.n_qubits:
            raise ValueError(
                f"quantum.n_latent ({self.quantum.n_latent}) must be between 1 and "
                f"n_qubits - 1 ({self.quantum.n_qubits - 1})."
            )
        if self.features.window_size < 2:
            raise ValueError("features.window_size must be at least 2 to compute a slope.")
        if not 0.0 < self.data.anomaly_fraction < 0.5:
            raise ValueError("data.anomaly_fraction must be between 0 and 0.5.")


def _build(cls: type, raw: dict[str, Any] | None, path: str) -> Any:
    """Construct ``cls`` from a dict, rejecting unknown keys with a clear message."""
    raw = raw or {}
    allowed = {f.name for f in fields(cls)}
    unknown = set(raw) - allowed
    if unknown:
        raise KeyError(
            f"Unknown key(s) under '{path}': {sorted(unknown)}. Allowed: {sorted(allowed)}"
        )
    return cls(**raw)


def load_config(path: str | Path) -> ExperimentConfig:
    """Load and validate an experiment config from YAML."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with path.open() as handle:
        raw = yaml.safe_load(handle) or {}

    allowed_top = {"data", "features", "quantum", "benchmark", "detectors"}
    unknown_top = set(raw) - allowed_top
    if unknown_top:
        raise KeyError(
            f"Unknown top-level key(s): {sorted(unknown_top)}. Allowed: {sorted(allowed_top)}"
        )

    config = ExperimentConfig(
        data=_build(DataConfig, raw.get("data"), "data"),
        features=_build(FeatureConfig, raw.get("features"), "features"),
        quantum=_build(QuantumConfig, raw.get("quantum"), "quantum"),
        benchmark=_build(BenchmarkConfig, raw.get("benchmark"), "benchmark"),
        detectors=list(raw.get("detectors", ExperimentConfig().detectors)),
    )
    config.validate()
    return config


def apply_overrides(config: ExperimentConfig, overrides: list[str]) -> ExperimentConfig:
    """Apply ``section.key=value`` overrides from the command line.

    Values are parsed with YAML so ``epochs=10`` becomes an int and
    ``seeds=[0,1]`` becomes a list.
    """
    for item in overrides:
        if "=" not in item or "." not in item.split("=", 1)[0]:
            raise ValueError(f"Override must look like section.key=value, got '{item}'")
        dotted, value = item.split("=", 1)
        section_name, key = dotted.split(".", 1)
        section = getattr(config, section_name, None)
        if section is None or not hasattr(section, key):
            raise KeyError(f"No config field '{section_name}.{key}'")
        setattr(section, key, yaml.safe_load(value))
    config.validate()
    return config
