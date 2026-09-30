# Repay-Master — Resume & LinkedIn Bullet Points

*Added Day 7, in the same format as the sibling DevTrack's notes, and updated
the same day after the security remediation. Numbers are measured: 75 from the
CI `test` job; model figures from `models/metrics.json`, cross-checked against
`train_model.py`; container behaviour from the Day-6 `compose-smoke-test` run;
dependency-audit status from a local `pip-audit` of the exact pinned set (and
from the CI step that now gates on it). Anything not verified is listed as such
at the bottom rather than left to be assumed.*

## Resume bullet points (pick 2-3 based on space)

- Built **Repay-Master**, a loan-affordability platform: a FastAPI backend over
  a scikit-learn `RandomForestClassifier` (200 trees) that classifies
  repayment risk as Low/Medium/High and explains each prediction with
  per-feature SHAP contributions, plus deterministic amortization and
  prepayment simulation. 75 pytest cases in CI.

- Trained the model from scratch (`train_model.py`): derived risk labels from
  the same DTI/burden thresholds the app's own scoring uses, standardized
  features, stratified 80/20 split, 80.0% held-out accuracy — recorded in
  `models/metrics.json` and **asserted at runtime** by the CI smoke test, which
  requires the API to return exactly that figure.

- Shipped a documented model card (`MODEL_CARD.md`) stating the honest limits:
  synthetic training data, rule-derived labels rather than observed outcomes,
  and an explicit "not financial advice" scope. SHAP has a tested fallback to
  `feature_importances_` scaled by input deviation, flagged
  `explanation_is_approximate`, so the UI never breaks when SHAP is unavailable.

- Containerized the API and made CI prove the container runs, not merely builds:
  the smoke test checks the joblib artifacts exist inside the image, the
  python/urllib healthcheck reaches `healthy`, `/risk/predict` returns a real
  class with five SHAP contributions in-container, and the sqlite DB lands in a
  named volume rather than a path `compose down` would delete.

## One-liner (LinkedIn / portfolio card)

Repay-Master — a FastAPI loan-affordability API with a trained scikit-learn
risk model, SHAP-explained predictions, amortization/prepayment simulation, and
a model card that states its limits; container health and model loading are
asserted in CI.

## Numbers, and where they come from

| Claim | Value | Source |
|---|---|---|
| pytest cases | 91 | CI `test` job log (54 before the Day-7 CORS and key-strength tests) |
| Model | RandomForestClassifier, 200 trees, `random_state=42` | `train_model.py:66` |
| Test accuracy | 80.0% on 40 held-out rows | `models/metrics.json` + asserted by smoke test |
| Training rows | 200 (201 lines incl. header) | CSV + `n_rows: 200` |
| Features | 5, standardized | `utils/risk.py` FEATURE_NAMES + StandardScaler |
| Password hashing | PBKDF2-HMAC-SHA256, 100k iterations, per-user salt | `utils/auth.py:39` |
| Coverage (production code) | 98% | CI `--cov=app` with `.coveragerc` omitting `app/tests/`; 347 stmts, 8 missed (97% before the Day-7 CORS and config modules) |
| Dependency audit | clean, and blocking | CI `pip-audit --desc` — no `\|\| true`, no `continue-on-error`, no waivers: `No known vulnerabilities found` |
| Signing-key floor | 32 bytes in production | `app/core/config.py` model validator; warns outside production so a dev key cannot stop a service |
| Compose services | 1 | `docker-compose.yml`: api only |

## Interview prep — questions to be ready for

**ML**
- Q: Why a RandomForest and not something deeper?
  A: 200 rows of five numeric features. A tree ensemble gives calibrated-enough
  class probabilities, native `feature_importances_`, and SHAP's fast
  TreeExplainer — with zero tuning surface to overfit a dataset this small. A
  neural net here would be theatre.
- Q: Your labels aren't real outcomes. Isn't the model meaningless?
  A: It approximates a documented heuristic (DTI < 28% & burden < 70% → Low,
  etc.), and the model card says exactly that. The value of the exercise is the
  *pipeline* — reproducible training, persisted metrics, runtime explanation —
  not claiming to predict real default risk. Say this before being asked.
