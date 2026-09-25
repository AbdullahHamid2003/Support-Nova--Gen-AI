"""Role-aware serialisation of domain objects for the API.

Customers only ever receive customer-safe fields (status, department name, latest update, sent
responses). Internal intelligence - AI output, validation checks, agent guidance, escalation notes,
evidence - is returned only to internal roles.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from supportnova.api.wording import current_wording
from supportnova.database.models import (
    AIRun,
    Analysis,
    Complaint,
    ComplaintHistory,
    CustomerResponse,
    Escalation,
    FollowUp,
    Resolution,
    Review,
    SlaRecord,
    User,
    ValidationResult,
)
from supportnova.rule_engine.models import RuleMatrix


def iso(value: datetime | date | None) -> str | None:
    return value.isoformat() if value else None


CUSTOMER_STATUS_MESSAGES = {
    "New": "We have received your complaint.", "Processing": "Your complaint is being reviewed.",
    "Analyzed": "Your complaint has been reviewed and is being routed to the right team.",
    "Assigned": "A support specialist has been assigned to your complaint.", "In Progress": "We are working on your complaint.",
    "Awaiting Customer": "We need a little more information from you - please reply to our message.",
    "Escalated": "Your complaint has been passed to a specialist team for priority handling.",
    "Resolved": "Your complaint has been resolved.", "Closed": "Your complaint is closed.",
    "Reopened": "Your complaint has been reopened and is being looked at again.",
}
CUSTOMER_EVENTS = ("status.changed", "complaint.submitted", "response.sent", "complaint.clarified")


def customer_update(h: ComplaintHistory | None) -> dict[str, Any] | None:
    """Customer-safe wording for a history event (internal notes, scores and rule IDs never leak)."""
    if h is None:
        return None
    if h.event_type == "response.sent":
        message = "We sent you a response."
    elif h.event_type == "complaint.clarified":
        message = "Thank you - we received the information you provided."
    else:
        message = CUSTOMER_STATUS_MESSAGES.get(h.to_status or "New", "Your complaint has been updated.")
    return {"message": message, "status": h.to_status, "at": iso(h.created_at)}


def user_public(u: User | None) -> dict[str, Any] | None:
    if u is None:
        return None
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "role": u.role_code,
            "department": u.department.code if u.department else None,
            "customer_ref": u.customer.customer_ref if u.customer else None}


def complaint_summary(c: Complaint, matrix: RuleMatrix, *, internal: bool = True) -> dict[str, Any]:
    dept = matrix.departments.get(c.department_code or "")
    sub = matrix.subcategories.get(c.subcategory_code or "")
    cat = matrix.categories.get(c.category_code or "")
    base: dict[str, Any] = {
        "complaint_ref": c.complaint_ref, "title": c.title, "status": c.status, "channel": c.channel,
        "created_at": iso(c.created_at), "updated_at": iso(c.updated_at), "complaint_date": iso(c.complaint_date),
        "department": dept.name if dept else None, "category": cat.name if cat else None,
        "subcategory": sub.name if sub else None, "processing_stage": c.processing_stage,
        "resolved_at": iso(c.resolved_at),
    }
    if not internal:
        return base
    base.update({
        "customer_ref": c.customer.customer_ref if c.customer else None,
        "customer_name": c.customer.full_name if c.customer else None, "customer_type": c.customer_type,
        "category_code": c.category_code, "subcategory_code": c.subcategory_code, "department_code": c.department_code,
        "urgency": c.urgency, "priority": c.priority, "sentiment": c.sentiment, "escalation_level": c.escalation_level,
        "escalation_required": c.escalation_required, "verification_status": c.verification_status,
        "verification_score": c.verification_score, "needs_review": c.needs_review, "sla_state": c.sla_state,
        "is_duplicate": c.is_duplicate, "is_repeat": c.is_repeat, "injection_detected": c.injection_detected,
        "ai_python_agreement": c.ai_python_agreement,
        "assigned_agent": c.assigned_agent.full_name if c.assigned_agent else None, "source": c.source,
        "product_sku": c.product_sku,
    })
    return base


def _latest(db: Session, model: Any, complaint_id: int) -> Any:
    return db.execute(select(model).where(model.complaint_id == complaint_id).order_by(model.id.desc())).scalars().first()


def check_name(matrix: RuleMatrix, code: str, stored: str) -> str:
    """Current display name of a validation check (live validation policy), else the name stored with the result."""
    return str(matrix.validation_check(code).get("name") or stored)


def comparison_view(comparison: dict[str, Any] | None) -> dict[str, Any] | None:
    """The stored AI-vs-rules comparison with each row's explanation in the current wording."""
    if not comparison or not isinstance(comparison.get("rows"), list):
        return comparison
    return {**comparison, "rows": [{**row, "explanation": current_wording(row.get("explanation"))} if isinstance(row, dict) else row
                                  for row in comparison["rows"]]}


