"""Runtime Rule Matrix service (SRS 1.8(14) Live Modification Challenge).

The YAML files are the version-controlled baseline; the database holds the live, editable
copy. Every edit is validated by building a candidate matrix and running the integrity
checks BEFORE it is saved; accepted edits are versioned and audited, and take effect
immediately (the cached matrix is rebuilt when the rules revision changes).
"""

from __future__ import annotations

import copy
import threading
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from supportnova.audit import service as audit
from supportnova.core.errors import NotFound, ValidationFailed
from supportnova.database.models import (
    Category,
    Department,
    Product,
    RuleRecord,
    Subcategory,
    SystemSetting,
    User,
)
from supportnova.rule_engine.integrity import IntegrityIssue, summarize, validate_matrix
from supportnova.rule_engine.loader import build_matrix, load_bundle_from_yaml
from supportnova.rule_engine.models import RuleMatrix

RULES_REVISION_KEY = "rules_revision"

# rule_type -> (bundle key, list key inside that bundle entry, id field)
LIST_TYPES: dict[str, tuple[str, str, str]] = {
    "resolution": ("resolution_rules", "resolution_rules", "rule_id"),
    "escalation": ("escalation_rules", "escalation_rules", "rule_id"),
    "routing": ("routing_rules", "routing_rules", "rule_id"),
    "conditional_routing": ("routing_rules", "conditional_routing", "rule_id"),
    "urgency_floor": ("priority_rules", "urgency_floors", "rule_id"),
    "category": ("category_rules", "category_rules", "rule_id"),
    "missing_info": ("missing_info_rules", "missing_info_rules", "rule_id"),
    "followup": ("followup_rules", "followup_rules", "rule_id"),
    "sla": ("sla_rules", "sla_rules", "rule_id"),
    "review": ("review_rules", "review_rules", "rule_id"),
}
# config rows: rule_id -> (bundle key, keys copied from that bundle entry). None = whole entry.
CONFIG_ROWS: dict[str, tuple[str, list[str] | None]] = {
    "escalation_config": ("escalation_rules", ["levels", "escalation_notes_requirements"]),
    "routing_precedence": ("routing_rules", ["routing_precedence"]),
    "priority_config": ("priority_rules", ["urgency_levels", "impact_levels", "priority_levels", "priority_matrix", "principles"]),
    "category_settings": ("category_rules", ["settings"]),
    "missing_info_config": ("missing_info_rules", ["never_block_categories", "never_block_subcategories"]),
    "followup_config": ("followup_rules", ["follow_up_types"]),
    "sla_config": ("sla_rules", ["at_risk_param", "states"]),
    "signals": ("signals", None),
    "parameters": ("parameters", None),
    "response_rules": ("response_rules", None),
    "precedence_rules": ("precedence_rules", None),
    "validation_policy": ("validation_policy", None),
    "actions": ("actions", None),
    "organization": ("organization", None),
}


def _subcategory_of(rule_type: str, body: dict[str, Any]) -> str | None:
    return body.get("subcategory") if rule_type in ("resolution", "routing", "category") else None


def seed_from_yaml(db: Session, *, force: bool = False) -> int:
    """Load the YAML baseline into the database (taxonomy, departments, products, rules)."""
    if not force and db.execute(select(RuleRecord.id).limit(1)).first():
        return 0
    bundle = load_bundle_from_yaml()
    if force:
        db.query(RuleRecord).delete()
    for d in bundle["departments"]["departments"]:
        if not db.execute(select(Department).where(Department.code == d["code"])).scalar_one_or_none():
            db.add(Department(code=d["code"], name=d["name"], description=d.get("description", "")))
    for c in bundle["taxonomy"]["categories"]:
        cat = db.execute(select(Category).where(Category.code == c["code"])).scalar_one_or_none()
        if not cat:
            cat = Category(code=c["code"], name=c["name"], description=c.get("description", ""))
            db.add(cat)
            db.flush()
        for s in c.get("subcategories", []):
            if not db.execute(select(Subcategory).where(Subcategory.code == s["code"])).scalar_one_or_none():
                db.add(Subcategory(code=s["code"], name=s["name"], description=s.get("description", ""), category_id=cat.id))
    for p in bundle["products"]["products"]:
        if not db.execute(select(Product).where(Product.sku == p["sku"])).scalar_one_or_none():
            db.add(Product(sku=p["sku"], name=p["name"], line=p.get("line", ""), type=p.get("type", "device"),
                           price=float(p.get("price", 0)), warranty_months=p.get("warranty_months"),
                           hazard_class=p.get("hazard_class"), aliases=list(p.get("aliases", []))))
    count = 0
    for rule_type, (bkey, lkey, idf) in LIST_TYPES.items():
        for body in bundle[bkey].get(lkey, []) or []:
            db.add(RuleRecord(rule_id=str(body[idf]), rule_type=rule_type, subcategory_code=_subcategory_of(rule_type, body),
                              name=str(body.get("name", body.get("code", body[idf])))[:200], body=body, is_active=True))
            count += 1
    for rule_id, (bkey, keys) in CONFIG_ROWS.items():
        entry = bundle[bkey]
        body = entry if keys is None else {k: entry.get(k) for k in keys}
        db.add(RuleRecord(rule_id=rule_id, rule_type="config", name=rule_id, body=body, is_active=True))
    db.flush()
    bump_revision(db)
    return count


