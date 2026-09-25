"""Dashboards, analytics, trend detection, reports and exports (SRS Steps 61-68)."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from supportnova.api.deps import current_user, db_session, require
from supportnova.audit import service as audit
from supportnova.core.errors import ValidationFailed
from supportnova.database.models import User
from supportnova.reporting import builders
from supportnova.reporting.exports import FORMATS, render
from supportnova.services import analytics as an
from supportnova.services.rules import rule_service

router = APIRouter(tags=["analytics"])


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(db_session)) -> dict[str, Any]:
    return an.dashboard(db, rule_service.matrix(db), user)


@router.get("/analytics/overview")
def overview(user: User = Depends(require("analytics:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    matrix = rule_service.matrix(db)
    return {"kpis": an.overview(db, matrix),
            "distributions": {d: an.distribution(db, matrix, d) for d in ("category", "subcategory", "department", "priority", "urgency",
                                                                           "sentiment", "channel", "status", "verification",
                                                                           "escalation", "customer_type", "product", "sla")}}


@router.get("/analytics/distribution/{dimension}")
def distribution(dimension: str, user: User = Depends(require("analytics:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    if dimension not in an.DIMENSIONS:
        raise ValidationFailed(f"Unknown dimension '{dimension}'.", details={"allowed": sorted(an.DIMENSIONS)})
    return {"dimension": dimension, "items": an.distribution(db, rule_service.matrix(db), dimension)}


@router.get("/analytics/trends")
def trends(days: int = Query(default=120, ge=7, le=730), granularity: str = Query(default="week", pattern="^(day|week)$"),
           dimension: str = "category", user: User = Depends(require("analytics:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    if dimension not in an.DIMENSIONS:
        raise ValidationFailed(f"Unknown dimension '{dimension}'.")
    return an.trends(db, rule_service.matrix(db), days=days, granularity=granularity, dimension=dimension)


@router.get("/analytics/alerts")
def alerts(window_days: int = Query(default=14, ge=3, le=90), user: User = Depends(require("analytics:read")),
           db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"items": an.trend_alerts(db, rule_service.matrix(db), window_days=window_days), "window_days": window_days}


@router.get("/analytics/validation")
def validation(user: User = Depends(require("analytics:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    return an.validation_stats(db, rule_service.matrix(db))


@router.get("/analytics/sla")
def sla(user: User = Depends(require("analytics:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    return an.sla_stats(db)


@router.get("/analytics/departments")
def departments(user: User = Depends(require("analytics:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"items": an.department_performance(db, rule_service.matrix(db))}


@router.get("/analytics/policy-usage")
def policy_usage(user: User = Depends(require("analytics:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"items": an.policy_usage(db)}


@router.get("/analytics/resolution-times")
def resolution_times(user: User = Depends(require("analytics:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    return {"items": an.resolution_times(db, rule_service.matrix(db))}


# ------------------------------------------------------------------------------------------ reports
@router.get("/reports")
def report_catalog(user: User = Depends(require("reports:export"))) -> dict[str, Any]:
    return {"items": [{"key": k, "name": name} for k, (name, _fn) in builders.REPORTS.items()], "formats": list(FORMATS)}


@router.get("/reports/{key}")
def build_report(key: str, format: str = "json", date_from: date | None = None, date_to: date | None = None,
                 department: str | None = None, category: str | None = None, run_id: int | None = None,
                 user: User = Depends(require("reports:export")), db: Session = Depends(db_session)) -> Response:
    params = builders.ReportParams(date_from=date_from, date_to=date_to, department=department or None,
                                   category=category or None, run_id=run_id)
    report = builders.build(db, rule_service.matrix(db), key, params)
    content, media, ext = render(report, format)
    if format != "json":
        audit.record(db, action="report.exported", entity_type="report", entity_id=key, actor=user,
                     summary=f"{report.title} exported as {ext}", details={"scope": params.describe(), "run_id": run_id})
        db.commit()
    headers = {} if format == "json" else {"Content-Disposition": f'attachment; filename="supportnova-{key}.{ext}"'}
    return Response(content, media_type=media, headers=headers)
