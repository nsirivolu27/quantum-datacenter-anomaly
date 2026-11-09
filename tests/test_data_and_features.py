import numpy as np
import pytest

from qdc_anomaly.config import DataConfig, FeatureConfig
from qdc_anomaly.data.synthetic import FAULT_TYPES, METRIC_COLUMNS, generate_telemetry
from qdc_anomaly.features.reduce import QubitReducer
from qdc_anomaly.features.windows import make_windows


def test_telemetry_shape_and_columns(telemetry, small_data_config):
    assert len(telemetry) == small_data_config.n_racks * small_data_config.n_steps
    for col in ["timestamp", "rack_id", "label", "fault_type", *METRIC_COLUMNS]:
        assert col in telemetry.columns
    assert telemetry["rack_id"].nunique() == small_data_config.n_racks


def test_anomaly_fraction_is_close_to_requested(telemetry, small_data_config):
    actual = telemetry["label"].mean()
    assert abs(actual - small_data_config.anomaly_fraction) < 0.05


def test_every_fault_type_label_is_consistent(telemetry):
    anomalous = telemetry[telemetry["label"] == 1]
    assert set(anomalous["fault_type"]).issubset(FAULT_TYPES)
    assert (telemetry.loc[telemetry["label"] == 0, "fault_type"] == "none").all()


def test_generation_is_deterministic(small_data_config):
    a = generate_telemetry(small_data_config)
    b = generate_telemetry(small_data_config)
    assert a.equals(b)


def test_thermal_runaway_actually_raises_temperature():
    """The end of a thermal runaway segment must be hotter than the steps just before it."""
    frame = generate_telemetry(DataConfig(n_racks=4, n_steps=600, anomaly_fraction=0.15, seed=3))
    checked = 0
    for _, rack in frame.groupby("rack_id"):
        rack = rack.reset_index(drop=True)
        is_hot = (rack["fault_type"] == "thermal_runaway").to_numpy()
        if not is_hot.any():
            continue
        # find segment boundaries
        edges = np.flatnonzero(np.diff(np.concatenate([[0], is_hot.astype(int), [0]])))
        for start, end in zip(edges[::2], edges[1::2], strict=True):
            if start < 20:
                continue
            before = rack["inlet_temp_c"].iloc[start - 20 : start].mean()
            tail = rack["inlet_temp_c"].iloc[end - 5 : end].mean()
            assert tail > before + 3, f"rack segment {start}:{end} did not heat up"
            checked += 1
    assert checked > 0


def test_windows_have_three_summaries_per_metric(windows):
    assert windows.X.shape[1] == 3 * len(METRIC_COLUMNS)
    assert len(windows.feature_names) == windows.X.shape[1]
    assert windows.X.shape[0] == len(windows.y) == len(windows.rack_id)


def test_window_labels_follow_coverage_rule(windows):
    assert set(np.unique(windows.y)) <= {0, 1}
    # ambiguous windows are never labeled anomalous
    assert not np.any(windows.ambiguous & (windows.y == 1))
    assert windows.y.sum() > 0


def test_windows_reject_missing_metric(telemetry):
    with pytest.raises(KeyError):
        make_windows(telemetry.drop(columns=["fan_rpm"]), FeatureConfig(), METRIC_COLUMNS)


def test_reducer_outputs_bounded_angles(windows):
    reducer = QubitReducer(n_components=4).fit(windows.X[:100])
    Z = reducer.transform(windows.X)
    assert Z.shape == (len(windows), 4)
    assert Z.min() >= 0.0 and Z.max() <= np.pi + 1e-9


def test_reducer_requires_fit(windows):
    with pytest.raises(RuntimeError):
        QubitReducer(n_components=4).transform(windows.X)
