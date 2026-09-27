"""Registration + login.

Reuses utils/auth.py's existing sqlite3 + PBKDF2 implementation directly --
the same module the Streamlit app already uses -- instead of standing up a
second, separate user store. One users table, shared by both clients: an
account created through this API can log into the Streamlit app and vice
versa.
"""
import logging
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

# utils/ lives at the repo root (sibling of backend/), not inside backend/ --
# same pattern already used by app/api/loans.py and app/api/risk.py.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.auth import authenticate, register_user  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.rate_limit import login_limiter  # noqa: E402
from app.core.security import create_access_token  # noqa: E402
from app.schemas.auth import LoginRequest, RegisterRequest, RegisterResponse, TokenResponse  # noqa: E402

logger = logging.getLogger("repaymaster.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(payload: RegisterRequest) -> RegisterResponse:
    ok, message = register_user(payload.username, payload.password)
    if not ok:
        # Both "empty username" and "username taken" come back as 400 --
        # a client error, not a server error.
        raise HTTPException(status_code=400, detail=message)
    return RegisterResponse(message=message)


def _client_ip(request: Request) -> str:
    """Socket peer address, used as the per-IP rate-limit key.

    Deliberately NOT X-Forwarded-For: that header is client-controlled, so
    trusting it without a known-proxy allowlist would let an attacker rotate
    the header and bypass the limit entirely -- strictly worse than the
    honest limitation that behind a reverse proxy all clients share one
    bucket. Documented in app/core/rate_limit.py alongside the other
    trade-offs of doing this in-process.
    """
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request) -> TokenResponse:
    """Authenticate and issue a JWT, with brute-force protection.

    Two independent limits are checked BEFORE doing any password work, so a
    throttled attacker gets a cheap 429 instead of the server paying for a
    PBKDF2 derivation on every guess -- rate limiting that ran after the
    expensive check would still leave the CPU-exhaustion vector open.
    """
    ip_key = f"login:ip:{_client_ip(request)}"
    account_key = f"login:acct:{payload.username.strip().lower()}"

    # IP budget: EVERY attempt consumes a slot regardless of outcome, so
    # check-and-consume atomically. peek()+record() here would be a
    # check-then-act race -- `login` is a sync def running in a threadpool, so
    # concurrent requests could all pass the check before any of them records,
    # admitting more than LOGIN_IP_LIMIT.
    #
    # Note attempt() does not consume a slot when it returns False: a blocked
    # IP recovers by window expiry rather than being pushed further out by its
    # own continued hammering. That is the standard behaviour (nginx limit_req
    # does the same) and it matters for legitimate users behind shared NAT,
    # who would otherwise stay locked out as long as anyone on that NAT keeps
    # retrying.
    ip_ok, ip_retry = login_limiter.attempt(
        ip_key, settings.LOGIN_IP_LIMIT, settings.LOGIN_IP_WINDOW_SECONDS
    )
    # Account budget: peek ONLY. Failures are recorded after authentication,
    # because a success must not consume this budget (see reset() below). The
    # resulting peek/record pair is not atomic, so concurrent failures against
    # one username can overshoot the limit by the number of in-flight
    # requests. That fails SAFE -- the account locks slightly earlier than
    # configured, never later -- and total admissions are already bounded by
    # the atomic IP check above, so the overshoot is small.
    account_ok, account_retry = login_limiter.peek(
        account_key,
        settings.LOGIN_ACCOUNT_FAILURE_LIMIT,
        settings.LOGIN_ACCOUNT_WINDOW_SECONDS,
    )
    if not ip_ok or not account_ok:
        retry_after = max(ip_retry, account_retry)
        # Same 429 shape whether the IP or the account tripped: telling an
        # attacker which of the two limits they hit would let them tune the
        # other one.
        logger.warning("Login throttled (ip=%s username=%s)", ip_key, account_key)
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please wait before trying again.",
            headers={"Retry-After": str(retry_after)},
        )

    ok, message = authenticate(payload.username, payload.password)
    if not ok:
        # window_seconds MUST be passed explicitly: record() prunes with the
        # window it is given, and pruning with a shorter default would delete
        # failures that are still inside this budget -- silently shrinking a
        # 300s limit to 60s.
        login_limiter.record(
            account_key, window_seconds=settings.LOGIN_ACCOUNT_WINDOW_SECONDS
        )
        # Deliberately the same 401 + generic-ish message whether the
        # username doesn't exist or the password is wrong (utils.auth
        # already differentiates in its message text, which is a minor,
        # pre-existing information leak inherited from the Streamlit app --
        # noted here rather than silently accepted; not fixed today because
        # changing utils/auth.py's return message would also change what
        # the Streamlit UI displays, which is out of scope for this API
        # feature).
        raise HTTPException(status_code=401, detail=message)

    login_limiter.reset(account_key)
    token = create_access_token(payload.username.strip())
    return TokenResponse(access_token=token)
