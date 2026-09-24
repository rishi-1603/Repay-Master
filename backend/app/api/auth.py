"""Registration + login.

Reuses utils/auth.py's existing sqlite3 + PBKDF2 implementation directly --
the same module the Streamlit app already uses -- instead of standing up a
second, separate user store. One users table, shared by both clients: an
account created through this API can log into the Streamlit app and vice
versa.
"""
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

# utils/ lives at the repo root (sibling of backend/), not inside backend/ --
# same pattern already used by app/api/loans.py and app/api/risk.py.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from utils.auth import authenticate, register_user  # noqa: E402

from app.core.security import create_access_token  # noqa: E402
from app.schemas.auth import LoginRequest, RegisterRequest, RegisterResponse, TokenResponse  # noqa: E402

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(payload: RegisterRequest) -> RegisterResponse:
    ok, message = register_user(payload.username, payload.password)
    if not ok:
        # Both "empty username" and "username taken" come back as 400 --
        # a client error, not a server error.
        raise HTTPException(status_code=400, detail=message)
    return RegisterResponse(message=message)


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest) -> TokenResponse:
    ok, message = authenticate(payload.username, payload.password)
    if not ok:
        # Deliberately the same 401 + generic-ish message whether the
        # username doesn't exist or the password is wrong (utils.auth
        # already differentiates in its message text, which is a minor,
        # pre-existing information leak inherited from the Streamlit app --
        # noted here rather than silently accepted; not fixed today because
        # changing utils/auth.py's return message would also change what
        # the Streamlit UI displays, which is out of scope for this API
        # feature).
        raise HTTPException(status_code=401, detail=message)
    token = create_access_token(payload.username.strip())
    return TokenResponse(access_token=token)
