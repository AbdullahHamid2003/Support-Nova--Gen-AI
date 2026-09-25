"""Adversarial Lab (SRS Deliverable 10, live "deliberate defect" demonstrations).

Scenarios live in config/adversarial_scenarios.yaml. Each run creates a sandboxed complaint
(source ``lab``, ref ``LAB-#####``) for a fictional lab customer, with a simulated order whose dates
are relative to the run day, and processes it through the production pipeline - optionally with a
fault profile that corrupts the GenAI output. Afterwards the scenario's expectations are checked
against what Python validation actually did.
"""

from __future__ import annotations

import zlib
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from supportnova.audit import service as audit
from supportnova.core.errors import NotFound, ValidationFailed
from supportnova.core.paths import CONFIG_DIR, KNOWLEDGE_BASE_DIR
from supportnova.core.timeutil import utcnow
from supportnova.database.models import (
    Analysis,
    Complaint,
    Customer,
    Order,
    User,
    ValidationCheck,
    ValidationResult,
)
from supportnova.genai_pipeline.fault_injection import PROFILES
from supportnova.services.complaints import create_complaint
from supportnova.services.pipeline import PipelineOptions
from supportnova.services.rules import rule_service

SCENARIO_FILE = CONFIG_DIR / "adversarial_scenarios.yaml"
SECURITY_SAMPLES = KNOWLEDGE_BASE_DIR / "security_samples"
_cache: tuple[float, dict[str, Any]] | None = None


def load() -> dict[str, Any]:
    global _cache
    mtime = SCENARIO_FILE.stat().st_mtime if SCENARIO_FILE.exists() else 0.0
    if _cache is None or _cache[0] != mtime:
        data = yaml.safe_load(SCENARIO_FILE.read_text(encoding="utf-8")) if SCENARIO_FILE.exists() else {}
        _cache = (mtime, data or {})
    return _cache[1]


def scenarios() -> list[dict[str, Any]]:
    return list(load().get("scenarios", []))


def scenario(scenario_id: str) -> dict[str, Any]:
    for s in scenarios():
        if s["id"] == scenario_id:
            return s
    raise NotFound(f"Lab scenario {scenario_id} not found.")


def _lab_customer(db: Session) -> Customer:
    spec = load().get("lab_customer") or {"customer_ref": "CUST-99001", "full_name": "Lab Test Customer (fictional)"}
    row = db.execute(select(Customer).where(Customer.customer_ref == spec["customer_ref"])).scalar_one_or_none()
    if row is None:
        row = Customer(customer_ref=spec["customer_ref"], full_name=spec["full_name"],
                       email=spec.get("email", "lab.customer@customers.lumora.invalid"), customer_type=spec.get("customer_type", "individual"))
        db.add(row)
        db.flush()
    return row


def _day(today: date, days_ago: Any) -> str | None:
    return (today - timedelta(days=int(days_ago))).isoformat() if days_ago is not None else None


def build_order(spec: dict[str, Any], order_ref: str, customer_ref: str, today: date, price: float) -> dict[str, Any]:
    """Simulated ledger record (same shape as data/sample_complaints/orders.json)."""
    ordered = _day(today, spec.get("ordered_days_ago", 10))
    total = round(price + (0 if price >= 50 else 5.99), 2)
    txns = [{"txn_ref": f"TXN-99{order_ref[-6:]}", "type": "charge", "amount": total, "date": ordered}]
    if spec.get("double_charge"):
        txns.append({"txn_ref": f"TXN-98{order_ref[-6:]}", "type": "charge", "amount": total,
                     "date": _day(today, int(spec.get("ordered_days_ago", 10)) - 1)})
    ret = spec.get("return")
    if ret:
        ret = {"status": ret.get("status", "received"), "received_date": _day(today, ret.get("received_days_ago", 10)),
               "refund_issued": bool(ret.get("refund_issued", False))}
    delivered = _day(today, spec["delivered_days_ago"]) if spec.get("delivered_days_ago") is not None else None
    return {
        "order_ref": order_ref, "customer_ref": customer_ref,
        "items": [{"sku": spec["sku"], "qty": 1, "unit_price": price}], "order_total": total,
        "shipping_method": spec.get("shipping_method", "standard"), "shipping_fee": round(total - price, 2), "order_date": ordered,
        "estimated_delivery_date": _day(today, spec.get("eta_days_ago")) if spec.get("eta_days_ago") is not None else delivered,
        "dispatched_date": _day(today, spec.get("dispatched_days_ago", max(0, int(spec.get("ordered_days_ago", 10)) - 2))),
        "delivered_date": delivered, "status": spec.get("status", "delivered" if delivered else "in_transit"),
        "tracking_last_update": _day(today, spec.get("tracking_days_ago", spec.get("delivered_days_ago", 1))),
        "transactions": txns, "care_plus": bool(spec.get("care_plus", False)), "replacement_count": int(spec.get("replacement_count", 0)),
        "careplus_claims_12m": 0, "return": ret, "cancellation": spec.get("cancellation"), "subscription": spec.get("subscription"),
        "trace": spec.get("trace"),
    }


