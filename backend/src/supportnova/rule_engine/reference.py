"""Reference labeler for the complaint dataset.

Dataset authors *declare* the ground truth of each scenario (primary and
secondary subcategory, which risk signals are really present, what the order
ledger says, the customer history). This module applies the approved Rule
Matrix to those DECLARED facts to produce the expected routing, urgency,
priority, escalation, eligibility, actions and follow-up.

This is deliberately different from the runtime Python Ground-Truth Pipeline,
which must DETECT the same facts from raw complaint text. The evaluation report
therefore measures how well the runtime pipeline (and the GenAI pipeline)
recover the policy-correct outcome from text - it is not circular.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from supportnova.complaint_processing.order_facts import derive_order_facts
from supportnova.core.timeutil import to_date

from .conditions import EvalContext
from .decision import DecisionEngine
from .models import RuleMatrix


def build_declared_context(matrix: RuleMatrix, declared: dict[str, Any]) -> EvalContext:
    """``declared`` keys: complaint_date, customer_ref, customer_type, order (ledger record or None),
    complaint_facts, signals, history, text, primary_subcategory, secondary_subcategories."""
    as_of: date = to_date(declared.get("complaint_date")) or date.today()
    derived = derive_order_facts(declared.get("order"), as_of=as_of, matrix=matrix,
                                 customer_ref=declared.get("customer_ref"),
                                 customer_type=declared.get("customer_type"))
    complaint = dict(declared.get("complaint_facts") or {})
    complaint.setdefault("customer_type", declared.get("customer_type"))
    if derived["order"].get("product_sku") and not complaint.get("product_sku"):
        complaint["product_sku"] = derived["order"]["product_sku"]
    sku = complaint.get("product_sku")
    if sku and sku in matrix.products:
        complaint.setdefault("product_line", matrix.products[sku].line)
    history = dict(declared.get("history") or {})
    history.setdefault("prior_same_issue_count", 0)
    history.setdefault("unresolved_prior_same_issue", 0)
    history.setdefault("references_resolved_complaint", False)
    primary = declared.get("primary_subcategory")
    monetary = {"REF-REQ", "REF-DLY", "REF-PAR", "BIL-DUP", "BIL-INC", "BIL-RFM", "BIL-SUB", "BIL-CAN", "DEL-LST"}
    claimed = complaint.get("max_amount")
    if primary in monetary and derived["order"].get("order_total"):
        claimed = max(float(claimed or 0), float(derived["order"]["order_total"]))
    facts = {
        "complaint": complaint,
        "order": derived["order"],
        "eligibility": derived["eligibility"],
        "customer": derived["customer"],
        "history": history,
        "case": {"claimed_amount": claimed},
        "classification": {"score": 10.0},
    }
    return EvalContext(matrix=matrix, facts=facts, signals=set(declared.get("signals") or []),
                       text=(declared.get("text") or "").lower())


def label_declared(matrix: RuleMatrix, declared: dict[str, Any]) -> dict[str, Any]:
    """Expected outcome (dataset ``expected`` block) for declared scenario facts."""
    ctx = build_declared_context(matrix, declared)
    primary = declared.get("primary_subcategory")
    secondary = list(declared.get("secondary_subcategories") or [])
    decision = DecisionEngine(matrix).decide(ctx, primary, secondary)
    comp: Any = decision.eligibility.compensation
    return {
        "category": decision.primary_category,
        "subcategory": decision.primary_subcategory,
        "secondary_subcategories": decision.secondary_subcategories,
        "urgency": decision.urgency,
        "impact": decision.impact,
        "priority": decision.priority,
        "department": decision.department,
        "supporting_departments": decision.supporting_departments,
        "policy_references": decision.policy_refs,
        "resolution_rule": decision.selected_rule_id,
        "required_actions": decision.required_actions,
        "refund_eligibility": decision.eligibility.refund,
        "replacement_eligibility": decision.eligibility.replacement,
        "compensation_eligibility": comp,
        "compensation_amount_usd": decision.eligibility.compensation_amount_usd,
        "escalation_required": decision.escalation.required,
        "escalation_level": decision.escalation.level,
        "escalation_rules": [f.rule_id for f in decision.escalation.fired],
        "follow_up_required": bool(decision.follow_up.get("required")),
        "follow_up_type": decision.follow_up.get("type"),
        "missing_information": [m.field for m in decision.missing_info],
        "blocking_missing_information": decision.blocking_missing_info,
    }
