# RepayMaster — Days 8–10 final QA report

**Verification date:** 2026-10-12 (Asia/Calcutta / UTC evidence timestamps)  
**Verified main commit:** `936311dd`  
**Repository:** https://github.com/rishi-1603/Repay-Master

## Result

**Overall: PARTIAL**

The finance core, API, model artifacts, Streamlit source, container, CI, and
financial reference validation pass. The listed Streamlit Cloud URL resolves,
but the Day-10 browser check presents Streamlit's platform authentication gate;
therefore the public Streamlit calculation workflow is not marked PASS without
viewer access.

## Evidence matrix

| Area | Result | Evidence |
|---|---|---|
| Financial calculations | **PASS** | `scripts/validate_finance_reference.py`: **52/52** checks passed using 50-digit Decimal EMI and analytic balance references |
| Edge inputs | **PASS** | Zero interest, negative/zero API inputs, non-finite JSON, fractional/very large principals, high-rate/long-tenure schedule, extra monthly and lump-sum prepayment covered |
| API workflow | **PASS** | Local FastAPI workflow: health, calculate, prepayment, risk/SHAP, invalid input, register/login, save/list history; see [verification log](verification-local-2026-10-12.md) |
| Model runtime | **PASS** | API returned a real risk class, five factors, `explanation_is_approximate=false`, and `model_test_accuracy=80.0` |
| Critical automated tests | **PASS** | **140 parameterized cases**, 98% backend production coverage (347 statements / 7 missed); ruff clean |
| Security/dependencies | **PASS** | Backend and root requirements audits clean; root Streamlit direct requirements are now exact pins; no tracked secret patterns or real `.env` files |
| CI/CD | **PASS** | Main run [38230072224](https://github.com/rishi-1603/Repay-Master/actions/runs/38230072224): Streamlit smoke, config validation, test, Docker build, and Compose smoke all passed |
| Container/API deployment | **PASS in CI** | Compose healthcheck, model artifacts, risk prediction, prepayment behavior, history persistence, and named volume verified by CI smoke |
| Streamlit UI | **PASS locally / UNVERIFIED publicly** | Local Streamlit launched and Playwright exercised the calculation button; the public URL showed a platform auth gate |
| README/architecture/screenshots | **PASS** | Formula/assumption/rounding section, architecture SVG, calculation-result capture, and public auth-gate capture included |
| Second verification | **PASS locally/CI; UNVERIFIED publicly** | Post-fix local API + reference run + merged-main CI passed; public viewer access remains the only missing evidence |

## Finding fixed in this pass

### High-rate float recurrence could create a hidden extra payment

The prior float-only schedule produced **361 rows** for a valid 99.99% APR,
360-month, 750,000-principal case and left a 324.76 residual after the nominal
term. The fix uses Decimal arithmetic for the EMI and monthly recurrence and an
explicit maturity boundary. The same case now completes in exactly 360 months,
with the independent analytic reference agreeing within the documented
currency tolerances.

Display schedule amounts are rounded to cents with `ROUND_HALF_UP`; the
unrounded Decimal balance and interest identity are retained until the API/UI
edge. The assumptions and formula are documented in the README.

Earlier merged fixes also cover PDF generation with multiple recommendations and
non-latin-1 text, and reject non-finite numeric input at the Pydantic boundary.

## Deployment truth

- Streamlit URL: https://repay-master-kwuphbmhsmnzb9g5eeetvd.streamlit.app/
- Current live check: resolves but redirects through Streamlit platform auth;
  no app viewer credential was available, so the public workflow is UNVERIFIED.
- FastAPI: no public backend URL is claimed.
- CI Compose is the evidence for the containerized backend and model runtime.

## Artifacts

- [Architecture diagram](architecture.svg)
- [Initial local dashboard](screenshots/repaymaster-local-dashboard.png)
- [Calculation result capture](screenshots/repaymaster-calculation-results.png)
- [Public deployment auth-gate capture](screenshots/repaymaster-live-auth-gate.png)
- [Independent Decimal checker](../scripts/validate_finance_reference.py)
