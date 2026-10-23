# 1. What problem are we solving

## The situation

A data center has hundreds of server racks. Each one reports a few numbers every minute:

- CPU and memory usage
- inlet air temperature
- fan speed
- power draw
- network and disk activity

Monitoring tools already raise alarms when one number crosses a line, like "temperature above 32 C". That catches the obvious stuff. It misses the slow problems:

- a fan that is wearing out, so temperature drifts a little higher than it should for the current power draw
- a memory leak that looks fine right up until the server falls over
- a switch misconfiguration that pins network traffic high while CPU stays low

In every one of those, no single number is out of range. What is wrong is the *relationship* between numbers. Catching that is called **anomaly detection**.

## How anomaly detection works here

We almost never have labeled examples of faults, but we have endless examples of normal operation. So the approach is:

1. show the model lots of normal data
2. ask it to score new data by how unusual it looks
3. look at the highest scores first

Every detector in this repo has the same two methods: `fit(normal_data)` and `score(new_data)`. A higher score means more unusual.

## Why a quantum computer might help

Quantum computers today are small (a few dozen qubits) and noisy. That rules out big problems like images or text. But telemetry is small: after a little preprocessing, each minute of data is just 4 numbers. That fits on 4 qubits.

Two quantum ideas are tested here:

- **Quantum kernel**: use a quantum circuit to measure how similar two windows of data are, then hand that similarity to a normal classical model.
- **Quantum autoencoder**: train a circuit to compress normal data. If it cannot compress a new window, that window is unusual.

Neither is expected to be faster. The question is whether they produce a *better* notion of "unusual" for this kind of data. The benchmark is built to answer that fairly.

## What you will be able to do after the lessons

- generate realistic telemetry with known faults
- prepare time series data for a quantum circuit
- build a quantum kernel and a quantum autoencoder in PennyLane
- run a fair comparison and read the results
- swap the simulator for a real quantum device
