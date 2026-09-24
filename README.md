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
├── data/
│   └── synthesized_student_loan_data.csv
└── backend/                # FastAPI backend, see "Backend API" below
    └── app/
        ├── api/             # loans, risk, auth, history routers
        ├── core/            # config, JWT security
        ├── schemas/         # Pydantic request/response models
        └── tests/
```

## Backend API (in progress)

A FastAPI backend is being built under `backend/` that wraps the existing
deterministic finance math (`utils/finance.py`) and the ML risk model
(`utils/risk.py`) as independently callable, tested HTTP endpoints, so this
logic is no longer only reachable from inside the Streamlit process.

**Currently implemented and tested:**
- `POST /loan/calculate` — EMI/repayment-option calculation (Short/Recommended/Long term)
- `POST /loan/prepayment` — prepayment/lump-sum simulation
- `POST /risk/predict` — RandomForest risk classification + SHAP-based explanation
- `POST /auth/register`, `POST /auth/login` — user accounts, backed by the
  *same* sqlite3 + PBKDF2 store `utils/auth.py` already used from the
  Streamlit app (one users table, not a second parallel one); login returns
  a short-lived JWT bearer token
- `GET /history`, `POST /history`, `DELETE /history/{id}` — saved-scenario
  CRUD, scoped to the authenticated user. Ownership is enforced at the SQL
  layer (`WHERE id = ? AND username = ?`), not just in the route handler,
  so one user can never read or delete another user's scenario even by
  guessing its id
- `GET /health`

Auth notes:
- Tokens are signed HS256 JWTs (PyJWT), expire after 60 minutes by default
  (`ACCESS_TOKEN_EXPIRE_MINUTES`), and are required as
  `Authorization: Bearer <token>` on every `/history` request.
- `SECRET_KEY` is **required** (no default) — the app fails to start
  immediately with a clear error if it isn't set, rather than silently
  falling back to a hardcoded value. Set a real random value via
  `SECRET_KEY` in `.env` — see `.env.example`.

Run it locally:
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8010
```
Then open `http://localhost:8010/docs` for interactive API docs.

Or with Docker:
```bash
cp backend/.env.example .env   # then edit SECRET_KEY in it
docker compose up --build
```
Verification status: the **image builds** — confirmed by the `docker-build`
CI job on GitHub Actions (run 35996304233), which was the first time
anything had actually built it (no Docker daemon exists in the environment
this was developed in). What is *not* verified is that a container started
from it runs correctly end-to-end — that job only builds, it does not run
the app. `docker compose up` has likewise never been brought up by
anything.

**CI (GitHub Actions, `.github/workflows/ci.yml`):** lint (ruff) + a
dependency vulnerability scan (pip-audit, non-blocking) + the test suite,
plus a separate job that builds the Docker image — the first real
verification that the Dockerfile builds at all, since it couldn't be
tested locally for the reason above.

**Roadmap (not yet built — tracked honestly, not claimed as done):**
- `POST /ai/explain` — Gemini-generated natural-language explanation of an
  already-computed risk result (Gemini explains, it never calculates)
- Kafka event publishing (`LoanCreated`, `RiskCalculated`) for downstream
  analytics
- Rate limiting on `/auth/login` (brute-force mitigation) — not yet added
  here; DevTrack has an equivalent Redis-backed implementation this project
  could reuse the pattern from once this API has its own Redis dependency
  for something else that justifies adding it
- Airflow DAG for scheduled batch risk scoring

The Streamlit app (`app.py`) is unchanged and still works standalone; it does

not yet call this API internally.
