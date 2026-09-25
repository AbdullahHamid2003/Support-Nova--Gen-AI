"""Load the rule matrix bundle from YAML (repository baseline) and build a :class:`RuleMatrix`.

A *bundle* is a plain dict with one entry per rule file. The database stores the
same structure, so the runtime-editable matrix and the version-controlled YAML
baseline are interchangeable.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import yaml

from supportnova.core.paths import CONFIG_DIR, RULES_DIR

from .models import (
    Action,
    Category,
    CategoryRule,
    ConditionalRouting,
    Department,
    EscalationLevel,
    EscalationRule,
    MissingInfoRule,
    Parameter,
    Product,
    ProhibitedAction,
    ResolutionRule,
    RoutingRule,
    RuleMatrix,
    SignalDefinition,
    SlaRule,
    Subcategory,
    UrgencyFloor,
)

# bundle key -> relative path (under the repository root)
BUNDLE_FILES: dict[str, tuple[Path, str]] = {
    "organization": (CONFIG_DIR, "organization.yaml"),
    "taxonomy": (CONFIG_DIR, "taxonomy.yaml"),
    "departments": (CONFIG_DIR, "departments.yaml"),
    "products": (CONFIG_DIR, "products.yaml"),
    "actions": (CONFIG_DIR, "actions.yaml"),
    "parameters": (RULES_DIR, "parameters.yaml"),
    "validation_policy": (RULES_DIR, "validation_policy.yaml"),
    "signals": (RULES_DIR, "complaint_rules/signals.yaml"),
    "category_rules": (RULES_DIR, "complaint_rules/category_rules.yaml"),
    "resolution_rules": (RULES_DIR, "complaint_rules/resolution_rules.yaml"),
    "priority_rules": (RULES_DIR, "complaint_rules/priority_rules.yaml"),
    "missing_info_rules": (RULES_DIR, "complaint_rules/missing_info_rules.yaml"),
    "followup_rules": (RULES_DIR, "complaint_rules/followup_rules.yaml"),
    "response_rules": (RULES_DIR, "complaint_rules/response_rules.yaml"),
    "review_rules": (RULES_DIR, "complaint_rules/review_rules.yaml"),
    "routing_rules": (RULES_DIR, "routing_rules/routing_rules.yaml"),
    "escalation_rules": (RULES_DIR, "escalation_rules/escalation_rules.yaml"),
    "sla_rules": (RULES_DIR, "sla_rules/sla_rules.yaml"),
    "precedence_rules": (RULES_DIR, "precedence/precedence_rules.yaml"),
}


class RuleMatrixError(ValueError):
    """Raised when the rule bundle is structurally invalid."""


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_bundle_from_yaml() -> dict[str, Any]:
    """Read every rule/config file into one bundle dict."""
    bundle: dict[str, Any] = {}
    for key, (base, rel) in BUNDLE_FILES.items():
        path = base / rel
        if not path.exists():
            raise RuleMatrixError(f"Missing rule file: {path}")
        bundle[key] = load_yaml(path) or {}
    return bundle


def _tuple(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (list, tuple)):
        return tuple(value)
    return (value,)


def _compile(patterns: Any) -> tuple[re.Pattern[str], ...]:
    compiled = []
    for pat in _tuple(patterns):
        try:
            compiled.append(re.compile(pat, re.IGNORECASE | re.DOTALL))
        except re.error as exc:  # pragma: no cover - config error surfaced to admins
            raise RuleMatrixError(f"Invalid regular expression {pat!r}: {exc}") from exc
    return tuple(compiled)


def build_matrix(bundle: dict[str, Any]) -> RuleMatrix:
    """Construct a :class:`RuleMatrix` from a bundle (YAML- or DB-sourced)."""
    b = copy.deepcopy(bundle)

    parameters = {
        key: Parameter(key=key, value=spec["value"], unit=spec.get("unit", ""), source=spec.get("source", ""),
                       description=spec.get("description", ""))
        for key, spec in (b["parameters"].get("parameters") or {}).items()
    }

    categories: dict[str, Category] = {}
    subcategories: dict[str, Subcategory] = {}
    for cat in b["taxonomy"].get("categories", []):
        categories[cat["code"]] = Category(cat["code"], cat["name"], cat.get("description", ""),
                                           cat.get("is_active", True))
        for sub in cat.get("subcategories", []):
            subcategories[sub["code"]] = Subcategory(sub["code"], sub["name"], cat["code"],
                                                     sub.get("description", ""), sub.get("is_active", True))

    departments = {
        d["code"]: Department(d["code"], d["name"], d.get("description", ""), d.get("is_active", True))
        for d in b["departments"].get("departments", [])
    }
    products = {
        p["sku"]: Product(sku=p["sku"], name=p["name"], line=p.get("line", ""), type=p.get("type", "device"),
                          price=float(p.get("price", 0)), warranty_months=p.get("warranty_months"),
                          hazard_class=p.get("hazard_class"), aliases=_tuple(p.get("aliases")))
        for p in b["products"].get("products", [])
    }
    actions = {
        a["code"]: Action(a["code"], a["name"], a.get("group", ""), a.get("description", ""))
        for a in b["actions"].get("actions", [])
    }
    prohibited = {
        p["code"]: ProhibitedAction(p["code"], p["name"], p.get("severity", "major"), _tuple(p.get("policy_refs")),
                                    _compile(p.get("patterns")))
        for p in b["actions"].get("prohibited_actions", [])
    }

    resolution_rules = [
        ResolutionRule(
            rule_id=r["rule_id"], name=r["name"], subcategory=r["subcategory"], precedence=int(r.get("precedence", 10)),
            when=r.get("when") or {}, urgency=r["urgency"], impact=r["impact"],
            required_actions=_tuple(r.get("required_actions")), recommended_actions=_tuple(r.get("recommended_actions")),
            prohibited_actions=_tuple(r.get("prohibited_actions")), eligibility=r.get("eligibility") or {},
            escalation=r.get("escalation", "No Escalation"), follow_up=r.get("follow_up") or {"required": False},
            timelines=_tuple(r.get("timelines")), policy_refs=_tuple(r.get("policy_refs")),
            department=r.get("department"), supporting_departments=_tuple(r.get("supporting_departments")),
            is_active=r.get("is_active", True),
        )
        for r in b["resolution_rules"].get("resolution_rules", [])
    ]

    esc = b["escalation_rules"]
    levels = [EscalationLevel(int(lv["rank"]), lv["name"], lv.get("action_code")) for lv in esc.get("levels", [])]
    levels.sort(key=lambda lv: lv.rank)
    escalation_rules = [
        EscalationRule(rule_id=e["rule_id"], name=e["name"], trigger=e.get("trigger", "other"), when=e.get("when") or {},
                       level=e["level"], departments=_tuple(e.get("departments")), policy_refs=_tuple(e.get("policy_refs")),
                       reason=e.get("reason", e["name"]), runtime_only=bool(e.get("runtime_only", False)),
                       is_active=e.get("is_active", True))
        for e in esc.get("escalation_rules", [])
    ]
    notes_fields = _tuple((esc.get("escalation_notes_requirements") or {}).get("required_fields"))

    rt = b["routing_rules"]
    routing = {
        r["subcategory"]: RoutingRule(r["rule_id"], r["subcategory"], r["primary_department"],
                                      _tuple(r.get("supporting_departments")), _tuple(r.get("policy_refs")))
        for r in rt.get("routing_rules", [])
    }
    conditional = [
        ConditionalRouting(c["rule_id"], c.get("name", c["rule_id"]), c.get("when") or {}, _tuple(c.get("add_supporting")),
                           _tuple(c.get("policy_refs")))
        for c in rt.get("conditional_routing", [])
    ]
    precedence_order = _tuple((rt.get("routing_precedence") or {}).get("order"))

    pr = b["priority_rules"]
    priority_matrix = {k: v for k, v in (pr.get("priority_matrix") or {}).items() if k != "policy_ref"}
    floors = [
        UrgencyFloor(f["rule_id"], f.get("name", f["rule_id"]), f.get("when") or {}, f.get("urgency"), f.get("impact"),
                     _tuple(f.get("policy_refs")))
        for f in pr.get("urgency_floors", [])
    ]

    mi = b["missing_info_rules"]
    missing = [
        MissingInfoRule(m["rule_id"], m["field"], m["label"], m.get("when") or {}, bool(m.get("blocking", False)),
                        m.get("question", ""), _tuple(m.get("keywords")), _tuple(m.get("policy_refs")))
        for m in mi.get("missing_info_rules", [])
    ]

    sla = {
        s["priority"]: SlaRule(s["rule_id"], s["priority"], float(s["first_response_hours"]),
                               float(s["resolution_hours"]), _tuple(s.get("policy_refs")))
        for s in b["sla_rules"].get("sla_rules", [])
    }

    cr = b["category_rules"]
    category_rules = {
        c["subcategory"]: CategoryRule(c["rule_id"], c["subcategory"],
                                       {str(k).lower(): float(v) for k, v in (c.get("terms") or {}).items()},
                                       {str(k).lower(): float(v) for k, v in (c.get("negative") or {}).items()},
                                       {str(k): float(v) for k, v in (c.get("signal_boosts") or {}).items()},
                                       {str(k): float(v) for k, v in (c.get("product_boosts") or {}).items()})
        for c in cr.get("category_rules", [])
    }

    sg = b["signals"]
    signals = {
        name: SignalDefinition(name, spec.get("name", name), tuple(str(t).lower() for t in _tuple(spec.get("terms"))),
                               _compile(spec.get("patterns")))
        for name, spec in (sg.get("signals") or {}).items()
    }

    matrix = RuleMatrix(
        parameters=parameters,
        categories=categories,
        subcategories=subcategories,
        departments=departments,
        products=products,
        actions=actions,
        prohibited_actions=prohibited,
        resolution_rules=resolution_rules,
        escalation_levels=levels,
        escalation_rules=escalation_rules,
        escalation_notes_fields=notes_fields,
        routing=routing,
        conditional_routing=conditional,
        routing_precedence=precedence_order,
        priority_matrix=priority_matrix,
        urgency_floors=floors,
        missing_info_rules=missing,
        never_block_categories=_tuple(mi.get("never_block_categories")),
        never_block_subcategories=_tuple(mi.get("never_block_subcategories")),
        follow_up_types=_tuple(b["followup_rules"].get("follow_up_types")),
        followup_rules=list(b["followup_rules"].get("followup_rules", [])),
        sla_rules=sla,
        category_rules=category_rules,
        category_settings={k: float(v) for k, v in (cr.get("settings") or {}).items()},
        signals=signals,
        negation_cues=tuple(str(c).lower() for c in _tuple(sg.get("negation_cues"))),
        negation_window=int(sg.get("negation_window", 3)),
        sentiment_config=sg.get("sentiment") or {},
        response_rules=b["response_rules"] or {},
        review_rules=list((b["review_rules"] or {}).get("review_rules", [])),
        precedence=b["precedence_rules"] or {},
        validation_policy=b["validation_policy"] or {},
        organization=b["organization"] or {},
        raw_bundle=bundle,
    )
    return matrix


def load_matrix() -> RuleMatrix:
    """Convenience: YAML baseline -> RuleMatrix."""
    return build_matrix(load_bundle_from_yaml())