def bundle_from_db(db: Session) -> dict[str, Any]:
    """Rebuild a bundle (same shape as the YAML files) from the database."""
    rows = db.execute(select(RuleRecord)).scalars().all()
    configs = {r.rule_id: r.body for r in rows if r.rule_type == "config"}
    bundle: dict[str, Any] = {key: {} for key in ("organization", "taxonomy", "departments", "products", "actions",
                                                  "parameters", "validation_policy", "signals", "category_rules",
                                                  "resolution_rules", "priority_rules", "missing_info_rules",
                                                  "followup_rules", "response_rules", "review_rules", "routing_rules",
                                                  "escalation_rules", "sla_rules", "precedence_rules")}
    for rule_id, (bkey, keys) in CONFIG_ROWS.items():
        body = copy.deepcopy(configs.get(rule_id) or {})
        if keys is None:
            bundle[bkey] = body
        else:
            bundle[bkey].update(body)
    for rule_type, (bkey, lkey, _idf) in LIST_TYPES.items():
        items = [dict(r.body, is_active=r.is_active) for r in rows if r.rule_type == rule_type]
        items.sort(key=lambda b: str(b.get("rule_id", "")))
        bundle[bkey][lkey] = items
    cats = db.execute(select(Category)).scalars().all()
    bundle["taxonomy"] = {"categories": [
        {"code": c.code, "name": c.name, "description": c.description, "is_active": c.is_active,
         "subcategories": [{"code": s.code, "name": s.name, "description": s.description, "is_active": s.is_active}
                           for s in c.subcategories]} for c in sorted(cats, key=lambda c: c.code)]}
    bundle["departments"] = {"departments": [
        {"code": d.code, "name": d.name, "description": d.description, "is_active": d.is_active}
        for d in db.execute(select(Department).order_by(Department.code)).scalars()]}
    bundle["products"] = {"products": [
        {"sku": p.sku, "name": p.name, "line": p.line, "type": p.type, "price": p.price, "warranty_months": p.warranty_months,
         "hazard_class": p.hazard_class, "aliases": list(p.aliases or [])}
        for p in db.execute(select(Product).order_by(Product.sku)).scalars()]}
    return bundle


def current_revision(db: Session) -> int:
    row = db.get(SystemSetting, RULES_REVISION_KEY)
    return int((row.value or {}).get("value", 0)) if row else 0


def bump_revision(db: Session) -> int:
    row = db.get(SystemSetting, RULES_REVISION_KEY)
    if row is None:
        db.add(SystemSetting(key=RULES_REVISION_KEY, value={"value": 1}))
        db.flush()
        return 1
    new = int((row.value or {}).get("value", 0)) + 1
    row.value = {"value": new}
    db.flush()
    return new