- Q: How is a prediction explained?
  A: `shap.TreeExplainer` on the scaled feature vector, per-class contributions
  sorted by magnitude. If SHAP import or computation fails, it falls back to
  `feature_importances_ * deviation` and sets `approximate: true`, so the
  client can say so honestly. The Day-6 container run returned
  `explanation_is_approximate: false`, i.e. SHAP really ran.

**Security**
- Q: How are passwords hashed? Why not bcrypt?
  A: PBKDF2-HMAC-SHA256, 100,000 iterations, per-user salt. A prior deployment
  hit bcrypt native-build incompatibility, and the file records that reason —
  the choice is deliberate and documented, not accidental. Be ready to discuss
  bcrypt/argon2 as the stronger default and why this project deviated.
- Q: How is brute force limited?
  A: An in-process per-IP limiter on login, checked *before* any password work.
  Its documented limit: in-process means per-replica, so it is correct only
  while this runs as one process — which is the whole deployment today.

**Design**
- Q: Why no Postgres/Redis/Kafka here when your other projects use them?
  A: Nothing needs them. Users and scenarios fit a single sqlite file mounted
  in a volume; the compute is synchronous and CPU-light. `docker-compose.yml`
  states this explicitly — absent infrastructure that is justified is better
  than present infrastructure that is decorative.
- Q: How is one user's scenario kept from another?
  A: Ownership is enforced in SQL (`WHERE id = ? AND username = ?`) inside
  `utils/auth.py`, not only in the router, so a routing bug cannot leak rows;
  delete of someone else's row returns the same 404 as a missing one.

**Testing & ops**
- Q: What does the compose smoke test prove?
  A: That the image *runs*: artifacts present and non-empty in the container,
  healthcheck healthy, a real High/Medium/Low prediction with five SHAP
  contributions, loan maths that actually changes with prepayment (an extra
  5000/month cut a 60-month term to 38 in the observed run), and the sqlite DB
  on the mounted volume.
- Q: What is not covered?
  A: See below — say it unprompted.

## Trade-offs / what you'd improve

- **The Streamlit front end (`app.py`) is not containerized and its widget
  layer is untested.** Its shared modules are tested — one test registers a
  user through the HTTP API and then logs in through the same `utils/auth.py`
  the Streamlit app uses — but nothing renders the UI. The Docker image serves
  only the FastAPI backend.
- **Coverage is 98% on production code** (347 statements, 8 missed). Read it
  with the caveat that this backend is small and mostly deterministic maths plus
  thin routes — a high percentage here is cheaper to earn than in the sibling
  CertiFake, whose 78% covers Kafka consumers and CV code. Do not present the
  two as comparable.
- **The Day-7 security remediation is a better story than the coverage number.**
  This repo's CI reported `success` while printing 36 known vulnerabilities,
  because the audit step was `pip-audit --desc || true` *and* carried
  `continue-on-error: true` — non-blocking twice over. Being able to say "I found
  that our green build gated on nothing, bumped the pins until the scan was clean
  with zero waivers, and only then made it block" is worth more in an interview
  than 98%. Be ready for the follow-up, which is the part that actually
  demonstrates judgement: which advisories were reachable here (the PyJWT
  payload-recursion DoS on ordinary decode paths) and which were not (the
  detached-payload one — no `detached_payload` or `b64:false` in this codebase —
  and the Starlette set, whose vulnerable APIs are all unused).
- **Synthetic data, rule-derived labels** — the model card's own limitations
  section. Never let this be described as predicting real credit risk.
- **sqlite single-file storage** is right for one process and wrong for many;
  moving to Postgres would be the first change if this grew a second replica,
  ahead of the rate limiter (same single-replica caveat).
- The model is loaded lazily behind `lru_cache`, so a broken artifact surfaces
  as a 503 on the first request rather than at boot. That is a deliberate
  trade (fast startup, loud-on-first-use) and the smoke test exists precisely
  because a green build cannot detect it.
