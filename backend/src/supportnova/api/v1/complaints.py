"""Complaint endpoints: submission, search & filtering, detail, pipeline progress, lifecycle, responses."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy import and_, asc, desc, func, or_, select, true
from sqlalchemy.orm import Session

from supportnova.api.deps import current_user, db_session, require
from supportnova.api.serializers import complaint_detail, complaint_summary, iso, timeline
from supportnova.audit import service as audit
from supportnova.core.errors import NotFound, PermissionDenied, ValidationFailed
from supportnova.core.timeutil import utcnow
from supportnova.database.models import (
    AIRun,
    Analysis,
    Complaint,
    Customer,
    CustomerResponse,
    Escalation,
    FollowUp,
    SlaRecord,
    User,
    ValidationResult,
)
from supportnova.services import complaints as svc
from supportnova.services.pipeline import STAGES, PipelineOptions, history_event, set_status
from supportnova.services.rules import rule_service
from supportnova.services.worker import worker

OPERATIONAL_SOURCES = ("web", "api", "dataset")
router = APIRouter(tags=["complaints"])


class ComplaintIn(BaseModel):
    title: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=10000)
    customer_type: str | None = None
    channel: str | None = "web_form"
    product_text: str | None = Field(default="", max_length=200)
    order_ref: str | None = None
    transaction_ref: str | None = None
    previous_complaint_ref: str | None = None
    preferred_contact: str | None = "email"
    requested_resolution: str | None = "none"
    requested_tone: str | None = "professional"
    supporting_info: str | None = Field(default="", max_length=6000)
    complaint_date: date | None = None
    customer_ref: str | None = None   # internal roles submitting on behalf of a customer


def _resolve_customer(db: Session, user: User, customer_ref: str | None) -> Customer | None:
    if user.role_code == "customer":
        if not user.customer_id:
            raise PermissionDenied("Your account is not linked to a customer profile.")
        return db.get(Customer, user.customer_id)
    if customer_ref:
        cust = db.execute(select(Customer).where(Customer.customer_ref == customer_ref.upper())).scalar_one_or_none()
        if cust is None:
            raise ValidationFailed("Please correct the highlighted fields.",
                                   details=[{"field": "customer_ref", "message": "Customer not found."}])
        return cust
    return None


def _complaint_in(raw: dict[str, Any]) -> dict[str, Any]:
    """Schema-level checks (types, hard length caps) as 422 field errors - never an unhandled 500."""
    try:
        return ComplaintIn(**raw).model_dump()
    except PydanticValidationError as exc:
        details = [{"field": str(e["loc"][0]) if e["loc"] else "body", "message": e["msg"]} for e in exc.errors()]
        raise ValidationFailed("Please correct the highlighted fields.", details=details) from None


async def _parse_submission(request: Request) -> tuple[dict[str, Any], list[tuple[str, bytes]]]:
    ctype = request.headers.get("content-type", "")
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        data: dict[str, Any] = {k: v for k, v in form.items() if isinstance(v, str)}
        files: list[tuple[str, bytes]] = []
        for key, value in form.multi_items():
            if key == "attachments" and isinstance(value, UploadFile) and value.filename:
                files.append((value.filename, await value.read()))
        return _complaint_in(data), files
    try:
        body = await request.json()
    except ValueError:
        raise ValidationFailed("The request body is not valid JSON.") from None
    if not isinstance(body, dict):
        raise ValidationFailed("The request body must be a JSON object.")
    return _complaint_in(body), []


def _submission_for(db: Session, user: User, data: dict[str, Any]) -> Customer | None:
    """Resolve the customer and apply profile defaults - shared by submit and the live precheck so both agree."""
    customer = _resolve_customer(db, user, data.pop("customer_ref", None))
    if customer is not None and not data.get("customer_type"):
        data["customer_type"] = customer.customer_type
    return customer


@router.post("/complaints", status_code=202)
async def submit_complaint(request: Request, user: User = Depends(require("complaint:create")),
                           db: Session = Depends(db_session)) -> dict[str, Any]:
    data, files = await _parse_submission(request)
    customer = _submission_for(db, user, data)
    complaint = svc.create_complaint(db, data, submitted_by=user, customer=customer, attachments=files, source="web")
    db.commit()
    worker.submit(complaint.id, PipelineOptions(trigger="submission", actor_id=user.id))
    return {"complaint_ref": complaint.complaint_ref, "status": complaint.status, "processing_stage": complaint.processing_stage}


@router.post("/complaints/validate")
async def validate_complaint(request: Request, user: User = Depends(require("complaint:create")),
                             db: Session = Depends(db_session)) -> dict[str, Any]:
    """Live form validation + duplicate preview (no complaint is created)."""
    data, _ = await _parse_submission(request)
    customer = _submission_for(db, user, data)
    errors = svc.validate_submission(db, data, customer=customer)
    duplicate = None
    if customer is not None and data.get("title") and data.get("description"):
        from supportnova.security.sanitization import normalize_text, text_hash
        digest = text_hash(f"{data['title']}\n{normalize_text(data['description'])}")
        dup = db.execute(select(Complaint.complaint_ref).where(Complaint.customer_id == customer.id, Complaint.text_hash == digest)).first()
        duplicate = dup[0] if dup else None
    return {"valid": not errors, "errors": errors, "duplicate_of": duplicate}


SORTABLE = {"created_at": Complaint.created_at, "priority": Complaint.priority, "status": Complaint.status,
            "verification_score": Complaint.verification_score, "complaint_ref": Complaint.complaint_ref,
            "updated_at": Complaint.updated_at, "urgency": Complaint.urgency}


@router.get("/complaints")
def list_complaints(
    q: str | None = None, status: list[str] | None = Query(default=None), category: list[str] | None = Query(default=None),
    subcategory: str | None = None, department: list[str] | None = Query(default=None), priority: list[str] | None = Query(default=None),
    urgency: list[str] | None = Query(default=None), sentiment: list[str] | None = Query(default=None),
    verification: list[str] | None = Query(default=None), escalated: bool | None = None, sla: list[str] | None = Query(default=None),
    channel: str | None = None, customer_ref: str | None = None, date_from: date | None = None, date_to: date | None = None,
    needs_review: bool | None = None, assigned_to_me: bool = False, repeat: bool | None = None, duplicate: bool | None = None,
    injection: bool | None = None, source: str | None = None, sort: str = "created_at", order: str = "desc",
    page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=200),
    user: User = Depends(current_user), db: Session = Depends(db_session),
) -> dict[str, Any]:
    matrix = rule_service.matrix(db)
    conds = []
    if user.role_code == "customer":
        conds.append(Complaint.customer_id == (user.customer_id or -1))
        conds.append(Complaint.source.in_(OPERATIONAL_SOURCES))
    elif "complaint:read_all" not in user.permissions:
        raise PermissionDenied("You do not have access to complaints.")
    if q:
        like = f"%{q.strip().lower()}%"
        conds.append(or_(func.lower(Complaint.complaint_ref).like(like), func.lower(Complaint.title).like(like),
                         func.lower(Complaint.order_ref).like(like),
                         Complaint.customer_id.in_(select(Customer.id).where(or_(func.lower(Customer.customer_ref).like(like),
                                                                                 func.lower(Customer.full_name).like(like))))))
    for values, col in ((status, Complaint.status), (category, Complaint.category_code), (department, Complaint.department_code),
                        (priority, Complaint.priority), (urgency, Complaint.urgency), (sentiment, Complaint.sentiment),
                        (verification, Complaint.verification_status), (sla, Complaint.sla_state)):
        if values:
            conds.append(col.in_(values))
    if subcategory:
        conds.append(Complaint.subcategory_code == subcategory)
    if escalated is not None:
        conds.append(Complaint.escalation_required.is_(escalated))
    if channel:
        conds.append(Complaint.channel == channel)
    if customer_ref:
        conds.append(Complaint.customer_id.in_(select(Customer.id).where(Customer.customer_ref == customer_ref.upper())))
    if date_from:
        conds.append(Complaint.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        conds.append(Complaint.created_at < datetime.combine(date_to + timedelta(days=1), datetime.min.time()))
    if needs_review is not None:
        conds.append(Complaint.needs_review.is_(needs_review))
    if assigned_to_me:
        conds.append(Complaint.assigned_agent_id == user.id)
    if repeat is not None:
        conds.append(Complaint.is_repeat.is_(repeat))
    if duplicate is not None:
        conds.append(Complaint.is_duplicate.is_(duplicate))
    if injection is not None:
        conds.append(Complaint.injection_detected.is_(injection))
    if source and user.role_code != "customer":
        conds.append(Complaint.source == source)
    elif user.role_code != "customer":
        conds.append(Complaint.source.in_(OPERATIONAL_SOURCES))  # lab / evaluation cases only on explicit request
    where = and_(*conds) if conds else true()
    total = db.scalar(select(func.count()).select_from(Complaint).where(where)) or 0
    column = SORTABLE.get(sort, Complaint.created_at)
    rows = db.execute(select(Complaint).where(where).order_by(desc(column) if order == "desc" else asc(column), desc(Complaint.id))
                      .offset((page - 1) * page_size).limit(page_size)).scalars().all()
    internal = user.role_code != "customer"
    return {"items": [complaint_summary(c, matrix, internal=internal) for c in rows], "total": total, "page": page, "page_size": page_size}


def _load(db: Session, ref: str, user: User) -> Complaint:
    complaint = svc.get_complaint(db, ref)
    svc.ensure_can_view(complaint, user)
    return complaint


@router.get("/complaints/{ref}")
def get_complaint(ref: str, user: User = Depends(current_user), db: Session = Depends(db_session)) -> dict[str, Any]:
    complaint = _load(db, ref, user)
    return complaint_detail(db, complaint, rule_service.matrix(db), user)


@router.get("/complaints/{ref}/pipeline")
def pipeline_progress(ref: str, user: User = Depends(current_user), db: Session = Depends(db_session)) -> dict[str, Any]:
    complaint = _load(db, ref, user)
    analysis = db.execute(select(Analysis).where(Analysis.complaint_id == complaint.id).order_by(Analysis.id.desc())).scalars().first()
    stage = complaint.processing_stage
    order = STAGES.index(stage) if stage in STAGES else -1
    progress = {"complaint_ref": complaint.complaint_ref, "stage": stage, "status": complaint.status,
                "done": stage in ("completed", "failed"), "failed": stage == "failed",
                "stages": [{"key": s, "state": "done" if (i < order or stage == "completed") else "active" if i == order else "pending"}
                           for i, s in enumerate(STAGES[1:-1], start=1)]}
    if user.role_code == "customer":  # customers see progress only, never validation internals
        return progress
    return {**progress, "verification_status": complaint.verification_status, "score": complaint.verification_score,
            "timings": analysis.stage_timings if analysis else {}, "provider": analysis.provider if analysis else None,
            "model": analysis.model if analysis else None}


@router.get("/complaints/{ref}/timeline")
def complaint_timeline(ref: str, user: User = Depends(require("complaint:read_all")), db: Session = Depends(db_session)) -> dict[str, Any]:
    complaint = _load(db, ref, user)
    from supportnova.database.models import AuditLog
    audits = db.execute(select(AuditLog).where(AuditLog.entity_id == complaint.complaint_ref).order_by(AuditLog.id)).scalars().all()
    return {"events": timeline(db, complaint),
            "audit": [{"id": a.id, "action": a.action, "summary": a.summary, "actor": a.actor_label, "role": a.actor_role,
                       "at": iso(a.created_at), "hash": a.hash[:12], "details": a.details} for a in audits]}


@router.get("/complaints/{ref}/ai-runs")
def complaint_ai_runs(ref: str, user: User = Depends(require("complaint:read_all")), db: Session = Depends(db_session)) -> dict[str, Any]:
    complaint = _load(db, ref, user)
    runs = db.execute(select(AIRun).where(AIRun.complaint_id == complaint.id).order_by(AIRun.id)).scalars().all()
    return {"items": [{"id": r.id, "analysis_id": r.analysis_id, "stage": r.stage, "attempt": r.attempt, "provider": r.provider,
                       "model": r.model, "prompt": f"{r.prompt_key}@{r.prompt_version}", "parsed_ok": r.parsed_ok,
                       "error_type": r.error_type, "error_message": r.error_message, "latency_ms": r.latency_ms,
                       "input_tokens": r.input_tokens, "output_tokens": r.output_tokens, "fault_injection": r.fault_injection,
                       "request": r.request, "response_text": r.response_text, "at": iso(r.created_at)} for r in runs]}


@router.get("/complaints/{ref}/analyses")
def complaint_analyses(ref: str, user: User = Depends(require("complaint:read_all")), db: Session = Depends(db_session)) -> dict[str, Any]:
    complaint = _load(db, ref, user)
    rows = db.execute(select(Analysis).where(Analysis.complaint_id == complaint.id).order_by(Analysis.version_no)).scalars().all()
    return {"items": [{"id": a.id, "version_no": a.version_no, "trigger": a.trigger, "status": a.status, "provider": a.provider,
                       "model": a.model, "fault_injection": a.fault_injection,
                       "prompt_versions": a.prompt_versions, "created_at": iso(a.created_at),
                       "total_latency_ms": a.total_latency_ms} for a in rows]}


class ReprocessIn(BaseModel):
    tone: str | None = None
    fault_profile: str | None = None


@router.post("/complaints/{ref}/reprocess", status_code=202)
def reprocess(ref: str, body: ReprocessIn, user: User = Depends(require("complaint:reprocess")),
              db: Session = Depends(db_session)) -> dict[str, Any]:
    complaint = _load(db, ref, user)
    if complaint.status in ("Closed",):
        raise ValidationFailed("Closed complaints cannot be reprocessed; reopen it first.")
    if body.fault_profile and "lab:use" not in user.permissions:
        raise PermissionDenied("Fault injection is restricted to the adversarial lab.")
    complaint.processing_stage = "queued"
    audit.record(db, action="complaint.reprocess_requested", entity_type="complaint", entity_id=complaint.complaint_ref, actor=user,
                 summary="Reprocessing requested", details=body.model_dump())
    db.commit()
    worker.submit(complaint.id, PipelineOptions(trigger="reprocess", actor_id=user.id, tone=body.tone, fault_profile=body.fault_profile))
    return {"complaint_ref": complaint.complaint_ref, "processing_stage": "queued"}


class StatusIn(BaseModel):
    status: str
    note: str = Field(default="", max_length=1000)


@router.post("/complaints/{ref}/status")
def change_status(ref: str, body: StatusIn, user: User = Depends(current_user), db: Session = Depends(db_session)) -> dict[str, Any]:
    complaint = _load(db, ref, user)
    if user.role_code == "customer":
        if body.status != "Reopened":
            raise PermissionDenied("Customers can only reopen resolved complaints.")
    elif "complaint:update" not in user.permissions:
        raise PermissionDenied("You cannot change complaint status.")
    svc.transition(db, complaint, body.status, actor=user, note=body.note)
    db.commit()
    if body.status == "Reopened":
        worker.submit(complaint.id, PipelineOptions(trigger="reopened", actor_id=user.id, link_duplicates=False))
    return {"complaint_ref": complaint.complaint_ref, "status": complaint.status}


class AssignIn(BaseModel):
    agent_id: int | None = None


@router.post("/complaints/{ref}/assign")
def assign(ref: str, body: AssignIn, user: User = Depends(require("complaint:update")), db: Session = Depends(db_session)) -> dict[str, Any]:
    complaint = _load(db, ref, user)
    agent = db.get(User, body.agent_id) if body.agent_id else user
    if agent is None or agent.role_code not in ("agent", "reviewer", "manager", "admin"):
        raise ValidationFailed("Choose a valid staff member.")
    complaint.assigned_agent_id = agent.id
    history_event(db, complaint, "complaint.assigned", f"Assigned to {agent.full_name}.", actor=user)
    if complaint.status == "Analyzed":
        set_status(db, complaint, "Assigned", actor=user)
    audit.record(db, action="complaint.assigned", entity_type="complaint", entity_id=complaint.complaint_ref, actor=user,
                 summary=f"Assigned to {agent.email}")
    db.commit()
    return {"complaint_ref": complaint.complaint_ref, "assigned_agent": agent.full_name, "status": complaint.status}


class EscalateIn(BaseModel):
    level: str
    reason: str = Field(min_length=5, max_length=1000)


@router.post("/complaints/{ref}/escalate")
def escalate(ref: str, body: EscalateIn, user: User = Depends(require("escalation:create")), db: Session = Depends(db_session)) -> dict[str, Any]:
    complaint = _load(db, ref, user)
    matrix = rule_service.matrix(db)
    if body.level not in {lv.name for lv in matrix.escalation_levels} or body.level == "No Escalation":
        raise ValidationFailed("Choose a valid escalation level.")
    db.add(Escalation(complaint_id=complaint.id, level=body.level, rank=matrix.level_rank(body.level), reason=body.reason,
                      source="agent", rule_ids=[], departments=[complaint.department_code or ""], notes={"note": body.reason},
                      status="open", created_by_id=user.id))
    complaint.escalation_required = True
    if matrix.level_rank(body.level) > matrix.level_rank(complaint.escalation_level):
        complaint.escalation_level = body.level
    if complaint.status not in ("Resolved", "Closed", "Escalated"):
        set_status(db, complaint, "Escalated", actor=user, note=f"Manually escalated to {body.level}.")
    audit.record(db, action="complaint.escalated", entity_type="complaint", entity_id=complaint.complaint_ref, actor=user,
                 summary=f"Escalated to {body.level}", details={"reason": body.reason})
    db.commit()
    return {"complaint_ref": complaint.complaint_ref, "escalation_level": complaint.escalation_level, "status": complaint.status}


@router.post("/complaints/{ref}/responses/{response_id}/send")
def send_response(ref: str, response_id: int, user: User = Depends(require("complaint:respond")),
                  db: Session = Depends(db_session)) -> dict[str, Any]:
    """Records the customer message as sent via the preferred contact channel (simulated delivery -
    no live email/SMS integration, SRS 1.4)."""
    complaint = _load(db, ref, user)
    resp = db.get(CustomerResponse, response_id)
    if resp is None or resp.complaint_id != complaint.id:
        raise NotFound("Response not found.")
    if resp.status not in ("ready", "approved"):
        raise ValidationFailed("This response has not passed validation or reviewer approval and cannot be sent.",
                               details={"status": resp.status})
    now = utcnow()
    resp.status, resp.sent_at, resp.sent_via = "sent", now, complaint.preferred_contact
    sla = db.execute(select(SlaRecord).where(SlaRecord.complaint_id == complaint.id)).scalar_one_or_none()
    if sla is not None and sla.first_response_at is None:
        sla.first_response_at = now
    vr = db.execute(select(ValidationResult).where(ValidationResult.complaint_id == complaint.id).order_by(ValidationResult.id.desc())).scalars().first()
    blocking = any(m.get("blocking") for m in ((vr.validated_decision or {}).get("missing_information", []) if vr else []))
    if blocking and complaint.status in ("Analyzed", "Assigned", "In Progress"):
        set_status(db, complaint, "Awaiting Customer", actor=user, note="Clarification requested from the customer.")
    elif complaint.status in ("Analyzed", "Assigned"):
        set_status(db, complaint, "In Progress", actor=user, note="Response sent to the customer.")
    history_event(db, complaint, "response.sent", f"Response v{resp.version_no} sent via {resp.sent_via} (simulated delivery).", actor=user)
    audit.record(db, action="response.sent", entity_type="complaint", entity_id=complaint.complaint_ref, actor=user,
                 summary=f"Response {resp.id} sent", details={"subject": resp.subject, "via": resp.sent_via})
    db.commit()
    return {"response_id": resp.id, "status": resp.status, "complaint_status": complaint.status}


class ResponseEditIn(BaseModel):
    body: str = Field(min_length=20, max_length=6000)
    tone: str | None = None


@router.post("/complaints/{ref}/responses/{response_id}/edit")
def edit_response(ref: str, response_id: int, body: ResponseEditIn, user: User = Depends(require("complaint:respond")),
                  db: Session = Depends(db_session)) -> dict[str, Any]:
    """Human edits create a new response version and are validated by the same promise checks."""
    from supportnova.services.reviews import validate_edited_response
    complaint = _load(db, ref, user)
    base = db.get(CustomerResponse, response_id)
    if base is None or base.complaint_id != complaint.id:
        raise NotFound("Response not found.")
    tone = body.tone or base.tone
    validation = validate_edited_response(db, complaint, body.body, tone=tone)
    latest = db.scalar(select(func.max(CustomerResponse.version_no)).where(CustomerResponse.complaint_id == complaint.id)) or 0
    new = CustomerResponse(complaint_id=complaint.id, analysis_id=base.analysis_id, version_no=latest + 1, kind=base.kind, tone=tone,
                           subject=base.subject, body=body.body, source="agent",
                           status="ready" if validation["ok"] and not complaint.needs_review else "requires_review", validation=validation)
    db.add(new)
    db.flush()
    audit.record(db, action="response.edited", entity_type="complaint", entity_id=complaint.complaint_ref, actor=user,
                 summary=f"Response edited (v{new.version_no}) - {'passed' if validation['ok'] else 'failed'} validation",
                 details={"issues": validation["issues"]})
    db.commit()
    return {"response_id": new.id, "status": new.status, "validation": validation}


class ClarifyIn(BaseModel):
    information: str = Field(min_length=3, max_length=4000)
    order_ref: str | None = None
    product_text: str | None = None


@router.post("/complaints/{ref}/clarify", status_code=202)
def clarify(ref: str, body: ClarifyIn, user: User = Depends(current_user), db: Session = Depends(db_session)) -> dict[str, Any]:
    """Customer (or agent on their behalf) answers a clarification request; the complaint is re-analysed."""
    complaint = _load(db, ref, user)
    if user.role_code != "customer" and "complaint:update" not in user.permissions:
        raise PermissionDenied("You cannot add information to this complaint.")
    stamp = utcnow().strftime("%Y-%m-%d %H:%M")
    complaint.supporting_info = ((complaint.supporting_info or "") + f"\n[Customer clarification {stamp}] {body.information}").strip()
    if body.order_ref:
        errors = svc.validate_submission(db, {"title": complaint.title, "description": complaint.description, "customer_type": complaint.customer_type,
                                              "channel": complaint.channel, "order_ref": body.order_ref}, customer=None)
        if any(e["field"] == "order_ref" for e in errors):
            raise ValidationFailed("Invalid order reference.", details=[e for e in errors if e["field"] == "order_ref"])
        complaint.order_ref = body.order_ref.upper()
    if body.product_text:
        complaint.product_text = body.product_text[:200]
    history_event(db, complaint, "complaint.clarified", "Additional information received from the customer.", actor=user)
    audit.record(db, action="complaint.clarified", entity_type="complaint", entity_id=complaint.complaint_ref, actor=user,
                 summary="Clarification added")
    complaint.processing_stage = "queued"
    db.commit()
    worker.submit(complaint.id, PipelineOptions(trigger="clarification", actor_id=user.id, link_duplicates=False))
    return {"complaint_ref": complaint.complaint_ref, "processing_stage": "queued"}


@router.post("/complaints/{ref}/follow-ups/{follow_up_id}/complete")
def complete_follow_up(ref: str, follow_up_id: int, user: User = Depends(require("complaint:update")),
                       db: Session = Depends(db_session)) -> dict[str, Any]:
    complaint = _load(db, ref, user)
    fu = db.get(FollowUp, follow_up_id)
    if fu is None or fu.complaint_id != complaint.id:
        raise NotFound("Follow-up not found.")
    fu.status, fu.sent_at = "completed", utcnow()
    history_event(db, complaint, "follow_up.completed", f"Follow-up '{fu.type}' completed.", actor=user)
    audit.record(db, action="follow_up.completed", entity_type="complaint", entity_id=complaint.complaint_ref, actor=user,
                 summary=f"Follow-up {fu.type} completed")
    db.commit()
    return {"id": fu.id, "status": fu.status}


@router.get("/complaints/{ref}/report.pdf")
def case_report(ref: str, user: User = Depends(require("complaint:read_all")), db: Session = Depends(db_session)) -> Response:
    from supportnova.reporting.exports import complaint_case_pdf
    complaint = _load(db, ref, user)
    detail = complaint_detail(db, complaint, rule_service.matrix(db), user)
    pdf = complaint_case_pdf(detail, timeline(db, complaint))
    audit.record(db, action="report.exported", entity_type="complaint", entity_id=complaint.complaint_ref, actor=user,
                 summary="Case report PDF exported")
    db.commit()
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{complaint.complaint_ref}-case-report.pdf"'})


@router.get("/complaints-export")
def export_complaints(request: Request, format: str = "csv", user: User = Depends(require("reports:export")),
                      db: Session = Depends(db_session)) -> Response:
    """Export the current filtered complaint list (same filters as GET /complaints)."""
    from supportnova.reporting.exports import tabular
    params = dict(request.query_params)
    params.pop("format", None)
    multi = {k: request.query_params.getlist(k) for k in ("status", "category", "department", "priority", "urgency", "sentiment",
                                                          "verification", "sla")}
    result = list_complaints(q=params.get("q"), status=multi["status"] or None, category=multi["category"] or None,
                             subcategory=params.get("subcategory"), department=multi["department"] or None,
                             priority=multi["priority"] or None, urgency=multi["urgency"] or None, sentiment=multi["sentiment"] or None,
                             verification=multi["verification"] or None, escalated=None, sla=multi["sla"] or None,
                             channel=params.get("channel"), customer_ref=params.get("customer_ref"), date_from=None, date_to=None,
                             needs_review=None, assigned_to_me=False, repeat=None, duplicate=None, injection=None,
                             source=params.get("source"), sort="created_at", order="desc", page=1, page_size=10000 if format != "pdf" else 500,
                             user=user, db=db)
    rows = result["items"]
    columns = ["complaint_ref", "created_at", "title", "customer_ref", "customer_type", "channel", "category", "subcategory", "department",
               "urgency", "priority", "sentiment", "status", "verification_status", "verification_score", "escalation_level", "sla_state",
               "is_repeat", "is_duplicate", "injection_detected"]
    content, media, ext = tabular("Complaint export", columns, [[r.get(c) for c in columns] for r in rows], format)
    audit.record(db, action="report.exported", entity_type="report", entity_id="complaints", actor=user,
                 summary=f"Complaint export ({format}, {len(rows)} rows)", details={"filters": params})
    db.commit()
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="supportnova-complaints.{ext}"'})

