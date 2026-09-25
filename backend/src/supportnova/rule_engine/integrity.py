"""Rule Matrix integrity validation - catches broken references before they reach production
(used by `scripts/validate_rules.py`, `POST /api/v1/rules/validate`, rule edits and tests).

Detects: unknown subcategories/departments/actions/signals/parameters/levels, subcategories
without a default rule or routing entry, missing classification rules, malformed conditions,
priority-matrix gaps, SLA gaps, duplicate IDs and policy references that do not exist in the
knowledge base (when a KB section index is supplied).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .conditions import ConditionError, EvalContext, evaluate, referenced_facts, referenced_signals
from .models import IMPACT_LEVELS, URGENCY_LEVELS, RuleMatrix

_POLICY_REF = re.compile(r"^[A-Z]{3}-[A-Z]{3}-\d{2}:\d+(\.\d+)*$")
KNOWN_FACT_ROOTS = {"complaint", "order", "customer", "eligibility", "history", "case", "classification", "sla"}


@dataclass
class IntegrityIssue:
    severity: str  # error | warning
    rule_id: str
    message: str


def _action_codes(items: tuple[Any, ...] | list[Any]) -> list[str]:
    out: list[str] = []
    for item in items:
        out.extend(item.get("any_of", []) if isinstance(item, dict) else [item])
    return out


def validate_matrix(matrix: RuleMatrix, *, kb_sections: set[str] | None = None) -> list[IntegrityIssue]:
    issues: list[IntegrityIssue] = []

    def err(rule_id: str, msg: str) -> None:
        issues.append(IntegrityIssue("error", rule_id, msg))

    def warn(rule_id: str, msg: str) -> None:
        issues.append(IntegrityIssue("warning", rule_id, msg))

    subs = matrix.subcategories
    depts = matrix.departments
    actions = set(matrix.actions) | set(matrix.prohibited_actions)
    signals = set(matrix.signals)
    levels = {lv.name for lv in matrix.escalation_levels}

    def check_condition(rule_id: str, cond: Any) -> None:
        try:
            evaluate(cond, EvalContext(matrix=matrix, text=""))
        except ConditionError as exc:
            err(rule_id, f"Malformed condition: {exc}")
        except KeyError as exc:
            err(rule_id, f"Condition references unknown parameter {exc}")
        for sig in referenced_signals(cond):
            if sig not in signals:
                err(rule_id, f"Condition references undefined signal '{sig}'")
        for fact in referenced_facts(cond):
            if fact.split(".")[0] not in KNOWN_FACT_ROOTS:
                warn(rule_id, f"Condition references unknown fact namespace '{fact}'")
        if isinstance(cond, dict):
            for key in ("subcategory_in",):
                for code in cond.get(key, []) or []:
                    if code not in subs:
                        err(rule_id, f"Condition references unknown subcategory '{code}'")
            for code in cond.get("category_in", []) or []:
                if code not in matrix.categories:
                    err(rule_id, f"Condition references unknown category '{code}'")
            for key in ("all", "any"):
                for sub in cond.get(key, []) or []:
                    if isinstance(sub, dict) and ("subcategory_in" in sub or "category_in" in sub):
                        check_condition(rule_id, {k: v for k, v in sub.items() if k in ("subcategory_in", "category_in")})

    def check_refs(rule_id: str, refs: tuple[str, ...] | list[str]) -> None:
        for ref in refs:
            if not _POLICY_REF.match(ref):
                err(rule_id, f"Malformed policy reference '{ref}' (expected DOC-ID:section)")
            elif kb_sections is not None:
                doc, section = ref.split(":", 1)
                if f"{doc}:{section}" not in kb_sections and not any(s.startswith(f"{doc}:{section}.") for s in kb_sections):
                    warn(rule_id, f"Policy reference '{ref}' not found in the active knowledge base")

    seen: set[str] = set()
    for rule in matrix.resolution_rules:
        if rule.rule_id in seen:
            err(rule.rule_id, "Duplicate rule ID")
        seen.add(rule.rule_id)
        if rule.subcategory not in subs:
            err(rule.rule_id, f"Unknown subcategory '{rule.subcategory}'")
        if rule.urgency not in URGENCY_LEVELS:
            err(rule.rule_id, f"Invalid urgency '{rule.urgency}'")
        if rule.impact not in IMPACT_LEVELS:
            err(rule.rule_id, f"Invalid impact '{rule.impact}'")
        if rule.escalation not in levels:
            err(rule.rule_id, f"Invalid escalation level '{rule.escalation}'")
        if rule.department and rule.department not in depts:
            err(rule.rule_id, f"Unknown department '{rule.department}'")
        for d in rule.supporting_departments:
            if d not in depts:
                err(rule.rule_id, f"Unknown supporting department '{d}'")
        for code in _action_codes(rule.required_actions) + list(rule.recommended_actions):
            if code not in matrix.actions:
                err(rule.rule_id, f"Unknown action code '{code}'")
        for code in rule.prohibited_actions:
            if code not in actions:
                err(rule.rule_id, f"Unknown prohibited action '{code}'")
        for key in rule.timelines:
            if key not in matrix.parameters:
                err(rule.rule_id, f"Unknown timeline parameter '{key}'")
        fu_type = rule.follow_up.get("type") if rule.follow_up else None
        if fu_type and fu_type not in matrix.follow_up_types:
            err(rule.rule_id, f"Unknown follow-up type '{fu_type}'")
        if not rule.required_actions:
            warn(rule.rule_id, "Rule has no required actions")
        check_condition(rule.rule_id, rule.when)
        check_refs(rule.rule_id, rule.policy_refs)

    for code, sub in subs.items():
        if not sub.is_active:
            continue
        rules = matrix.rules_for(code)
        if not rules:
            err(code, "Active subcategory has no resolution rules")
        elif not any(not r.when for r in rules):
            err(code, "Subcategory has no default (unconditional) resolution rule")
        if code not in matrix.routing:
            err(code, "Active subcategory has no routing rule")
        if code not in matrix.category_rules:
            warn(code, "Subcategory has no classification rule, so the rules cannot confirm it on their own")

    for code, rt in matrix.routing.items():
        if code not in subs:
            err(rt.rule_id, f"Routing rule for unknown subcategory '{code}'")
        for d in (rt.primary_department, *rt.supporting_departments):
            if d not in depts:
                err(rt.rule_id, f"Unknown department '{d}'")
    for cr in matrix.conditional_routing:
        check_condition(cr.rule_id, cr.when)
        for d in cr.add_supporting:
            if not d.startswith("$") and d not in depts:
                err(cr.rule_id, f"Unknown department '{d}'")

    esc_ids: set[str] = set()
    for esc in matrix.escalation_rules:
        if esc.rule_id in esc_ids:
            err(esc.rule_id, "Duplicate escalation rule ID")
        esc_ids.add(esc.rule_id)
        if esc.level not in levels:
            err(esc.rule_id, f"Invalid escalation level '{esc.level}'")
        for d in esc.departments:
            if not d.startswith("$") and d not in depts:
                err(esc.rule_id, f"Unknown department '{d}'")
        check_condition(esc.rule_id, esc.when)
        check_refs(esc.rule_id, esc.policy_refs)

    for floor in matrix.urgency_floors:
        check_condition(floor.rule_id, floor.when)
        if floor.urgency and floor.urgency not in URGENCY_LEVELS:
            err(floor.rule_id, f"Invalid urgency '{floor.urgency}'")
        if floor.impact and floor.impact not in IMPACT_LEVELS:
            err(floor.rule_id, f"Invalid impact '{floor.impact}'")
    for mi in matrix.missing_info_rules:
        check_condition(mi.rule_id, mi.when)

    for urgency in URGENCY_LEVELS:
        for impact in IMPACT_LEVELS:
            if matrix.priority_matrix.get(urgency, {}).get(impact) not in ("P0", "P1", "P2", "P3"):
                err("PRIORITY-MATRIX", f"Missing/invalid priority for urgency={urgency}, impact={impact}")
    for prio in ("P0", "P1", "P2", "P3"):
        sla = matrix.sla_rules.get(prio)
        if not sla:
            err("SLA", f"No SLA rule for priority {prio}")
        elif sla.first_response_hours <= 0 or sla.resolution_hours < sla.first_response_hours:
            err(sla.rule_id, "SLA targets must be positive and resolution >= first response")
    for key, param in matrix.parameters.items():
        if param.source and not _POLICY_REF.match(param.source):
            warn(key, f"Parameter source '{param.source}' is not a DOC-ID:section reference")
    for _sub_code, cat in matrix.category_rules.items():
        for sig in cat.signal_boosts:
            if sig not in signals:
                err(cat.rule_id, f"Signal boost references undefined signal '{sig}'")
        for sku in cat.product_boosts:
            if sku not in matrix.products:
                err(cat.rule_id, f"Product boost references unknown SKU '{sku}'")
    return issues


def summarize(issues: list[IntegrityIssue]) -> dict[str, Any]:
    return {
        "valid": not any(i.severity == "error" for i in issues),
        "errors": sum(i.severity == "error" for i in issues),
        "warnings": sum(i.severity == "warning" for i in issues),
        "issues": [asdict(i) for i in issues],
    }
