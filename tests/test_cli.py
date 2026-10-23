import pandas as pd

from qdc_anomaly.cli import main


def test_generate_writes_csv(tmp_path):
    out = tmp_path / "telemetry.csv"
    code = main(
        ["generate", "--out", str(out), "--set", "data.n_racks=2", "--set", "data.n_steps=300"]
    )
    assert code == 0
    frame = pd.read_csv(out)
    assert len(frame) == 600
    assert "inlet_temp_c" in frame.columns


def test_score_with_classical_detector(tmp_path):
    data = tmp_path / "telemetry.csv"
    main(["generate", "--out", str(data), "--set", "data.n_racks=2", "--set", "data.n_steps=400"])
    out = tmp_path / "scores.csv"
    code = main(
        [
            "score",
            "--input",
            str(data),
            "--detector",
            "isolation_forest",
            "--out",
            str(out),
            "--set",
            "benchmark.n_train=40",
        ]
    )
    assert code == 0
    scores = pd.read_csv(out)
    assert {"timestamp", "rack_id", "score", "label"} <= set(scores.columns)
    assert len(scores) > 0
