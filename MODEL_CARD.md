# Model Card — RepayMaster Affordability Risk Model

## Overview
- **Model type:** `RandomForestClassifier` (scikit-learn), 200 trees, `random_state=42`
- **Version:** v2.0.0
- **Task:** Multiclass classification — predicts affordability risk (`Low` / `Medium` / `High`) for a loan given the borrower's inputs.

## Training data
- `data/synthesized_student_loan_data.csv` — 200 synthetic data rows (201
  lines including the header; `models/metrics.json` records `n_rows: 200`, and
  the two now agree — an earlier revision of this card said 201 by counting the
  header) with columns
  `Loan_Amount_USD`, `Monthly_Income_USD`, `Monthly_Expenses_USD`, `Interest_Rate`,
  `Monthly_Installment_USD`.
- The dataset does not ship with a risk label, so `train_model.py` derives one
  using the same debt-to-income (DTI) and total-burden thresholds the app's own
  affordability scoring uses (DTI < 28% and burden < 70% → Low; DTI < 43% and
  burden < 85% → Medium; otherwise High).

## Features
`loan_amount`, `interest_rate`, `monthly_income`, `monthly_expenses`, `monthly_payment`
— standardized with `StandardScaler` before being fed to the model.

## Performance
See `models/metrics.json` for the exact figure from the last training run:
`test_accuracy: 80.0` on a 20% stratified held-out split (40 of 200 rows),
`random_state=42`. Re-run `python train_model.py` to retrain and refresh that
file.

This figure is also asserted at runtime: the API returns it as
`model_test_accuracy`, and the compose smoke test in CI requires it to equal
80.0 exactly. That matters because `utils/risk.py:load_model_metrics()`
swallows every read error and returns `{"test_accuracy": None}`, so a missing
or unreadable metrics file would otherwise degrade to `null` silently instead
of failing a check.

## Explainability
The "Why did the model predict this?" panel in the app uses `shap.TreeExplainer`
to compute per-feature SHAP contributions for the specific prediction. If SHAP is
unavailable or errors at runtime, the app falls back to the model's global
`feature_importances_` scaled by the input's deviation from the training mean,
so the panel always renders something rather than crashing.

## Limitations
- Trained on a small, **synthetic** dataset — it does not reflect real lending
  outcomes, real default rates, or any specific bank's underwriting criteria.
- **Not financial advice.** Do not use this model's output to make real lending,
  borrowing, or credit decisions.
- Risk labels were rule-derived, not observed outcomes, so the model is
  approximating a heuristic rather than learning true default risk.
