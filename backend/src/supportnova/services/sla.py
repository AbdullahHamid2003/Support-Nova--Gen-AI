"""SLA tracking and risk detection (SRS Steps 55-56; SLA-RUL-15 s3, s7). Targets and the at-risk
threshold are configuration (Rule Matrix), so "modify an SLA" is a data change."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from supportnova.audit import service as audit
from supportnova.core.timeutil import utcnow
from supportnova.database.models import Complaint, ComplaintHistory, Escalation, SlaRecord
from supportnova.rule_engine.models import RuleMatrix

OPEN_STATES = ("New", "Processing", "Analyzed", "Assigned", "In Progress", "Awaiting Customer", "Escalated", "Reopened")


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    from datetime import UTC
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def ensure_sla(db: Session, complaint: Complaint, priority: str, matrix: RuleMatrix) -> SlaRecord | None:
    rule = matrix.sla_rules.get(priority)
    if not rule:
        return None
    record = db.execute(select(SlaRecord).where(SlaRecord.complaint_id == complaint.id)).scalar_one_or_none()
    started = _aware(complaint.created_at) or utcnow()
    if record is None:
        record = SlaRecord(complaint_id=complaint.id, priority=priority, rule_id=rule.rule_id, started_at=started,
                           first_response_due_at=started + timedelta(hours=rule.first_response_hours),
                           resolution_due_at=started + timedelta(hours=rule.resolution_hours))
        db.add(record)
    elif record.priority != priority:
        record.priority, record.rule_id = priority, rule.rule_id
        record.first_response_due_at = started + timedelta(hours=rule.first_response_hours)
        record.resolution_due_at = started + timedelta(hours=rule.resolution_hours)
    evaluate(record, matrix, utcnow())
    complaint.sla_state = record.resolution_state
    db.flush()
    return record


def _state(start: datetime, due: datetime, done: datetime | None, now: datetime, at_risk_pct: float) -> str:
    if done is not None:
        return "Met" if done <= due else "Breached"
    if now > due:
        return "Breached"
    total = (due - start).total_seconds() or 1
    return "At Risk" if (now - start).total_seconds() / total >= at_risk_pct / 100 else "On Track"


def evaluate(record: SlaRecord, matrix: RuleMatrix, now: datetime) -> None:
    pct = float(matrix.param("sla_at_risk_pct"))
    start = _aware(record.started_at) or now
    record.response_state = _state(start, _aware(record.first_response_due_at) or now, _aware(record.first_response_at), now, pct)
    record.resolution_state = _state(start, _aware(record.resolution_due_at) or now, _aware(record.resolved_at), now, pct)
    if record.resolution_state == "At Risk" and record.at_risk_flagged_at is None:
        record.at_risk_flagged_at = now
    if record.resolution_state == "Breached" and record.breached_at is None:
        record.breached_at = now


def refresh_all(db: Session, matrix: RuleMatrix, *, now: datetime | None = None) -> dict[str, int]:
    """Periodic SLA monitor: update states and enforce ESC-039 (P0/P1 breach -> Department Manager)."""
    now = now or utcnow()
    rows = db.execute(select(SlaRecord, Complaint).join(Complaint, Complaint.id == SlaRecord.complaint_id)
                      .where(Complaint.status.in_(OPEN_STATES), Complaint.source.in_(("web", "api", "dataset")))).all()
    counts = {"checked": 0, "at_risk": 0, "breached": 0, "escalated": 0}
    esc_rule = next((e for e in matrix.escalation_rules if e.rule_id == "ESC-039" and e.is_active), None)
    for record, complaint in rows:
        before = record.resolution_state
        evaluate(record, matrix, now)
        complaint.sla_state = record.resolution_state
        counts["checked"] += 1
        counts["at_risk"] += record.resolution_state == "At Risk"
        counts["breached"] += record.resolution_state == "Breached"
        if before != record.resolution_state and record.resolution_state in ("At Risk", "Breached"):
            db.add(ComplaintHistory(complaint_id=complaint.id, event_type=f"sla.{record.resolution_state.lower().replace(' ', '_')}",
                                    actor_label="SLA monitor", message=f"SLA {record.resolution_state} ({record.priority}, due "
                                    f"{record.resolution_due_at:%Y-%m-%d %H:%M} UTC)."))
        if (esc_rule and record.resolution_state == "Breached" and not record.breach_escalated
                and record.priority in ("P0", "P1")):
            record.breach_escalated = True
            db.add(Escalation(complaint_id=complaint.id, level=esc_rule.level, rank=matrix.level_rank(esc_rule.level),
                              reason=esc_rule.reason, source="sla", rule_ids=[esc_rule.rule_id],
                              departments=[complaint.department_code or "", "DEPT-MGT"], status="open"))
            complaint.escalation_required = True
            if matrix.level_rank(esc_rule.level) > matrix.level_rank(complaint.escalation_level):
                complaint.escalation_level = esc_rule.level
            audit.record(db, action="complaint.sla_breach_escalated", entity_type="complaint", entity_id=complaint.complaint_ref,
                         summary=f"SLA breached on {record.priority}: escalated to {esc_rule.level} ({esc_rule.rule_id}).",
                         actor_label="SLA monitor")
            counts["escalated"] += 1
    db.flush()
    return counts
