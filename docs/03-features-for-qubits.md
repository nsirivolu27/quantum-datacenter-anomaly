# 3. Getting the data ready for qubits

Code: `src/qdc_anomaly/features/windows.py` and `src/qdc_anomaly/features/reduce.py`

## Step 1: windows

The detectors score one row at a time, but faults play out over minutes. So we slide a 10 minute window over each rack's data and summarise each window with three numbers per metric:

- **mean**: the typical level in the window
- **std**: how much it bounced around
- **slope**: last value minus first value, the trend

Seven metrics times three summaries gives 21 numbers per window. The slope is what catches ramps: early in a thermal runaway the average temperature looks normal but the slope does not.

## Labeling windows

A window is:

- **anomalous** if at least half of its minutes are inside a fault
- **normal** if none are
- **ambiguous** if it only clips the start or end of a fault

Ambiguous windows are left out of the benchmark. A window that caught the first two minutes of a slow ramp carries almost no signal. Counting it as anomalous would penalise every detector for something nobody could catch; counting it as normal would teach the model that the start of a fault is fine. Leaving them out and saying so is the honest choice.

## Step 2: shrink to 4 numbers

The quantum models encode one number per qubit, and we use 4 qubits. So the 21 numbers per window are reduced to 4:

1. scale every column to mean 0 and spread 1 (using only the normal training data)
2. PCA to 4 components, keeping the directions with the most variation
3. squash each component into the range 0 to pi

The classical detectors get the exact same 4 numbers. That is the fairness rule for the whole repo.

## Why 0 to pi matters

The 4 numbers become rotation angles on the qubits. Rotations wrap around: rotating by 0 and rotating by 2 pi give the same result. If you feed raw numbers in, two very different windows can land on the same quantum state and look identical to the model.

Squashing into 0 to pi avoids the wrap. Values outside the training range are clipped to the edge, which is fine: a window far outside normal is suspicious anyway, and the edge is the "most different" position.

## How much information is lost

With the default settings, 4 components keep about 65 to 70 percent of the variation in the 21 numbers. The benchmark prints this. Every detector pays the same cost. If you have more qubits to spend, raise `n_components` and `n_qubits` together in the config; it will refuse to run if they differ.

## Things to try

- Change `window_size` to 5 and 20 and see which faults get easier or harder.
- Drop the slope and see how much it was worth.
- Set `angle_max` to 2 pi in `QubitReducer` and look at the kernel matrix for windows that wrongly look identical.
