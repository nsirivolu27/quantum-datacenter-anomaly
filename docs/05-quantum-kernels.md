# 5. Quantum kernels, explained simply

Code: `src/qdc_anomaly/detectors/quantum_kernel.py`

## The idea

A one class SVM does not look at your data directly. It only needs to know, for any two points, **how similar are they?** That function is called a kernel.

The classical version says two points are similar if they are close together. The quantum version:

1. load point A onto 4 qubits with a small circuit
2. load point B the same way
3. measure how much the two resulting quantum states overlap

Overlap is 1 if the points are identical and 0 if the states are completely different. That number is the kernel.

The SVM then does everything else, exactly as before. The quantum computer only answers "how similar?" questions. This is why kernel methods are the most practical quantum approach right now: the hard optimisation stays classical.

## How overlap is measured

You cannot read overlap off a quantum computer directly. The trick:

1. run the loading circuit for point A
2. run the loading circuit for point B **backwards**
3. check whether every qubit is back at 0

If A and B are the same, step 2 exactly undoes step 1 and you get all zeros every time. The more different they are, the less often you get all zeros. The fraction of all zeros is the overlap.

In code it is three lines:

```python
@qml.qnode(device)
def overlap_circuit(x1, x2):
    feature_map(x1, wires, n_layers)
    qml.adjoint(feature_map)(x2, wires, n_layers)   # the same circuit, backwards
    return qml.probs(wires=wires)                    # probs[0] is "all zeros"
```

## The loading circuit

```python
for each layer:
    rotate each qubit by its feature value        (RY)
    link each qubit to its neighbour              (CNOT ring)
    rotate each qubit by its feature value again  (RZ)
```

Loading the same numbers more than once, with linking steps in between, is called **data re uploading**. One rotation per qubit gives a similarity function classical kernels can already copy. Repeating with links between qubits gives one they cannot easily copy, which is the point.

`n_layers` is in the config. Two is the default. More layers make the kernel pickier (fewer points look similar) and slower.

## What it costs

Fitting on N training windows needs about N squared over 2 circuit runs. Scoring M windows needs M times N more. With the default 160 and 400 that is roughly 77,000 circuit runs per seed, a few minutes on a laptop simulator. On a real device every run costs money, which is why these stay small.

## Reading the results

Compare `quantum_kernel_svm` with `one_class_svm`. They are the same algorithm with a different kernel.

- quantum higher: the quantum similarity suits this data better
- classical higher: the ordinary kernel was already a good fit
- about the same: the limit is the 4 numbers going in, not the kernel

All three outcomes teach you something. Write down which one you got and why you think so.

## Sanity checks

`tests/test_quantum.py` checks that a point is 100 percent similar to itself, that similarity is symmetric, and that it stays between 0 and 1. If you edit the loading circuit, run them first.

## Going further

- Make the loading circuit trainable and optimise it to separate normal from faulty windows (PennyLane calls this kernel alignment).
- Add `shots=1000` to the device to see what measurement noise does to the kernel (lesson 8).
