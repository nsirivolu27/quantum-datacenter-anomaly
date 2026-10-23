# 2. Telemetry simulation

Code: `src/qdc_anomaly/data/synthetic.py`

## Why simulate

Public data center telemetry with trustworthy fault labels does not exist. Without labels you cannot compute recall, and without recall you cannot compare detectors. A simulator gives you ground truth and lets you control the difficulty.

The trade off is realism. The generator here is deliberately simple so you can read it in five minutes and know exactly what signal exists. Everything is a function of one latent variable, the **load curve**, plus noise and a few physical couplings.

## The normal regime

```
load          diurnal sine (quiet at night, busy by day) + mean reverting drift
cpu_util      100 * load + noise
mem_util      slow low pass of load, 40 to 70 percent
power_kw      2 + 6 * load
inlet_temp_c  18 + 12 * lowpass(power / 8)      <- thermal lag: temperature cannot jump
fan_rpm       2000 + 180 * (temp - 18)          <- the cooling loop reacts to temperature
net_mbps      load * lognormal noise            <- bursty
disk_iops     load * lognormal noise
```

Two details matter for detection:

- **Thermal lag.** `_thermal_lag` is a first order low pass filter. Temperature trails power by several steps. A detector that only looks at one instant cannot see this; windows (lesson 3) can.
- **Coupling.** Fan speed is a function of temperature, temperature of power, power of CPU. Normal data lives on a low dimensional manifold inside the 7 metric space. Anomalies are points off that manifold.

## The five fault modes

| Fault | What changes | Which coupling breaks |
|---|---|---|
| `thermal_runaway` | temperature ramps +8 C, fans rise but not enough | temperature vs power |
| `memory_leak` | memory ramps toward 99 percent | memory vs load |
| `fan_failure` | fan RPM drops 60 percent, temperature rises | fan vs temperature |
| `network_saturation` | network pinned near 9500 Mbps, CPU +8 | network vs CPU |
| `power_spike` | power +2.5 kW with no CPU change | power vs CPU |

Each fault is a contiguous segment of 20 to 60 steps. Ramped faults start small, which is realistic and also makes the first few steps hard to detect. Lesson 3 explains how windows handle that.

## Controlling difficulty

`DataConfig` has four levers:

- `anomaly_fraction` controls how many segments are injected
- `n_steps` and `n_racks` control dataset size
- `seed` makes everything reproducible

To make the task harder, shrink the fault magnitudes in `_inject_fault`. To make it easier, grow them. A good exercise is to find the magnitude at which the classical baselines start failing and see whether the quantum detectors fail at the same point.

## Checking a generated dataset

```bash
qdc generate --out data/telemetry.csv
```

prints a fault type count table. The tests in `tests/test_data_and_features.py` assert that the anomaly fraction is close to the requested value, that labels and fault types agree, and that a thermal runaway segment really is hotter at its end than the steps before it.

## Real data

`src/qdc_anomaly/data/cloudwatch.py` loads the same frame layout from Amazon CloudWatch. It has no labels, so you can score with it but not compute recall. The usual approach is to fit on a quiet week and review the top scored windows by hand.