def _next_ref(db: Session) -> str:
    refs = db.execute(select(Complaint.complaint_ref).where(Complaint.complaint_ref.like("LAB-%"))).scalars().all()
    highest = max((int(r[4:]) for r in refs if r[4:].isdigit()), default=0)
    return f"LAB-{highest + 1:05d}"


def create_run(db: Session, *, actor: User, scenario_id: str | None = None, complaint: dict[str, Any] | None = None,
               fault_profile: str | None = None) -> tuple[Complaint, PipelineOptions]:
    """Create the lab complaint; the caller submits it to the worker with the returned options."""
    spec: dict[str, Any] = (scenario(scenario_id) if scenario_id
                            else {"id": None, "complaint": complaint or {}, "fault_profile": fault_profile})
    profile = fault_profile if fault_profile is not None else spec.get("fault_profile")
    if profile and profile not in PROFILES:
        raise ValidationFailed(f"Unknown fault profile '{profile}'.", details=[{"field": "fault_profile", "message": ", ".join(PROFILES)}])
    data = dict(spec.get("complaint") or {})
    if not data.get("title") or not data.get("description"):
        raise ValidationFailed("A lab complaint needs a title and a description.")
    customer = _lab_customer(db)
    order_spec = spec.get("order")
    if order_spec:
        matrix = rule_service.matrix(db)
        order_ref = str(data.get("order_ref") or f"LMR-99{zlib.crc32(str(spec['id']).encode()) % 10000:04d}").upper()
        product = matrix.products.get(order_spec["sku"])
        record = build_order(order_spec, order_ref, customer.customer_ref, utcnow().date(), float(product.price if product else 100.0))
        row = db.execute(select(Order).where(Order.order_ref == order_ref)).scalar_one_or_none()
        if row is None:
            row = Order(order_ref=order_ref)
            db.add(row)
        row.customer_id, row.order_date, row.order_total, row.status, row.data = (
            customer.id, date.fromisoformat(record["order_date"]), record["order_total"], record["status"], record)
        data.setdefault("order_ref", order_ref)
    data.setdefault("customer_type", customer.customer_type)
    data.setdefault("channel", "web_form")
    c = create_complaint(db, data, submitted_by=actor, customer=customer, source="lab", dataset_case_id=spec.get("id"),
                         complaint_ref=_next_ref(db), skip_duplicate_check=True, lenient=True)
    audit.record(db, action="lab.run_started", entity_type="complaint", entity_id=c.complaint_ref, actor=actor,
                 summary=f"Adversarial lab run {spec.get('id') or 'custom'} (fault profile: {profile or 'none'})",
                 details={"scenario": spec.get("id"), "fault_profile": profile})
    return c, PipelineOptions(trigger="lab", fault_profile=profile, actor_id=actor.id, auto_assign=False, link_duplicates=False)


