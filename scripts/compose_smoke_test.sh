#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Compose-stack smoke test for Repay-Master.
#
#     COMPOSE_CMD="docker compose" scripts/compose_smoke_test.sh
#
# WHY THIS EXISTS
# ---------------
# docker-compose.yml and Dockerfile both carried an explicit note that runtime
# was unverified -- the compose file said "What is STILL not verified is
# runtime: no Docker daemon existed where this was written, so nothing has ever
# started these containers, confirmed the healthcheck passes, or driven a
# request through the app", and the Dockerfile said the same about a container
# actually RUNNING end to end. Both were accurate. This script and the
# compose-smoke-test CI job that calls it are what retire those caveats.
#
# The existing CI jobs build the image and run pytest against the runner's own
# Python. Neither can answer the questions that only a started container can:
#
#   * Does the trained model artifact survive into the image and LOAD there?
#     models/*.joblib are committed and COPY'd, but utils/risk.py loads them
#     lazily behind functools.lru_cache, so a missing or unreadable artifact
#     fails at REQUEST time, not at import or build time. A green build plus a
#     green pytest suite is fully compatible with /risk/predict returning 503.
#   * Does the healthcheck actually pass? It probes with python/urllib because
#     this image installs no apt packages at all (no curl/wget/nc). That was
#     reasoned about from the image contents, never observed.
#   * Is the sqlite DB path writable, and does it land in the volume?
#     utils/auth.py resolves DB_PATH to /app/data/app.db, which compose mounts
#     as the repaymaster_data volume. If that resolution were wrong the app
#     would still work but silently lose every registered user on
#     `docker compose down` -- the exact failure the volume exists to prevent.
#
# Runs on the CI RUNNER, not inside the container, for the same reason as the
# sibling DevTrack project: this image has no HTTP client, the requests are
# plain JSON, and the runner already has curl. Driving the published port also
# proves the port mapping. (The sibling CertiFake project does the opposite and
# runs inside its container, because that test needs the app image's own Pillow
# to render an image for OCR -- a dependency this project does not have.)
#
# Exit 0 = stack verified. Non-zero = broken; the calling CI job dumps
# `docker compose logs` on failure.
# ---------------------------------------------------------------------------
set -euo pipefail

COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"
BASE="${SMOKE_BASE_URL:-http://localhost:8010}"
API_CONTAINER=repaymaster_api
API_READY_TRIES="${SMOKE_API_TRIES:-60}"

# models/metrics.json records "test_accuracy": 80.0. Asserting the API echoes
# that exact number is what proves the artifact was READ: utils/risk.py's
# load_model_metrics() swallows every exception and returns
# {"test_accuracy": None}, so a missing/unreadable metrics.json degrades
# silently to model_test_accuracy: null rather than failing.
EXPECTED_TEST_ACCURACY=80.0

pass() { printf '  [ OK ]   %s\n' "$1"; }
info() { printf '  [ .. ]   %s\n' "$1"; }
die()  { printf '  [FAIL]   %s\n' "$1" >&2; exit 1; }

json_get() { python3 -c "import sys,json; d=json.load(sys.stdin); print(d$1)"; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "=== 1. model artifacts are really inside the running container ==="
# Committed to git and COPY'd by the Dockerfile -- but "should be there" is not
# "is there", and this is the artifact the whole /risk feature depends on.
for f in /app/models/risk_model.joblib /app/models/risk_scaler.joblib /app/models/metrics.json; do
  $COMPOSE_CMD exec -T api test -s "$f" || die "$f missing or empty inside the container -- the Dockerfile's COPY models/ did not land"
done
pass "risk_model.joblib, risk_scaler.joblib and metrics.json present and non-empty in the image"

echo "=== 2. api container reached Docker 'healthy' ==="
API_HEALTH="$(docker inspect -f '{{.State.Health.Status}}' "$API_CONTAINER" 2>/dev/null || echo missing)"
[ "$API_HEALTH" = "healthy" ] \
  || die "api container health is '$API_HEALTH' (want healthy). Its healthcheck probes http://127.0.0.1:8010/health using python/urllib, because the image has no curl."
pass "healthcheck reports healthy (first time this has been observed rather than inferred)"

echo "=== 3. API reachable on the published port ==="
for i in $(seq 1 "$API_READY_TRIES"); do
  if curl -sf "$BASE/health" > /dev/null 2>&1; then
    pass "GET $BASE/health -> 200 (attempt $i)"
    break
  fi
  [ "$i" = "$API_READY_TRIES" ] && die "API never answered on $BASE after $API_READY_TRIES tries"
  sleep 1
done

echo "=== 4. loan maths (no auth required on these routes) ==="
LOAN_PAYLOAD='{"loan_amount":500000,"interest_rate":8.5,"monthly_income":80000,"monthly_expenses":45000}'

CALC="$(curl -sf -X POST "$BASE/loan/calculate" -H "Content-Type: application/json" -d "$LOAN_PAYLOAD")" \
  || die "POST /loan/calculate failed"
SUGGESTED="$(printf '%s' "$CALC" | json_get "['suggested_months']")"
DTI="$(printf '%s' "$CALC" | json_get "['affordability']['dti_ratio']")"
[ -n "$SUGGESTED" ] && [ "$SUGGESTED" != "None" ] || die "/loan/calculate returned no suggested_months: $CALC"
pass "POST /loan/calculate -> suggested_months=$SUGGESTED, dti_ratio=$DTI"

# extra_monthly must actually shorten the term, or the prepayment simulation is
# returning numbers that do not mean anything.
PREPAY="$(curl -sf -X POST "$BASE/loan/prepayment" -H "Content-Type: application/json" \
  -d "${LOAN_PAYLOAD%\}},\"months\":60,\"extra_monthly\":5000}")" \
  || die "POST /loan/prepayment failed"
