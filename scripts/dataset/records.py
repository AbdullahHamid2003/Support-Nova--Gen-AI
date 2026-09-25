"""Record helpers shared by the generator and the validator.

The most important function is :func:`declared_input`, which rebuilds the exact
``declared`` argument of ``label_declared`` from a published record plus the order
ledger. The validator uses it to prove that every ``expected`` block is
reproducible from the record's declared facts.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .common import ORDER_REF_PATTERN
from .textutil import complaint_text

_ORDER_RE = re.compile(ORDER_REF_PATTERN)

# labeler output key -> expected key (same name unless listed)
LABEL_KEYS: tuple[str, ...] = (
    "category", "subcategory", "urgency", "impact", "priority", "department", "supporting_departments",
    "policy_references", "resolution_rule", "required_actions", "refund_eligibility", "replacement_eligibility",
    "compensation_eligibility", "compensation_amount_usd", "escalation_required", "escalation_level",
    "escalation_rules", "follow_up_required", "follow_up_type", "missing_information",
    "blocking_missing_information",
)

EXPECTED_KEYS: tuple[str, ...] = (
    "primary_issue", "secondary_issues", "category", "subcategory", "sentiment", "emotion_indicators", "urgency",
    "impact", "priority", "entities", "department", "supporting_departments", "policy_references",
    "resolution_rule", "required_actions", "refund_eligibility", "replacement_eligibility",
    "compensation_eligibility", "compensation_amount_usd", "escalation_required", "escalation_level",
    "escalation_rules", "follow_up_required", "follow_up_type", "missing_information",
    "blocking_missing_information", "is_duplicate_of", "is_near_duplicate_of", "is_repeat_of", "prompt_injection",
    "manual_review_expected",
)

RECORD_KEYS: tuple[str, ...] = (
    "complaint_id", "title", "description", "customer_ref", "customer_name", "customer_type", "product_service",
    "product_sku", "order_reference", "transaction_reference", "channel", "complaint_date",
    "previous_complaint_reference", "preferred_contact_method", "requested_resolution", "supporting_information",
    "attachments", "requested_tone", "seed_status", "declared", "expected", "difficulty_type", "tags",
    "scenario_id", "split",
)

SECURITY_SIGNALS = frozenset({"security_breach", "lock_security", "fraud"})
PRIVACY_SIGNALS = frozenset({"privacy_breach", "consent_violation", "data_rights_request", "minors_data"})
SAFETY_SIGNALS = frozenset({"fire_event", "overheating", "electrical_hazard", "injury"})
SENSITIVE_REVIEW_SIGNALS = frozenset({"legal_threat", "staff_harassment", "injury", "lock_security"})


def jsonable(value: Any) -> Any:
    """Normalise tuples/dicts to plain JSON types (for exact comparisons)."""
    return json.loads(json.dumps(value))


def is_valid_order_ref(value: str | None) -> bool:
    return bool(value) and bool(_ORDER_RE.match(str(value)))


def build_ledger_indexes(orders: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """(order_ref -> order, txn_ref -> order)."""
    by_ref = {o["order_ref"]: o for o in orders}
    by_txn: dict[str, dict[str, Any]] = {}
    for order in orders:
        for txn in order.get("transactions") or []:
            by_txn[txn["txn_ref"]] = order
    return by_ref, by_txn


def resolve_order(record: dict[str, Any], by_ref: dict[str, dict[str, Any]],
                  by_txn: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Ledger record the complaint points to.

    * well-formed order reference found in the ledger -> that order
    * well-formed order reference NOT in the ledger    -> ``{}`` (order.exists = False)
    * no / malformed order reference                   -> the order of the transaction reference, else ``None``
    """
    ref = record.get("order_reference")
    if is_valid_order_ref(ref):
        return by_ref.get(str(ref), {})
    txn = record.get("transaction_reference")
    if txn and txn in by_txn:
        return by_txn[txn]
    return None


def text_of(record: dict[str, Any]) -> str:
    return complaint_text(record.get("title"), record.get("description"), record.get("supporting_information"))


def declared_input(record: dict[str, Any], by_ref: dict[str, dict[str, Any]],
                   by_txn: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The ``declared`` argument of ``label_declared`` for a published record."""
    declared = record["declared"]
    expected = record["expected"]
    return {
        "complaint_date": record["complaint_date"],
        "customer_ref": record["customer_ref"],
        "customer_type": record["customer_type"],
        "order": resolve_order(record, by_ref, by_txn),
        "complaint_facts": dict(declared["complaint_facts"]),
        "signals": list(declared["signals"]),
        "history": dict(declared["history"]),
        "text": text_of(record),
        "primary_subcategory": expected["subcategory"],
        "secondary_subcategories": [s["subcategory"] for s in expected.get("secondary_issues") or []],
    }


def label_projection(label: dict[str, Any]) -> dict[str, Any]:
    """The labeler output restricted to the keys stored in ``expected`` (JSON-normalised)."""
    return jsonable({key: label.get(key) for key in LABEL_KEYS})


def manual_review_expected(*, prompt_injection: bool, tags: list[str], category: str | None,
                           signals: list[str], blocking_missing: bool) -> bool:
    """Cases a human reviewer must approve (CHP-SOP-13 s7, review_rules REV-005/007/008/010, MIS blocking)."""
    if prompt_injection or "ambiguous" in tags or "contradictory_policy" in tags:
        return True
    if category in ("SAF", "PRV"):
        return True
    if SENSITIVE_REVIEW_SIGNALS & set(signals):
        return True
    return bool(blocking_missing)
