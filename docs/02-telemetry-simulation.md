# 2. How the fake telemetry is made

Code: `src/qdc_anomaly/data/synthetic.py`

## Why fake data

Real data center telemetry with labeled faults is not public. Without labels you cannot measure how many faults a detector catches. So this repo generates its own data, with faults injected on purpose, and records exactly where they are.

The generator is kept simple on purpose. You can read it in a few minutes and know exactly what signal is in the data.

## Normal operation

Everything starts from one hidden variable: **load**, which follows a daily curve (quiet overnight, busy during the day) plus some drift. The seven metrics are built from it:

| Metric | How it is made |
|---|---|
| `cpu_util` | load, scaled to percent, plus noise |
| `mem_util` | a smoothed version of load, 40 to 70 percent |
| `power_kw` | 2 kW plus 6 kW times load |
| `inlet_temp_c` | follows power, but slowly (temperature cannot jump) |
| `fan_rpm` | rises with temperature (the cooling reacts) |
| `net_mbps` | load with bursty noise |
| `disk_iops` | load with bursty noise |

The important thing is that the metrics are **linked**. Fan depends on temperature, temperature on power, power on CPU. Normal data sits on a narrow band inside the 7 dimensional space. Faults are points that fall off that band.

## The five faults

| Fault | What happens | What breaks |
|---|---|---|
| `thermal_runaway` | temperature ramps up 8 C, fans rise but not enough | temperature vs power |
| `memory_leak` | memory climbs toward 99 percent | memory vs load |
| `fan_failure` | fan speed drops 60 percent, temperature rises | fan vs temperature |
| `network_saturation` | network pinned near maximum, CPU up a bit | network vs CPU |
| `power_spike` | power jumps 2.5 kW with no CPU change | power vs CPU |

Each fault lasts 20 to 60 minutes. The ramped faults start small, which is realistic and also means the first few minutes are hard to catch.

## Settings

In `configs/default.yaml` under `data`:

- `anomaly_fraction` controls how much of the data is inside a fault
- `n_racks` and `n_steps` control dataset size
- `seed` makes the output repeatable

## Try it

```bash
qdc generate --out data/telemetry.csv
```

This prints how many minutes of each fault type were injected.

## Real data

`src/qdc_anomaly/data/cloudwatch.py` loads the same column layout from Amazon CloudWatch. Real data has no labels, so you can score it but not measure recall. The usual approach is to fit on a quiet week and manually review the top scored windows.
