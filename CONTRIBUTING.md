# Contributing

## Setup

Terminal, from the repo root:

```bash
pip install -e ".[dev,plots]"
make test-fast
```

## Before opening a pull request

```bash
make lint
make test
```

CI runs the same two commands plus a tiny end to end benchmark.

## Adding a detector

1. Subclass `AnomalyDetector` in a new module under `src/qdc_anomaly/detectors/`. Implement `fit(X_normal)` and `score(X)`; higher score means more anomalous.
2. Register the name in `build_detector` and the relevant name list in `src/qdc_anomaly/detectors/__init__.py`.
3. Add tests: it fits and scores the `reduced` fixture, it rejects `score` before `fit`, and it beats chance (`roc_auc > 0.55`) on that fixture.
4. If it needs an optional dependency, import it lazily and raise `ImportError` with the exact pip command.

## Adding a fault mode

1. Add a branch to `_inject_fault` in `src/qdc_anomaly/data/synthetic.py` and the name to `FAULT_TYPES`.
2. Add a test that checks the fault does what its name says, the way `test_thermal_runaway_actually_raises_temperature` does.
3. Mention it in `docs/02-telemetry-simulation.md`.

## Style

- Plain, readable code over clever code. Someone in their second year should be able to follow every function.
- Errors are explicit. No silent fallbacks, no swallowed exceptions, no default that hides a misconfiguration.
- Every new config field goes in a dataclass in `config.py` and in `configs/default.yaml` with a comment.
- Docs explain the why; docstrings explain the what.
