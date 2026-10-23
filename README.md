# Quantum Data Center Anomaly Detection

A beginner friendly project that answers one question: **can a small quantum circuit spot problems in data center telemetry, and how does it stack up against the tools teams already use?**

You do not need a quantum background to follow it. If you know basic Python and have seen scikit-learn before, you can read every file in this repo. The quantum parts are explained from scratch in `docs/`.

## The idea in one picture

```
rack metrics   ->   10 minute windows   ->   4 numbers per window   ->   detector   ->   anomaly score
(cpu, temp, fan, ...)                                                       |
                                          classical:  isolation forest, one class SVM, PCA
                                          quantum:    quantum kernel SVM, quantum autoencoder
```

Every detector gets the same four numbers and is scored the same way. So any difference in the results comes from the detector, not from the data prep.

## Why data centers

Every server rack reports CPU, memory, temperature, fan speed, power, network and disk. Problems like a dying fan or a memory leak do not trip a simple threshold; they show up as the *relationship* between metrics going wrong (temperature too high for the current power draw, for example). That is an anomaly detection problem.

It is also a good fit for today's small quantum computers: the data is a few continuous numbers, which maps directly onto a few qubits. Both quantum models here use 4 qubits.

## Quick start

Terminal (PowerShell or bash, from the repo folder):

```bash
pip install -e ".[dev,plots]"
make test-fast          # classical tests, a few seconds
make test               # adds the quantum tests, about a minute
make benchmark-quick    # small end to end run, a couple of minutes
make benchmark          # full run, writes results/report.md
```

Or with Docker:

```bash
docker build -t qdc-anomaly .
docker run --rm -v "$PWD/results:/app/results" qdc-anomaly
```

## What is inside

| Folder | What it does |
|---|---|
| `src/qdc_anomaly/data/` | Makes fake but realistic telemetry with labeled faults; loads real data from CloudWatch |
| `src/qdc_anomaly/features/` | Turns the time series into windows and shrinks each window to 4 numbers |
| `src/qdc_anomaly/detectors/` | The five detectors, all with the same `fit` and `score` methods |
| `src/qdc_anomaly/evaluation/` | Scoring and the benchmark that compares everything |
| `configs/default.yaml` | Every setting in one file |
| `docs/` | The lessons, in order |
| `notebooks/walkthrough.ipynb` | The whole pipeline in one notebook |
| `tests/` | Checks that each piece does what it says |

## Lessons

Read these in order. Each one is short and points at the code it explains.

1. [What problem are we solving](docs/01-problem-framing.md)
2. [How the fake telemetry is made](docs/02-telemetry-simulation.md)
3. [Getting the data ready for qubits](docs/03-features-for-qubits.md)
4. [The classical detectors](docs/04-classical-baselines.md)
5. [Quantum kernels, explained simply](docs/05-quantum-kernels.md)
6. [The quantum autoencoder](docs/06-quantum-autoencoder.md)
7. [Comparing fairly](docs/07-honest-benchmarking.md)
8. [Running on a real quantum computer](docs/08-running-on-hardware.md)

## Command line

```bash
qdc generate  --out data/telemetry.csv                       # make a dataset
qdc benchmark --config configs/default.yaml                  # compare all detectors
qdc benchmark --detectors isolation_forest quantum_autoencoder --set quantum.epochs=20
qdc score     --input data/telemetry.csv --detector quantum_kernel_svm --out results/scores.csv
```

Change any setting with `--set section.key=value`.

## Adding your own detector

Subclass `AnomalyDetector` (two methods: `fit` and `score`), add it to the list in `detectors/__init__.py`, write one test. It then shows up in the CLI and the benchmark automatically.

## What to expect

The quantum models are not expected to beat the classical ones on a laptop simulator. The goal is a fair, readable comparison so you can see where a quantum approach helps, where it does not, and what it costs in time.

## License

MIT.
