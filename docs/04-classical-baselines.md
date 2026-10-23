# 4. The classical detectors

Code: `src/qdc_anomaly/detectors/classical.py`

A quantum model only means something next to a strong classical one. Three are included, picked so each quantum model has a classical twin.

## Isolation forest

The go to anomaly detector in most monitoring stacks. It builds random decision trees; points that get isolated in very few splits are unusual. Fast and needs almost no tuning.

## One class SVM

Draws a boundary around the normal data and scores by distance outside it. It only needs a **similarity function** between pairs of points, called a kernel. Here the kernel is the standard RBF: two points are similar if they are close together.

This is the twin of the **quantum kernel SVM** (lesson 5). Same algorithm, different similarity function. Comparing the two rows in the results tells you whether the quantum similarity is any better.

## PCA reconstruction

Fit PCA on normal data with 2 components. For a new point, project it down to 2 numbers and back up again, and score by how much was lost. Normal data reconstructs well; unusual data does not.

This is the twin of the **quantum autoencoder** (lesson 6). Both compress to the same size and score by how badly compression went.

## What they score

From the default settings on a laptop (3 seeds, 160 normal training windows, 400 test windows):

| Detector | ROC AUC | PR AUC | F1 at 10 percent alert budget |
|---|---|---|---|
| isolation_forest | 0.82 | 0.54 | 0.48 |
| one_class_svm | 0.84 | 0.59 | 0.52 |
| pca_reconstruction | 0.75 | 0.45 | 0.41 |

(ROC AUC of 0.5 would be random guessing; 1.0 is perfect. Lesson 7 explains the columns.)

All three are weakest on memory leaks, which are slow and stay within normal range for most of the fault. Keep that in mind when you read the quantum results: a model that lifts memory leak recall is doing something real.

Run `make benchmark` to regenerate these numbers.

## Why no neural network baseline

On a few hundred windows of 4 numbers, a neural network overfits and adds tuning noise without adding insight. The three above are the right comparison at this scale. Adding a small one is a good exercise if you want to.
