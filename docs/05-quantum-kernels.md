# 5. Quantum kernels

Code: `src/qdc_anomaly/detectors/quantum_kernel.py`

## The one idea

A kernel method never touches raw features. It only needs a similarity `k(x, x')` between pairs of points. The algorithm (here a one class SVM) is entirely classical and convex; the kernel is where you inject structure.

A quantum computer gives a natural similarity. Encode `x` into a quantum state `|phi(x)>` with a fixed circuit. Do the same for `x'`. Then

```
k(x, x') = |<phi(x') | phi(x)>|^2
```

is the squared overlap of the two states: 1 when identical, 0 when orthogonal, and always a valid kernel because it is an inner product in the Hilbert space of the circuit.

## The adjoint trick

You cannot read out an inner product directly. The trick:

1. run the encoding circuit `U(x)`
2. run the inverse encoding circuit `U(x')^dagger`
3. measure all qubits; the probability of `|00...0>` is exactly `|<phi(x')|phi(x)>|^2`

If `x == x'` the two circuits cancel and you land on `|00...0>` with probability 1. The implementation is three lines:

```python
@qml.qnode(device)
def overlap_circuit(x1, x2):
    feature_map(x1, wires, n_layers)
    qml.adjoint(feature_map)(x2, wires, n_layers)
    return qml.probs(wires=wires)
```

`kernel(x1, x2)` returns `probs[0]`.

## The feature map

```python
for _ in range(n_layers):
    RY(x_i) on every qubit         # load the data
    CNOT ring                      # entangle neighbours
    RZ(x_i) on every qubit         # load the data again
```

Loading the same data in several layers is **data re uploading**. One rotation per qubit gives a kernel that is a product of cosines, which classical kernels can already express. Re uploading with entanglement in between gives a kernel that is much harder to write down classically, which is the whole point.

`n_layers=2` is the default. More layers make the kernel sharper (points look less similar) and slower. Try 1 and 3 and watch the kernel matrix.

## Where the cost goes

Fitting on `n` points needs the `n x n` kernel matrix: `n(n-1)/2` circuit runs (symmetric, diagonal is 1). Scoring `m` points needs `m x n` more. With `n=160, m=400` that is about 77,000 circuits per seed on a statevector simulator, a few minutes on a laptop. On a real device every circuit costs shots and money, which is why kernel methods on hardware stay small.

PennyLane's `qml.kernels.square_kernel_matrix` and `kernel_matrix` do the bookkeeping. `assume_normalized_kernel=True` skips computing the diagonal.

## Reading the result

`QuantumKernelSVMDetector` and `OneClassSVMDetector` are the same algorithm with different kernels. Compare their rows in the benchmark table:

- quantum higher: the quantum feature map produced a more useful similarity for this data
- classical higher: the RBF kernel was already a good fit and the quantum map added nothing (or hurt, usually by being too sharp)
- similar: the bottleneck is the four PCA features, not the kernel

All three outcomes are informative. Write down which one you see and why you think so before reading lesson 7.

## Sanity checks you should run

The tests in `tests/test_quantum.py` check that `k(x, x) = 1`, that `k` is symmetric and in `[0, 1]`, and that the batched kernel matrix matches pairwise evaluation. If you change the feature map, run them first.

## Going further

- **Kernel alignment**: make the feature map trainable (add rotation parameters) and optimise it to separate normal from anomalous windows. PennyLane's `qml.kernels.target_alignment` is the tool.
- **Projected quantum kernels**: measure local observables instead of the full overlap; cheaper on hardware and often as good.
- **Shot noise**: set `shots=1000` on the device and watch the kernel matrix become noisy. Lesson 8 covers this.
