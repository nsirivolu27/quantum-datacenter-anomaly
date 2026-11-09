# 6. The quantum autoencoder

Code: `src/qdc_anomaly/detectors/quantum_autoencoder.py`

## The idea

A classical autoencoder squeezes data through a narrow bottleneck and then tries to rebuild it. Normal data, which it trained on, rebuilds well. Unusual data does not. The rebuild error is the anomaly score.

The quantum version does the same thing with qubits:

1. load the 4 numbers onto 4 qubits
2. apply a trainable circuit
3. split the qubits into 2 **latent** qubits (keep) and 2 **trash** qubits (should be empty)

"Empty" means the trash qubit reads 0 when measured. Training adjusts the circuit so that, on normal data, the trash qubits read 0 as often as possible. All the information gets pushed into the latent qubits.

At scoring time, the anomaly score is simply **how often a trash qubit reads 1**. If the circuit cannot push a window into 2 qubits, that window is unlike the training data.

## Why there is no decoder

Quantum circuits can be run backwards exactly. If the circuit compresses normal data perfectly, running it in reverse rebuilds the input perfectly. So you never need to build the decoder; checking the trash qubits is enough.

## The circuit

```python
qml.AngleEmbedding(x, wires, rotation="Y")        # 4 numbers -> 4 qubits
qml.StronglyEntanglingLayers(weights, wires)       # the trainable part
return [qml.expval(qml.PauliZ(w)) for w in trash_wires]
```

`StronglyEntanglingLayers` is a standard off the shelf circuit: three rotations per qubit, then link neighbours, repeated `n_layers` times. The `weights` are what training adjusts.

A measurement of +1 on a trash qubit means it read 0; the probability of reading 1 is `(1 - measurement) / 2`. The training loss is the average of that over the trash qubits and over a batch.

## Training

Plain Adam optimiser, mini batches of normal windows, for `epochs` rounds. The detector keeps `history`, the loss per epoch, so you can plot it. The tests check the loss goes down.

PennyLane can push a whole batch of windows through the circuit in one call, which is what makes training reasonable on a laptop.

## One thing to know: flat training

Big random quantum circuits have a known problem where the training signal vanishes and the loss stays flat. At 4 qubits and 2 layers this does not happen, which is one more reason small telemetry problems are a good place to learn. If you go to 10 or more qubits and training stalls, this is why. Fewer layers usually fixes it.

## Reading the results

Compare `quantum_autoencoder` with `pca_reconstruction`. Both compress to 2 dimensions and score by how badly compression went.

- quantum higher: the circuit found structure the linear PCA missed
- classical higher: the data is close to linear and the circuit did not fully train, or found a poor solution
- always check `history`: if the final loss is still above about 0.2 the model has not finished training. Raise `epochs` before drawing conclusions.

## Things to try

- Plot `history` for three seeds. Training is seed sensitive and you should see it.
- Try `n_latent` of 1 and 3. Does the best setting match what PCA prefers?
- Swap `rotation="Y"` for `"X"`. In theory nothing changes; does it in practice?
