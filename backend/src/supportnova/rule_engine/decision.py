"""Deterministic decision engine - the "ground truth decides" half of SupportNova.

Given a classification (primary + secondary subcategories) and an evaluation
context (facts, signals, text), compute the rule-matrix outcome: routing,
urgency/impact/priority, escalation, eligibility, required/prohibited actions,
follow-up, missing information, supported timelines and policy references.
Every value carries the rule IDs that produced it, so the UI can explain it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .conditions import EvalContext, describe, evaluate
from .models import IMPACT_LEVELS, URGENCY_LEVELS, ResolutionRule, RuleMatrix

ELIGIBILITY_DIMENSIONS = ("refund", "replacement", "compensation")


@dataclass
class FiredEscalation:
    rule_id: str
    name: str
    level: str
    rank: int
    reason: str
    departments: list[str]
    policy_refs: list[str]
    condition: str


@dataclass
class EscalationOutcome:
    required: bool
    level: str
    rank: int
    fired: list[FiredEscalation] = field(default_factory=list)
    departments: list[str] = field(default_factory=list)


@dataclass
class EligibilityOutcome:
    refund: str
    replacement: str
    compensation: str
    compensation_type: str | None = None
    compensation_amount_usd: float | None = None
    compensation_max_usd: float | None = None
    pending_rule_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class MissingInfoItem:
    rule_id: str
    field: str
    label: str
    blocking: bool
    question: str
    keywords: list[str]
    policy_refs: list[str]


@dataclass
class Decision:
    primary_subcategory: str | None
    primary_category: str | None
    secondary_subcategories: list[str]
    selected_rule_id: str | None
    selected_rule_name: str | None
    selected_rule_condition: str
    pending_rule_ids: list[str]
    urgency: str
    impact: str
    priority: str
    urgency_sources: list[str]
    department: str | None
    supporting_departments: list[str]
    routing_rule_ids: list[str]
    required_actions: list[Any]
    recommended_actions: list[str]
    prohibited_actions: list[str]
    eligibility: EligibilityOutcome
    escalation: EscalationOutcome
    follow_up: dict[str, Any]
    missing_info: list[MissingInfoItem]
    blocking_missing_info: bool
    policy_refs: list[str]
    timelines: dict[str, dict[str, Any]]
    sla: dict[str, Any]
    trace: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def required_action_codes(self) -> set[str]:
        codes: set[str] = set()
        for item in self.required_actions:
            if isinstance(item, dict):
                codes |= set(item.get("any_of", []))
            else:
                codes.add(item)
        return codes


def _max_level(levels: tuple[str, ...], current: str, candidate: str | None) -> str:
    if candidate and candidate in levels and levels.index(candidate) > levels.index(current):
        return candidate
    return current


def _eligibility_status(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("status", "not_applicable"))
    return str(value or "not_applicable")


class DecisionEngine:
    """Evaluate the rule matrix for one complaint. Stateless apart from the matrix."""

    def __init__(self, matrix: RuleMatrix) -> None:
        self.matrix = matrix

    # ---- resolution rule selection ------------------------------------------
    def select_rule(self, ctx: EvalContext, subcategory: str) -> tuple[ResolutionRule | None, list[ResolutionRule]]:
        """Highest-precedence rule whose condition is TRUE; rules evaluating to unknown are 'pending'."""
        pending: list[ResolutionRule] = []
        for rule in self.matrix.rules_for(subcategory):
            result = evaluate(rule.when, ctx)
            if result is True:
                return rule, pending
            if result is None:
                pending.append(rule)
        return None, pending

    # ---- main entry point -----------------------------------------------------
    def decide(self, ctx: EvalContext, primary: str | None, secondary: list[str] | None = None) -> Decision:
        m = self.matrix
        secondary = [s for s in (secondary or []) if s and s != primary]
        ctx.subcategory = primary
        ctx.secondary_subcategories = secondary
        trace: list[str] = []

        rule, pending = (self.select_rule(ctx, primary) if primary else (None, []))
        if rule:
            trace.append(f"Resolution rule {rule.rule_id} selected ({describe(rule.when)}).")
        elif primary:
            trace.append(f"No resolution rule matched subcategory {primary}.")
        for p in pending:
            trace.append(f"Rule {p.rule_id} may apply after verification ({describe(p.when)}).")

        # ---- urgency / impact / priority ----------------------------------
        urgency = rule.urgency if rule else "Medium"
        impact = rule.impact if rule else "Medium"
        sources = [rule.rule_id] if rule else []
        for floor in m.urgency_floors:
            if evaluate(floor.when, ctx) is True:
                new_u = _max_level(URGENCY_LEVELS, urgency, floor.urgency)
                new_i = _max_level(IMPACT_LEVELS, impact, floor.impact)
                if (new_u, new_i) != (urgency, impact):
                    trace.append(f"{floor.rule_id} ({floor.name}) raised urgency/impact to {new_u}/{new_i}.")
                    sources.append(floor.rule_id)
                urgency, impact = new_u, new_i
        priority = m.compute_priority(urgency, impact)

        # ---- escalation -----------------------------------------------------------
        department = None
        routing_ids: list[str] = []
        if primary and primary in m.routing:
            rt = m.routing[primary]
            department = rule.department if rule and rule.department else rt.primary_department
            routing_ids.append(rt.rule_id)

        fired: list[FiredEscalation] = []
        for esc in m.escalation_rules:
            if not esc.is_active or esc.runtime_only:
                continue
            if evaluate(esc.when, ctx) is True:
                depts = [department if d == "$primary_department" else d for d in esc.departments]
                fired.append(FiredEscalation(esc.rule_id, esc.name, esc.level, m.level_rank(esc.level), esc.reason,
                                             [d for d in depts if d], list(esc.policy_refs), describe(esc.when)))
        rank = max([f.rank for f in fired], default=0)
        if rule and m.level_rank(rule.escalation) > 0 and not any(f.level == rule.escalation for f in fired):
            fired.append(FiredEscalation(rule.rule_id, f"Rule-inherent escalation ({rule.name})", rule.escalation,
                                         m.level_rank(rule.escalation), f"Required by resolution rule {rule.rule_id}.",
                                         [department] if department else [], list(rule.policy_refs),
                                         describe(rule.when)))
            rank = max(rank, m.level_rank(rule.escalation))
            trace.append(f"{rule.rule_id} requires escalation level {rule.escalation}.")
        level = m.level_by_rank(rank).name
        esc_depts: list[str] = []
        for f in fired:
            for d in f.departments:
                if d not in esc_depts:
                    esc_depts.append(d)
        escalation = EscalationOutcome(required=rank > 0, level=level, rank=rank, fired=fired, departments=esc_depts)
        ctx.escalation_rank = rank
        for f in fired:
            trace.append(f"Escalation {f.rule_id} fired: {f.reason} -> {f.level}.")

        # ---- routing (primary + supporting) ---------------------------------------
        supporting: list[str] = []

        def add(dept: str | None) -> None:
            if dept and dept != department and dept not in supporting:
                supporting.append(dept)

        if primary and primary in m.routing:
            for d in m.routing[primary].supporting_departments:
                add(d)
        if rule:
            for d in rule.supporting_departments:
                add(d)
        for sec in secondary:
            if sec in m.routing:
                add(m.routing[sec].primary_department)
        for cond in m.conditional_routing:
            if evaluate(cond.when, ctx) is True:
                for d in cond.add_supporting:
                    if d == "$secondary_primary_departments":
                        continue  # handled above
                    add(d)
                routing_ids.append(cond.rule_id)
        for d in esc_depts:
            add(d)

        # ---- actions ---------------------------------------------------------------
        required: list[Any] = list(rule.required_actions) if rule else []
        recommended: list[str] = list(rule.recommended_actions) if rule else []
        prohibited: list[str] = list(rule.prohibited_actions) if rule else []
        if rank > 0:
            code = m.level_by_rank(rank).action_code
            flat = {c for item in required for c in (item.get("any_of", []) if isinstance(item, dict) else [item])}
            if code and code not in flat:
                required.append(code)
        for sec in secondary:
            sec_rule, _ = self.select_rule(ctx, sec)
            if sec_rule:
                for item in sec_rule.required_actions:
                    for c in (item.get("any_of", []) if isinstance(item, dict) else [item]):
                        if c not in recommended:
                            recommended.append(c)
        ctx.subcategory = primary  # select_rule for secondaries must not leak

        # ---- eligibility -------------------------------------------------------------
        elig_src = rule.eligibility if rule else {}
        values = {d: _eligibility_status(elig_src.get(d)) for d in ELIGIBILITY_DIMENSIONS}
        comp = elig_src.get("compensation") if isinstance(elig_src.get("compensation"), dict) else {}
        pending_ids: list[str] = []
        for p in pending:
            for d in ELIGIBILITY_DIMENSIONS:
                if _eligibility_status(p.eligibility.get(d)) != values[d] and values[d] != "requires_verification":
                    values[d] = "requires_verification"
                    if p.rule_id not in pending_ids:
                        pending_ids.append(p.rule_id)
        amount = ctx.resolve(comp.get("amount_usd")) if comp else None
        max_amount = ctx.resolve(comp.get("max_amount_usd")) if comp else None
        eligibility = EligibilityOutcome(
            refund=values["refund"], replacement=values["replacement"], compensation=values["compensation"],
            compensation_type=comp.get("type") if comp else None,
            compensation_amount_usd=float(amount) if amount is not None else None,
            compensation_max_usd=float(max_amount) if max_amount is not None else None,
            pending_rule_ids=pending_ids,
            notes=[f"Outcome depends on unverified facts for {pid}." for pid in pending_ids],
        )

        # ---- missing information ------------------------------------------------------
        missing: list[MissingInfoItem] = []
        never_block = (self.matrix.category_of(primary) in m.never_block_categories) or (
            primary in m.never_block_subcategories)
        for mi in m.missing_info_rules:
            if evaluate(mi.when, ctx) is True:
                missing.append(MissingInfoItem(mi.rule_id, mi.field, mi.label, mi.blocking and not never_block,
                                               mi.question, list(mi.keywords), list(mi.policy_refs)))
        blocking = any(x.blocking for x in missing)

        # ---- follow-up ------------------------------------------------------------------
        sla_rule = m.sla_rules.get(priority)
        rule_fu = dict(rule.follow_up) if rule else {"required": False}
        fup = {r["rule_id"]: r for r in m.followup_rules}

        def fup_due(rule_id: str, default: float) -> float | None:
            due = fup.get(rule_id, {}).get("due_hours", default)
            if due == "sla_first_response":
                return sla_rule.first_response_hours if sla_rule else default
            return float(due) if isinstance(due, (int, float)) else default

        if blocking:
            follow_up = {"required": True, "type": fup.get("FUP-001", {}).get("type", "Request for additional information"),
                         "due_hours": fup_due("FUP-001", 24), "source_rule": "FUP-001"}
        elif rank > 0:
            follow_up = {"required": True, "type": fup.get("FUP-002", {}).get("type", "Escalation acknowledgement"),
                         "due_hours": fup_due("FUP-002", 4), "source_rule": "FUP-002"}
        elif rule_fu.get("required"):
            follow_up = {"required": True, "type": rule_fu.get("type"), "due_hours": rule_fu.get("due_hours"),
                         "source_rule": rule.rule_id if rule else None}
        else:
            follow_up = {"required": False, "type": None, "due_hours": None,
                         "source_rule": rule.rule_id if rule else None}

        # ---- policy references & timelines -------------------------------------------------
        policy_refs: list[str] = list(rule.policy_refs) if rule else []
        for f in fired:
            for ref in f.policy_refs:
                if ref not in policy_refs:
                    policy_refs.append(ref)
        timelines: dict[str, dict[str, Any]] = {}
        for key in (rule.timelines if rule else ()):
            if key in m.parameters:
                param = m.parameters[key]
                timelines[key] = {"value": param.value, "unit": param.unit, "source": param.source}
        sla = {
            "priority": priority,
            "first_response_hours": sla_rule.first_response_hours if sla_rule else None,
            "resolution_hours": sla_rule.resolution_hours if sla_rule else None,
            "rule_id": sla_rule.rule_id if sla_rule else None,
        }

        return Decision(
            primary_subcategory=primary,
            primary_category=m.category_of(primary),
            secondary_subcategories=secondary,
            selected_rule_id=rule.rule_id if rule else None,
            selected_rule_name=rule.name if rule else None,
            selected_rule_condition=describe(rule.when) if rule else "",
            pending_rule_ids=[p.rule_id for p in pending],
            urgency=urgency,
            impact=impact,
            priority=priority,
            urgency_sources=sources,
            department=department,
            supporting_departments=supporting,
            routing_rule_ids=routing_ids,
            required_actions=required,
            recommended_actions=[r for r in recommended if r not in {c for c in _flatten(required)}],
            prohibited_actions=prohibited,
            eligibility=eligibility,
            escalation=escalation,
            follow_up=follow_up,
            missing_info=missing,
            blocking_missing_info=blocking,
            policy_refs=policy_refs,
            timelines=timelines,
            sla=sla,
            trace=trace,
        )


def _flatten(items: list[Any]) -> list[str]:
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            out.extend(item.get("any_of", []))
        else:
            out.append(item)
    return out
