"""JWT bearer-token auth for the endpoints that need to know who is calling
(currently just /history).

PyJWT (not python-jose) was chosen deliberately: HS256 needs no optional
`cryptography` extra, keeping this project's dependency footprint small --
consistent with utils/auth.py's existing choice to avoid bcrypt after a
past native-build compatibility problem. There is no server-side session
store; a signed, short-lived token issued at /auth/login is the standard
stateless way for a REST client to prove identity on later requests
without re-checking a password against sqlite every single time.
"""
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings

_bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": username, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def get_current_username(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> str:
    """FastAPI dependency: decode+validate the bearer token, return the
    username it was issued for. Raises 401 for a missing, expired, or
    tampered/invalid token -- callers never see a stack trace, and an
    expired token is reported differently from a garbage one only in the
    message, never in status code, so no information is leaked either way.
    """
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token") from exc

    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication token")
    return username
