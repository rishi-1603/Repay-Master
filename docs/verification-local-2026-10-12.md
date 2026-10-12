# RepayMaster local/CI verification — 2026-10-12

Local API target: `http://127.0.0.1:8011`  
Public Streamlit target: https://repay-master-kwuphbmhsmnzb9g5eeetvd.streamlit.app/

Local API workflow passed:

- `/health`: 200
- `/loan/calculate`: 200; Short/Recommended/Long options returned
- `/loan/prepayment`: 200; 60 months → 28 months with an extra 5,000/month
- `/risk/predict`: 200; five top factors, SHAP explanation, model accuracy 80.0
- Infinity JSON input: 422
- negative rate: 422
- register/login/save/list history: 201 / 200 / 201 / 200

Independent finance reference:

- `scripts/validate_finance_reference.py`: 52/52 checks passed
- Decimal closed-form EMI and analytic balance identity agree with the library
- high-rate 99.99%/360-month schedule terminates at 360, not 361

The public Streamlit URL resolved to Streamlit's platform authentication gate,
so its application workflow is not marked publicly verified without viewer
access. Local Streamlit was launched and the calculation button was exercised
with Playwright. CI main run 38230072224 passed Streamlit smoke, backend tests,
Docker build, and Compose smoke.
