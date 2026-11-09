# 7. Comparing fairly

Code: `src/qdc_anomaly/evaluation/benchmark.py` and `src/qdc_anomaly/evaluation/metrics.py`

A lot of quantum machine learning results look better than they are because of small mistakes in how the comparison was run. This lesson shows the mistakes and how the benchmark avoids them.

## The procedure

1. Generate the data once and window it once.
2. For each random seed:
   - pick `n_train` normal windows for training
   - pick `n_test` windows from the rest, with the natural mix of normal and faulty
   - fit the scaler and PCA on the training windows only
   - fit every detector on those, score the test windows
3. Report the average and spread across seeds.

## Mistakes this avoids

**Letting test data into preprocessing.** The scaler and PCA never see test windows. If they did, the faults would shape the feature space and flatter every detector.

**Different inputs for different detectors.** Everyone gets the same 4 numbers. Otherwise you cannot tell whether the detector or the features made the difference.

**Training on data that secretly contains faults.** Only windows with zero fault minutes go into training.

**One random seed.** Quantum training and the test split are both seed sensitive. Three seeds is the minimum; use `--set benchmark.seeds=[0,1,2,3,4]` when you have time.

**Reporting accuracy.** With 8 percent faults, a detector that flags nothing is 92 percent accurate. Accuracy is never shown.

**Picking the threshold after looking at the answers.** Precision, recall and F1 use a fixed **alert budget**: the top 10 percent of scores are flagged, period. That matches how teams work ("we can look at ten alerts a day") and cannot be tuned to the test set.

## The columns

| Column | Plain meaning |
|---|---|
| ROC AUC | How well scores rank faults above normal, across all thresholds. 0.5 is chance, 1.0 is perfect. |
| PR AUC | Same idea, but focused on the rare fault class. More sensitive to the top of the list. |
| Precision at 10 percent | Of the alerts we would send, how many are real faults? |
| Recall at 10 percent | Of the real faults, how many did we catch? |
| F1 at 10 percent | A single number combining the two. |
| Fit (s), Score (s) | Wall clock time. Quantum rows will be much slower on a simulator. That is a real cost. |

The second table, recall per fault type, is the one to read most carefully. An average can hide a detector that catches every power spike and no memory leaks.

## How to read a report

Open `results/report.md` after `make benchmark`, then:

1. Compare each quantum row with its classical twin (kernel SVM vs one class SVM, autoencoder vs PCA).
2. Check the spread. A 0.03 gap with a 0.07 spread is noise.
3. Look at the per fault table for any fault where one model clearly wins.
4. Look at the time columns and ask whether a gain is worth the cost.

## Recording results

Use `docs/results.md`. The classical rows are already there. The quantum rows depend on library version, seed and epoch count, so run them yourself and write down what you see. Producing and interpreting those numbers is the point of the lesson.

## Things to try

- Set `benchmark.n_train=60`. Kernel methods usually cope with less data; does the autoencoder?
- Count ambiguous windows as faults (one line in `split_windows`) and see how far every score drops.
- Add local outlier factor as a fourth classical baseline (two lines) and see if any conclusion changes.
