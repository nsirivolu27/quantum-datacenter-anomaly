"""Command line entry point.

    qdc generate   --out data/telemetry.csv          write a synthetic dataset
    qdc benchmark  --config configs/default.yaml     run every detector, write results/
    qdc score      --detector quantum_autoencoder    fit on normal data, score a CSV

Run ``qdc <command> --help`` for the flags of each command.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from qdc_anomaly.config import ExperimentConfig, apply_overrides, load_config
from qdc_anomaly.data.synthetic import METRIC_COLUMNS, generate_telemetry
from qdc_anomaly.data.synthetic import summarize as summarize_faults
from qdc_anomaly.detectors import ALL_NAMES, build_detector
from qdc_anomaly.evaluation.benchmark import run_benchmark, write_report
from qdc_anomaly.features.reduce import QubitReducer
from qdc_anomaly.features.windows import make_windows

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "default.yaml"


def _load(args: argparse.Namespace) -> ExperimentConfig:
    config = load_config(args.config) if args.config else ExperimentConfig()
    return apply_overrides(config, args.set or [])


def cmd_generate(args: argparse.Namespace) -> int:
    config = _load(args)
    frame = generate_telemetry(config.data)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(out, index=False)
    print(f"Wrote {len(frame)} rows to {out}")
    print(summarize_faults(frame).to_string(index=False))
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    config = _load(args)
    if args.detectors:
        unknown = set(args.detectors) - set(ALL_NAMES)
        if unknown:
            raise SystemExit(f"Unknown detector(s) {sorted(unknown)}. Available: {ALL_NAMES}")
        config.detectors = args.detectors
    results = run_benchmark(config, verbose=not args.quiet)
    report = write_report(results, config, args.out or config.benchmark.output_dir)
    print(f"\nReport written to {report}")
    print(report.read_text())
    return 0


def cmd_score(args: argparse.Namespace) -> int:
    config = _load(args)
    frame = pd.read_csv(args.input, parse_dates=["timestamp"])
    metrics = [c for c in METRIC_COLUMNS if c in frame.columns]
    if len(metrics) < config.features.n_components:
        raise SystemExit(
            f"Input has {len(metrics)} known metric columns, fewer than n_components={config.features.n_components}"
        )
    dataset = make_windows(frame, config.features, metrics)

    if "label" in frame.columns:
        normal = dataset.subset(dataset.y == 0)
    else:
        normal = dataset  # unlabeled: assume the fit data is mostly normal
    rng = np.random.default_rng(0)
    fit_idx = rng.choice(len(normal), min(len(normal), config.benchmark.n_train), replace=False)
    fit_mask = np.zeros(len(normal), dtype=bool)
    fit_mask[fit_idx] = True
    fit_set = normal.subset(fit_mask)

    reducer = QubitReducer(n_components=config.features.n_components).fit(fit_set.X)
    detector = build_detector(args.detector, config.quantum)
    detector.fit(reducer.transform(fit_set.X))
    scores = detector.score(reducer.transform(dataset.X))

    out = pd.DataFrame({"timestamp": dataset.end_time, "rack_id": dataset.rack_id, "score": scores})
    if "label" in frame.columns:
        out["label"] = dataset.y
        out["fault_type"] = dataset.fault_type
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(out_path, index=False)
    print(f"Wrote {len(out)} window scores to {out_path}")
    top = out.sort_values("score", ascending=False).head(10)
    print(top.to_string(index=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qdc", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--config",
            default=str(DEFAULT_CONFIG) if DEFAULT_CONFIG.exists() else None,
            help="Path to a YAML config (default: configs/default.yaml)",
        )
        p.add_argument(
            "--set",
            action="append",
            metavar="SECTION.KEY=VALUE",
            help="Override a config value, e.g. --set quantum.epochs=20",
        )

    p = sub.add_parser("generate", help="Write a synthetic telemetry CSV")
    add_common(p)
    p.add_argument("--out", default="data/telemetry.csv")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("benchmark", help="Run all detectors and write a report")
    add_common(p)
    p.add_argument("--detectors", nargs="+", help=f"Subset of {ALL_NAMES}")
    p.add_argument("--out", help="Output directory (default: benchmark.output_dir from config)")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(func=cmd_benchmark)

    p = sub.add_parser("score", help="Fit one detector and score every window in a CSV")
    add_common(p)
    p.add_argument(
        "--input", required=True, help="Telemetry CSV (from `qdc generate` or CloudWatch)"
    )
    p.add_argument("--detector", default="quantum_autoencoder", choices=ALL_NAMES)
    p.add_argument("--out", default="results/scores.csv")
    p.set_defaults(func=cmd_score)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
