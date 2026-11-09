"""Posting journal entries. Idempotent by key and balanced by construction."""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import JournalEntry, JournalLine
from app.domain.ledger import Line, validate_entry


def post_entry(session: Session, idempotency_key: str, description: str, lines: list[Line],
               reverses_entry_id: int | None = None) -> JournalEntry:
    """Insert a balanced entry. A repeated key returns the existing entry, never a duplicate."""
    existing = session.scalar(select(JournalEntry).where(JournalEntry.idempotency_key == idempotency_key))
    if existing is not None:
        return existing
    validate_entry(lines)
    entry = JournalEntry(idempotency_key=idempotency_key, description=description,
                         reverses_entry_id=reverses_entry_id)
    entry.lines = [JournalLine(account=ln.account, side=ln.side, amount=ln.amount) for ln in lines]
    session.add(entry)
    session.flush()
    return entry


def all_lines(session: Session) -> list[Line]:
    rows = session.scalars(select(JournalLine)).all()
    return [Line(r.account, r.side, r.amount) for r in rows]
