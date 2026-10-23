# 3. Features for qubits

Code: `src/qdc_anomaly/features/windows.py`, `src/qdc_anomaly/features/reduce.py`

## From time series to vectors

All detectors here are point based: they score one vector at a time. Faults are temporal. Sliding windows bridge the gap.

For each rack and each window of `window_size` steps, we compute per metric:

- **mean** (the level)
- **std** (the volatility)
- **slope** (last minus first, the trend)

Seven metrics times three summaries gives a 21 dimensional vector. The slope is what catches ramps: a thermal runaway in its first ten steps has a nearly normal mean but a clearly abnormal slope.

## Window labels and the ambiguity rule

A window is **anomalous** if at least half its steps fall inside a fault, **normal** if none do, and **ambiguous** otherwise.

Ambiguous windows are excluded from the benchmark. The reasoning: a window that catches the first two steps of a ramp carries almost no signal. Counting it as anomalous punishes every detector for something nobody could detect; counting it as normal teaches the detector that the beginning of a fault is fine. Neither is honest. Excluding them and saying so is.

The effect is large. With the default config, including ambiguous windows as anomalous drops every detector's ROC AUC by roughly 0.1. When you read a paper's benchmark, this is the kind of choice to look for.

## Down to one number per qubit

The quantum detectors encode one feature per qubit as a rotation angle. Four qubits means four features. `QubitReducer` does:

1. `StandardScaler` fit on the normal training windows
2. `PCA` to `n_components`
3. squash each component into `[0, pi]` using the training range plus a margin, clipping at inference time

The classical detectors receive the identical reduced vectors. That is the fairness rule of the whole repository: every method sees the same four numbers.

## The periodicity trap

Step 3 is the one people skip and regret. Rotation gates are periodic: `RY(theta)` and `RY(theta + 2 pi)` are the same gate. If you feed raw PCA scores as angles, two very different windows can land on the same quantum state and the kernel will call them identical.

Mapping to `[0, pi]` avoids the wraparound. Clipping out of range values at inference does something useful too: a window far outside the training range is itself suspicious, and clipping to the edge of the range preserves that as "as different as possible" rather than wrapping it back toward the middle.

## How much is lost

With the default config PCA to 4 components keeps roughly 65 to 70 percent of the variance of the 21 features. The benchmark prints this per seed. The remaining 30 percent is partly noise and partly real signal, and it is a cost all detectors pay equally. If you have more qubits (or a faster simulator) raise `n_components` and `n_qubits` together; the config validator insists they match.

## Exercises

- Change `window_size` to 5 and 20 and watch which fault types gain or lose recall.
- Replace the mean/std/slope summaries with the raw last step only and see how much the slope was worth.
- Try `angle_max = 2 * pi` in `QubitReducer` and observe the kernel matrix; look for off diagonal entries near 1 between dissimilar windows.
