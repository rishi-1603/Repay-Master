# Model Card — RepayMaster Affordability Risk Model

## Overview
- **Model type:** `RandomForestClassifier` (scikit-learn), 200 trees, `random_state=42`
- **Version:** v2.0.0
- **Task:** Multiclass classification — predicts affordability risk (`Low` / `Medium` / `High`) for a loan given the borrower's inputs.

## Training data
- `data/synthesized_student_loan_data.csv` — 201 synthetic rows with columns
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
See `models/metrics.json` for the exact figure from the last training run
(80% test-set accuracy on a 20% held-out split as of the last run in this repo).
Re-run `python train_model.py` to retrain and refresh this file.

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
