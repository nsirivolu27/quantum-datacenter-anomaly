# 4. Classical baselines

Code: `src/qdc_anomaly/detectors/classical.py`

A quantum method that is not compared against a strong classical baseline on identical inputs tells you nothing. Three baselines are included, chosen so that each quantum method has a direct classical twin.

## Isolation forest

The default anomaly detector in most monitoring stacks. It builds random trees that split the data at random thresholds; anomalies are isolated in few splits, normal points in many. Fast, no assumptions about shape, little tuning.

Scoring: `-score_samples`, because scikit-learn returns higher for more normal and the repository convention is higher means more anomalous.

## One class SVM with an RBF kernel

The direct classical twin of the **quantum kernel SVM**. Both are the same algorithm, a one class SVM, with different kernels:

```
RBF kernel       k(x, x') = exp(-gamma * ||x - x'||^2)
quantum kernel   k(x, x') = |<phi(x') | phi(x)>|^2
```

If the quantum kernel SVM beats this one, the quantum feature map produced a more useful similarity for this data. If it does not, it did not. Nothing else differs.

`nu=0.05` is the expected fraction of training outliers; `gamma="scale"` sets the width from the feature variance. Both are kept identical for the quantum version where they apply.

## PCA reconstruction

The direct classical twin of the **quantum autoencoder**. Fit PCA with `n_latent` components on normal data, project a new point down and back up, score by squared reconstruction error. It is a linear autoencoder.

The quantum autoencoder also compresses to `n_latent` qubits and scores by how badly compression went. Same bottleneck size, same idea, different (non linear, unitary) map.

## What the baselines score

From the default config run on the simulator (3 seeds, 160 normal fit windows, 400 test windows, 4 PCA components):

| Detector | ROC AUC | PR AUC | F1 at 10 percent alert budget |
|---|---|---|---|
| isolation_forest | 0.82 ± 0.06 | 0.54 ± 0.13 | 0.48 ± 0.08 |
| one_class_svm | 0.84 ± 0.07 | 0.59 ± 0.09 | 0.52 ± 0.03 |
| pca_reconstruction | 0.75 ± 0.11 | 0.45 ± 0.23 | 0.41 ± 0.19 |

Per fault, every baseline is weakest on `memory_leak`. That is expected: memory is a slow, smooth ramp that stays within its normal range for most of the segment, and after PCA to four components it carries little weight. Keep that in mind when you read the quantum results; a method that lifts memory leak recall is doing something real.

Run `make benchmark` to regenerate these numbers; they will shift slightly with library versions.

## Why not deep learning baselines

An LSTM autoencoder or a transformer would be a stronger baseline on a large real dataset. On a few hundred four dimensional windows they overfit and add tuning noise. The study question here is about feature maps and compression at tiny scale, where the three baselines above are the right comparison. Adding a small MLP autoencoder is a good exercise.
