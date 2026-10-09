# Model card: transaction categorizer

**Model version:** `tfidf-lr-5bdd9335` · **Task:** assign one of 17 spending categories to a bank-transaction description · **Type:** TF-IDF (word + character n-grams) → multinomial Logistic Regression, with a confidence threshold that sends uncertain rows to the user.

> **Everything below was measured on SYNTHETIC data.** The numbers show how well the model reproduces the labels of a data generator. They are **not** an estimate of accuracy on real bank statements, which are messier and which this model has never seen.

## Intended use

- Suggest a category for each uploaded transaction so a person can review budgets faster.
- Leave a row `Uncategorized` when the description is missing or the model is not confident, so the person decides.
- Every prediction can be overridden by the user; the user's own label (CSV `category` column, or a correction in the app) always wins.

**Not intended for:** fraud or risk decisions, credit or lending, tax or accounting records, or any decision made without a human able to see and correct the result. It is a portfolio project, not a regulated financial system.

## Training data

| | |
|---|---|
| Source | `DoDataThings/us-bank-transaction-categories-v2` (Hugging Face), pinned to revision `3e8d052c…` |
| License | MIT (as stated on the dataset card) |
| Nature | **Synthetic.** Generated from templates modeled on eight US bank-statement formats, ~500 real merchant names, random store numbers, addresses and reference codes. The card states that real bank data is private. |
| Size | 68,000 rows; 45,702 after removing 22,298 exact duplicates; 17 classes |
| Classes | Education, Entertainment, Fees, Groceries, Healthcare, Income, Insurance, Mortgage, Personal Care, Rent, Restaurants, Shopping, Subscription, Transfer, Transportation, Travel, Utilities |
| How to reproduce | `python -m backend.ml.prepare_training_data` then `python -m backend.ml.train_categorizer` |

Labels are whatever the generator assigned. Some are ambiguous by construction (for example "Zelle payment from …" is labelled `Income` in some rows and `Transfer` in others).

## Features

Text only. The description is lower-cased; digits, reference codes (`ID: …`) and punctuation are removed; a token records whether money went **out** (`dir_debit`, canonical amount > 0) or **in** (`dir_credit`, amount < 0). The amount itself is not used. The same normalization code runs in training and in production. Word 1–2-grams and character 3–5-grams are weighted with TF-IDF.

## How it was evaluated

- **Group-aware split.** Rows are split by an approximate *merchant group* (the first words of the description before any store number, after removing payment-method prefixes such as `SQ *`), never row by row, so the same merchant cannot appear in both training and test data. A random row split would let the model memorize merchants and inflate scores. The grouping is a heuristic: one merchant written two ways can still land in two groups.
- 7 group folds: **1 fold is held out as the test set** (6,752 rows, 1,177 groups, zero groups shared with development); **6 folds form the development set** (38,950 rows).
- **Grouped cross-validation on the development set** gives out-of-fold predictions used to choose the confidence threshold and to measure how much scores vary.
- The shipped model is trained on the whole development set and scored once on the test set.
- Accuracy is reported only as a secondary figure; the classes are balanced, so macro-F1 is the headline metric.

## Results (synthetic data)

| | Macro-F1 | Weighted-F1 | Notes |
|---|---|---|---|
| **Cross-validation (6 folds)** | **0.942 ± 0.026** | | per fold: 0.888, 0.941, 0.946, 0.949, 0.953, 0.974 |
| Held-out test set | 0.972 | 0.973 | accuracy 0.974 (secondary) |
| Keyword-rules baseline, test set | 0.549 | 0.550 | rules cover 55.1% of rows, 83.1% accurate where they apply; rows they cannot categorize count as wrong |

Use the cross-validation figure as the more honest estimate: the test fold happened to be an easier one, and the fold-to-fold spread (0.888 to 0.974) shows how much a few big, ambiguous merchant groups can move the score.

**Confidence threshold: 0.40**, the lowest value for which confident predictions reach 95% accuracy on pooled out-of-fold predictions. On the test set:

- auto-categorized: **98.0%** of rows, **99.0%** accurate
- sent to manual review: **2.0%**

Weakest classes on the test set (per-class precision / recall / F1):

| Class | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| Transfer | 0.98 | 0.64 | 0.78 | 409 |
| Subscription | 0.75 | 1.00 | 0.86 | 336 |
| Entertainment | 0.91 | 1.00 | 0.95 | 356 |
| Healthcare | 0.97 | 0.99 | 0.98 | 363 |

The main confusion is `Transfer` rows predicted as `Subscription` (110) or `Entertainment` (37). The full per-class table and confusion matrix are in `backend/artifacts/categorizer/metadata.json`.

## Robustness: meaningless text

A probe of 2,000 generated nonsense descriptions (random letters and numbers, with or without address tails, payment words or city names, fixed seed):