def expectation_report(db: Session, c: Complaint) -> dict[str, Any]:
    spec = next((s for s in scenarios() if s["id"] == c.dataset_case_id), None)
    expect = (spec or {}).get("expect") or {}
    vr = db.execute(select(ValidationResult).where(ValidationResult.complaint_id == c.id).order_by(ValidationResult.id.desc())).scalars().first()
    analysis = db.execute(select(Analysis).where(Analysis.complaint_id == c.id).order_by(Analysis.id.desc())).scalars().first()
    checks = {ch.code: ch for ch in db.execute(select(ValidationCheck).where(ValidationCheck.result_id == vr.id)).scalars()} if vr else {}
    items: list[dict[str, Any]] = []
    if vr is None:
        return {"state": "pending" if c.processing_stage not in ("completed", "failed") else c.processing_stage, "met": None, "items": [],
                "fault_profile": analysis.fault_injection if analysis else None}
    if "verification" in expect:
        items.append({"expectation": "Verification decision", "expected": expect["verification"], "actual": c.verification_status,
                      "ok": c.verification_status == expect["verification"]})
    if "injection_detected" in expect:
        items.append({"expectation": "Prompt injection detected", "expected": expect["injection_detected"], "actual": c.injection_detected,
                      "ok": bool(c.injection_detected) == bool(expect["injection_detected"])})
    for code in expect.get("failed_checks", []):
        ch = checks.get(code)
        items.append({"expectation": f"{code} fails (the rule check caught the defect)", "expected": "fail", "actual": ch.status if ch else "not run",
                      "ok": bool(ch and ch.status == "fail"), "detail": ch.message if ch else None})
    for code in expect.get("passed_checks", []):
        ch = checks.get(code)
        items.append({"expectation": f"{code} passes", "expected": "pass", "actual": ch.status if ch else "not run",
                      "ok": bool(ch and ch.status in ("pass", "not_applicable")), "detail": ch.message if ch else None})
    vd = vr.validated_decision or {}
    final = {"urgency": vd.get("urgency"), "priority": vd.get("priority"), "department": vd.get("department"),
             "escalation_level": (vd.get("escalation") or {}).get("level"),
             "refund_eligibility": (vd.get("eligibility") or {}).get("refund"),
             "compensation_eligibility": (vd.get("eligibility") or {}).get("compensation"),
             "category": (vd.get("classification") or {}).get("category"), "subcategory": (vd.get("classification") or {}).get("subcategory")}
    for bad in expect.get("final_policy_refs_exclude", []):
        present = any(str(r).startswith(bad) for r in vd.get("policy_refs") or [])
        items.append({"expectation": f"Final decision never cites {bad}", "expected": "absent",
                      "actual": "present" if present else "absent", "ok": not present})
    for field, value in (expect.get("final") or {}).items():
        items.append({"expectation": f"Final {field.replace('_', ' ')}", "expected": value, "actual": final.get(field),
                      "ok": final.get(field) == value})
    return {"state": "completed", "met": all(i["ok"] for i in items) if items else None, "items": items,
            "fault_profile": analysis.fault_injection if analysis else None, "score": c.verification_score,
            "review_reasons": [r.get("code") for r in vr.review_reasons or []],
            "failed_checks": sorted(code for code, ch in checks.items() if ch.status == "fail")}


def list_runs(db: Session, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.execute(select(Complaint).where(Complaint.source == "lab").order_by(Complaint.id.desc()).limit(limit)).scalars().all()
    out = []
    names = {s["id"]: s for s in scenarios()}
    for c in rows:
        s = names.get(c.dataset_case_id or "")
        out.append({"complaint_ref": c.complaint_ref, "scenario_id": c.dataset_case_id, "scenario": s.get("name") if s else "Custom test",
                    "group": s.get("group") if s else "Custom", "title": c.title, "created_at": c.created_at.isoformat(),
                    "status": c.status, "processing_stage": c.processing_stage, "verification_status": c.verification_status,
                    "injection_detected": c.injection_detected, **expectation_report(db, c)})
    return out


def document_scan(data: bytes, file_name: str) -> dict[str, Any]:
    """Dry-run a document through parsing + injection screening without adding it to the knowledge base."""
    from supportnova.document_processing.chunking import chunk_sections
    from supportnova.document_processing.parsers import parse_document
    from supportnova.security import injection
    from supportnova.security.files import DOCUMENT_TYPES, validate_upload
    vf = validate_upload(file_name, data, allowed=DOCUMENT_TYPES, max_bytes=15 * 1024 * 1024)
    parsed = parse_document(data, vf.extension)
    sections = []
    for s in parsed.sections:
        rep = injection.scan(s.text)
        sections.append({"section_id": s.section_id, "heading": s.heading, "suspicious": rep.is_suspicious,
                         "risk_score": round(rep.risk_score, 3), "findings": rep.to_dict().get("findings", []),
                         "excerpt": s.text[:400]})
    meta = parsed.detected_metadata or {}
    chunks = chunk_sections(str(meta.get("doc_id") or "SCAN"), str(meta.get("version") or "0"), parsed.sections)
    return {"file_name": vf.file_name, "format": vf.extension, "title": parsed.title, "sections": sections,
            "chunks": len(chunks), "quarantined_sections": [s["section_id"] for s in sections if s["suspicious"]],
            "verdict": ("Malicious instructions found - these sections would be quarantined and never used as policy evidence."
                        if any(s["suspicious"] for s in sections) else "No embedded instructions found.")}


def security_samples() -> list[dict[str, Any]]:
    if not SECURITY_SAMPLES.exists():
        return []
    return [{"name": p.name, "size_bytes": p.stat().st_size} for p in sorted(SECURITY_SAMPLES.iterdir()) if p.is_file()]


def sample_path(name: str) -> Path:
    path = SECURITY_SAMPLES / Path(name).name
    if not path.exists():
        raise NotFound("Security sample not found.")
    return path
