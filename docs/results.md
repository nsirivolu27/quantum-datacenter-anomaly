# Results log

Record your benchmark runs here so conclusions are tied to a config and a version.

## Template

```
Date:
Machine:
PennyLane version:
Config: configs/default.yaml with overrides: (none)
Command: make benchmark

Paste the two tables from results/report.md below.

Observations (compare each quantum row to its classical twin; note per fault differences
and whether differences exceed the standard deviation):

```

## Classical rows, default config

Statevector simulator not required. Produced with `qdc benchmark --detectors isolation_forest one_class_svm pca_reconstruction`.

| Detector | ROC AUC | PR AUC | Precision at 10% | Recall at 10% | F1 at 10% |
|---|---|---|---|---|---|
| isolation_forest | 0.818 ± 0.064 | 0.536 ± 0.128 | 0.442 ± 0.076 | 0.520 ± 0.090 | 0.477 ± 0.083 |
| one_class_svm | 0.836 ± 0.067 | 0.589 ± 0.090 | 0.483 ± 0.029 | 0.569 ± 0.034 | 0.523 ± 0.031 |
| pca_reconstruction | 0.745 ± 0.112 | 0.449 ± 0.227 | 0.383 ± 0.176 | 0.451 ± 0.207 | 0.414 ± 0.190 |

| Detector | fan_failure | memory_leak | network_saturation | power_spike | thermal_runaway |
|---|---|---|---|---|---|
| isolation_forest | 0.61 | 0.14 | 0.47 | 0.39 | 0.67 |
| one_class_svm | 0.63 | 0.15 | 0.60 | 0.39 | 0.93 |
| pca_reconstruction | 0.65 | 0.39 | 0.23 | 0.39 | 0.27 |

Observation: every baseline is weakest on memory leaks, which are slow and stay within the normal range for most of the segment. PCA reconstruction is the only one that catches a reasonable share of them, at the cost of thermal runaway and network saturation.

## Quantum rows

Not yet recorded. Run `make benchmark` with PennyLane installed and paste the full report here.