def review_reasons_view(matrix: RuleMatrix, reasons: list[Any] | None) -> list[dict[str, Any]]:
    """Review reasons with the current display name of each reason code; the stored snapshot is not changed."""
    names = {r.get("code"): r.get("name") for r in matrix.review_rules}
    return [{**r, "name": names.get(r.get("code")) or r.get("name"), "detail": current_wording(r.get("detail"))}
            for r in reasons or []]


def complaint_detail(db: Session, c: Complaint, matrix: RuleMatrix, user: User) -> dict[str, Any]:
    internal = user.role_code != "customer"
    data = complaint_summary(c, matrix, internal=internal)
    data.update({
        "description": c.description, "supporting_info": c.supporting_info, "product_text": c.product_text,
        "order_ref": c.order_ref, "transaction_ref": c.transaction_ref, "previous_complaint_ref": c.previous_complaint_ref,
        "preferred_contact": c.preferred_contact, "requested_resolution": c.requested_resolution, "requested_tone": c.requested_tone,
        "attachments": [{"file_name": a.file_name, "content_type": a.content_type, "size_bytes": a.size_bytes} for a in c.attachments],
    })
    responses = db.execute(select(CustomerResponse).where(CustomerResponse.complaint_id == c.id)
                           .order_by(CustomerResponse.id.desc())).scalars().all()
    followups = db.execute(select(FollowUp).where(FollowUp.complaint_id == c.id).order_by(FollowUp.due_at)).scalars().all()
    if not internal:
        data["responses"] = [{"subject": r.subject, "body": r.body, "sent_at": iso(r.sent_at)} for r in responses if r.status == "sent"]
        data["follow_ups"] = [{"type": f.type, "due_at": iso(f.due_at), "status": f.status} for f in followups if f.status in ("scheduled", "sent")]
        events = db.execute(select(ComplaintHistory).where(ComplaintHistory.complaint_id == c.id,
                                                           ComplaintHistory.event_type.in_(CUSTOMER_EVENTS))
                            .order_by(ComplaintHistory.id)).scalars().all()
        data["latest_update"] = customer_update(events[-1]) if events else None
        data["updates"] = [u for u in (customer_update(e) for e in events) if u]
        data["resolution_status"] = "Resolved" if c.status in ("Resolved", "Closed") else "In progress"
        return data
    analysis = _latest(db, Analysis, c.id)
    vr = db.execute(select(ValidationResult).where(ValidationResult.complaint_id == c.id).order_by(ValidationResult.id.desc())).scalars().first()
    resolution = _latest(db, Resolution, c.id)
    sla = db.execute(select(SlaRecord).where(SlaRecord.complaint_id == c.id)).scalar_one_or_none()
    escalations = db.execute(select(Escalation).where(Escalation.complaint_id == c.id).order_by(Escalation.id)).scalars().all()
    review = db.execute(select(Review).where(Review.complaint_id == c.id).order_by(Review.id.desc())).scalars().first()
    data["preprocessing"] = c.preprocessing
    data["analysis"] = None
    if analysis is not None:
        data["analysis"] = {
            "id": analysis.id, "version_no": analysis.version_no, "status": analysis.status, "provider": analysis.provider,
            "model": analysis.model, "fault_injection": analysis.fault_injection,
            "prompt_versions": analysis.prompt_versions, "policy_versions": analysis.policy_versions,
            "ruleset_hash": analysis.ruleset_hash, "output": analysis.output, "communication": analysis.communication,
            "retrieval": analysis.retrieval, "stage_timings": analysis.stage_timings, "error": analysis.error,
            "created_at": iso(analysis.created_at), "completed_at": iso(analysis.completed_at), "total_latency_ms": analysis.total_latency_ms,
            "ai_attempts": db.query(AIRun).filter(AIRun.analysis_id == analysis.id).count(),
        }
    data["validation"] = None
    if vr is not None:
        data["validation"] = {
            "id": vr.id, "overall_status": vr.overall_status, "score": vr.verification_score, "decision": vr.decision,
            "dimension_scores": vr.dimension_scores, "review_reasons": review_reasons_view(matrix, vr.review_reasons),
            "counts": vr.counts, "comparison": comparison_view(vr.comparison), "validated_decision": vr.validated_decision,
            "python_expected": vr.python_expected, "ruleset_hash": vr.ruleset_hash,
            "checks": [{"code": ch.code, "name": check_name(matrix, ch.code, ch.name), "dimension": ch.dimension,
                        "severity": ch.severity, "status": ch.status,
                        "message": current_wording(ch.message), "expected": ch.expected, "actual": ch.actual, "rule_refs": ch.rule_refs,
                        "policy_refs": ch.policy_refs} for ch in vr.checks],
        }
    data["resolution"] = ({"ai_steps": resolution.ai_steps, "validated_steps": resolution.validated_steps,
                           "eligibility": resolution.eligibility, "status": resolution.status} if resolution else None)
    data["responses"] = [{"id": r.id, "version_no": r.version_no, "kind": r.kind, "tone": r.tone, "subject": r.subject, "body": r.body,
                          "status": r.status, "source": r.source, "validation": r.validation,
                          "created_at": iso(r.created_at), "sent_at": iso(r.sent_at), "sent_via": r.sent_via} for r in responses]
    data["escalations"] = [{"id": e.id, "level": e.level, "rank": e.rank, "reason": e.reason, "source": e.source, "rule_ids": e.rule_ids,
                            "departments": e.departments, "notes": e.notes, "status": e.status, "created_at": iso(e.created_at)}
                           for e in escalations]
    data["follow_ups"] = [{"id": f.id, "type": f.type, "message": f.message, "due_at": iso(f.due_at), "status": f.status,
                           "source_rule": f.source_rule} for f in followups]
    data["sla"] = ({"priority": sla.priority, "rule_id": sla.rule_id, "started_at": iso(sla.started_at),
                    "first_response_due_at": iso(sla.first_response_due_at), "resolution_due_at": iso(sla.resolution_due_at),
                    "first_response_at": iso(sla.first_response_at), "resolved_at": iso(sla.resolved_at),
                    "response_state": sla.response_state, "resolution_state": sla.resolution_state} if sla else None)
    data["review"] = ({"id": review.id, "status": review.status, "reasons": review_reasons_view(matrix, review.reasons),
                       "final_decision": review.final_decision,
                       "assigned_to": review.assigned_to_id, "created_at": iso(review.created_at),
                       "actions": [{"action": a.action, "comment": a.comment, "actor": a.actor_label, "at": iso(a.created_at),
                                    "payload": a.payload, "before": a.before, "after": a.after} for a in review.actions]}
                      if review else None)
    related = []
    for rid in (c.duplicate_of_id, c.repeat_of_id):
        if rid:
            other = db.get(Complaint, rid)
            if other:
                related.append({"complaint_ref": other.complaint_ref, "relation": "duplicate_of" if rid == c.duplicate_of_id else "repeat_of",
                                "status": other.status, "title": other.title})
    data["related"] = related
    return data


def timeline(db: Session, c: Complaint) -> list[dict[str, Any]]:
    rows = db.execute(select(ComplaintHistory).where(ComplaintHistory.complaint_id == c.id).order_by(ComplaintHistory.id)).scalars()
    return [{"id": h.id, "event_type": h.event_type, "message": current_wording(h.message), "actor": h.actor_label, "from_status": h.from_status,
             "to_status": h.to_status, "data": h.data, "at": iso(h.created_at)} for h in rows]
