# 🏦 RepayMaster — Loan Repayment Timeline Predictor

RepayMaster is a Streamlit app that helps you plan how to repay a loan: it
calculates EMIs across multiple tenures, visualizes the repayment timeline,
assesses affordability risk with a machine-learning model, and can generate
personalized repayment strategies with Gemini.

## Features
- **EMI calculator** — enter loan amount, interest rate, and start date in USD
  or INR, plus your monthly income/expenses.
- **Live USD↔INR exchange rate** display (with an offline fallback estimate).
- **Repayment comparison** — Short / Recommended / Long term options, with
  EMI comparison chart, payment breakdown donut, and monthly cash-flow chart.
- **ML Risk Assessment** — a `RandomForest` model predicts Low/Medium/High
  affordability risk, with a SHAP-based (or feature-importance fallback)
  explanation of the prediction. See [`MODEL_CARD.md`](MODEL_CARD.md).
- **Financial health metrics** — debt-to-income ratio, total monthly burden,
  savings potential.
- **Loan Payment Achievements** — a gamified milestone timeline (10%, 25%,
  50%, 90%, one year, five years, etc.) per repayment term.
- **Amortization schedule** — full month-by-month table with CSV export.
- **India-specific tips** — Section 24(b) / 80C tax deduction notes and
  practical prepayment tips.
- **Prepayment simulator** — see the interest/time saved from extra monthly
  payments or a one-time lump sum.
- **Compare multiple loan offers** side by side.
- **Save scenarios to history** — optional local username/password login
  (SQLite-backed) lets you save and revisit past scenarios; the calculator
  works fully without an account too.
- **AI-Powered Recommendations** — Gemini-generated repayment strategy advice.
- **PDF report export** of the full analysis.

## Getting started

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app opens at `http://localhost:8501`.

### Enabling AI recommendations
Create `.streamlit/secrets.toml` (gitignored) with:

```toml
GEMINI_API_KEY = "your-gemini-api-key"
```

or set the `GEMINI_API_KEY` environment variable before launching. Without a
key, every other feature still works — the AI section just shows a warning
telling you how to enable it.

### Retraining the risk model
The pretrained model lives in `models/`. To retrain it from
`data/synthesized_student_loan_data.csv`:

```bash
python train_model.py
```

## Project structure
```
Repay-Master/
├── app.py                  # main Streamlit entry point
├── requirements.txt
├── README.md
├── MODEL_CARD.md
├── train_model.py          # one-off script that (re)builds models/*.joblib
├── .streamlit/
│   └── config.toml         # dark theme
├── utils/
│   ├── finance.py          # EMI, amortization, achievements, prepayment math
│   ├── currency.py         # formatting + live FX rate
│   ├── risk.py             # risk model load/predict/explain
│   ├── auth.py             # local login + saved-scenario history (SQLite)
│   └── pdf_report.py       # PDF report generation
├── models/
│   ├── risk_model.joblib
│   ├── risk_scaler.joblib
│   └── metrics.json
└── data/
    └── synthesized_student_loan_data.csv
```

No frontend, backend, Docker, or CI/CD — this is a single, self-contained
Streamlit application.
