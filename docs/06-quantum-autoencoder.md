# 6. Quantum autoencoder

Code: `src/qdc_anomaly/detectors/quantum_autoencoder.py`

## The one idea

A classical autoencoder squeezes data through a bottleneck and scores anomalies by reconstruction error. Normal data was seen during training and compresses well; anomalies do not.

The quantum version (Romero, Olson, Aspuru-Guzik, 2017) does the same with qubits:

```
|x>  --[ U(theta) ]-->  latent qubits (keep)  +  trash qubits (should be |0>)
```

Train `U(theta)` so that on normal data the trash qubits end up in `|0>`. If compression succeeded, all the information fits in the latent qubits and the trash is empty.

At inference, the anomaly score is the probability that a trash qubit reads `|1>`. A window the circuit cannot compress is a window it did not see in training.

## Why there is no decoder

Quantum gates are reversible. If `U(theta)` maps normal data to `latent (x) |0...0>`, then `U(theta)^dagger` applied to `latent (x) |0...0>` recovers the input exactly. A perfect encoder implies a perfect decoder for free, so trash qubit purity alone measures reconstruction quality. You never need to build or run the decoder.

## The circuit

```python
qml.AngleEmbedding(x, wires, rotation="Y")        # 4 features -> 4 qubits
qml.StronglyEntanglingLayers(weights, wires)       # trainable, n_layers deep
return [qml.expval(qml.PauliZ(w)) for w in trash_wires]
```

With `n_qubits=4, n_latent=2` there are two trash qubits. `<Z> = 1` means `|0>`, so the probability of `|1>` is `(1 - <Z>) / 2`. The loss is the mean of that over trash qubits and over a batch.

`StronglyEntanglingLayers` is a standard hardware efficient ansatz: three rotations per qubit followed by a ring of CNOTs, repeated `n_layers` times. Weight shape is `(n_layers, n_qubits, 3)`.

## Training

Plain Adam from PennyLane with autograd, mini batches of normal windows. The detector stores `history`, the mean trash probability per epoch, so you can plot the loss curve. The test suite asserts the loss decreases.

PennyLane broadcasts a batch of inputs through `AngleEmbedding`, so one circuit call evaluates a whole batch. That is what makes training affordable on a simulator.

## Barren plateaus, briefly

Deep random variational circuits have gradients that vanish exponentially in the number of qubits. At 4 qubits and 2 layers this is not a problem, which is one more reason tiny telemetry problems are a good place to study QML. If you scale to 10+ qubits and training stalls at a flat loss, that is the plateau. Mitigations: fewer layers, local cost functions (this one already is local: it measures individual trash qubits), layerwise training, identity initialisation.

## Reading the result

`QuantumAutoencoderDetector` and `PCAReconstructionDetector` share the bottleneck size `n_latent`. Compare their rows:

- quantum higher: the unitary, non linear compression captured structure the linear projection missed
- classical higher: the data is close to linear in the four PCA features and the variational circuit either underfit (too few epochs or layers) or found a poor local minimum
- check `history`: if the final trash probability is still high (above 0.2), the model has not converged; raise `epochs` or `learning_rate` before concluding anything

## Exercises

- Plot `detector.history` for three seeds; variational training is seed sensitive and you should see it.
- Set `n_latent=1` and `n_latent=3`. With one latent qubit the model must throw away a lot; with three it barely compresses. Which gives the best anomaly score, and does the same hold for PCA?
- Replace `rotation="Y"` with `"X"` in the embedding. Nothing should change in principle; does it in practice?
