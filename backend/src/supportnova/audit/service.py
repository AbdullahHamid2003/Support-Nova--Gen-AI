"""Append-only, hash-chained audit trail (SRS 1.6 lxiv, Step 59).

Each record stores sha256(prev_hash + canonical record). ``verify_chain`` recomputes the chain;
any edited or deleted row breaks it. Ordinary application code has no update/delete path, the ORM
blocks it, and PostgreSQL enforces it with a trigger (see the initial Alembic migration).

Chaining happens at commit time: ``record`` stages the entry on the session and a ``before_commit``
hook seals all staged entries under a process lock plus a PostgreSQL advisory transaction lock, so
concurrent transactions (API requests, pipeline workers, several server processes) always extend
one linear chain, and entries of a rolled-back transaction are discarded together with it.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import event, select, text
from sqlalchemy.orm import Session, SessionTransaction

from supportnova.core.logging import request_id_var
from supportnova.core.timeutil import utcnow
from supportnova.database.models import AuditLog, User

_lock = threading.Lock()
_PENDING = "supportnova.audit.pending"
_HELD = "supportnova.audit.lock_held"
_ADVISORY_KEY = 5_318_008_424  # arbitrary, app-wide constant for pg_advisory_xact_lock
LOCK_TIMEOUT_SECONDS = 30


class AuditImmutableError(RuntimeError):
    pass


@event.listens_for(AuditLog, "before_update")
def _block_update(*_args: Any) -> None:
    raise AuditImmutableError("Audit records are immutable.")


@event.listens_for(AuditLog, "before_delete")
def _block_delete(*_args: Any) -> None:
    raise AuditImmutableError("Audit records cannot be deleted.")


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def _digest(prev_hash: str, row: dict[str, Any]) -> str:
    canonical = json.dumps(row, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


def _row_payload(entry: AuditLog) -> dict[str, Any]:
    return {
        "created_at": _utc_iso(entry.created_at),
        "actor_id": entry.actor_id, "actor_label": entry.actor_label, "actor_role": entry.actor_role,
        "action": entry.action, "entity_type": entry.entity_type, "entity_id": entry.entity_id,
        "summary": entry.summary, "details": entry.details,
    }


def record(db: Session, *, action: str, entity_type: str, entity_id: str | int, summary: str = "",
           details: dict[str, Any] | None = None, actor: User | None = None, actor_label: str | None = None,
           ip_address: str | None = None) -> AuditLog:
    """Stage an audit record in the caller's transaction; it is chained and written on commit."""
    entry = AuditLog(
        created_at=utcnow(),
        actor_id=actor.id if actor else None,
        actor_label=actor_label or (f"{actor.full_name} <{actor.email}>" if actor else "system"),
        actor_role=actor.role_code if actor else "system",
        action=action, entity_type=entity_type, entity_id=str(entity_id), summary=summary[:2000],
        # round-trip so the hashed value is exactly what the JSON column stores
        details=json.loads(json.dumps(details or {}, default=str)), ip_address=ip_address,
        request_id=request_id_var.get(), prev_hash="", hash="",
    )
    db.info.setdefault(_PENDING, []).append(entry)
    return entry


def pending(db: Session) -> list[AuditLog]:
    return list(db.info.get(_PENDING, []))


@event.listens_for(Session, "before_commit")
def _seal(session: Session) -> None:
    staged: list[AuditLog] = session.info.get(_PENDING) or []
    if not staged:
        return
    session.flush()  # write everything else first, before taking the chain lock (no lock held while waiting on rows)
    if not _lock.acquire(timeout=LOCK_TIMEOUT_SECONDS):
        raise TimeoutError("Timed out waiting for the audit chain lock.")
    session.info[_HELD] = True
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _ADVISORY_KEY})
    prev = session.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).scalar() or ""
    for entry in staged:
        entry.prev_hash = prev
        entry.hash = _digest(prev, _row_payload(entry))
        session.add(entry)
        session.flush([entry])
        prev = entry.hash
    session.info[_PENDING] = []


@event.listens_for(Session, "after_transaction_end")
def _release(session: Session, transaction: SessionTransaction) -> None:
    if transaction.parent is not None:
        return
    session.info.pop(_PENDING, None)  # committed entries are written; rolled-back ones are discarded
    if session.info.pop(_HELD, False):
        _lock.release()


def verify_chain(db: Session, *, limit: int | None = None) -> dict[str, Any]:
    """Recompute the hash chain; returns the first broken record, if any."""
    query = select(AuditLog).order_by(AuditLog.id)
    if limit:
        query = query.limit(limit)
    prev = ""
    checked = 0
    for entry in db.execute(query).scalars():
        expected = _digest(prev, _row_payload(entry))
        if entry.prev_hash != prev or entry.hash != expected:
            return {"valid": False, "checked": checked, "broken_at_id": entry.id,
                    "message": f"Audit chain broken at record {entry.id}."}
        prev = entry.hash
        checked += 1
    return {"valid": True, "checked": checked, "broken_at_id": None, "message": "Audit chain intact."}