SAVED="$(printf '%s' "$PREPAY" | json_get "['months_saved']")"
info "prepayment response: $PREPAY"
[ "$SAVED" -gt 0 ] 2>/dev/null || die "paying an extra 5000/month saved $SAVED months (want > 0) -- the prepayment simulation is not doing anything"
pass "POST /loan/prepayment -> months_saved=$SAVED (> 0, so the simulation is real)"

echo "=== 5. ML risk prediction: loads joblib + runs SHAP inside the container ==="
# The endpoint this whole project exists for, and the one a green build cannot
# vouch for: load_risk_model() is lazy and lru_cached, so this is the first
# moment the artifacts are actually deserialized -- by the container's own
# scikit-learn/joblib versions, not the runner's.
RISK_PAYLOAD='{"loan_amount":500000,"interest_rate":8.5,"monthly_income":80000,"monthly_expenses":45000,"monthly_payment":10250}'
RISK="$(curl -sf -X POST "$BASE/risk/predict" -H "Content-Type: application/json" -d "$RISK_PAYLOAD")" \
  || die "POST /risk/predict failed (a 503 here means the model artifacts were not found in the container; a 500 means they failed to deserialize -- check $COMPOSE_CMD logs api)"
info "risk response: $(printf '%s' "$RISK" | head -c 400)"

LEVEL="$(printf '%s' "$RISK" | json_get "['risk_level']")"
ACCURACY="$(printf '%s' "$RISK" | json_get "['model_test_accuracy']")"
NFACTORS="$(printf '%s' "$RISK" | python3 -c "import sys,json; print(len(json.load(sys.stdin)['top_factors']))")"

case "$LEVEL" in High|Medium|Low) ;; *) die "risk_level '$LEVEL' is not one of the model's classes (High/Medium/Low per models/metrics.json)" ;; esac
pass "risk_level='$LEVEL' (a real class from the trained model)"

python3 -c "import sys; sys.exit(0 if abs(float('$ACCURACY') - $EXPECTED_TEST_ACCURACY) < 1e-9 else 1)" \
  || die "model_test_accuracy came back as '$ACCURACY', want $EXPECTED_TEST_ACCURACY from models/metrics.json. load_model_metrics() swallows read errors and returns None, so this means the artifact was not read from inside the container."
pass "model_test_accuracy=$ACCURACY matches models/metrics.json (artifact genuinely read in-container)"

[ "$NFACTORS" -ge 1 ] 2>/dev/null || die "top_factors is empty -- the SHAP explanation step produced nothing"
pass "SHAP explanation produced $NFACTORS factor contribution(s)"

echo "=== 6. auth + saved-scenario history (sqlite in the mounted volume) ==="
USERNAME="compose-smoke-$$"
PASSWORD="password123"

CODE="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE/auth/register" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}")"
[ "$CODE" = "201" ] || die "POST /auth/register -> $CODE (want 201)"
pass "registered user '$USERNAME'"

TOKEN="$(curl -sf -X POST "$BASE/auth/login" -H "Content-Type: application/json" \
  -d "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}" | json_get "['access_token']")"
[ -n "$TOKEN" ] || die "POST /auth/login returned no access_token"
pass "logged in, JWT issued"

SCEN="$(curl -sf -X POST "$BASE/history" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"label\":\"compose smoke scenario\",\"params\":$LOAN_PAYLOAD}")" \
  || die "POST /history failed"
SCEN_ID="$(printf '%s' "$SCEN" | json_get "['id']")"
[ -n "$SCEN_ID" ] && [ "$SCEN_ID" != "None" ] || die "POST /history returned no id: $SCEN"
pass "saved scenario id=$SCEN_ID"

curl -sf "$BASE/history" -H "Authorization: Bearer $TOKEN" | grep -q "compose smoke scenario" \
  || die "GET /history does not list the scenario just saved"
pass "GET /history lists it"

CODE="$(curl -s -o /dev/null -w '%{http_code}' -X DELETE "$BASE/history/$SCEN_ID" -H "Authorization: Bearer $TOKEN")"
[ "$CODE" = "204" ] || die "DELETE /history/$SCEN_ID -> $CODE (want 204)"
pass "DELETE /history/$SCEN_ID -> 204"

echo "=== 7. the sqlite DB landed in the mounted volume ==="
# utils/auth.py resolves DB_PATH relative to its own file: /app/utils/auth.py
# -> /app/data/app.db. compose mounts repaymaster_data there. Asserting the
# file exists in the container proves the write went to the volume rather than
# to a container-local path that `docker compose down` would delete along with
# every registered user.
$COMPOSE_CMD exec -T api test -s /app/data/app.db \
  || die "/app/data/app.db does not exist after a successful register -- utils/auth.py is not writing where the volume is mounted"
pass "/app/data/app.db exists and is non-empty (persisted via the repaymaster_data volume)"

echo
echo "PASS: Repay-Master compose stack verified end to end"
echo "      (artifacts in image -> healthy container -> loan maths -> joblib+SHAP"
echo "       risk prediction -> auth -> history -> sqlite in the mounted volume)"
