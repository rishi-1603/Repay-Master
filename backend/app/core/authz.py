"""Role-based access for operations endpoints.

`require_role("ops")` is a FastAPI dependency: it authenticates the bearer token, then looks up
the caller's current grants in the database. The token does not carry roles, so revoking a grant
takes effect on the next request, not when the token expires.
"""
from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import get_current_username
from app.db.base import get_db
from app.services.roles import granted_roles


def require_role(role: str):
    def dependency(username: str = Depends(get_current_username), db: Session = Depends(get_db)) -> str:
        if role not in granted_roles(db, username):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"{role} role required")
        return username
    return dependency
