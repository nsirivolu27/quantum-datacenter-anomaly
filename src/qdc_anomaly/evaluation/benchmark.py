"""Run every detector on the same data and write a report.

The protocol, which is the part worth studying:

    1. Generate telemetry, window it, hold the whole thing fixed.
    2. For each seed:
         a. sample n_train windows that are labeled normal        -> fit set
         b. sample n_test windows from the rest, mixed labels     -> test set
         c. fit the QubitReducer on the fit set only (no peeking at test data)
         d. fit each detector on the reduced fit set, score the reduced test set
    3. Report mean and std across seeds.

Every detector sees the identical reduced vectors.  Any difference in the
table is due to the detector, not to feature engineering.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from qdc_anomaly.config import ExperimentConfig
from qdc_anomaly.data.synthetic import METRIC_COLUMNS, generate_telemetry
from qdc_anomaly.detectors import build_detector
from qdc_anomaly.evaluation.metrics import compute_metrics, per_fault_recall
from qdc_anomaly.features.reduce import QubitReducer
from qdc_anomaly.features.windows import WindowedDataset, make_windows


@dataclass
class RunResult:
    detector: str
    seed: int
    roc_auc: float
    pr_auc: float
    precision_at_budget: float
    recall_at_budget: float
    f1_at_budget: float
    fit_seconds: float
    score_seconds: float
    per_fault_recall: dict[str, float]


def split_windows(
    dataset: WindowedDataset, n_train: int, n_test: int, seed: int
) -> tuple[WindowedDataset, WindowedDataset]:
    """Normal only fit set, mixed test set, disjoint.

    Ambiguous windows (fault covers less than half the window) are excluded
    from both sets: they are neither clean enough to teach "normal" nor
    anomalous enough to fairly penalise a miss.
    """
    rng = np.random.default_rng(seed)
    normal_idx = np.flatnonzero((dataset.y == 0) & ~dataset.ambiguous)
    anomalous_idx = np.flatnonzero(dataset.y == 1)
    if len(normal_idx) < n_train + n_test // 2:
        raise ValueError(
            f"Only {len(normal_idx)} normal windows; need at least {n_train + n_test // 2}. "
            "Increase data.n_steps or data.n_racks, or lower benchmark sizes."
        )
    if len(anomalous_idx) < 5:
        raise ValueError(
            f"Only {len(anomalous_idx)} anomalous windows; increase data.anomaly_fraction."
        )

    normal_idx = rng.permutation(normal_idx)
    train_idx = normal_idx[:n_train]
    remaining_normal = normal_idx[n_train:]

    # Keep the natural anomaly rate in the test set, capped by availability.
    n_anom = min(len(anomalous_idx), max(5, int(n_test * len(anomalous_idx) / len(dataset))))
    n_norm = min(len(remaining_normal), n_test - n_anom)
    test_idx = np.concatenate(
        [
            rng.choice(remaining_normal, n_norm, replace=False),
            rng.choice(anomalous_idx, n_anom, replace=False),
        ]
    )
    test_idx = rng.permutation(test_idx)

    train_mask = np.zeros(len(dataset), dtype=bool)
    train_mask[train_idx] = True
    test_mask = np.zeros(len(dataset), dtype=bool)
    test_mask[test_idx] = True
    return dataset.subset(train_mask), dataset.subset(test_mask)


def run_benchmark(config: ExperimentConfig, verbose: bool = True) -> list[RunResult]:
    telemetry = generate_telemetry(config.data)
    dataset = make_windows(telemetry, config.features, METRIC_COLUMNS)
    if verbose:
        print(
            f"Telemetry: {len(telemetry)} rows, {len(dataset)} windows, "
            f"{int(dataset.y.sum())} anomalous ({dataset.y.mean():.1%})"
        )

    results: list[RunResult] = []
    for seed in config.benchmark.seeds:
        train, test = split_windows(
            dataset, config.benchmark.n_train, config.benchmark.n_test, seed
        )
        reducer = QubitReducer(n_components=config.features.n_components).fit(train.X)
        X_train = reducer.transform(train.X)
        X_test = reducer.transform(test.X)
        if verbose:
            kept = reducer.explained_variance_ratio.sum()
            print(
                f"\nSeed {seed}: train {len(train)} normal, test {len(test)} "
                f"({int(test.y.sum())} anomalous), PCA keeps {kept:.1%} of variance"
            )

        for name in config.detectors:
            detector = build_detector(name, config.quantum, seed=seed)
            t0 = time.perf_counter()
            detector.fit(X_train)
            t1 = time.perf_counter()
            scores = detector.score(X_test)
            t2 = time.perf_counter()

            metrics = compute_metrics(test.y, scores)
            faults = per_fault_recall(test.y, scores, test.fault_type)
            results.append(
                RunResult(
                    detector=name,
                    seed=seed,
                    fit_seconds=t1 - t0,
                    score_seconds=t2 - t1,
                    per_fault_recall=faults,
                    **{k: v for k, v in metrics.as_dict().items() if k != "alert_budget"},
                )
            )
            if verbose:
                print(
                    f"  {name:22s} ROC AUC {metrics.roc_auc:.3f}  PR AUC {metrics.pr_auc:.3f}  "
                    f"F1@10% {metrics.f1_at_budget:.3f}  fit {t1 - t0:5.1f}s  score {t2 - t1:5.1f}s"
                )
    return results


def summarize(results: list[RunResult]) -> pd.DataFrame:
    rows = [{k: v for k, v in asdict(r).items() if k != "per_fault_recall"} for r in results]
    frame = pd.DataFrame(rows)
    metric_cols = [
        "roc_auc",
        "pr_auc",
        "precision_at_budget",
        "recall_at_budget",
        "f1_at_budget",
        "fit_seconds",
        "score_seconds",
    ]
    summary = frame.groupby("detector", sort=False)[metric_cols].agg(["mean", "std"])
    summary.columns = [f"{m}_{s}" for m, s in summary.columns]
    return summary.reset_index()


def fault_table(results: list[RunResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        for fault, recall in r.per_fault_recall.items():
            rows.append({"detector": r.detector, "fault": fault, "recall": recall})
    if not rows:
        return pd.DataFrame(columns=["detector", "fault", "recall"])
    frame = pd.DataFrame(rows)
    return frame.pivot_table(
        index="detector", columns="fault", values="recall", aggfunc="mean", sort=False
    ).reset_index()


def _format_cell(row: pd.Series, metric: str, digits: int = 3) -> str:
    """'mean ± std' for one metric, or just the mean when there is a single seed."""
    mean, std = row[f"{metric}_mean"], row[f"{metric}_std"]
    std_text = "" if np.isnan(std) else f" ± {std:.{digits}f}"
    return f"{mean:.{digits}f}{std_text}"


def write_report(
    results: list[RunResult], config: ExperimentConfig, output_dir: str | Path
) -> Path:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    summary = summarize(results)
    faults = fault_table(results)
    summary.to_csv(output_dir / "summary.csv", index=False)
    faults.to_csv(output_dir / "per_fault_recall.csv", index=False)
    with (output_dir / "runs.json").open("w") as handle:
        json.dump([asdict(r) for r in results], handle, indent=2)

    lines = ["# Benchmark report", ""]
    lines.append(
        f"Seeds: {config.benchmark.seeds}. Fit set: {config.benchmark.n_train} normal windows. "
        f"Test set: up to {config.benchmark.n_test} windows. Qubits: {config.quantum.n_qubits}. "
        f"Alert budget: top 10% of scores flagged."
    )
    lines += ["", "## Detection quality (mean ± std across seeds)", ""]
    lines.append(
        "| Detector | ROC AUC | PR AUC | Precision@10% | Recall@10% | F1@10% | Fit (s) | Score (s) |"
    )
    lines.append("|---|---|---|---|---|---|---|---|")
    for _, row in summary.iterrows():
        cells = [
            _format_cell(row, "roc_auc"),
            _format_cell(row, "pr_auc"),
            _format_cell(row, "precision_at_budget"),
            _format_cell(row, "recall_at_budget"),
            _format_cell(row, "f1_at_budget"),
            _format_cell(row, "fit_seconds", digits=1),
            _format_cell(row, "score_seconds", digits=1),
        ]
        lines.append(f"| {row['detector']} | " + " | ".join(cells) + " |")

    if not faults.empty:
        lines += ["", "## Recall at the alert budget by fault type", ""]
        fault_cols = [c for c in faults.columns if c != "detector"]
        lines.append("| Detector | " + " | ".join(fault_cols) + " |")
        lines.append("|---|" + "---|" * len(fault_cols))
        for _, row in faults.iterrows():
            cells = [f"{row[c]:.2f}" if pd.notna(row[c]) else "n/a" for c in fault_cols]
            lines.append(f"| {row['detector']} | " + " | ".join(cells) + " |")

    report_path = output_dir / "report.md"
    report_path.write_text("\n".join(lines) + "\n")
    return report_path