| | Auto-categorized (confident prediction) |
|---|---|
| Confidence threshold only | 47.3% |
| **With the unrecognized-text guard** | **0.1%** |

**The guard:** a description is trusted only if it contains at least one *informative* word, meaning a word the model knows that appears in fewer than about 5% of training descriptions (IDF ≥ 4.0) and is not an address word (US state codes, `us`, `usa`). Otherwise the row is left `Uncategorized` with reason `unrecognized_text` and confidence 0, whatever the model's own confidence. Cost: it blocks 0.09% of real held-out test rows (6 of 6,752), which would otherwise have been categorized correctly.

## Limitations

- **Synthetic, US-centric data.** Formats from other countries (for example UPI references) and merchants outside the training list are not represented. Expect lower accuracy on real statements.
- **Over-confidence on text it has never seen.** Logistic regression stays confident on meaningless input: `ZXQJ 8841 KLM` was first labelled `Transportation` at 0.93 confidence, and the confidence threshold alone could not stop it (see "Robustness"). A guard now leaves such rows `Uncategorized`, but plausible-looking made-up merchant names (for example `ACME CORP 2291`) still receive a guess, and nonsense containing rare real words such as city names is not caught by the guard (the confidence threshold caught those in our probe, which is not a guarantee).
- **Ambiguity is real.** Zelle, transfers and generic payment descriptions do not identify a category by themselves.
- **No amount or date features.** A $5 and a $500 charge at the same merchant get the same prediction.
- **Merchant grouping is approximate**, so a small amount of leakage between train and test is possible.
- **Label noise** from the generator is part of the training signal.
- **Model confidence is not calibrated probability**; treat it as a ranking signal.
- Retraining is manual. Corrections made in the app are stored but **not** used to retrain the model.

## Operation and safety

- Training is offline only; the API never trains. The artifact (`backend/artifacts/categorizer/model.joblib`) and its `metadata.json` ship with the application.
- At startup the API verifies the artifact's SHA-256 against the metadata and refuses artifacts built with a different scikit-learn version. If loading fails, `/readyz` reports not-ready and uploads are rejected: the app never guesses.
- Only this repository-owned artifact is ever deserialized; user-supplied files are never loaded as models.
- Transaction descriptions are not written to logs.
- Metadata records the model version, training-data description, timestamp, feature configuration, split method, metrics, threshold, library versions and artifact checksum. Training is deterministic for a fixed dataset and seed (metrics and version are identical across runs); the compressed file's bytes can differ between runs.


---

# Unusual-transaction review (separate from the categorizer)

**What it is:** a short ranked list of expenses that stand out from the person's own spending, so they can look at the handful that matter. **It is not fraud detection**, and "unusual" does not mean "wrong": a holiday, a new laptop or an annual bill will all rank high.

**How it works (nothing is trained on uploaded data beyond robust statistics):**
- Each expense is compared with the typical amount for its own category, using the median and the median absolute deviation of the log amount (robust to the very outliers we look for, and suited to right-skewed spending). Categories with fewer than 8 expenses are compared with all spending.
- The score is that deviation, capped at 6 standard deviations and scaled to 0-1; ties among capped rows are ordered by the uncapped deviation.
- The top **K = 10** (the review capacity) are stored with their rank and a plain-language reason, e.g. "Amount 2,196.33 is about 15.3x the typical Utilities amount (143.83)." The user marks each one **confirmed** (worth following up) or **dismissed** (expected).
- At least 20 expenses are needed; otherwise the result is `skipped` with a reason. Money-in rows are never ranked. No contamination rate is assumed: the number flagged is the review capacity, not a claim about how many are "bad".

**Evaluation (`python -m backend.ml.anomaly_eval`).** On 20 labelled synthetic fixtures (900 ordinary rows plus 10 injected spikes of 4-12x the category's typical amount, K = 10; with 10 injected per fixture precision@10 equals recall@10):

| Method | precision@10 | recall@10 |
|---|---|---|
| **Category-relative deviation (shipped)** | **0.775 ± 0.113** | 0.775 ± 0.113 |
| Isolation Forest alone | 0.675 ± 0.141 | 0.675 ± 0.141 |
| 70/30 blend of both | 0.785 ± 0.115 | 0.785 ± 0.115 |

The blend was never worse than the deviation score and was better in only 4 of 40 fixtures (+0.1 hit on average), so the simpler, fully explainable deviation score ships and Isolation Forest is kept only for this comparison.

**Limits of this evaluation:** the injected anomalies are amount spikes, which is exactly what the shipped method looks for, so the numbers are optimistic and say nothing about other kinds of oddity (timing, duplicates, a new merchant) or about real fraud. Heavy-tailed categories (e.g. Shopping) produce legitimate large amounts that are hard to separate from injected ones. Real-world precision is unknown.
