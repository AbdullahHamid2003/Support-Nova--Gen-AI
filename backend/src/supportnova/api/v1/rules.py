"""Rule Matrix, taxonomy, prompt and GenAI configuration endpoints (SRS Steps 8, 14-15, 20, 48-49;
1.8(5) new category, 1.8(14) live modification). Every change is validated, versioned and audited."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

import yaml
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from supportnova.api.deps import db_session, require
from supportnova.api.serializers import iso
from supportnova.audit import service as audit
from supportnova.complaint_processing.fact_builder import build_perception
from supportnova.core.config import get_settings
from supportnova.core.errors import NotFound, ValidationFailed
from supportnova.database.models import (
    AIRun,
    Category,
    Complaint,
    Department,
    Order,
    Prompt,
    RuleRecord,
    Subcategory,
    User,
)
from supportnova.genai_pipeline import prompts as prompt_svc
from supportnova.genai_pipeline.fault_injection import PROFILES
from supportnova.genai_pipeline.providers import get_provider
from supportnova.rule_engine.conditions import describe
from supportnova.rule_engine.decision import DecisionEngine
from supportnova.rule_engine.integrity import summarize, validate_matrix
from supportnova.services.rules import CONFIG_ROWS, LIST_TYPES, bump_revision, rule_service

router = APIRouter(tags=["rules"])


def _rule_json(r: RuleRecord) -> dict[str, Any]:
    body = r.body or {}
    return {"rule_id": r.rule_id, "rule_type": r.rule_type, "name": r.name, "subcategory": r.subcategory_code, "is_active": r.is_active,
            "version": r.version, "updated_at": iso(r.updated_at), "body": body,
            "condition": describe(body.get("when")) if isinstance(body, dict) and "when" in body else None}


@router.get("/rules")
def list_rules(type: str | None = None, subcategory: str | None = None, q: str | None = None, active: bool | None = None,
               user: User = Depends(require("rules:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    query = select(RuleRecord).where(RuleRecord.rule_type != "config")
    if type:
        query = query.where(RuleRecord.rule_type == type)
    if subcategory:
        query = query.where(RuleRecord.subcategory_code == subcategory)
    if active is not None:
        query = query.where(RuleRecord.is_active.is_(active))
    rows = db.execute(query.order_by(RuleRecord.rule_type, RuleRecord.rule_id)).scalars().all()
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r.rule_id.lower() or ql in (r.name or "").lower() or ql in str(r.body).lower()]
    counts = dict(db.execute(select(RuleRecord.rule_type, func.count()).where(RuleRecord.rule_type != "config")
                             .group_by(RuleRecord.rule_type)).tuples().all())
    return {"items": [_rule_json(r) for r in rows], "total": len(rows), "counts": counts,
            "ruleset_hash": rule_service.matrix(db).ruleset_hash}


@router.get("/rules/meta")
def rules_meta(user: User = Depends(require("rules:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    m = rule_service.matrix(db)
    return {"actions": [asdict(a) for a in m.actions.values()],
            "prohibited_actions": [{"code": p.code, "name": p.name, "severity": p.severity} for p in m.prohibited_actions.values()],
            "signals": [{"name": s.name, "label": s.label, "terms": list(s.terms)[:12]} for s in m.signals.values()],
            "escalation_levels": [asdict(lv) for lv in m.escalation_levels], "follow_up_types": list(m.follow_up_types),
            "priority_matrix": m.priority_matrix, "rule_types": list(LIST_TYPES), "config_ids": list(CONFIG_ROWS),
            "parameters": {k: asdict(p) for k, p in m.parameters.items()},
            "sla": {k: asdict(v) for k, v in m.sla_rules.items()}}


@router.get("/rules/{rule_type}/{rule_id}")
def get_rule(rule_type: str, rule_id: str, user: User = Depends(require("rules:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    row = db.execute(select(RuleRecord).where(RuleRecord.rule_type == rule_type, RuleRecord.rule_id == rule_id)).scalar_one_or_none()
    if row is None:
        raise NotFound(f"Rule {rule_type}:{rule_id} not found.")
    return _rule_json(row)


class RuleBodyIn(BaseModel):
    body: dict[str, Any]
    is_active: bool = True


@router.put("/rules/{rule_type}/{rule_id}")
def upsert_rule(rule_type: str, rule_id: str, payload: RuleBodyIn, user: User = Depends(require("rules:manage")),
                db: Session = Depends(db_session)) -> dict[str, Any]:
    if rule_type == "config":
        row = rule_service.update_config(db, config_id=rule_id, body=payload.body, actor=user)
    else:
        body = dict(payload.body)
        body["rule_id"] = rule_id
        row = rule_service.upsert_rule(db, rule_type=rule_type, body=body, actor=user, is_active=payload.is_active)
    db.commit()
    return _rule_json(row)


class ActiveIn(BaseModel):
    active: bool


@router.post("/rules/{rule_type}/{rule_id}/active")
def toggle_rule(rule_type: str, rule_id: str, body: ActiveIn, user: User = Depends(require("rules:manage")),
                db: Session = Depends(db_session)) -> dict[str, Any]:
    row = rule_service.set_active(db, rule_type=rule_type, rule_id=rule_id, active=body.active, actor=user)
    db.commit()
    return _rule_json(row)


class ParameterIn(BaseModel):
    value: float | int | str
    reason: str = Field(default="", max_length=500)


@router.put("/rule-parameters/{key}")
def update_parameter(key: str, body: ParameterIn, user: User = Depends(require("rules:manage")),
                     db: Session = Depends(db_session)) -> dict[str, Any]:
    rule_service.update_parameter(db, key=key, value=body.value, actor=user, reason=body.reason)
    db.commit()
    p = rule_service.matrix(db).parameters[key]
    return asdict(p)


class RulePreviewIn(BaseModel):
    rule_type: str
    rule_id: str = Field(min_length=1, max_length=64)
    body: dict[str, Any]
    is_active: bool = True


@router.post("/rules/validate")
def validate_rules(payload: RulePreviewIn | None = None, user: User = Depends(require("rules:read")),
                   db: Session = Depends(db_session)) -> dict[str, Any]:
    """Integrity check of the live Rule Matrix - or, with a body, of the matrix as it would be after that
    (unsaved) edit. The preview writes nothing: no rule change, no revision bump, no audit entry."""
    from supportnova.knowledge_base.store import knowledge_service
    if payload is not None:
        report = rule_service.preview(db, rule_type=payload.rule_type, rule_id=payload.rule_id, body=payload.body,
                                      is_active=payload.is_active)
        return {**report, "preview": True, "rule_type": payload.rule_type, "rule_id": payload.rule_id}
    matrix = rule_service.matrix(db)
    snap = knowledge_service.snapshot(db, matrix)
    report = summarize(validate_matrix(matrix, kb_sections=snap.active_section_keys(date.today())))
    return {**report, "ruleset_hash": matrix.ruleset_hash,
            "counts": {"resolution": len(matrix.resolution_rules), "escalation": len(matrix.escalation_rules),
                       "routing": len(matrix.routing), "category": len(matrix.category_rules), "signals": len(matrix.signals),
                       "missing_info": len(matrix.missing_info_rules), "urgency_floors": len(matrix.urgency_floors),
                       "parameters": len(matrix.parameters), "sla": len(matrix.sla_rules)}}


class SimulateIn(BaseModel):
    title: str = ""
    description: str
    product_text: str = ""
    order_ref: str | None = None
    customer_type: str = "individual"
    requested_resolution: str = "none"
    subcategory_override: str | None = None


@router.post("/rules/simulate")
def simulate(body: SimulateIn, user: User = Depends(require("rules:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    """Rule Simulator: run ONLY the deterministic Python pipeline (no GenAI) on a text - shows which
    signals, classification rules, resolution/escalation rules fire. Used to demonstrate live rule edits."""
    matrix = rule_service.matrix(db)
    order = None
    lookup = False
    if body.order_ref:
        row = db.execute(select(Order).where(Order.order_ref == body.order_ref.upper())).scalar_one_or_none()
        order, lookup = (dict(row.data) if row else {}), True
    perception = build_perception(matrix, title=body.title, description=body.description, product_text=body.product_text,
                                  order_ref=body.order_ref, customer_type=body.customer_type,
                                  requested_resolution=body.requested_resolution, order=order, order_lookup_attempted=lookup,
                                  customer_ref=(order or {}).get("customer_ref"))
    sub = body.subcategory_override or perception.classification.primary
    decision = DecisionEngine(matrix).decide(perception.context(matrix), sub, perception.classification.secondary)
    return {"signals": perception.signal_summary(), "classification": perception.classification.to_dict(),
            "sentiment": asdict(perception.sentiment), "entities": [asdict(e) for e in perception.entities.entities],
            "facts": perception.facts, "decision": decision.to_dict(), "ruleset_hash": matrix.ruleset_hash}


@router.get("/rules/export")
def export_rules(format: str = Query(default="xlsx", pattern="^(csv|xlsx|yaml|pdf)$"), user: User = Depends(require("rules:read")),
                 db: Session = Depends(db_session)) -> Response:
    """Complaint Resolution Rule Matrix deliverable: Rule ID, Category, Subcategory, Conditions, Department,
    Urgency, Priority, Policy, Escalation, Required actions, Prohibited actions, Follow-up."""
    from supportnova.reporting.exports import tabular
    from supportnova.services.rules import bundle_from_db
    matrix = rule_service.matrix(db)
    if format == "yaml":
        return Response(yaml.safe_dump(bundle_from_db(db), sort_keys=False, allow_unicode=True), media_type="application/x-yaml",
                        headers={"Content-Disposition": 'attachment; filename="supportnova-rule-matrix.yaml"'})
    rows = []
    for r in matrix.resolution_rules:
        cat = matrix.category_of(r.subcategory)
        routing = matrix.routing.get(r.subcategory)
        rows.append([r.rule_id, matrix.categories[cat].name if cat in matrix.categories else cat,
                     matrix.subcategories[r.subcategory].name if r.subcategory in matrix.subcategories else r.subcategory,
                     describe(r.when), r.department or (routing.primary_department if routing else ""),
                     ", ".join(r.supporting_departments or (routing.supporting_departments if routing else ())),
                     r.urgency, r.impact, matrix.compute_priority(r.urgency, r.impact), "; ".join(r.policy_refs), r.escalation,
                     ", ".join(a if isinstance(a, str) else " or ".join(a.get("any_of", [])) for a in r.required_actions),
                     ", ".join(r.prohibited_actions),
                     f"{r.follow_up.get('type')} ({r.follow_up.get('due_hours')}h)" if r.follow_up.get("required") else "none",
                     "active" if r.is_active else "inactive"])
    for e in matrix.escalation_rules:
        rows.append([e.rule_id, "(all)", "(all)", describe(e.when), ", ".join(e.departments), "", "", "", "", "; ".join(e.policy_refs),
                     e.level, "", "", "Escalation acknowledgement", "active" if e.is_active else "inactive"])
    cols = ["Rule ID", "Category", "Subcategory", "Conditions", "Department", "Supporting", "Urgency", "Impact", "Priority", "Policy",
            "Escalation", "Required actions", "Prohibited actions", "Follow-up", "Status"]
    content, media, ext = tabular("Complaint Resolution Rule Matrix", cols, rows, format)
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="supportnova-rule-matrix.{ext}"'})


# ------------------------------------------------------------------ taxonomy (new category / department)
@router.get("/taxonomy")
def taxonomy(user: User = Depends(require("rules:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    cats = db.execute(select(Category).options(selectinload(Category.subcategories)).order_by(Category.code)).scalars().all()
    matrix = rule_service.matrix(db)
    return {"categories": [{"code": c.code, "name": c.name, "description": c.description, "is_active": c.is_active,
                            "subcategories": [{"code": s.code, "name": s.name, "description": s.description, "is_active": s.is_active,
                                               "rules": len(matrix.rules_for(s.code)),
                                               "department": matrix.routing[s.code].primary_department if s.code in matrix.routing else None,
                                               "has_classifier": s.code in matrix.category_rules}
                                              for s in c.subcategories]} for c in cats],
            "departments": [{"code": d.code, "name": d.name, "description": d.description, "is_active": d.is_active}
                            for d in db.execute(select(Department).order_by(Department.code)).scalars()]}


class CategoryIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z]{3,4}$")
    name: str = Field(min_length=3, max_length=120)
    description: str = ""


@router.post("/taxonomy/categories", status_code=201)
def create_category(body: CategoryIn, user: User = Depends(require("taxonomy:manage")), db: Session = Depends(db_session)) -> dict[str, Any]:
    if db.execute(select(Category).where(Category.code == body.code)).first():
        raise ValidationFailed(f"Category {body.code} already exists.")
    db.add(Category(code=body.code, name=body.name, description=body.description))
    db.flush()
    bump_revision(db)
    rule_service.invalidate()
    audit.record(db, action="taxonomy.category_created", entity_type="category", entity_id=body.code, actor=user,
                 summary=f"Category {body.code} {body.name} created", details=body.model_dump())
    db.commit()
    return body.model_dump()


class SubcategoryIn(BaseModel):
    code: str = Field(pattern=r"^[A-Z]{3,4}-[A-Z]{3}$")
    category: str
    name: str = Field(min_length=3, max_length=120)
    description: str = ""
    department: str
    supporting_departments: list[str] = []
    urgency: str = "Medium"
    impact: str = "Medium"
    required_actions: list[str] = ["REQUEST_ADDITIONAL_INFO"]
    prohibited_actions: list[str] = ["GUARANTEE_COMPENSATION"]
    policy_refs: list[str] = []
    follow_up_type: str | None = "Resolution confirmation"
    follow_up_hours: int = 72
    keywords: dict[str, float] = {}


@router.post("/taxonomy/subcategories", status_code=201)
def create_subcategory(body: SubcategoryIn, user: User = Depends(require("taxonomy:manage")), db: Session = Depends(db_session)) -> dict[str, Any]:
    """Adds a subcategory together with its routing rule, default resolution rule and classification rule
    in one validated transaction - a new complaint category needs no code change (SRS 1.8(5))."""
    cat = db.execute(select(Category).where(Category.code == body.category)).scalar_one_or_none()
    if cat is None:
        raise ValidationFailed("Unknown category.")
    if db.execute(select(Subcategory).where(Subcategory.code == body.code)).first():
        raise ValidationFailed(f"Subcategory {body.code} already exists.")
    db.add(Subcategory(code=body.code, name=body.name, description=body.description, category_id=cat.id))
    db.flush()
    rule_service.invalidate()
    routing = {"rule_id": f"RTE-{body.code}", "subcategory": body.code, "primary_department": body.department,
               "supporting_departments": body.supporting_departments, "policy_refs": body.policy_refs or ["RTE-RUL-14:3"]}
    resolution = {"rule_id": f"RES-{body.code}-01", "name": f"{body.name} - default handling", "subcategory": body.code, "precedence": 10,
                  "when": {}, "urgency": body.urgency, "impact": body.impact, "required_actions": body.required_actions,
                  "recommended_actions": [], "prohibited_actions": body.prohibited_actions,
                  "eligibility": {"refund": "requires_verification", "replacement": "not_applicable", "compensation": "not_applicable"},
                  "escalation": "No Escalation",
                  "follow_up": ({"required": True, "type": body.follow_up_type, "due_hours": body.follow_up_hours}
                                if body.follow_up_type else {"required": False}),
                  "timelines": [], "policy_refs": body.policy_refs}
    category_rule = {"rule_id": f"CAT-{body.code}", "subcategory": body.code,
                     "terms": body.keywords or {w.lower(): 3.0 for w in body.name.split() if len(w) > 3}}
    for rule_type, rule in (("routing", routing), ("resolution", resolution), ("category", category_rule)):
        db.add(RuleRecord(rule_id=rule["rule_id"], rule_type=rule_type, subcategory_code=body.code, name=rule.get("name", rule["rule_id"]),
                          body=rule, is_active=True, updated_by_id=user.id))
    db.flush()
    from supportnova.rule_engine.loader import build_matrix
    from supportnova.services.rules import bundle_from_db
    report = summarize(validate_matrix(build_matrix(bundle_from_db(db))))
    if not report["valid"]:
        db.rollback()
        raise ValidationFailed("The new subcategory would make the Rule Matrix invalid.", details=report["issues"])
    bump_revision(db)
    rule_service.invalidate()
    audit.record(db, action="taxonomy.subcategory_created", entity_type="subcategory", entity_id=body.code, actor=user,
                 summary=f"Subcategory {body.code} {body.name} created with routing, resolution and classification rules",
                 details=body.model_dump())
    db.commit()
    return {"code": body.code, "rules": [routing["rule_id"], resolution["rule_id"], category_rule["rule_id"]], "warnings": report["warnings"]}


class DepartmentIn(BaseModel):
    code: str = Field(pattern=r"^DEPT-[A-Z]{3}$")
    name: str = Field(min_length=3, max_length=120)
    description: str = ""


@router.post("/taxonomy/departments", status_code=201)
def create_department(body: DepartmentIn, user: User = Depends(require("taxonomy:manage")), db: Session = Depends(db_session)) -> dict[str, Any]:
    if db.execute(select(Department).where(Department.code == body.code)).first():
        raise ValidationFailed(f"Department {body.code} already exists.")
    db.add(Department(code=body.code, name=body.name, description=body.description))
    db.flush()
    bump_revision(db)
    rule_service.invalidate()
    audit.record(db, action="taxonomy.department_created", entity_type="department", entity_id=body.code, actor=user,
                 summary=f"Department {body.code} {body.name} created")
    db.commit()
    return body.model_dump()


# ------------------------------------------------------------------ prompts
@router.get("/prompts")
def list_prompts(user: User = Depends(require("rules:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    rows = db.execute(select(Prompt).options(selectinload(Prompt.versions)).order_by(Prompt.prompt_key)).scalars().all()
    return {"items": [{"key": p.prompt_key, "description": p.description,
                       "versions": [{"version": v.version, "status": v.status, "output_schema": v.output_schema, "params": v.params,
                                     "changelog": v.changelog, "sha256": v.sha256, "created_at": iso(v.created_at),
                                     "system_template": v.system_template, "user_template": v.user_template} for v in p.versions]}
                      for p in rows]}


class PromptVersionIn(BaseModel):
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    system_template: str = Field(min_length=50)
    user_template: str = Field(min_length=20)
    output_schema: str
    params: dict[str, Any] = {}
    changelog: str = Field(min_length=3)
    activate: bool = False


@router.post("/prompts/{key}/versions", status_code=201)
def create_prompt_version(key: str, body: PromptVersionIn, user: User = Depends(require("prompts:manage")),
                          db: Session = Depends(db_session)) -> dict[str, Any]:
    row = prompt_svc.create_version(db, key=key, version=body.version, system_template=body.system_template,
                                    user_template=body.user_template, output_schema=body.output_schema, params=body.params,
                                    changelog=body.changelog, actor=user, activate=body.activate)
    db.commit()
    return {"key": key, "version": row.version, "status": row.status, "sha256": row.sha256}


@router.post("/prompts/{key}/versions/{version}/activate")
def activate_prompt(key: str, version: str, user: User = Depends(require("prompts:manage")), db: Session = Depends(db_session)) -> dict[str, Any]:
    row = prompt_svc.activate_version(db, key=key, version=version, actor=user)
    db.commit()
    return {"key": key, "version": row.version, "status": row.status}


# ------------------------------------------------------------------ GenAI status & run evidence
@router.get("/ai/status")
def ai_status(user: User = Depends(require("rules:read"))) -> dict[str, Any]:
    s = get_settings()
    provider = get_provider()
    return {"configured_provider": s.ai_provider, "resolved_provider": s.resolved_provider, "active_provider": provider.describe(),
            "api_key_configured": s.ai_configured,
            "timeout_seconds": s.ai_timeout_seconds, "max_attempts": 1 + s.ai_max_retries, "embedding_provider": s.embedding_provider,
            "fault_profiles": PROFILES,
            "notice": None if s.ai_configured else
            ("No AI_API_KEY is set on the server, so the AI step is off. Each complaint is still checked by the rules and "
             "sent to manual review. Add AI_API_KEY to .env.secrets and restart the backend.")}


@router.get("/ai/runs")
def ai_runs(failed_only: bool = False, stage: str | None = None, limit: int = Query(default=50, le=500),
            user: User = Depends(require("evaluation:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    query = select(AIRun)
    if failed_only:
        query = query.where(AIRun.parsed_ok.is_(False))
    if stage:
        query = query.where(AIRun.stage == stage)
    rows = db.execute(query.order_by(AIRun.id.desc()).limit(limit)).scalars().all()
    stats = dict(db.execute(select(AIRun.parsed_ok, func.count()).group_by(AIRun.parsed_ok)).tuples().all())
    ids = {r.complaint_id for r in rows if r.complaint_id}
    refs = dict(db.execute(select(Complaint.id, Complaint.complaint_ref).where(Complaint.id.in_(ids))).tuples().all()) if ids else {}
    return {"items": [{"id": r.id, "complaint_id": r.complaint_id, "complaint_ref": refs.get(r.complaint_id) if r.complaint_id else None,
                       "stage": r.stage, "attempt": r.attempt, "provider": r.provider,
                       "model": r.model, "prompt": f"{r.prompt_key}@{r.prompt_version}", "parsed_ok": r.parsed_ok,
                       "error_type": r.error_type, "error_message": r.error_message, "latency_ms": r.latency_ms,
                       "fault_injection": r.fault_injection, "at": iso(r.created_at)} for r in rows],
            "stats": {"valid": stats.get(True, 0), "invalid": stats.get(False, 0)}}



@router.post("/rules/reset-to-baseline")
def reset_to_baseline(confirm: bool = False, user: User = Depends(require("rules:manage")),
                      db: Session = Depends(db_session)) -> dict[str, Any]:
    """Reload the Rule Matrix from the versioned YAML baseline in rules/ and config/ (discards database
    edits; the previous state stays in the audit trail)."""
    from supportnova.services.rules import seed_from_yaml
    if not confirm:
        raise ValidationFailed("Pass confirm=true to replace the live Rule Matrix with the YAML baseline.")
    before = rule_service.matrix(db).ruleset_hash
    count = seed_from_yaml(db, force=True)
    rule_service.invalidate()
    after = rule_service.matrix(db)
    issues = validate_matrix(after)
    audit.record(db, action="rules.reset_to_baseline", entity_type="rules", entity_id="matrix", actor=user,
                 summary=f"Rule Matrix reloaded from YAML ({count} rules)", details={"before": before, "after": after.ruleset_hash})
    db.commit()
    return {"rules": count, "ruleset_hash": after.ruleset_hash, "previous_hash": before, "integrity": summarize(issues)}
