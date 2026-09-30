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

## Backend API

A FastAPI backend under `backend/` wraps the existing deterministic finance
math (`utils/finance.py`) and the ML risk model (`utils/risk.py`) as
independently callable, tested HTTP endpoints, so this logic is no longer only
reachable from inside the Streamlit process. It is implemented, tested (54
pytest cases) and — since Day 6 — verified running inside its own container.

**Currently implemented and tested:**
- `POST /loan/calculate` — EMI/repayment-option calculation (Short/Recommended/Long term)
- `POST /loan/prepayment` — prepayment/lump-sum simulation
- `POST /risk/predict` — RandomForest risk classification + SHAP-based explanation
- `POST /auth/register`, `POST /auth/login` — user accounts, backed by the
  *same* sqlite3 + PBKDF2 store `utils/auth.py` already used from the
  Streamlit app (one users table, not a second parallel one); login returns
  a short-lived JWT bearer token. Login is additionally **rate limited**
  against brute-force and credential-stuffing attempts (see below)
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

### Login rate limiting (`backend/app/core/rate_limit.py`)

`POST /auth/login` enforces two independent limits, both checked **before**
any password hashing runs — a throttled attacker gets a cheap `429` instead
of the server paying for a PBKDF2 derivation on every guess:

| Limit | Default | Counts | Why it exists |
|---|---|---|---|
| per client IP | 20 / 60s | *every* attempt | credential stuffing — many usernames from one host |
| per account | 5 failures / 300s | failures only | distributed guessing of one username from many hosts |

Each alone is trivially evaded (rotate IPs, or spread across usernames), so
both are needed. A successful login clears that account's failure history, so
a user who mistypes twice isn't left one typo from a lockout. Rejections
return `429` with a `Retry-After` header, and the response body is identical
whether the IP or the account tripped — revealing which would let an attacker
tune the other. All four values are configurable via env (`LOGIN_IP_LIMIT`,
`LOGIN_IP_WINDOW_SECONDS`, `LOGIN_ACCOUNT_FAILURE_LIMIT`,
`LOGIN_ACCOUNT_WINDOW_SECONDS`).

**Why in-process rather than Redis here.** The sibling projects (DevTrack,
CertiFake) both rate-limit through Redis; this one deliberately does not. This
API is a single-process service backed by a sqlite file, with no second
replica and no existing Redis dependency for anything else. Adding Redis
solely to hold login counters would mean a new service, container, failure
mode and "what if Redis is down" question — to protect one endpoint on one
process whose entire state fits in memory. The honest limitations that follow
from that choice:

1. **State is per-process.** Run uvicorn with `--workers 4` and the effective
   limit becomes 4× the configured one. The correct fix at that point is a
   shared store — which is precisely the condition under which adding Redis
   *would* be justified.
2. **State does not survive a restart.** A redeploy clears counters.
3. **Client IP is the socket peer, not `X-Forwarded-For`.** That header is
   client-controlled, so trusting it without a known-proxy allowlist would let
   an attacker rotate it and bypass the per-IP limit entirely — strictly worse
   than the honest limitation that behind a reverse proxy all clients share one
   bucket. Per-account limiting still works correctly behind a proxy.

Two implementation details worth knowing, because both were found by testing
rather than assumed:

- **Sliding-window log, not fixed window.** The Redis implementations
  elsewhere in this portfolio use `INCR`+`EXPIRE` (fixed window), which admits
  up to ~2× the limit straddling a window boundary — an acceptable trade-off
  there because it saves round-trips. Here the state is already local, so the
  more accurate algorithm costs nothing and closes that loophole. A test runs
  the same scenario against a minimal fixed-window counter and asserts the two
  algorithms actually disagree.
- **`attempt()` checks and consumes under one lock acquisition.** `login` is a
  synchronous `def`, so FastAPI runs it in a threadpool and requests genuinely
  execute concurrently. A `peek()`-then-`record()` pair is a check-then-act
  race: measured with a slow clock, it admitted **60 requests against a limit
  of 10**. The atomic `attempt()` admits exactly 10. Both a timing-independent
  test (lock-acquisition count must be 1) and an empirical one pin this, and
  both were verified to fail if the atomic version is reverted to the pair.
- **Tracked keys are capped** (LRU eviction at 5,000) because a limiter keyed
  by username is itself a memory-exhaustion vector: an attacker can send logins
  for millions of random usernames to grow the dict without bound.

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
Verification status (updated Day 5):
- **The image builds** — confirmed by the `docker-build` CI job on GitHub
  Actions (run 35996304233), which was the first time anything had actually
  built it (no Docker daemon exists in the environment this was developed in).
- **`docker-compose.yml` is now syntactically validated** by `docker compose
  config` in CI, and `scripts/check_images.py` confirms every referenced image
  — including the pinned `python:3.12-slim-trixie` base — still resolves in its
  registry.
- **Verified running in CI (Day 6).** The `compose-smoke-test` job boots this
  compose file and drives real requests through the container; it passed on
  commit `4cda54b` (run 36611637287). Observed: the python/urllib healthcheck
  reaching `healthy` for the first time; the joblib artifacts present and
  non-empty inside the image; `/risk/predict` returning a real class with five
  SHAP contributions and `model_test_accuracy` exactly 80.0 (the check that
  matters, since `load_model_metrics()` returns `None` on any read error);
  loan maths that actually responds to prepayment; and the sqlite DB on the
  mounted volume. `docker-compose.yml` and `Dockerfile` record the full list.

