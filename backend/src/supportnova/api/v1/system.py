"""Health, immutable audit log and system information."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from supportnova import __version__
from supportnova.api.deps import current_user, db_session, require_any
from supportnova.api.serializers import iso
from supportnova.audit import service as audit
from supportnova.core.config import get_settings
from supportnova.core.errors import PermissionDenied
from supportnova.database.models import AuditLog, Complaint, User
from supportnova.reporting.exports import tabular

router = APIRouter(tags=["system"])


@router.get("/health")
def health(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Liveness + readiness (database reachable). Never exposes configuration secrets."""
    settings = get_settings()
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "version": __version__, "database": "ok" if db_ok else "unavailable",
            "ai_provider": settings.resolved_provider, "ai_mode": "live" if settings.ai_configured else "not_configured"}


def _audit_query(user: User, *, action: str | None, entity_type: str | None, entity_id: str | None, actor: str | None,
                 date_from: date | None, date_to: date | None) -> list[Any]:
    conds: list[Any] = []
    if "audit:read" not in user.permissions:
        # reviewers / managers: complaint and review trail only
        conds.append(AuditLog.entity_type.in_(["complaint", "review", "report", "evaluation_run"]))
    if action:
        conds.append(AuditLog.action.like(f"{action}%"))
    if entity_type:
        conds.append(AuditLog.entity_type == entity_type)
    if entity_id:
        conds.append(AuditLog.entity_id == entity_id.upper() if entity_id[:3].isalpha() else AuditLog.entity_id == entity_id)
    if actor:
        like = f"%{actor.lower()}%"
        conds.append(or_(func.lower(AuditLog.actor_label).like(like), func.lower(AuditLog.actor_role).like(like)))
    if date_from:
        conds.append(AuditLog.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        conds.append(AuditLog.created_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    return conds


def _entry(a: AuditLog) -> dict[str, Any]:
    return {"id": a.id, "at": iso(a.created_at), "actor": a.actor_label, "role": a.actor_role, "action": a.action,
            "entity_type": a.entity_type, "entity_id": a.entity_id, "summary": a.summary, "details": a.details,
            "ip_address": a.ip_address, "request_id": a.request_id, "hash": a.hash, "prev_hash": a.prev_hash}


@router.get("/audit")
def audit_log(action: str | None = None, entity_type: str | None = None, entity_id: str | None = None, actor: str | None = None,
              date_from: date | None = None, date_to: date | None = None, page: int = Query(default=1, ge=1),
              page_size: int = Query(default=50, ge=1, le=500),
              user: User = Depends(require_any("audit:read", "audit:read_complaint")), db: Session = Depends(db_session)) -> dict[str, Any]:
    conds = _audit_query(user, action=action, entity_type=entity_type, entity_id=entity_id, actor=actor, date_from=date_from, date_to=date_to)
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*conds)) or 0
    rows = db.execute(select(AuditLog).where(*conds).order_by(AuditLog.id.desc()).offset((page - 1) * page_size).limit(page_size)).scalars()
    actions = db.execute(select(AuditLog.action, func.count()).where(*conds).group_by(AuditLog.action)).all()
    return {"items": [_entry(a) for a in rows], "total": total, "page": page, "page_size": page_size,
            "actions": sorted(({"action": a, "count": n} for a, n in actions), key=lambda x: -x["count"])}


@router.get("/audit/verify")
def verify(user: User = Depends(require_any("audit:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    result = audit.verify_chain(db)
    audit.record(db, action="audit.verified", entity_type="audit", entity_id="chain", actor=user,
                 summary=result["message"], details={"checked": result["checked"], "valid": result["valid"]})
    db.commit()
    return result


@router.get("/audit/export")
def export(format: str = "csv", action: str | None = None, entity_type: str | None = None, entity_id: str | None = None,
           actor: str | None = None, date_from: date | None = None, date_to: date | None = None,
           user: User = Depends(require_any("audit:read")), db: Session = Depends(db_session)) -> Response:
    conds = _audit_query(user, action=action, entity_type=entity_type, entity_id=entity_id, actor=actor, date_from=date_from, date_to=date_to)
    rows = db.execute(select(AuditLog).where(*conds).order_by(AuditLog.id).limit(20000)).scalars().all()
    cols = ["id", "at", "actor", "role", "action", "entity_type", "entity_id", "summary", "hash"]
    content, media, ext = tabular("Audit log", cols, [[_entry(a)[c] for c in cols] for a in rows], format)
    audit.record(db, action="report.exported", entity_type="report", entity_id="audit", actor=user, summary=f"Audit log export ({len(rows)} rows)")
    db.commit()
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="supportnova-audit.{ext}"'})


@router.get("/complaints/{ref}/audit")
def complaint_audit(ref: str, user: User = Depends(require_any("audit:read", "audit:read_complaint", "complaint:read_all")),
                    db: Session = Depends(db_session)) -> dict[str, Any]:
    if user.role_code == "customer":
        raise PermissionDenied("Audit records are internal.")
    c = db.execute(select(Complaint).where(Complaint.complaint_ref == ref.upper())).scalar_one_or_none()
    rows = db.execute(select(AuditLog).where(AuditLog.entity_id == (c.complaint_ref if c else ref.upper()))
                      .order_by(AuditLog.id)).scalars().all()
    return {"items": [_entry(a) for a in rows]}


@router.get("/system/info")
def system_info(user: User = Depends(current_user), db: Session = Depends(db_session)) -> dict[str, Any]:
    if "settings:manage" not in user.permissions:
        raise PermissionDenied("Administrators only.")
    s = get_settings()
    return {"version": __version__, "environment": s.app_env, "database": db.get_bind().dialect.name,
            "ai": {"provider": s.resolved_provider, "model": s.resolved_model, "configured": s.ai_configured,
                   "timeout_seconds": s.ai_timeout_seconds, "max_retries": s.ai_max_retries, "refusal_fallback": s.ai_refusal_fallback},
            "embedding_provider": s.embedding_provider, "retrieval_top_k": s.retrieval_top_k,
            "workers": s.background_workers, "sla_monitor_interval_seconds": s.sla_monitor_interval_seconds,
            "rate_limits": {"per_minute": s.rate_limit_per_minute, "auth_per_minute": s.login_rate_limit_per_minute},
            "uploads": {"max_document_mb": s.max_upload_mb, "max_attachment_mb": s.max_attachment_mb},
            "duplicates": {"window_hours": s.duplicate_window_hours, "near_duplicate_threshold": s.near_duplicate_threshold,
                           "reject_exact": s.reject_exact_duplicates}}
