# 1. Problem framing

## What a data center operator actually wants

A modern data center hall holds hundreds of racks. Each rack reports a handful of metrics every few seconds: CPU and memory utilisation, inlet air temperature, fan speed, power draw, network throughput, disk IOPS. Monitoring stacks (CloudWatch, Prometheus, Datadog, DCIM tools) already alert on static thresholds: "page someone if inlet temperature exceeds 32 C".

Static thresholds miss the interesting failures. A fan that is slowly dying does not trip a threshold; it shows up as temperature drifting a few degrees above what the current power draw should produce. A memory leak looks fine until the hour it falls over. A misconfigured switch pins network traffic high while CPU barely moves. These are **joint** anomalies: no single metric is out of range, but the relationship between metrics is wrong.

That is the job of anomaly detection: learn what the joint distribution of normal operation looks like, then score how far a new observation falls from it.

## Why this is semi supervised

Operators have mountains of normal data and very few labeled faults. So the realistic setup is:

- fit on data believed to be normal
- score new data
- flag the top fraction as alerts, where the fraction is set by how many pages a team can absorb

Everything in this repository follows that shape. Detectors expose `fit(X_normal)` and `score(X)`. Thresholding happens only in evaluation.

## Why it suits small quantum circuits

Quantum machine learning on current hardware is limited to a few dozen noisy qubits, and simulators used for research get slow past ten to fifteen. That rules out images and text. It does not rule out telemetry:

- the data is dense and continuous, which maps directly onto rotation angles
- the useful signal is low dimensional (after PCA, four components keep most of the variance of the windowed features)
- the problem is a similarity or compression problem, and both quantum kernels and quantum autoencoders are exactly that

So telemetry anomaly detection is one of the few industrially relevant problems where a 4 qubit circuit is not a toy reduction of the real thing. It is close to the real thing.

## What "potentially usable in a data center now" means here

Three things are true today:

1. The classical baselines in this repository run in milliseconds and could be deployed as is.
2. The quantum kernel SVM runs on a simulator in minutes for a few hundred windows and could be run on cloud QPUs (Braket, IBM) for a scoring pass, at a cost per circuit.
3. Nobody should expect a speedup. The research question is whether the quantum feature map produces a better **similarity measure** or **compression** for this kind of data. The benchmark is designed to answer that fairly.

## What you will be able to do after the sequence

- generate labeled telemetry with realistic correlated faults
- turn a time series into qubit ready features and know the pitfalls
- implement a quantum kernel and a variational autoencoder in PennyLane
- run a fair semi supervised benchmark and read its report critically
- swap the simulator for a real device
