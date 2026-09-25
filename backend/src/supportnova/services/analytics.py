"""Analytics, dashboards and trend detection (SRS Steps 61-65). Every number is computed from the
application database at request time - nothing is hard-coded or fabricated. Lab and evaluation
complaints are excluded so dashboards reflect operational data."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from supportnova.core.timeutil import utcnow
from supportnova.database.models import (
    Analysis,
    AuditLog,
    Complaint,
    ComplaintHistory,
    CustomerResponse,
    Document,
    DocumentVersion,
    Escalation,
    PolicyReference,
    Prompt,
    Review,
    RuleRecord,
    SlaRecord,
    User,
    ValidationCheck,
    ValidationResult,
)
from supportnova.rule_engine.models import RuleMatrix

OPERATIONAL = ("web", "api", "dataset")
DIMENSIONS = {
    "category": Complaint.category_code, "subcategory": Complaint.subcategory_code, "department": Complaint.department_code,
    "priority": Complaint.priority, "urgency": Complaint.urgency, "sentiment": Complaint.sentiment, "channel": Complaint.channel,
    "status": Complaint.status, "verification": Complaint.verification_status, "escalation": Complaint.escalation_level,
    "customer_type": Complaint.customer_type, "product": Complaint.product_sku, "sla": Complaint.sla_state,
}


def _base():
    return Complaint.source.in_(OPERATIONAL)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=utcnow().tzinfo)


_NONE_LABELS = {"department": "Not routed", "product": "No product identified", "category": "Unclassified",
                "subcategory": "Unclassified"}  # e.g. linked duplicates are never analysed or routed


def label(matrix: RuleMatrix, dimension: str, key: str | None) -> str:
    if key is None:
        return _NONE_LABELS.get(dimension, "Not set")
    if dimension == "category" and key in matrix.categories:
        return matrix.categories[key].name
    if dimension == "subcategory" and key in matrix.subcategories:
        return matrix.subcategories[key].name
    if dimension == "department" and key in matrix.departments:
        return matrix.departments[key].name
    if dimension == "product" and key in matrix.products:
        return matrix.products[key].name
    return str(key)


def distribution(db: Session, matrix: RuleMatrix, dimension: str, *, since: datetime | None = None) -> list[dict[str, Any]]:
    col = DIMENSIONS[dimension]
    q = select(col, func.count()).where(_base())
    if since:
        q = q.where(Complaint.created_at >= since)
    rows = db.execute(q.group_by(col)).all()
    total = sum(n for _, n in rows) or 1
    return sorted(({"key": k, "label": label(matrix, dimension, k), "count": n, "share": round(n / total, 4)} for k, n in rows),
                  key=lambda x: -x["count"])


def overview(db: Session, matrix: RuleMatrix) -> dict[str, Any]:
    base = _base()
    total = db.scalar(select(func.count()).select_from(Complaint).where(base)) or 0

    def count(*conds: Any) -> int:
        return db.scalar(select(func.count()).select_from(Complaint).where(base, *conds)) or 0

    analysed = count(Complaint.verification_status != "Pending")
    verified = count(Complaint.verification_status.in_(["Verified", "Human Verified"]))
    agreement = db.execute(select(Complaint.ai_python_agreement, func.count()).where(base, Complaint.ai_python_agreement.is_not(None))
                           .group_by(Complaint.ai_python_agreement)).tuples().all()
    agree = dict(agreement)
    resolved = db.execute(select(Complaint.created_at, Complaint.resolved_at).where(base, Complaint.resolved_at.is_not(None))).all()
    hours = [(_aware(r) - _aware(c)).total_seconds() / 3600 for c, r in resolved if r and c]  # type: ignore[operator]
    latency = db.scalar(select(func.avg(Analysis.total_latency_ms)).join(Complaint, Complaint.id == Analysis.complaint_id).where(base))
    return {
        "total": total, "open": count(Complaint.status.notin_(["Resolved", "Closed"])),
        "resolved": count(Complaint.status.in_(["Resolved", "Closed"])), "escalated": count(Complaint.escalation_required.is_(True)),
        "manual_review_pending": db.scalar(select(func.count()).select_from(Review).where(Review.status.in_(["pending", "in_review"]))) or 0,
        "verified_rate": round(verified / analysed, 4) if analysed else None, "analysed": analysed,
        "auto_verified": count(Complaint.verification_status == "Verified"),
        "human_verified": count(Complaint.verification_status == "Human Verified"),
        "avg_verification_score": round(float(db.scalar(select(func.avg(Complaint.verification_score)).where(base)) or 0), 1),
        "sla_at_risk": count(Complaint.sla_state == "At Risk", Complaint.status.notin_(["Resolved", "Closed"])),
        "sla_breached": count(Complaint.sla_state == "Breached", Complaint.status.notin_(["Resolved", "Closed"])),
        "repeat": count(Complaint.is_repeat.is_(True)), "duplicates": count(Complaint.is_duplicate.is_(True)),
        "injection_detected": count(Complaint.injection_detected.is_(True)),
        "ai_python_agreement_rate": round(agree.get(True, 0) / (agree.get(True, 0) + agree.get(False, 0)), 4) if agree else None,
        "ai_python_mismatches": agree.get(False, 0),
        "avg_resolution_hours": round(sum(hours) / len(hours), 1) if hours else None,
        "avg_processing_ms": round(float(latency), 0) if latency else None,
    }


def trends(db: Session, matrix: RuleMatrix, *, days: int = 90, granularity: str = "week", dimension: str = "category",
           top: int = 6) -> dict[str, Any]:
    since = utcnow() - timedelta(days=days)
    col = DIMENSIONS.get(dimension, Complaint.category_code)
    rows = db.execute(select(Complaint.created_at, col, Complaint.escalation_required, Complaint.sentiment)
                      .where(_base(), Complaint.created_at >= since)).all()

    def bucket(dt: datetime) -> str:
        d = dt.date()
        if granularity == "day":
            return d.isoformat()
        start = d - timedelta(days=d.weekday())
        return start.isoformat()

    totals: Counter[str] = Counter()
    by_key: dict[str, Counter[str]] = defaultdict(Counter)
    esc: Counter[str] = Counter()
    neg: Counter[str] = Counter()
    for created, key, escalated, sentiment in rows:
        b = bucket(created)
        totals[b] += 1
        by_key[str(key)][b] += 1
        if escalated:
            esc[b] += 1
        if sentiment in ("Negative", "Strongly Negative"):
            neg[b] += 1
    buckets = sorted(totals)
    leaders = sorted(by_key, key=lambda k: -sum(by_key[k].values()))[:top]
    series = []
    for b in buckets:
        point: dict[str, Any] = {"bucket": b, "total": totals[b], "escalations": esc[b], "negative": neg[b]}
        for k in leaders:
            point[k] = by_key[k][b]
        series.append(point)
    return {"granularity": granularity, "dimension": dimension, "series": series,
            "keys": [{"key": k, "label": label(matrix, dimension, None if k == "None" else k)} for k in leaders]}


def trend_alerts(db: Session, matrix: RuleMatrix, *, window_days: int = 14) -> list[dict[str, Any]]:
    """Emerging patterns: rising categories/products/departments, escalation spikes, recurring product
    issues and repeated service failures (SRS Step 65)."""
    now = utcnow()
    cur_start, prev_start = now - timedelta(days=window_days), now - timedelta(days=2 * window_days)
    alerts: list[dict[str, Any]] = []
    for dimension in ("category", "department", "product"):
        col = DIMENSIONS[dimension]
        cur = dict(db.execute(select(col, func.count()).where(_base(), Complaint.created_at >= cur_start)
                              .group_by(col)).tuples().all())
        prev = dict(db.execute(select(col, func.count()).where(_base(), Complaint.created_at >= prev_start,
                                                             Complaint.created_at < cur_start).group_by(col)).tuples().all())
        for key, n in cur.items():
            p = prev.get(key, 0)
            if key and n >= 5 and n >= 1.5 * max(p, 1):
                alerts.append({"type": f"rising_{dimension}", "severity": "high" if n >= 2.5 * max(p, 1) else "medium",
                               "key": key, "label": label(matrix, dimension, key), "current": n, "previous": p,
                               "change": round((n - p) / max(p, 1), 2),
                               "message": f"{label(matrix, dimension, key)} complaints rose from {p} to {n} in the last {window_days} days."})
    cur_esc = db.scalar(select(func.count()).select_from(Complaint).where(_base(), Complaint.escalation_required.is_(True),
                                                                          Complaint.created_at >= now - timedelta(days=7))) or 0
    prev_esc = db.scalar(select(func.count()).select_from(Complaint).where(_base(), Complaint.escalation_required.is_(True),
                                                                           Complaint.created_at >= now - timedelta(days=35),
                                                                           Complaint.created_at < now - timedelta(days=7))) or 0
    weekly = prev_esc / 4
    if cur_esc >= 4 and cur_esc >= 1.5 * max(weekly, 1):
        alerts.append({"type": "escalation_spike", "severity": "high", "current": cur_esc, "previous": round(weekly, 1),
                       "message": f"Escalations spiked to {cur_esc} this week (weekly average {weekly:.1f})."})
    recurring = db.execute(select(Complaint.product_sku, Complaint.subcategory_code, func.count())
                           .where(_base(), Complaint.created_at >= now - timedelta(days=30), Complaint.product_sku.is_not(None),
                                  Complaint.category_code.in_(["PRD", "SAF", "WAR", "TEC"]))
                           .group_by(Complaint.product_sku, Complaint.subcategory_code).having(func.count() >= 4)).all()
    for sku, sub, n in recurring:
        alerts.append({"type": "recurring_product_issue", "severity": "high" if (sub or "").startswith("SAF") else "medium",
                       "key": f"{sku}:{sub}", "label": f"{label(matrix, 'product', sku)} - {label(matrix, 'subcategory', sub)}",
                       "current": n, "message": f"{n} complaints about {label(matrix, 'product', sku)} "
                                                f"({label(matrix, 'subcategory', sub)}) in the last 30 days."})
    service_fail = db.scalar(select(func.count()).select_from(Complaint).where(
        _base(), Complaint.created_at >= now - timedelta(days=30),
        (Complaint.subcategory_code == "SVC-OUT") | (Complaint.is_repeat.is_(True)))) or 0
    if service_fail >= 5:
        alerts.append({"type": "repeated_service_failures", "severity": "medium", "current": service_fail,
                       "message": f"{service_fail} service-outage or repeat complaints in the last 30 days."})
    return sorted(alerts, key=lambda a: (a["severity"] != "high", -a.get("current", 0)))


def validation_stats(db: Session, matrix: RuleMatrix) -> dict[str, Any]:
    base_ids = select(Complaint.id).where(_base())
    latest = select(func.max(ValidationResult.id)).where(ValidationResult.complaint_id.in_(base_ids)).group_by(ValidationResult.complaint_id)
    checks = db.execute(select(ValidationCheck.code, ValidationCheck.name, ValidationCheck.dimension, ValidationCheck.status, func.count())
                        .where(ValidationCheck.result_id.in_(latest)).group_by(ValidationCheck.code, ValidationCheck.name,
                                                                               ValidationCheck.dimension, ValidationCheck.status)).all()
    by_code: dict[str, dict[str, Any]] = {}
    for code, name, dim, status, n in checks:
        current = matrix.validation_check(code).get("name") or name  # current display name, also for older results
        entry = by_code.setdefault(code, {"code": code, "name": current, "dimension": dim, "pass": 0, "warn": 0, "fail": 0,
                                          "not_applicable": 0})
        entry[status] = entry.get(status, 0) + n
    decisions = dict(db.execute(select(ValidationResult.decision, func.count()).where(ValidationResult.id.in_(latest))
                                .group_by(ValidationResult.decision)).tuples().all())
    comparisons = db.execute(select(ValidationResult.comparison).where(ValidationResult.id.in_(latest))).scalars().all()
    field_stats: dict[str, Counter[str]] = defaultdict(Counter)
    for comp in comparisons:
        for row in (comp or {}).get("rows", []):
            field_stats[row["field"]][row["match"]] += 1
    reasons: Counter[str] = Counter()
    for rr in db.execute(select(ValidationResult.review_reasons).where(ValidationResult.id.in_(latest))).scalars():
        for r in rr or []:
            reasons[r["code"]] += 1
    dims: dict[str, list[float]] = defaultdict(list)
    for ds in db.execute(select(ValidationResult.dimension_scores).where(ValidationResult.id.in_(latest))).scalars():
        for k, v in (ds or {}).items():
            dims[k].append(float(v))
    return {
        "checks": sorted(by_code.values(), key=lambda e: -e["fail"]),
        "decisions": decisions,
        "field_agreement": [{"field": f, "match": c["match"], "partial": c["partial"], "mismatch": c["mismatch"],
                             "rate": round(c["match"] / max(1, sum(c.values())), 4)} for f, c in field_stats.items()],
        "review_reasons": [{"code": k, "count": v} for k, v in reasons.most_common()],
        "dimension_scores": {k: round(sum(v) / len(v), 1) for k, v in dims.items() if v},
    }


def sla_stats(db: Session) -> dict[str, Any]:
    rows = db.execute(select(SlaRecord.priority, SlaRecord.resolution_state, func.count()).join(Complaint, Complaint.id == SlaRecord.complaint_id)
                      .where(_base()).group_by(SlaRecord.priority, SlaRecord.resolution_state)).all()
    table: dict[str, dict[str, int]] = defaultdict(lambda: {"On Track": 0, "At Risk": 0, "Breached": 0, "Met": 0})
    for prio, state, n in rows:
        table[prio][state] = n
    return {"by_priority": [{"priority": p, **v} for p, v in sorted(table.items())]}


def department_performance(db: Session, matrix: RuleMatrix) -> list[dict[str, Any]]:
    rows = db.execute(select(Complaint.department_code, Complaint.status, Complaint.created_at, Complaint.resolved_at,
                             Complaint.escalation_required, Complaint.verification_score, Complaint.sla_state).where(_base())).all()
    agg: dict[str, dict[str, Any]] = {}
    for dept, status, created, resolved, escalated, score, sla in rows:
        a = agg.setdefault(dept or "UNASSIGNED", {"department": dept, "name": label(matrix, "department", dept), "volume": 0, "open": 0,
                                                   "resolved": 0, "escalated": 0, "breached": 0, "_hours": [], "_scores": []})
        a["volume"] += 1
        a["open"] += status not in ("Resolved", "Closed")
        a["resolved"] += status in ("Resolved", "Closed")
        a["escalated"] += bool(escalated)
        a["breached"] += sla == "Breached"
        if resolved and created:
            a["_hours"].append((_aware(resolved) - _aware(created)).total_seconds() / 3600)  # type: ignore[operator]
        if score is not None:
            a["_scores"].append(score)
    out = []
    for a in agg.values():
        hours, scores = a.pop("_hours"), a.pop("_scores")
        a["avg_resolution_hours"] = round(sum(hours) / len(hours), 1) if hours else None
        a["avg_verification_score"] = round(sum(scores) / len(scores), 1) if scores else None
        a["breach_rate"] = round(a["breached"] / a["volume"], 3) if a["volume"] else 0
        out.append(a)
    return sorted(out, key=lambda a: -a["volume"])


def policy_usage(db: Session) -> list[dict[str, Any]]:
    base_ids = select(Complaint.id).where(_base())
    rows = db.execute(select(PolicyReference.doc_id, PolicyReference.section_id, PolicyReference.cited_by, func.count())
                      .join(Analysis, Analysis.id == PolicyReference.analysis_id).where(Analysis.complaint_id.in_(base_ids))
                      .group_by(PolicyReference.doc_id, PolicyReference.section_id, PolicyReference.cited_by)).all()
    agg: dict[tuple[str, str], dict[str, Any]] = {}
    for doc, sec, by, n in rows:
        a = agg.setdefault((doc, sec), {"doc_id": doc, "section": sec, "ai": 0, "rule": 0, "retrieval": 0})
        a[by] = a.get(by, 0) + n
    return sorted(agg.values(), key=lambda a: -(a["ai"] + a["rule"]))[:60]


def resolution_times(db: Session, matrix: RuleMatrix) -> list[dict[str, Any]]:
    rows = db.execute(select(Complaint.priority, Complaint.created_at, Complaint.resolved_at).where(_base(), Complaint.resolved_at.is_not(None))).all()
    agg: dict[str, list[float]] = defaultdict(list)
    for prio, created, resolved in rows:
        agg[prio or "n/a"].append((_aware(resolved) - _aware(created)).total_seconds() / 3600)  # type: ignore[operator]
    return [{"priority": p, "count": len(v), "avg_hours": round(sum(v) / len(v), 1),
             "target_hours": matrix.sla_rules[p].resolution_hours if p in matrix.sla_rules else None} for p, v in sorted(agg.items())]


def _latest_update(db: Session, complaint_id: int) -> dict[str, Any] | None:
    from supportnova.api.serializers import CUSTOMER_EVENTS, customer_update
    h = db.execute(select(ComplaintHistory).where(ComplaintHistory.complaint_id == complaint_id,
                                                  ComplaintHistory.event_type.in_(CUSTOMER_EVENTS))
                   .order_by(ComplaintHistory.id.desc())).scalars().first()
    return customer_update(h)


def dashboard(db: Session, matrix: RuleMatrix, user: User) -> dict[str, Any]:
    """Role dashboards (SRS Steps 61-63): each role sees only what its permissions allow."""
    role = user.role_code
    items: list[dict[str, Any]]
    if role == "customer":
        rows = db.execute(select(Complaint).where(Complaint.customer_id == (user.customer_id or -1), _base())
                          .order_by(Complaint.created_at.desc())).scalars().all()
        items = [{"complaint_ref": c.complaint_ref, "title": c.title, "status": c.status, "submitted_at": c.created_at.isoformat(),
                  "department": label(matrix, "department", c.department_code) if c.department_code else None,
                  "latest_update": _latest_update(db, c.id),
                  "resolution_status": "Resolved" if c.status in ("Resolved", "Closed") else
                  ("Waiting for your reply" if c.status == "Awaiting Customer" else "In progress")} for c in rows]
        return {"role": role, "counts": dict(Counter(c.status for c in rows)), "total": len(rows), "items": items}
    out: dict[str, Any] = {"role": role}
    if role == "agent":
        mine = db.execute(select(Complaint).where(Complaint.assigned_agent_id == user.id, Complaint.status.notin_(["Resolved", "Closed"]))
                          .order_by(Complaint.priority.asc().nulls_last(), Complaint.created_at.asc())).scalars().all()
        items = []
        for c in mine[:60]:
            vr = db.execute(select(ValidationResult).where(ValidationResult.complaint_id == c.id)
                            .order_by(ValidationResult.id.desc())).scalars().first()
            vd = (vr.validated_decision if vr else None) or {}
            resp = db.execute(select(CustomerResponse).where(CustomerResponse.complaint_id == c.id)
                              .order_by(CustomerResponse.id.desc())).scalars().first()
            items.append({
                "complaint_ref": c.complaint_ref, "title": c.title, "status": c.status, "created_at": c.created_at.isoformat(),
                "category": label(matrix, "category", c.category_code), "subcategory": label(matrix, "subcategory", c.subcategory_code),
                "priority": c.priority, "urgency": c.urgency, "sentiment": c.sentiment, "verification_status": c.verification_status,
                "verification_score": c.verification_score, "sla_state": c.sla_state, "escalation_level": c.escalation_level,
                "escalation_warning": bool(c.escalation_required), "ai_recommendation": vd.get("summary"),
                "guidance": ((vd.get("agent_guidance") or {}).get("validated") or [])[:3],
                "suggested_response": {"id": resp.id, "status": resp.status, "subject": resp.subject} if resp else None,
                "injection_detected": c.injection_detected})
        out["my_queue"] = {"open": len(mine), "by_priority": dict(Counter(c.priority for c in mine)),
                           "sla_at_risk": sum(c.sla_state in ("At Risk", "Breached") for c in mine),
                           "escalated": sum(bool(c.escalation_required) for c in mine),
                           "needs_review": sum(bool(c.needs_review) for c in mine),
                           "verification": dict(Counter(c.verification_status for c in mine)), "items": items}
        return out
    out["overview"] = overview(db, matrix)
    out["distributions"] = {d: distribution(db, matrix, d) for d in ("category", "department", "priority", "status", "sentiment")}
    if role in ("reviewer", "manager", "admin"):
        out["validation"] = validation_stats(db, matrix)
        pending = db.execute(select(Review).join(Complaint, Complaint.id == Review.complaint_id)
                             .where(Review.status.in_(["pending", "in_review"]), _base())).scalars().all()
        reasons: Counter[str] = Counter()
        for r in pending:
            reasons.update(r.reason_codes or [])
        out["review_queue"] = {"pending": len(pending), "reasons": dict(reasons)}
    if role in ("manager", "admin"):
        out["sla"] = sla_stats(db)
        out["departments"] = department_performance(db, matrix)
        out["alerts"] = trend_alerts(db, matrix)
    if role == "admin":
        out["system"] = {
            "users": db.scalar(select(func.count()).select_from(User)), "documents": db.scalar(select(func.count()).select_from(Document)),
            "document_versions": db.scalar(select(func.count()).select_from(DocumentVersion)),
            "rules": db.scalar(select(func.count()).select_from(RuleRecord).where(RuleRecord.rule_type != "config")),
            "prompts": db.scalar(select(func.count()).select_from(Prompt)), "ruleset_hash": matrix.ruleset_hash,
            "audit_entries": db.scalar(select(func.count()).select_from(AuditLog)),
            "open_escalations": db.scalar(select(func.count()).select_from(Escalation).where(Escalation.status == "open")),
        }
    return out
