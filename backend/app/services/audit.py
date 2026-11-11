"""Audit trail for privileged actions. The caller commits, so the record and the change succeed or fail together."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AuditEvent


def record(session: Session, actor: str, action: str, target: str, detail: str | None = None) -> None:
    session.add(AuditEvent(actor=actor, action=action, target=target, detail=detail))


def recent(session: Session, limit: int = 100) -> list[AuditEvent]:
    return list(session.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)).all())
