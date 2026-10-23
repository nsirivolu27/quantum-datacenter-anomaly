# 7. Honest benchmarking

Code: `src/qdc_anomaly/evaluation/benchmark.py`, `src/qdc_anomaly/evaluation/metrics.py`

Most QML papers that report an advantage made one of a small number of protocol mistakes. This lesson lists them and shows how the benchmark here avoids each one.

## The protocol

1. Generate telemetry once, window it once. The dataset is fixed.
2. For each seed:
   - sample `n_train` **normal, unambiguous** windows as the fit set
   - sample `n_test` windows from the remainder at the natural anomaly rate
   - fit `QubitReducer` on the fit set only
   - fit each detector on the reduced fit set, score the reduced test set
3. Report mean and standard deviation across seeds.

## The mistakes it avoids

**Leaking test data into preprocessing.** The scaler and PCA are fit on the training windows only. Fitting them on everything lets the test anomalies shape the feature space, which flatters every detector but flatters the ones most sensitive to feature geometry (kernels) the most.

**Different features for different methods.** Every detector receives the identical four dimensional vectors. If the quantum SVM saw raw 21 dimensional features and the classical SVM saw PCA scores, any difference would be uninterpretable.

**Training on contaminated normal data.** Only windows with zero fault coverage enter the fit set. Semi supervised detectors assume this.

**One seed.** Variational circuits are seed sensitive; so is which anomalies land in the test set. Three seeds is the minimum; `--set benchmark.seeds=[0,1,2,3,4]` is better when you have the time.

**Accuracy on an imbalanced problem.** With 8 percent anomalies a detector that flags nothing is 92 percent accurate. Accuracy is not reported anywhere.

**Threshold chosen after seeing the test labels.** The F1, precision and recall columns use a fixed **alert budget**: flag exactly the top 10 percent of scores. That is how an operations team actually works ("we can look at ten alerts a day") and it cannot be tuned to the test set.

## The metrics

| Column | Question it answers |
|---|---|
| ROC AUC | Across all thresholds, how well does the score rank anomalies above normal? 0.5 is chance. |
| PR AUC | Same, but focused on the rare positive class; more sensitive to the top of the ranking. |
| Precision at 10 percent | Of the alerts we would actually page on, how many are real? |
| Recall at 10 percent | Of the real faults, how many made it into those alerts? |
| F1 at 10 percent | Harmonic mean of the two. |
| Fit (s), Score (s) | Wall clock. The quantum rows will be orders of magnitude slower on a simulator; that is a real cost. |

The second table, recall per fault type at the alert budget, is the one to read most carefully. An average hides a detector that catches every power spike and no memory leaks.

## How to read the report

Open `results/report.md` after `make benchmark`. Then:

1. Compare each quantum row to its classical twin (kernel SVM vs RBF SVM, autoencoder vs PCA). Those are the apples to apples comparisons.
2. Look at the standard deviations. A 0.03 difference with a 0.07 standard deviation is noise.
3. Look at the per fault table for any fault where one method is clearly better. That is where a feature map story, if any, lives.
4. Look at the timing columns and ask whether a difference you found is worth the cost.

## What the default run shows

Numbers from the classical rows are in lesson 4. For the quantum rows, run the benchmark and record what you see in `docs/results.md` (a template is provided). The repository deliberately does not ship quantum numbers in the lesson text: they depend on simulator version, seed, and epoch count, and the exercise of producing and interpreting them is the lesson.

## Exercises

- Set `benchmark.n_train=60` and rerun. Kernel methods degrade gracefully with less data; does the autoencoder?
- Include ambiguous windows as anomalous (one line change in `split_windows`) and record how far every ROC AUC falls. Now you know how much a labeling convention is worth.
- Add a fourth classical baseline (local outlier factor is a two line addition) and see whether it changes any conclusion.
