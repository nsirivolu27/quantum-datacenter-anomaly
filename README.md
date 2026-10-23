# Quantum Data Center Anomaly Detection

A study repository that asks one concrete question: **can near term quantum machine learning detect faults in data center telemetry, and how does it compare to the classical tools an SRE team already uses?**

It is built as a real Python package, not a notebook dump. Every detector implements the same two method interface, every method is scored on identical features with identical protocol, and the lesson sequence in `docs/` walks from problem framing to running on real hardware.

```
telemetry  ->  sliding windows  ->  scale + PCA to n_qubits  ->  detector  ->  anomaly score
                                                                |
                      isolation forest / one class SVM / PCA ---+--- quantum kernel SVM / quantum autoencoder
```

## Why this problem

Data centers emit a constant stream of per rack metrics: CPU, memory, inlet temperature, fan speed, power, network, disk. Faults show up as subtle joint shifts across several of them before any single threshold trips. That makes it a natural anomaly detection problem, and the low dimensional, dense, continuous nature of the data makes it a realistic fit for today's small quantum circuits. Both quantum detectors here run on 4 qubits.

## Quick start

Terminal (any shell, from the repo root):

```bash
pip install -e ".[dev,plots]"
make test-fast          # classical, data, metrics, CLI tests; a few seconds
make test               # adds the quantum circuit tests; about a minute
make benchmark-quick    # small end to end run, couple of minutes on a laptop
make benchmark          # full default config, writes results/report.md
```

Or with Docker:

```bash
docker build -t qdc-anomaly .
docker run --rm -v "$PWD/results:/app/results" qdc-anomaly
```

## What is inside

| Path | What you learn there |
|---|---|
| `src/qdc_anomaly/data/synthetic.py` | A physically motivated telemetry simulator with five labeled fault modes |
| `src/qdc_anomaly/data/cloudwatch.py` | Loading the same frame layout from Amazon CloudWatch |
| `src/qdc_anomaly/features/` | Windowing a time series, then scaling and PCA down to one angle per qubit |
| `src/qdc_anomaly/detectors/classical.py` | Isolation forest, RBF one class SVM, PCA reconstruction |
| `src/qdc_anomaly/detectors/quantum_kernel.py` | Quantum kernel via the adjoint trick, fed to a precomputed kernel one class SVM |
| `src/qdc_anomaly/detectors/quantum_autoencoder.py` | Variational quantum autoencoder scored by trash qubit purity |
| `src/qdc_anomaly/evaluation/` | ROC AUC, PR AUC, metrics at a fixed alert budget, per fault recall, the benchmark protocol |
| `configs/default.yaml` | Every knob in one place |
| `docs/` | The lesson sequence |
| `tests/` | What "correct" means for each module |

## The lesson sequence

Read in order; each lesson points at the code it explains.

1. [Problem framing](docs/01-problem-framing.md): what data center anomaly detection is and why it suits small quantum circuits
2. [Telemetry simulation](docs/02-telemetry-simulation.md): the simulator, the fault modes, and why labels matter
3. [Features for qubits](docs/03-features-for-qubits.md): windows, PCA, angle encoding, and the periodicity trap
4. [Classical baselines](docs/04-classical-baselines.md): what the quantum methods have to beat
5. [Quantum kernels](docs/05-quantum-kernels.md): the adjoint trick, data re uploading, kernel SVMs
6. [Quantum autoencoder](docs/06-quantum-autoencoder.md): trash qubits, variational training, barren plateaus
7. [Honest benchmarking](docs/07-honest-benchmarking.md): the protocol, the metrics, and how to read the report
8. [Running on hardware](docs/08-running-on-hardware.md): swapping the simulator for Amazon Braket or IBM, shots, noise, cost

## Command line

```bash
qdc generate  --out data/telemetry.csv                      # synthetic dataset
qdc benchmark --config configs/default.yaml                 # full comparison
qdc benchmark --detectors isolation_forest quantum_autoencoder --set quantum.epochs=20
qdc score     --input data/telemetry.csv --detector quantum_kernel_svm --out results/scores.csv
```

Any config value can be overridden with `--set section.key=value`.

## Extending

Add a detector in three steps: subclass `AnomalyDetector` (two methods, `fit` and `score`), register it in `detectors/__init__.py`, add a test. It will appear in the CLI and the benchmark table automatically.

To run against a real fleet, replace `generate_telemetry` with `load_cloudwatch` (see `docs/08-running-on-hardware.md` for the Braket side).

## Honest expectations

The quantum detectors here are not expected to beat the classical baselines on a simulator, and the benchmark is set up so that if they do not, the table says so. The point of the repository is to make the comparison rigorous and readable, so you can see exactly where a quantum feature map helps, where it does not, and what it costs.

## License

MIT. See `LICENSE`.
