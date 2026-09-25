"""Manual review queue and reviewer actions (SRS Steps 57-59, 1.6 lxi-lxiv).

approve | reject | modify | reclassify | reassign | escalate | regenerate | comment.
The original AI output and the original validation result are never modified: every action stores
before/after snapshots with the reviewer identity and timestamp, and is written to the audit trail.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from supportnova.audit import service as audit
from supportnova.core.errors import NotFound, PermissionDenied, ValidationFailed
from supportnova.core.timeutil import utcnow
from supportnova.database.models import (
    Complaint,
    CustomerResponse,
    Escalation,
    Review,
    ReviewAction,
    User,
)
from supportnova.services.pipeline import history_event, set_status
from supportnova.services.rules import rule_service

ACTIONS = ("approve", "reject", "modify", "reclassify", "reassign", "escalate", "regenerate", "comment")
_EDITABLE = ("department_code", "urgency", "priority", "escalation_level", "sentiment")
# timeline wording for each reviewer action (the event type stays "review.<action>")
_ACTION_TEXT = {"approve": "approved the decision", "reject": "rejected the draft response", "modify": "corrected the decision",
                "reclassify": "reclassified the complaint", "reassign": "reassigned the complaint",
                "escalate": "escalated the complaint", "regenerate": "asked for a new response", "comment": "added a comment"}


def _snapshot(c: Complaint) -> dict[str, Any]:
    return {"status": c.status, "verification_status": c.verification_status, "category": c.category_code,
            "subcategory": c.subcategory_code, "department": c.department_code, "urgency": c.urgency, "priority": c.priority,
            "escalation_level": c.escalation_level, "escalation_required": c.escalation_required,
            "assigned_agent_id": c.assigned_agent_id, "sentiment": c.sentiment}


def get_review(db: Session, review_id: int) -> Review:
    review = db.get(Review, review_id)
    if review is None:
        raise NotFound(f"Review {review_id} not found.")
    return review


def claim(db: Session, review: Review, user: User) -> Review:
    if review.status == "completed":
        raise ValidationFailed("This review is already completed.")
    review.assigned_to_id = user.id
    review.status = "in_review"
    review.started_at = review.started_at or utcnow()
    db.add(ReviewAction(review_id=review.id, action="comment", comment=f"Claimed by {user.full_name}.", actor_id=user.id,
                        actor_label=user.full_name))
    audit.record(db, action="review.claimed", entity_type="review", entity_id=review.id, actor=user,
                 summary=f"Review {review.id} claimed")
    return review


def act(db: Session, review: Review, user: User, *, action: str, payload: dict[str, Any] | None = None,
        comment: str = "") -> dict[str, Any]:
    """Apply a reviewer action; returns follow-up work for the caller (e.g. reprocessing)."""
    if action not in ACTIONS:
        raise ValidationFailed(f"Unknown review action '{action}'.")
    if "review:act" not in user.permissions:
        raise PermissionDenied("Only reviewers, managers and administrators can act on reviews.")
    if review.status == "completed" and action not in ("comment",):
        raise ValidationFailed("This review is already completed.")
    payload = payload or {}
    complaint = db.get(Complaint, review.complaint_id)
    assert complaint is not None
    matrix = rule_service.matrix(db)
    before = _snapshot(complaint)
    followup: dict[str, Any] = {}
    if action in ("reject", "modify", "reclassify", "reassign") and not comment.strip():
        raise ValidationFailed("A comment explaining the decision is required for this action.")

    if action == "approve":
        complaint.verification_status = "Human Verified"
        complaint.needs_review = False
        for resp in db.execute(select(CustomerResponse).where(CustomerResponse.complaint_id == complaint.id,
                                                              CustomerResponse.status == "requires_review")).scalars():
            resp.status = "approved"
            resp.approved_by_id, resp.approved_at = user.id, utcnow()
        review.status, review.final_decision, review.completed_at = "completed", "approved", utcnow()
    elif action == "reject":
        for resp in db.execute(select(CustomerResponse).where(CustomerResponse.complaint_id == complaint.id,
                                                              CustomerResponse.status.in_(["requires_review", "ready"]))).scalars():
            resp.status = "rejected"
        review.final_decision = "rejected"
        review.status = "in_review"
    elif action == "modify":
        changes = {k: v for k, v in (payload.get("fields") or {}).items() if k in _EDITABLE and v not in (None, "")}
        if "department_code" in changes and changes["department_code"] not in matrix.departments:
            raise ValidationFailed("Unknown department.")
        if "priority" in changes and changes["priority"] not in ("P0", "P1", "P2", "P3"):
            raise ValidationFailed("Invalid priority.")
        if "urgency" in changes and changes["urgency"] not in ("Low", "Medium", "High", "Critical"):
            raise ValidationFailed("Invalid urgency.")
        for k, v in changes.items():
            setattr(complaint, k, v)
        body = (payload.get("response_body") or "").strip()
        if body:
            latest = db.execute(select(CustomerResponse).where(CustomerResponse.complaint_id == complaint.id)
                                .order_by(CustomerResponse.version_no.desc(), CustomerResponse.id.desc())).scalars().first()
            validation = validate_edited_response(db, complaint, body, tone=payload.get("tone") or (latest.tone if latest else "professional"))
            db.add(CustomerResponse(complaint_id=complaint.id, analysis_id=latest.analysis_id if latest else None,
                                    version_no=(latest.version_no + 1) if latest else 1, kind="response",
                                    tone=payload.get("tone") or (latest.tone if latest else "professional"),
                                    subject=(latest.subject if latest else f"Update on your complaint {complaint.complaint_ref}"),
                                    body=body, source="reviewer",
                                    status="approved" if validation["ok"] else "requires_review", validation=validation,
                                    approved_by_id=user.id if validation["ok"] else None,
                                    approved_at=utcnow() if validation["ok"] else None))
            followup["response_validation"] = validation
        review.final_decision = "modified"
        if payload.get("complete", True):
            review.status, review.completed_at = "completed", utcnow()
            complaint.verification_status = "Human Verified"
            complaint.needs_review = False
    elif action == "reclassify":
        sub = payload.get("subcategory")
        if sub not in matrix.subcategories:
            raise ValidationFailed("Choose a valid subcategory.")
        review.final_decision = "reclassified"
        review.status, review.completed_at = "completed", utcnow()
        followup["reprocess"] = {"classification_override": sub, "trigger": "reclassification"}
    elif action == "reassign":
        dept = payload.get("department_code")
        if dept:
            if dept not in matrix.departments:
                raise ValidationFailed("Unknown department.")
            complaint.department_code = dept
        agent_id = payload.get("agent_id")
        if agent_id:
            agent = db.get(User, int(agent_id))
            if agent is None or agent.role_code != "agent":
                raise ValidationFailed("Choose a valid agent.")
            complaint.assigned_agent_id = agent.id
            if complaint.status in ("Analyzed", "New"):
                set_status(db, complaint, "Assigned", actor=user, note=f"Reassigned to {agent.full_name}.")
        review.final_decision = "reassigned"
    elif action == "escalate":
        level = payload.get("level")
        if level not in {lv.name for lv in matrix.escalation_levels} or level == "No Escalation":
            raise ValidationFailed("Choose an escalation level.")
        dept_codes = payload.get("departments") or [complaint.department_code]
        db.add(Escalation(complaint_id=complaint.id, level=level, rank=matrix.level_rank(level), reason=comment or "Reviewer escalation",
                          source="reviewer", rule_ids=[], departments=[d for d in dept_codes if d], notes={"reviewer_note": comment},
                          status="open", created_by_id=user.id))
        complaint.escalation_required = True
        if matrix.level_rank(level) > matrix.level_rank(complaint.escalation_level):
            complaint.escalation_level = level
        if complaint.status not in ("Resolved", "Closed"):
            set_status(db, complaint, "Escalated", actor=user, note=f"Escalated by reviewer to {level}.")
        review.final_decision = "escalated"
    elif action == "regenerate":
        tone = payload.get("tone")
        followup["reprocess"] = {"tone": tone, "trigger": "regenerate"}
        review.final_decision = "regenerated"
        review.status, review.completed_at = "completed", utcnow()
    after = _snapshot(complaint)
    db.add(ReviewAction(review_id=review.id, action=action, payload=payload, comment=comment, before=before, after=after,
                        actor_id=user.id, actor_label=user.full_name))
    if review.status == "completed":
        review.final_snapshot = {"decision": review.final_decision, "complaint": after, "by": user.email, "at": utcnow().isoformat()}
    history_event(db, complaint, f"review.{action}", f"Reviewer {_ACTION_TEXT.get(action, action)}" + (f": {comment}" if comment else "."),
                  actor=user, data={"payload": payload})
    audit.record(db, action=f"review.{action}", entity_type="complaint", entity_id=complaint.complaint_ref, actor=user,
                 summary=f"Review {review.id}: {action}", details={"before": before, "after": after, "payload": payload,
                                                                   "comment": comment})
    db.flush()
    return followup


def validate_edited_response(db: Session, complaint: Complaint, body: str, *, tone: str) -> dict[str, Any]:
    """Human-edited responses go through the same unsupported-promise / prohibited-behaviour checks."""
    from supportnova.database.models import ValidationResult
    from supportnova.hallucination_checks import promises

    matrix = rule_service.matrix(db)
    vr = db.execute(select(ValidationResult).where(ValidationResult.complaint_id == complaint.id)
                    .order_by(ValidationResult.id.desc())).scalars().first()
    validated = vr.validated_decision if vr else {}
    elig = validated.get("eligibility", {})
    findings = promises.promise_findings(matrix, body, {"refund": elig.get("refund"), "compensation": elig.get("compensation")})
    findings += promises.prohibited_behaviour(matrix, body, exclude=("PROMISE_REFUND_BEFORE_VERIFICATION", "GUARANTEE_COMPENSATION",
                                                                     "CASH_COMPENSATION", "GRANT_POLICY_EXCEPTION"))
    timeline, seen = promises.timeline_findings(matrix, body, validated.get("timelines", []))
    tone_issues = promises.tone_findings(matrix, body, tone)
    issues = [{"code": f.code, "severity": f.severity, "text": f.text, "message": f.message} for f in findings + timeline]
    return {"ok": not issues, "issues": issues, "tone": [f.message for f in tone_issues], "timelines": seen}


def queue(db: Session, *, status: str | None = None, reason: str | None = None, assigned_to: int | None = None,
          include_lab: bool = False, limit: int = 50, offset: int = 0) -> tuple[list[Review], int]:
    """Review queue, most urgent first. Adversarial-lab cases are shown only on request."""
    sources = ["web", "api", "dataset", "lab"] if include_lab else ["web", "api", "dataset"]
    q = select(Review).join(Complaint, Complaint.id == Review.complaint_id).where(Complaint.source.in_(sources))
    q = q.where(Review.status == status) if status else q.where(Review.status.in_(["pending", "in_review"]))
    if assigned_to:
        q = q.where(Review.assigned_to_id == assigned_to)
    rows = db.execute(q.order_by(Review.priority.asc().nulls_last(), Review.created_at.asc())).scalars().all()
    if reason:
        rows = [r for r in rows if reason in (r.reason_codes or [])]
    return list(rows[offset: offset + limit]), len(rows)

