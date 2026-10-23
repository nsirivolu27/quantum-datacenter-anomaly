# 8. Running on hardware

Everything so far ran on `default.qubit`, PennyLane's exact statevector simulator. This lesson covers moving to a faster simulator, then to a real quantum processor, and what changes when you do.

## Step 1: a faster simulator

```bash
pip install pennylane-lightning
qdc benchmark --set quantum.device=lightning.qubit
```

`lightning.qubit` is a C++ statevector simulator with the same semantics as `default.qubit`, typically several times faster. Nothing else changes. Use it for any run with more than a handful of qubits.

## Step 2: shot noise on the simulator

Real devices do not return probabilities; they return samples. Add `shots` to the device to simulate that:

```python
dev = qml.device("default.qubit", wires=4, shots=1000)
```

The device string in the config does not carry shots, so for this experiment edit `QuantumKernelSVMDetector.__init__` or expose a `shots` field in `QuantumConfig` (a good first pull request).

What to expect:

- the kernel matrix becomes noisy; `k(x, x)` is still 1 but off diagonal entries jitter by about `1/sqrt(shots)`
- the one class SVM becomes less stable; `nu` may need raising
- autoencoder gradients become noisy; Adam copes, but lower the learning rate

A kernel matrix that is no longer positive semidefinite is a real failure mode. PennyLane's `qml.kernels.threshold_matrix` and `closest_psd_matrix` are the fixes; read about them before trusting any hardware kernel result.

## Step 3: Amazon Braket

```bash
pip install amazon-braket-pennylane-plugin
```

Then in Python, with AWS credentials configured:

```python
import pennylane as qml

# Managed simulator: fast, cheap, pay per task
dev = qml.device(
    "braket.aws.qubit",
    device_arn="arn:aws:braket:::device/quantum-simulator/amazon/sv1",
    wires=4,
    shots=1000,
    s3_destination_folder=("your-bucket", "qdc-anomaly"),
)

# A real QPU: pick one from the Braket console, check its availability window
dev = qml.device(
    "braket.aws.qubit",
    device_arn="arn:aws:braket:us-east-1::device/qpu/ionq/Aria-1",
    wires=4,
    shots=1000,
    s3_destination_folder=("your-bucket", "qdc-anomaly"),
)
```

`QuantumConfig.device` accepts any PennyLane device name, but Braket devices need extra arguments, so construct the device yourself and pass it in, or extend `QuantumConfig` with `device_kwargs`. Both detectors take the device from `qml.device(config.device, wires=...)` in one place, so the change is small.

Cost model: Braket bills per task plus per shot. A kernel matrix for 160 training points is about 12,700 circuits; at 1000 shots each that is a meaningful bill on a QPU and a small one on SV1. Start with SV1, then run **one scoring pass** (not training) on a QPU with a kernel fit on the simulator.

The CloudWatch loader in `data/cloudwatch.py` uses the same AWS credentials, so a Braket plus CloudWatch pipeline lives entirely in one account.

## Step 4: IBM Quantum

```bash
pip install pennylane-qiskit
```

```python
dev = qml.device("qiskit.remote", wires=4, backend=backend, shots=1000)
```

where `backend` comes from `QiskitRuntimeService`. Same caveats as Braket.

## What actually changes on hardware

1. **Noise.** Gate errors of around 0.1 to 1 percent compound across the circuit. The adjoint trick doubles circuit depth, so the quantum kernel is more exposed than the autoencoder. Expect `k(x, x)` to come back around 0.8 to 0.95 instead of 1 and normalise accordingly.
2. **Connectivity.** The CNOT ring assumes any qubit can talk to its neighbour. Transpilation will insert SWAPs on devices where it cannot. Check the compiled depth.
3. **Latency.** A QPU task takes seconds to minutes to schedule. The kernel matrix must be batched into as few tasks as possible. Braket and Qiskit both support batching circuits in one task; use it.
4. **Determinism.** Tests that assert exact values will fail. Loosen tolerances to a few times `1/sqrt(shots)` for hardware runs.

## The realistic deployment story today

Fit everything on a simulator. Store the training set and the SVM. Periodically, send a batch of recent windows to a QPU for scoring, compare to the simulator's scores for the same windows, and log the disagreement. That gives you a running measurement of how far hardware is from the ideal kernel, which is the number anyone deciding whether to invest in this will ask for.

## Further reading

- Havlicek et al., "Supervised learning with quantum enhanced feature spaces", Nature 2019 (quantum kernels)
- Romero, Olson, Aspuru-Guzik, "Quantum autoencoders for efficient compression of quantum data", 2017
- Schuld and Killoran, "Quantum machine learning in feature Hilbert spaces", PRL 2019
- McClean et al., "Barren plateaus in quantum neural network training landscapes", Nat. Commun. 2018
- PennyLane documentation: kernels module, Braket plugin, Qiskit plugin