### Deployment config checks (Day 5)

Added `healthcheck` (Python against `GET /health` on 8010 — the image installs
no apt packages at all, so there is no curl/wget/nc to use) and
`restart: unless-stopped` to the single `api` service.

Two CI checks were added, neither of which needs a Docker daemon:
`scripts/check_images.py` resolves every image reference against its registry,
and `scripts/check_config_consistency.py` asserts cross-file agreement (a
service whose env points at another service must declare the `depends_on` edge;
nothing may gate on `service_healthy` for a service with no healthcheck; no
placeholder image strings).

**Why a project with one service and no infrastructure needs these at all:**
the sibling CertiFake project's compose stack was broken for **17 days**
because MinIO deleted `minio/minio` from Docker Hub on 2026-09-11, and nothing
caught it — `docker-compose config` validates syntax, not whether an image
still exists. This project's exposure is smaller but real and identical in
kind: an unpinned or deleted base image breaks the build with no commit to this
repo. Both scripts are byte-identical to CertiFake's and DevTrack's copies on
purpose; three divergent forks of a config checker would be the duplication
problem it exists to prevent. Both were mutation-tested against deliberately
reintroduced defects (8 of 8 caught) — which was not a formality, since an
earlier version silently skipped *every* Kubernetes check while still printing
PASS.

Note this compose file has no `depends_on` at all, and that is correct rather
than an omission: the API has no Postgres/Redis/Kafka dependency (see above —
deliberately not added, because nothing here needs them). It is also why the
Day-4 rate limiter can be in-process: a single container is the whole
deployment, so per-process state *is* global state. Running this compose file
with `scale api=2` would break that limiter's guarantees, which is the
condition under which Redis would finally be justified.

**CI (GitHub Actions, `.github/workflows/ci.yml`):** lint (ruff, pinned) + a
**blocking** dependency vulnerability scan (pip-audit) + the 75-case test suite,
plus a job that builds the Docker image, a `config-validation` job (compose
validation + image-availability + cross-file consistency), and the
`compose-smoke-test` job described above.

### Security posture (Day-7 remediation)

Three changes, made together because each one alone would have been misleading:

1. **The dependency audit now gates the build.** It previously ran
   `pip-audit --desc || true` *and* had `continue-on-error: true` — non-blocking
   twice over. On the last green build before this change it printed "Found 36
   known vulnerabilities in 3 packages" and still reported `success`. The pins
   have been bumped until the scan is genuinely clean (`No known vulnerabilities
   found`, zero waivers), and only then was the escape hatch removed. The
   workflow comment states the rule for the future: an unfixable advisory gets
   an explicit `--ignore-vuln <ID>` with a written reason and a re-review date,
   never a blanket `|| true`.
2. **Bumped pins:** PyJWT 2.10.1 → 2.15.1 (12+ advisories, including the
   payload-recursion DoS on ordinary decode paths that this app uses), FastAPI
   0.115.6 → 0.142.2 (which moves Starlette 0.41.3 → 1.7.0, clearing six
   advisories), pytest 8.3.3 → 9.1.1, uvicorn 0.34.0 → 0.54.0. The
   `pandas`/`numpy`/`joblib`/`shap` pins that carried no version at all are now
   exact, so two builds of one commit cannot install different code. The app was
   verified to serve a real HTTP request under the new Starlette/uvicorn pair,
   not merely to pass unit tests.
   *Not* reachable here, and recorded so the bump is not over-claimed: the
   PyJWT detached-payload advisory needs `detached_payload`/`b64:false`, which
   appears nowhere in this codebase, and the Starlette advisories concern
   `StaticFiles`/`FileResponse`, `request.url.hostname`, bare `HTTPEndpoint` and
   urlencoded form limits — also unused.
3. **CORS can no longer be configured unsafely** (`app/core/cors.py`). The old
   `CORS_ORIGINS="*"` default combined with a hardcoded `allow_credentials=True`;
   in that combination Starlette echoes the caller's `Origin` rather than
   sending `*`, which trusts every website for credentialed cross-origin
   requests. Now: a wildcard under `APP_ENV=production` fails startup loudly
   (the pattern already used here for `SECRET_KEY`), `allow_credentials` is
   derived rather than hardcoded and is `False` whenever origins are a wildcard,
   and an unset/empty value denies cross-origin access instead of permitting
   all. Rated MEDIUM rather than HIGH because this API uses Bearer tokens and
   never sets a cookie — a latent bug, not an exploited one. 21 tests cover it,
   including one that asserts the unsafe pairing cannot be produced for any
   environment name.

## Future Improvements (not built — tracked honestly, not claimed as done)
- **A real evaluation of the model.** The 80.0% figure in `models/metrics.json`
  is measured and asserted exactly by the CI smoke test, but it is 40 held-out
  rows of a 200-row synthetic dataset with rule-derived labels. Cross-validation,
  calibration and per-class metrics on data that is not generated from the same
  thresholds the labels came from — that is the work, and until then the number
  should be quoted with its sample size attached.
- `POST /ai/explain` — Gemini-generated natural-language explanation of an
  already-computed risk result (Gemini explains, it never calculates)
- Kafka event publishing (`LoanCreated`, `RiskCalculated`) for downstream
  analytics
- Airflow DAG for scheduled batch risk scoring

The Streamlit app (`app.py`) is unchanged and still works standalone; it does

not yet call this API internally.
