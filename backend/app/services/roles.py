"""Operational role grants: who may run operations endpoints.

Roles are stored in role_grants and read on every request (see app/core/authz.py), so a
revoke takes effect on the next call. `admin` implies `ops`. Every change is audited in the
same transaction.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import RoleGrant
from app.services import audit

ROLES = ("ops", "admin")
IMPLIED = {"admin": {"admin", "ops"}, "ops": {"ops"}}


class UnknownRole(ValueError):
    pass


def _check(role: str) -> str:
    if role not in ROLES:
        raise UnknownRole(f"unknown role {role!r}; expected one of {', '.join(ROLES)}")
    return role


def granted_roles(session: Session, username: str) -> set[str]:
    """Roles the user effectively holds, including implied ones."""
    direct = set(session.scalars(select(RoleGrant.role).where(RoleGrant.username == username)).all())
    effective: set[str] = set()
    for role in direct:
        effective |= IMPLIED.get(role, set())
    return effective


def grant(session: Session, username: str, role: str, actor: str) -> bool:
    """Returns True if the grant was created, False if the user already held it."""
    _check(role)
    if session.get(RoleGrant, (username, role)) is not None:
        return False
    session.add(RoleGrant(username=username, role=role))
    audit.record(session, actor, "role.grant", username, role)
    session.commit()
    return True


def revoke(session: Session, username: str, role: str, actor: str) -> bool:
    _check(role)
    grant_row = session.get(RoleGrant, (username, role))
    if grant_row is None:
        return False
    session.delete(grant_row)
    audit.record(session, actor, "role.revoke", username, role)
    session.commit()
    return True
