"""First-run seeding: roles, demo users, Rule Matrix, prompts, knowledge base and the demo dataset.

Everything is idempotent. The demo dataset is imported *chronologically per customer* (customers run in
parallel, see services/batch.py) and every complaint is processed by the real pipeline; each case's
``seed_status`` (the state the case had reached before later complaints arrived) is then applied, so
repeat/duplicate detection sees the same history the dataset describes. Activity added this way (agent sending a validated response, resolution) is
recorded as "Demo Data Seeder (simulated history)" in the timeline and the audit log - it is
simulated, and labelled as such.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from supportnova.audit import service as audit
from supportnova.core.config import get_settings
from supportnova.core.logging import get_logger
from supportnova.core.paths import DATA_DIR, KNOWLEDGE_BASE_DIR
from supportnova.core.timeutil import to_datetime, utcnow
from supportnova.database.base import session_scope
from supportnova.database.models import (
    Complaint,
    ComplaintHistory,
    Customer,
    CustomerResponse,
    Department,
    Document,
    Order,
    Role,
    SlaRecord,
    User,
)
from supportnova.genai_pipeline.prompts import seed_prompts
from supportnova.security.auth import hash_password
from supportnova.security.rbac import ROLE_NAMES, ROLE_PERMISSIONS
from supportnova.services import datasets
from supportnova.services.batch import run_by_customer
from supportnova.services.complaints import create_complaint
from supportnova.services.pipeline import PipelineOptions, process_complaint
from supportnova.services.rules import seed_from_yaml

log = get_logger(__name__)
SEEDER_LABEL = "Demo Data Seeder (simulated history)"
SAMPLE_DIR = DATA_DIR / "sample_complaints"
progress: dict[str, Any] = {"state": "idle", "done": 0, "total": 0, "started_at": None, "finished_at": None, "error": None}
_thread: threading.Thread | None = None

DEMO_USERS: list[dict[str, Any]] = [
    {"email": "admin@lumora.example", "full_name": "Amelia Hart", "role": "admin"},
    {"email": "manager@lumora.example", "full_name": "Marcus Webb", "role": "manager"},
    {"email": "reviewer@lumora.example", "full_name": "Rhea Castillo", "role": "reviewer"},
    {"email": "reviewer2@lumora.example", "full_name": "Tomas Lindqvist", "role": "reviewer"},
    {"email": "agent@lumora.example", "full_name": "Aisha Rahman", "role": "agent", "department": "DEPT-LOG"},
    {"email": "agent.billing@lumora.example", "full_name": "Daniel Okafor", "role": "agent", "department": "DEPT-BIL"},
    {"email": "agent.tech@lumora.example", "full_name": "Mei Tanaka", "role": "agent", "department": "DEPT-TEC"},
    {"email": "agent.returns@lumora.example", "full_name": "Lucas Moreau", "role": "agent", "department": "DEPT-RET"},
    {"email": "agent.warranty@lumora.example", "full_name": "Priya Nair", "role": "agent", "department": "DEPT-WAR"},
    {"email": "agent.safety@lumora.example", "full_name": "Jonas Becker", "role": "agent", "department": "DEPT-SAF"},
    {"email": "agent.security@lumora.example", "full_name": "Sofia Alvarez", "role": "agent", "department": "DEPT-SEC"},
    {"email": "agent.compliance@lumora.example", "full_name": "Kwame Mensah", "role": "agent", "department": "DEPT-CMP"},
    {"email": "agent.relations@lumora.example", "full_name": "Hannah Cohen", "role": "agent", "department": "DEPT-CRL"},
    {"email": "agent.management@lumora.example", "full_name": "Omar Haddad", "role": "agent", "department": "DEPT-MGT"},
    {"email": "customer@lumora.example", "full_name": None, "role": "customer", "customer_ref": None},
]


# ------------------------------------------------------------------------------------------ reference data
def seed_roles(db: Session) -> None:
    for code, perms in ROLE_PERMISSIONS.items():
        role = db.execute(select(Role).where(Role.code == code)).scalar_one_or_none()
        name, desc = ROLE_NAMES[code]
        if role is None:
            db.add(Role(code=code, name=name, description=desc, permissions=list(perms)))
        else:  # the code-defined matrix is authoritative: RBAC changes apply on restart
            role.name, role.description, role.permissions = name, desc, list(perms)
    db.flush()


def _customer_for_demo(db: Session) -> Customer | None:
    """The demo customer login is linked to the dataset customer with the most complaints."""
    row = db.execute(select(Complaint.customer_id, func.count()).where(Complaint.source == "dataset", Complaint.customer_id.is_not(None))
                     .group_by(Complaint.customer_id).order_by(func.count().desc()).limit(1)).first()
    if row:
        return db.get(Customer, row[0])
    return db.execute(select(Customer).order_by(Customer.id).limit(1)).scalar_one_or_none()


def seed_users(db: Session) -> int:
    settings = get_settings()
    if not settings.seed_demo_users:
        return 0
    roles = {r.code: r for r in db.execute(select(Role)).scalars()}
    depts = {d.code: d for d in db.execute(select(Department)).scalars()}
    password = settings.demo_password.get_secret_value()
    added = 0
    for spec in DEMO_USERS:
        user = db.execute(select(User).where(User.email == spec["email"])).scalar_one_or_none()
        if spec["role"] == "customer":
            customer = _customer_for_demo(db)
            if customer is None:
                continue
            if user is None:
                user = User(email=spec["email"], full_name=customer.full_name, password_hash=hash_password(password),
                            role_id=roles["customer"].id, customer_id=customer.id)
                db.add(user)
                added += 1
            elif user.customer_id is None:
                user.customer_id, user.full_name = customer.id, customer.full_name
            continue
        if user is None:
            dept = depts.get(spec.get("department") or "")
            db.add(User(email=spec["email"], full_name=spec["full_name"], password_hash=hash_password(password),
                        role_id=roles[spec["role"]].id, department_id=dept.id if dept else None))
            added += 1
    if db.execute(select(User).where(User.email == "seeder@system.invalid")).scalar_one_or_none() is None:
        db.add(User(email="seeder@system.invalid", full_name=SEEDER_LABEL, password_hash=hash_password(secrets.token_urlsafe(32)),
                    role_id=roles["reviewer"].id, is_active=False))  # cannot sign in; labels simulated history
    db.flush()
    return added


def seed_customers_and_orders(db: Session) -> dict[str, int]:
    out = {"customers": 0, "orders": 0}
    cust_file, order_file = SAMPLE_DIR / "customers.json", SAMPLE_DIR / "orders.json"
    if cust_file.exists():
        existing = set(db.execute(select(Customer.customer_ref)).scalars())
        for c in json.loads(cust_file.read_text(encoding="utf-8")):
            if c["customer_ref"] not in existing:
                db.add(Customer(customer_ref=c["customer_ref"], full_name=c["full_name"], email=c.get("email") or f"{c['customer_ref'].lower()}@example.invalid",
                                phone=c.get("phone"), customer_type=c.get("customer_type") or "individual"))
                out["customers"] += 1
        db.flush()
    if order_file.exists():
        customers = dict(db.execute(select(Customer.customer_ref, Customer.id)).tuples().all())
        existing = set(db.execute(select(Order.order_ref)).scalars())
        payload = json.loads(order_file.read_text(encoding="utf-8"))
        orders = payload if isinstance(payload, list) else payload.get("orders", [])
        for o in orders:
            if o["order_ref"] in existing:
                continue
            db.add(Order(order_ref=o["order_ref"], customer_id=customers.get(o.get("customer_ref")),
                         order_date=to_datetime(o.get("order_date")).date() if o.get("order_date") else None,  # type: ignore[union-attr]
                         order_total=float(o.get("order_total") or 0), status=o.get("status") or "delivered", data=o))
            out["orders"] += 1
        db.flush()
    return out


def seed_reference(db: Session) -> dict[str, Any]:
    """Synchronous part of first-run seeding (fast)."""
    seed_roles(db)
    rules = seed_from_yaml(db)
    prompts = seed_prompts(db)
    kb: dict[str, Any] = {"ingested": 0}
    if db.scalar(select(func.count()).select_from(Document)) == 0 and (KNOWLEDGE_BASE_DIR / "manifest.yaml").exists():
        from supportnova.services.documents import bootstrap_knowledge_base
        kb = bootstrap_knowledge_base(db, KNOWLEDGE_BASE_DIR / "manifest.yaml")
    ledger = seed_customers_and_orders(db)
    users = seed_users(db)
    return {"rules": rules, "prompts": prompts, "knowledge_base": kb, **ledger, "users": users}


# ------------------------------------------------------------------------------------------ seed status
def apply_seed_status(db: Session, complaint: Complaint, seed_status: str | None, *, full: bool) -> None:
    """Move a processed complaint to the state its record describes. ``full`` also simulates agent
    activity (sending the validated response); evaluation runs use the state change only."""
    from supportnova.services.pipeline import history_event, set_status
    if not seed_status or seed_status == "New" or complaint.is_duplicate or complaint.processing_stage != "completed":
        return
    seeder = db.execute(select(User).where(User.email == "seeder@system.invalid")).scalar_one_or_none()
    base = complaint.created_at or utcnow()
    now = utcnow()
    if seed_status == "Awaiting Customer" and complaint.status not in ("Resolved", "Closed"):
        set_status(db, complaint, "Awaiting Customer", actor=seeder, note="Clarification requested from the customer (simulated).")
        return
    if complaint.verification_status == "Manual Review":
        return  # stays in the review queue - a human must decide
    sent_at = min(base + timedelta(hours=3), now)
    if full:
        resp = db.execute(select(CustomerResponse).where(CustomerResponse.complaint_id == complaint.id, CustomerResponse.status == "ready")
                          .order_by(CustomerResponse.id.desc())).scalars().first()
        if resp is not None:
            resp.status, resp.sent_at, resp.sent_via = "sent", sent_at, complaint.preferred_contact
            history_event(db, complaint, "response.sent", f"Response v{resp.version_no} sent via {resp.sent_via} (simulated).",
                          actor=seeder)
            sla = db.execute(select(SlaRecord).where(SlaRecord.complaint_id == complaint.id)).scalar_one_or_none()
            if sla is not None and sla.first_response_at is None:
                sla.first_response_at = sent_at
    if seed_status == "In Progress" and complaint.status in ("Analyzed", "Assigned"):
        set_status(db, complaint, "In Progress", actor=seeder, note="Agent working on the case (simulated).")
    elif seed_status == "Escalated" and complaint.status != "Escalated" and complaint.escalation_required:
        set_status(db, complaint, "Escalated", actor=seeder, note="Case escalated (simulated).")
    elif seed_status in ("Resolved", "Closed"):
        resolved_at = min(base + timedelta(hours=26), now)
        set_status(db, complaint, "Resolved", actor=seeder, note="Case resolved (simulated).")
        complaint.resolved_at = resolved_at
        sla = db.execute(select(SlaRecord).where(SlaRecord.complaint_id == complaint.id)).scalar_one_or_none()
        if sla is not None:
            sla.resolved_at = resolved_at
            sla.resolution_state = "Met" if resolved_at <= sla.resolution_due_at else "Breached"
            complaint.sla_state = sla.resolution_state
        if seed_status == "Closed":
            set_status(db, complaint, "Closed", actor=seeder, note="Case closed after resolution (simulated).")
            complaint.closed_at = min(resolved_at + timedelta(days=2), now)
    _stamp_simulated(db, complaint, base)


_OFFSETS = {"Escalated": 1, "Awaiting Customer": 2, "In Progress": 4, "Resolved": 26, "Closed": 74}


def _stamp_simulated(db: Session, complaint: Complaint, base: Any) -> None:
    """Place simulated events at plausible business times after submission (never in the future)."""
    db.flush()
    now = utcnow()
    for h in db.execute(select(ComplaintHistory).where(ComplaintHistory.complaint_id == complaint.id,
                                                       ComplaintHistory.actor_label == SEEDER_LABEL)).scalars():
        hours = 3 if h.event_type == "response.sent" else _OFFSETS.get(h.to_status or "", 5)
        h.created_at = min(base + timedelta(hours=hours), now)


def align_timeline(db: Session, complaint: Complaint) -> None:
    """Imported cases are processed today but were submitted on their dataset date: shift the pipeline's
    timeline events so they start at the submission time (audit-log entries keep their real time)."""
    rows = db.execute(select(ComplaintHistory).where(ComplaintHistory.complaint_id == complaint.id,
                                                    ComplaintHistory.actor_label != SEEDER_LABEL)
                      .order_by(ComplaintHistory.id)).scalars().all()
    if not rows or complaint.created_at is None:
        return
    delta = complaint.created_at - rows[0].created_at
    if delta.total_seconds() < 0:
        for h in rows:
            h.created_at = h.created_at + delta


# ------------------------------------------------------------------------------------------ dataset import
def dataset_loaded(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(Complaint).where(Complaint.source == "dataset")) or 0


def import_dataset(*, limit: int | None = None, path: Any = None, workers: int | None = None) -> dict[str, Any]:
    """Import and process the demo dataset (idempotent: existing case IDs are skipped) - each customer's
    complaints in date order, different customers in parallel (BATCH_WORKERS)."""
    src = path or datasets.BUILTIN["dev"]
    if not src.exists():
        progress.update(state="unavailable", error=f"Demo dataset file {src.name} not found.")
        return {"imported": 0, "reason": "dataset file missing"}
    records = sorted(datasets.read_path(src), key=lambda r: (str(r.get("complaint_date")), str(r.get("complaint_id"))))
    if limit:
        records = records[:limit]
    progress.update(state="running", done=0, total=len(records), started_at=utcnow().isoformat(), finished_at=None, error=None)
    t0 = time.perf_counter()
    imported = 0
    lock = threading.Lock()
    with session_scope() as db:
        seeder = db.execute(select(User).where(User.email == "seeder@system.invalid")).scalar_one_or_none()
        existing = set(db.execute(select(Complaint.complaint_ref).where(Complaint.source == "dataset")).scalars())
        seeder_id = seeder.id if seeder else None

    def import_one(rec: dict[str, Any]) -> None:
        nonlocal imported
        ref = str(rec.get("complaint_id") or "").upper()
        if ref not in existing:
            try:
                with session_scope() as db:
                    customer = db.execute(select(Customer).where(Customer.customer_ref == (rec.get("customer_ref") or "").upper())
                                          ).scalar_one_or_none()
                    c = create_complaint(db, datasets.to_submission(rec), submitted_by=None, customer=customer, source="dataset",
                                         created_at=to_datetime(rec.get("complaint_date")), dataset_case_id=ref, complaint_ref=ref,
                                         skip_duplicate_check=True, lenient=True)
                    cid = c.id
                process_complaint(cid, PipelineOptions(trigger="dataset", actor_id=seeder_id))
                with session_scope() as db:
                    c2 = db.get(Complaint, cid)
                    if c2 is not None:
                        align_timeline(db, c2)
                        apply_seed_status(db, c2, rec.get("seed_status"), full=True)
                with lock:
                    imported += 1
            except Exception as exc:  # keep going; report at the end
                log.warning("dataset import failed for %s: %s", ref, exc)
        with lock:
            progress["done"] += 1

    run_by_customer(records, import_one, workers=workers or get_settings().batch_workers)
    with session_scope() as db:
        audit.record(db, action="dataset.imported", entity_type="dataset", entity_id=src.name, actor_label=SEEDER_LABEL,
                     summary=f"Imported {imported} demo complaints in {time.perf_counter() - t0:.0f}s",
                     details={"records": len(records), "imported": imported})
    progress.update(state="completed", finished_at=utcnow().isoformat())
    return {"imported": imported, "seconds": round(time.perf_counter() - t0, 1)}


# ------------------------------------------------------------------------------------------ demo time-lapse
def _anchor_refs() -> set[str]:
    """Complaints that other dataset records rely on as history (previous/repeat/duplicate targets) keep the
    state the dataset declares, so repeat detection - also in holdout evaluations - stays faithful."""
    refs: set[str] = set()
    for path in (datasets.BUILTIN["dev"], datasets.BUILTIN["holdout"]):
        if not path.exists():
            continue
        for rec in datasets.read_path(path):
            exp = rec.get("expected") or {}
            for ref in (rec.get("previous_complaint_reference"), exp.get("is_repeat_of"), exp.get("is_duplicate_of"),
                        exp.get("is_near_duplicate_of")):
                if ref:
                    refs.add(str(ref).upper())
            if rec.get("seed_status") and rec.get("seed_status") != "New":
                refs.add(str(rec.get("complaint_id")).upper())
    return refs


def _fraction(ref: str) -> float:
    """Deterministic pseudo-random number in [0, 1) per complaint (stable demo data)."""
    import hashlib
    return int(hashlib.sha256(ref.encode()).hexdigest()[:8], 16) / 0x100000000


def simulate_lifecycle(*, older_than_days: int = 21) -> dict[str, int]:
    """Demo time-lapse (SEED_SIMULATE_LIFECYCLE): complaints older than ``older_than_days`` move through a plausible
    lifecycle - reviewer decision, validated response sent, resolution, closure - so resolution-time, SLA and
    department analytics have history. Every step is attributed to "Demo Data Seeder (simulated history)" in the
    timeline and the audit log. Cases with injection attempts or blocked customer text stay in the review queue;
    recent complaints stay open."""
    from supportnova.database.models import Escalation, FollowUp, Review, ValidationCheck, ValidationResult
    from supportnova.services import reviews as review_svc
    from supportnova.services.pipeline import history_event, set_status
    from supportnova.services.rules import rule_service
    counts = {"resolved": 0, "closed": 0, "reviewed": 0, "kept_open": 0}
    anchors = _anchor_refs()
    now = utcnow()
    with session_scope() as db:
        seeder = db.execute(select(User).where(User.email == "seeder@system.invalid")).scalar_one_or_none()
        if seeder is None:
            return counts
        sla_rules = rule_service.matrix(db).sla_rules
        rows = db.execute(select(Complaint).where(Complaint.source == "dataset", Complaint.is_duplicate.is_(False),
                                                  Complaint.processing_stage == "completed",
                                                  Complaint.status.notin_(["Resolved", "Closed"]))).scalars().all()
        for c in rows:
            base = c.created_at
            if base is None or (now - base).days < older_than_days or c.complaint_ref in anchors:
                counts["kept_open"] += 1
                continue
            frac = _fraction(c.complaint_ref)
            review = db.execute(select(Review).where(Review.complaint_id == c.id,
                                                     Review.status.in_(["pending", "in_review"]))).scalars().first()
            if review is not None:
                vr = db.execute(select(ValidationResult).where(ValidationResult.complaint_id == c.id)
                                .order_by(ValidationResult.id.desc())).scalars().first()
                failed = ({ch.code for ch in db.execute(select(ValidationCheck).where(ValidationCheck.result_id == vr.id,
                                                                                      ValidationCheck.status == "fail")).scalars()}
                          if vr else set())
                if c.injection_detected or failed & {"RSP-002", "RSP-006", "SEC-001", "SEC-002"} or frac < 0.08:
                    counts["kept_open"] += 1
                    continue
                review_svc.act(db, review, seeder, action="approve", comment="Simulated review.")
                counts["reviewed"] += 1
            prio = c.priority or "P2"
            target = sla_rules[prio].resolution_hours if prio in sla_rules else 72.0
            resolved_at = min(base + timedelta(hours=max(2.0, target * (0.25 + 0.9 * frac))), now)
            resp = db.execute(select(CustomerResponse).where(CustomerResponse.complaint_id == c.id,
                                                             CustomerResponse.status.in_(["ready", "approved"]))
                              .order_by(CustomerResponse.id.desc())).scalars().first()
            if resp is not None:
                resp.status, resp.sent_via = "sent", c.preferred_contact
                resp.sent_at = min(base + timedelta(hours=2 + 4 * frac), resolved_at)
                history_event(db, c, "response.sent", f"Response v{resp.version_no} sent via {resp.sent_via} (simulated).",
                              actor=seeder)
            set_status(db, c, "Resolved", actor=seeder, note="Case resolved (simulated).")
            c.resolved_at = resolved_at
            sla = db.execute(select(SlaRecord).where(SlaRecord.complaint_id == c.id)).scalar_one_or_none()
            if sla is not None:
                sla.first_response_at = sla.first_response_at or (resp.sent_at if resp else resolved_at)
                sla.resolved_at = resolved_at
                sla.resolution_state = "Met" if resolved_at <= sla.resolution_due_at else "Breached"
                sla.response_state = ("Met" if sla.first_response_at and sla.first_response_at <= sla.first_response_due_at
                                      else "Breached")
                c.sla_state = sla.resolution_state
            for esc in db.execute(select(Escalation).where(Escalation.complaint_id == c.id, Escalation.status == "open")).scalars():
                esc.status, esc.resolved_at = "resolved", resolved_at
            for fu in db.execute(select(FollowUp).where(FollowUp.complaint_id == c.id, FollowUp.status == "scheduled")).scalars():
                fu.status, fu.sent_at = "completed", min(resolved_at + timedelta(hours=24), now)
            counts["resolved"] += 1
            if (now - base).days > older_than_days + 14 and frac > 0.2:
                set_status(db, c, "Closed", actor=seeder, note="Case closed after resolution (simulated).")
                c.closed_at = min(resolved_at + timedelta(days=3), now)
                counts["closed"] += 1
            db.flush()
            for h in db.execute(select(ComplaintHistory).where(ComplaintHistory.complaint_id == c.id,
                                                               ComplaintHistory.actor_label == SEEDER_LABEL)).scalars():
                if h.event_type == "response.sent":
                    h.created_at = resp.sent_at if resp is not None and resp.sent_at else resolved_at
                elif h.event_type.startswith("review."):
                    h.created_at = min(base + timedelta(hours=1 + 20 * frac), resolved_at)
                elif h.to_status == "Closed":
                    h.created_at = c.closed_at or resolved_at
                else:
                    h.created_at = resolved_at
        audit.record(db, action="dataset.lifecycle_simulated", entity_type="dataset", entity_id="demo", actor_label=SEEDER_LABEL,
                     summary=f"Simulated history: {counts['resolved']} resolved, {counts['closed']} closed, {counts['reviewed']} reviews",
                     details=counts)
    return counts


def start_background_import() -> bool:
    global _thread
    if _thread is not None and _thread.is_alive():
        return False
    _thread = threading.Thread(target=_safe_import, name="dataset-import", daemon=True)
    _thread.start()
    return True


def _safe_import() -> None:
    try:
        import_dataset()
        if get_settings().seed_simulate_lifecycle:
            progress["lifecycle"] = simulate_lifecycle()
        with session_scope() as db:
            seed_users(db)  # link the demo customer login once dataset customers have complaints
    except Exception as exc:  # pragma: no cover
        log.exception("background dataset import failed")
        progress.update(state="failed", error=str(exc)[:300])