class RuleService:
    """Caches the live RuleMatrix; rebuilt when the rules revision changes."""

    def __init__(self) -> None:
        self._matrix: RuleMatrix | None = None
        self._revision = -1
        self._lock = threading.Lock()

    def matrix(self, db: Session) -> RuleMatrix:
        revision = current_revision(db)
        if self._matrix is not None and revision == self._revision:
            return self._matrix
        with self._lock:
            if self._matrix is None or revision != self._revision:
                if revision == 0:
                    self._matrix = build_matrix(load_bundle_from_yaml())
                else:
                    self._matrix = build_matrix(bundle_from_db(db))
                self._revision = revision
            return self._matrix

    def invalidate(self) -> None:
        with self._lock:
            self._matrix = None
            self._revision = -1

    # ---- editing ----------------------------------------------------------------
    def _candidate_report(self, db: Session, mutate: Any) -> dict[str, Any]:
        """Integrity report of the live matrix with ``mutate`` applied - nothing is written."""
        bundle = bundle_from_db(db)
        mutate(bundle)
        try:
            matrix = build_matrix(bundle)
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            detail = f"missing field {exc}" if isinstance(exc, KeyError) else str(exc)
            return summarize([IntegrityIssue("error", "-", f"The rule could not be built: {detail}")])
        return summarize(validate_matrix(matrix))

    def _candidate(self, db: Session, mutate: Any) -> dict[str, Any]:
        report = self._candidate_report(db, mutate)
        if not report["valid"]:
            raise ValidationFailed("The change would make the Rule Matrix invalid.", details=report["issues"])
        return report

    @staticmethod
    def _list_mutation(rule_type: str, body: dict[str, Any], is_active: bool) -> tuple[str, Any]:
        if rule_type not in LIST_TYPES:
            raise ValidationFailed(f"Unknown rule type '{rule_type}'.")
        bkey, lkey, idf = LIST_TYPES[rule_type]
        rule_id = str(body.get(idf) or "").strip()
        if not rule_id:
            raise ValidationFailed(f"'{idf}' is required.")

        def mutate(bundle: dict[str, Any]) -> None:
            items = [b for b in bundle[bkey].get(lkey, []) if str(b.get(idf)) != rule_id]
            items.append(dict(body, is_active=is_active))
            bundle[bkey][lkey] = items
        return rule_id, mutate

    @staticmethod
    def _config_mutation(config_id: str, body: dict[str, Any]) -> Any:
        if config_id not in CONFIG_ROWS:
            raise ValidationFailed(f"Unknown configuration '{config_id}'.")
        bkey, keys = CONFIG_ROWS[config_id]

        def mutate(bundle: dict[str, Any]) -> None:
            if keys is None:
                bundle[bkey] = copy.deepcopy(body)
            else:
                bundle[bkey].update(copy.deepcopy(body))
        return mutate

    def preview(self, db: Session, *, rule_type: str, rule_id: str, body: dict[str, Any], is_active: bool = True) -> dict[str, Any]:
        """Validate an edit WITHOUT saving it (the rule editor's Validate button)."""
        if rule_type == "config":
            return self._candidate_report(db, self._config_mutation(rule_id, body))
        body = dict(body)
        body[LIST_TYPES[rule_type][2] if rule_type in LIST_TYPES else "rule_id"] = rule_id
        return self._candidate_report(db, self._list_mutation(rule_type, body, is_active)[1])

    def upsert_rule(self, db: Session, *, rule_type: str, body: dict[str, Any], actor: User | None,
                    is_active: bool = True) -> RuleRecord:
        rule_id, mutate = self._list_mutation(rule_type, body, is_active)
        report = self._candidate(db, mutate)
        row = db.execute(select(RuleRecord).where(RuleRecord.rule_type == rule_type, RuleRecord.rule_id == rule_id)
                         ).scalar_one_or_none()
        before = dict(row.body) if row else None
        if row is None:
            row = RuleRecord(rule_id=rule_id, rule_type=rule_type, body=body, is_active=is_active, version=1,
                             subcategory_code=_subcategory_of(rule_type, body), name=str(body.get("name", rule_id))[:200])
            db.add(row)
        else:
            row.body = body
            row.is_active = is_active
            row.version += 1
            row.name = str(body.get("name", rule_id))[:200]
            row.subcategory_code = _subcategory_of(rule_type, body)
        row.updated_by_id = actor.id if actor else None
        db.flush()
        audit.record(db, action="rule.created" if before is None else "rule.updated", entity_type="rule",
                     entity_id=f"{rule_type}:{rule_id}", actor=actor,
                     summary=f"{'Created' if before is None else 'Updated'} {rule_type} rule {rule_id} (v{row.version})",
                     details={"before": before, "after": body, "is_active": is_active, "warnings": report["warnings"]})
        bump_revision(db)
        self.invalidate()
        return row

    def set_active(self, db: Session, *, rule_type: str, rule_id: str, active: bool, actor: User | None) -> RuleRecord:
        row = db.execute(select(RuleRecord).where(RuleRecord.rule_type == rule_type, RuleRecord.rule_id == rule_id)
                         ).scalar_one_or_none()
        if not row:
            raise NotFound(f"Rule {rule_type}:{rule_id} not found.")
        return self.upsert_rule(db, rule_type=rule_type, body=dict(row.body), actor=actor, is_active=active)

    def update_config(self, db: Session, *, config_id: str, body: dict[str, Any], actor: User | None) -> RuleRecord:
        report = self._candidate(db, self._config_mutation(config_id, body))
        row = db.execute(select(RuleRecord).where(RuleRecord.rule_type == "config", RuleRecord.rule_id == config_id)
                         ).scalar_one()
        before = copy.deepcopy(row.body)
        row.body = body
        row.version += 1
        row.updated_by_id = actor.id if actor else None
        db.flush()
        audit.record(db, action="rule.config_updated", entity_type="rule", entity_id=f"config:{config_id}", actor=actor,
                     summary=f"Updated rule configuration {config_id} (v{row.version})",
                     details={"before": before, "after": body, "warnings": report["warnings"]})
        bump_revision(db)
        self.invalidate()
        return row

    def update_parameter(self, db: Session, *, key: str, value: Any, actor: User | None, reason: str = "") -> RuleRecord:
        row = db.execute(select(RuleRecord).where(RuleRecord.rule_type == "config", RuleRecord.rule_id == "parameters")
                         ).scalar_one()
        body = copy.deepcopy(row.body)
        params = body.get("parameters") or {}
        if key not in params:
            raise NotFound(f"Parameter '{key}' not found.")
        old = params[key].get("value")
        params[key]["value"] = value
        updated = self.update_config(db, config_id="parameters", body=body, actor=actor)
        audit.record(db, action="rule.parameter_changed", entity_type="rule_parameter", entity_id=key, actor=actor,
                     summary=f"Parameter {key} changed from {old} to {value}", details={"old": old, "new": value, "reason": reason})
        return updated


rule_service = RuleService()
