import numpy as np
import pytest

from qdc_anomaly.detectors import CLASSICAL_NAMES, build_detector
from qdc_anomaly.evaluation.benchmark import run_benchmark, summarize, write_report
from qdc_anomaly.evaluation.metrics import compute_metrics, per_fault_recall


@pytest.mark.parametrize("name", CLASSICAL_NAMES)
def test_classical_detector_beats_random(name, reduced, quantum_config):
    detector = build_detector(name, quantum_config, seed=0)
    detector.fit(reduced["X_fit"])
    scores = detector.score(reduced["X_test"])
    assert scores.shape == (len(reduced["y_test"]),)
    assert np.all(np.isfinite(scores))
    metrics = compute_metrics(reduced["y_test"], scores)
    assert metrics.roc_auc > 0.55, f"{name} is not better than chance"


@pytest.mark.parametrize("name", CLASSICAL_NAMES)
def test_score_before_fit_raises(name, reduced, quantum_config):
    with pytest.raises(RuntimeError):
        build_detector(name, quantum_config).score(reduced["X_test"])


def test_unknown_detector_name(quantum_config):
    with pytest.raises(KeyError):
        build_detector("quantum_magic", quantum_config)


def test_perfect_scores_give_perfect_metrics():
    y = np.array([0, 0, 0, 0, 0, 0, 0, 0, 1, 1])
    scores = y.astype(float)
    m = compute_metrics(y, scores, alert_budget=0.2)
    assert m.roc_auc == 1.0 and m.pr_auc == 1.0
    assert m.precision_at_budget == 1.0 and m.recall_at_budget == 1.0


def test_metrics_reject_single_class():
    with pytest.raises(ValueError):
        compute_metrics(np.zeros(10), np.random.rand(10))


def test_metrics_reject_nan_scores():
    y = np.array([0, 1, 0, 1])
    with pytest.raises(ValueError):
        compute_metrics(y, np.array([0.1, np.nan, 0.2, 0.3]))


def test_per_fault_recall_excludes_normal():
    y = np.array([0, 1, 1, 0])
    scores = np.array([0.1, 0.9, 0.2, 0.3])
    faults = np.array(["none", "power_spike", "memory_leak", "none"])
    recall = per_fault_recall(y, scores, faults, alert_budget=0.25)
    assert recall == {"memory_leak": 0.0, "power_spike": 1.0}


def test_benchmark_runs_classical_only_and_writes_report(tiny_experiment, tmp_path):
    tiny_experiment.detectors = CLASSICAL_NAMES
    results = run_benchmark(tiny_experiment, verbose=False)
    assert len(results) == len(CLASSICAL_NAMES)
    summary = summarize(results)
    assert set(summary["detector"]) == set(CLASSICAL_NAMES)
    report = write_report(results, tiny_experiment, tmp_path)
    text = report.read_text()
    assert "ROC AUC" in text
    assert (tmp_path / "summary.csv").exists()
    assert (tmp_path / "runs.json").exists()
