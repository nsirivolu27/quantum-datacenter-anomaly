# 8. Running on a real quantum computer

So far everything ran on `default.qubit`, PennyLane's built in simulator. This lesson covers a faster simulator, then real devices, and what changes when you switch.

## A faster simulator

```bash
pip install pennylane-lightning
qdc benchmark --set quantum.device=lightning.qubit
```

Same results, usually several times faster. Use it for anything bigger than the defaults.

## Simulating measurement noise

A real device does not give you exact probabilities. It runs the circuit many times (called shots) and counts. You can simulate that:

```python
dev = qml.device("default.qubit", wires=4, shots=1000)
```

The config does not have a shots field yet; adding one to `QuantumConfig` is a good first contribution. What you will see:

- kernel values jitter by roughly 1 over the square root of shots
- the SVM gets less stable; you may need to raise `nu`
- autoencoder training gets noisier; lower the learning rate

A noisy kernel matrix can stop being mathematically valid for an SVM. PennyLane has `qml.kernels.closest_psd_matrix` to repair it. Read about that before trusting any hardware kernel result.

## Amazon Braket

```bash
pip install amazon-braket-pennylane-plugin
```

With AWS credentials set up:

```python
import pennylane as qml

# Managed simulator on AWS: cheap, pay per task
dev = qml.device(
    "braket.aws.qubit",
    device_arn="arn:aws:braket:::device/quantum-simulator/amazon/sv1",
    wires=4,
    shots=1000,
    s3_destination_folder=("your-bucket", "qdc-anomaly"),
)

# A real device: pick one in the Braket console and check its hours
dev = qml.device(
    "braket.aws.qubit",
    device_arn="arn:aws:braket:us-east-1::device/qpu/ionq/Aria-1",
    wires=4,
    shots=1000,
    s3_destination_folder=("your-bucket", "qdc-anomaly"),
)
```

Both detectors create their device in one place (`qml.device(config.device, wires=...)`), so pointing them at a Braket device is a small change.

Cost: Braket charges per task plus per shot. A kernel matrix for 160 training windows is about 12,700 circuits. On the SV1 simulator that is cheap; on a real device it adds up. The practical approach is to fit on a simulator and send only a small scoring batch to the real device.

The CloudWatch loader uses the same AWS credentials, so data loading and quantum scoring can live in one account.

## IBM Quantum

```bash
pip install pennylane-qiskit
```

```python
dev = qml.device("qiskit.remote", wires=4, backend=backend, shots=1000)
```

where `backend` comes from `QiskitRuntimeService`. Same advice as Braket.

## What changes on real hardware

1. **Noise.** Each gate has a small error and they add up. The kernel circuit runs the loading circuit twice, so it is more exposed than the autoencoder. Expect a point's similarity to itself to come back around 0.8 to 0.95 instead of 1.
2. **Layout.** Our circuit links each qubit to its neighbour in a ring. Not every device supports that directly; the compiler will add extra gates. Check the compiled depth.
3. **Waiting.** A real device task takes seconds to minutes to schedule. Send circuits in batches, not one at a time.
4. **Exact tests fail.** Loosen tolerances to a few times 1 over the square root of shots.

## A realistic way to use this today

Fit everything on a simulator and save the model. Every so often, send a batch of recent windows to a real device for scoring, compare against the simulator's scores for the same windows, and log the difference. That running number tells you how far hardware is from ideal, which is exactly what someone deciding whether to invest will ask.

## Further reading

- Havlicek et al., "Supervised learning with quantum enhanced feature spaces", Nature 2019
- Romero, Olson, Aspuru-Guzik, "Quantum autoencoders for efficient compression of quantum data", 2017
- PennyLane docs: kernels module, Braket plugin, Qiskit plugin
