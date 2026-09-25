"""Complaint submission, validation and lifecycle (SRS Steps 9-11, 60; 1.6 iii-v, lxv)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from supportnova.audit import service as audit
from supportnova.core.config import get_settings
from supportnova.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from supportnova.core.paths import storage_dir
from supportnova.core.timeutil import to_datetime, utcnow
from supportnova.database.models import Complaint, ComplaintAttachment, Customer, User
from supportnova.knowledge_base.embeddings import similarity_vectors, to_bytes
from supportnova.security.files import ATTACHMENT_TYPES, validate_upload
from supportnova.security.sanitization import normalize_text, text_hash
from supportnova.services.pipeline import history_event, set_status
from supportnova.services.rules import rule_service

LIFECYCLE = ["New", "Processing", "Analyzed", "Assigned", "In Progress", "Awaiting Customer", "Escalated", "Resolved", "Closed", "Reopened"]
TRANSITIONS: dict[str, set[str]] = {
    "New": {"Processing"},
    "Processing": {"Analyzed", "Assigned", "Escalated", "Awaiting Customer", "New"},
    "Analyzed": {"Assigned", "In Progress", "Awaiting Customer", "Escalated", "Resolved", "Closed"},
    "Assigned": {"In Progress", "Awaiting Customer", "Escalated", "Resolved"},
    "In Progress": {"Awaiting Customer", "Escalated", "Resolved"},
    "Awaiting Customer": {"In Progress", "Processing", "Escalated", "Resolved", "Closed"},
    "Escalated": {"In Progress", "Awaiting Customer", "Resolved"},
    "Resolved": {"Closed", "Reopened"},
    "Closed": {"Reopened"},
    "Reopened": {"Processing", "In Progress", "Escalated", "Resolved"},
}
MAX_ATTACHMENTS = 5


def next_complaint_ref(db: Session) -> str:
    refs = db.execute(select(Complaint.complaint_ref).where(Complaint.complaint_ref.like("CMP-%"))).scalars().all()
    highest = max((int(r[4:]) for r in refs if r[4:].isdigit()), default=0)
    return f"CMP-{highest + 1:05d}"


def validate_submission(db: Session, data: dict[str, Any], *, customer: Customer | None) -> list[dict[str, str]]:
    """Field-level validation errors (empty, too short, invalid references, unsupported values)."""
    org = rule_service.matrix(db).organization
    formats = org.get("reference_formats", {})
    errors: list[dict[str, str]] = []
    title = (data.get("title") or "").strip()
    description = normalize_text(data.get("description") or "")
    if not title:
        errors.append({"field": "title", "message": "Complaint title is required."})
    elif len(title) < 5:
        errors.append({"field": "title", "message": "The title is too short (minimum 5 characters)."})
    elif len(title) > 180:
        errors.append({"field": "title", "message": "The title is too long (maximum 180 characters)."})
    if not description:
        errors.append({"field": "description", "message": "A description of the problem is required."})
    elif len(description) < 20 or len(description.split()) < 4:
        errors.append({"field": "description", "message": "The description is too short - please describe what happened (at least 20 characters)."})
    elif len(description) > 8000:
        errors.append({"field": "description", "message": "The description is too long (maximum 8000 characters)."})
    allowed = {
        "customer_type": {c["code"] for c in org.get("customer_types", [])},
        "channel": {c["code"] for c in org.get("channels", [])},
        "preferred_contact": {c["code"] for c in org.get("preferred_contact_methods", [])},
        "requested_resolution": {c["code"] for c in org.get("requested_resolutions", [])},
        "requested_tone": {c["code"] for c in org.get("response_tones", [])},
    }
    for field, values in allowed.items():
        value = data.get(field)
        if field in ("customer_type", "channel") and not value:
            errors.append({"field": field, "message": f"{field.replace('_', ' ').capitalize()} is required."})
        elif value and value not in values:
            errors.append({"field": field, "message": f"Unsupported value '{value}'."})
    for field, key in (("order_ref", "order"), ("transaction_ref", "transaction"), ("previous_complaint_ref", "complaint")):
        value = (data.get(field) or "").strip().upper()
        if value and formats.get(key) and not re.match(formats[key], value):
            example = {"order": "LMR-123456", "transaction": "TXN-12345678", "complaint": "CMP-00042"}[key]
            errors.append({"field": field, "message": f"Invalid reference format (expected e.g. {example})."})
    prev = (data.get("previous_complaint_ref") or "").strip().upper()
    if prev and not any(e["field"] == "previous_complaint_ref" for e in errors):
        row = db.execute(select(Complaint).where(Complaint.complaint_ref == prev)).scalar_one_or_none()
        if row is None:
            errors.append({"field": "previous_complaint_ref", "message": f"Previous complaint {prev} was not found."})
        elif customer is not None and row.customer_id not in (None, customer.id):
            errors.append({"field": "previous_complaint_ref", "message": f"Previous complaint {prev} does not belong to this customer."})
    return errors


LENIENT_DEFAULTS = {"customer_type": "individual", "channel": "web_form", "preferred_contact": "email",
                    "requested_resolution": "none", "requested_tone": "professional"}


def create_complaint(db: Session, data: dict[str, Any], *, submitted_by: User | None, customer: Customer | None,
                     attachments: list[tuple[str, bytes]] | None = None, source: str = "web",
                     created_at: datetime | None = None, dataset_case_id: str | None = None,
                     complaint_ref: str | None = None, skip_duplicate_check: bool = False, lenient: bool = False) -> Complaint:
    """Create a complaint. ``lenient`` (bulk imports, evaluation, lab) only blocks on missing/unusable
    text: unsupported option values fall back to defaults and malformed references are kept so the
    pipeline flags them (REV-014) instead of the import silently dropping the case."""
    settings = get_settings()
    errors = validate_submission(db, data, customer=customer)
    intake_warnings: list[dict[str, str]] = []
    if lenient:
        data = dict(data)
        for e in [e for e in errors if e["field"] not in ("title", "description")]:
            if e["field"] in LENIENT_DEFAULTS:
                data[e["field"]] = LENIENT_DEFAULTS[e["field"]]
            intake_warnings.append(e)
        errors = [e for e in errors if e["field"] in ("title", "description")]
    files = attachments or []
    if len(files) > MAX_ATTACHMENTS:
        errors.append({"field": "attachments", "message": f"At most {MAX_ATTACHMENTS} attachments are allowed."})
    validated_files = []
    for name, blob in files:
        try:
            validated_files.append((validate_upload(name, blob, allowed=ATTACHMENT_TYPES,
                                                    max_bytes=settings.max_attachment_mb * 1024 * 1024), blob))
        except ValidationFailed as exc:
            errors.append({"field": "attachments", "message": f"{name}: {exc.message}"})
    if errors:
        raise ValidationFailed("Please correct the highlighted fields.", details=errors)
    normalized = normalize_text(data["description"])
    digest = text_hash(f"{data['title']}\n{normalized}")
    when = created_at or utcnow()
    if (settings.reject_exact_duplicates and not skip_duplicate_check and customer is not None):
        window_start = when - timedelta(hours=settings.duplicate_window_hours)
        dup = db.execute(select(Complaint).where(Complaint.customer_id == customer.id, Complaint.text_hash == digest,
                                                 Complaint.created_at >= window_start)).scalars().first()
        if dup is not None:
            raise Conflict(f"This complaint was already submitted as {dup.complaint_ref}.",
                           details={"duplicate_of": dup.complaint_ref}, code="duplicate_complaint")
    complaint = Complaint(
        complaint_ref=complaint_ref or next_complaint_ref(db), customer_id=customer.id if customer else None,
        submitted_by_id=submitted_by.id if submitted_by else None, source=source, dataset_case_id=dataset_case_id,
        title=data["title"].strip(), description=data["description"], supporting_info=data.get("supporting_info") or "",
        customer_type=data.get("customer_type") or (customer.customer_type if customer else "individual"),
        channel=data.get("channel") or "web_form", product_text=(data.get("product_text") or "").strip()[:200],
        order_ref=(data.get("order_ref") or "").strip().upper() or None,
        transaction_ref=(data.get("transaction_ref") or "").strip().upper() or None,
        previous_complaint_ref=(data.get("previous_complaint_ref") or "").strip().upper() or None,
        preferred_contact=data.get("preferred_contact") or "email", requested_resolution=data.get("requested_resolution") or "none",
        requested_tone=data.get("requested_tone") or "professional",
        complaint_date=to_datetime(data.get("complaint_date")) or when,
        description_normalized=normalized, text_hash=digest,
        embedding=to_bytes(similarity_vectors([f"{data['title']}\n{normalized}"])[0]),
        status="New", processing_stage="queued", verification_status="Pending",
    )
    complaint.created_at = when
    db.add(complaint)
    db.flush()
    for vf, blob in validated_files:
        folder = storage_dir() / "attachments" / complaint.complaint_ref
        folder.mkdir(parents=True, exist_ok=True)
        (folder / vf.file_name).write_bytes(blob)
        db.add(ComplaintAttachment(complaint_id=complaint.id, file_name=vf.file_name, content_type=vf.content_type,
                                   size_bytes=vf.size_bytes, sha256=vf.sha256,
                                   storage_path=str((folder / vf.file_name).relative_to(storage_dir()))))
    for meta in data.get("attachment_metadata") or []:   # dataset records carry attachment metadata only
        db.add(ComplaintAttachment(complaint_id=complaint.id, file_name=str(meta.get("file_name"))[:200],
                                   content_type=str(meta.get("content_type", "application/octet-stream"))[:100], size_bytes=0))
    history_event(db, complaint, "complaint.submitted", f"Complaint submitted via {complaint.channel}.", actor=submitted_by,
                  to_status="New", data={"source": source})
    if intake_warnings:
        history_event(db, complaint, "complaint.intake_warnings", "Imported with data-quality warnings: "
                      + "; ".join(f"{w['field']}: {w['message']}" for w in intake_warnings), data={"warnings": intake_warnings})
    audit.record(db, action="complaint.created", entity_type="complaint", entity_id=complaint.complaint_ref, actor=submitted_by,
                 summary=f"Complaint {complaint.complaint_ref} created ({source})",
                 details={"channel": complaint.channel, "customer": customer.customer_ref if customer else None,
                          "attachments": len(files), "text_sha256": digest})
    return complaint


def transition(db: Session, complaint: Complaint, to_status: str, *, actor: User | None, note: str = "") -> Complaint:
    if to_status not in LIFECYCLE:
        raise ValidationFailed(f"Unknown status '{to_status}'.")
    allowed = TRANSITIONS.get(complaint.status, set())
    if to_status not in allowed:
        raise ValidationFailed(f"Cannot move a complaint from {complaint.status} to {to_status}.",
                               details={"allowed": sorted(allowed)})
    if to_status == "Reopened" and complaint.resolved_at is not None:
        matrix = rule_service.matrix(db)
        limit = int(matrix.param("reopen_window_days"))
        resolved_at = complaint.resolved_at if complaint.resolved_at.tzinfo else complaint.resolved_at.replace(tzinfo=utcnow().tzinfo)
        if actor is not None and actor.role_code == "customer" and (utcnow() - resolved_at).days > limit:
            raise ValidationFailed(f"Complaints can be reopened within {limit} days of resolution (CHP-POL-01 s8.2).")
    old = complaint.status
    set_status(db, complaint, to_status, actor=actor, note=note or f"{old} -> {to_status}")
    if to_status == "Resolved":
        from supportnova.database.models import FollowUp, SlaRecord
        sla = db.execute(select(SlaRecord).where(SlaRecord.complaint_id == complaint.id)).scalar_one_or_none()
        if sla is not None:
            sla.resolved_at = utcnow()
            from supportnova.services.sla import evaluate
            evaluate(sla, rule_service.matrix(db), utcnow())
            complaint.sla_state = sla.resolution_state
        db.add(FollowUp(complaint_id=complaint.id, type="Closure confirmation",
                        message=f"Closure confirmation for {complaint.complaint_ref}.", due_at=utcnow() + timedelta(hours=48),
                        status="scheduled", source_rule="FUP-003"))
    audit.record(db, action="complaint.status_changed", entity_type="complaint", entity_id=complaint.complaint_ref, actor=actor,
                 summary=f"{old} -> {to_status}", details={"note": note})
    return complaint


def get_complaint(db: Session, ref: str) -> Complaint:
    row = db.execute(select(Complaint).where(Complaint.complaint_ref == ref.upper())).scalar_one_or_none()
    if row is None:
        raise NotFound(f"Complaint {ref} not found.")
    return row


def ensure_can_view(complaint: Complaint, user: User) -> None:
    if user.role_code == "customer":
        if (not user.customer_id or complaint.customer_id != user.customer_id
                or complaint.source not in ("web", "api", "dataset")):
            raise NotFound(f"Complaint {complaint.complaint_ref} not found.")
    elif "complaint:read_all" not in user.permissions:
        raise PermissionDenied("You do not have access to complaints.")

