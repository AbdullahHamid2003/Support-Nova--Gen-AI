"""Derive order and eligibility facts from the simulated order ledger (SRS Steps 29-31).

"Check transaction, check policy, check date, check conditions, check customer
eligibility" - these facts are what make refund/replacement/compensation
eligibility a deterministic Python decision rather than GenAI opinion.
The ledger is simulated (no live payment/CRM integration - SRS 1.4).
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

from supportnova.core.timeutil import business_days_between, to_date
from supportnova.rule_engine.models import RuleMatrix

_DAYS_PER_MONTH = 30.44


def _charges(order: dict[str, Any]) -> list[dict[str, Any]]:
    return [t for t in order.get("transactions") or [] if t.get("type", "charge") == "charge"]


def duplicate_charge_verified(order: dict[str, Any]) -> bool:
    """Two charges of the same amount within 3 days = verified duplicate."""
    charges = sorted(_charges(order), key=lambda t: str(t.get("date")))
    for i, first in enumerate(charges):
        for second in charges[i + 1:]:
            d1, d2 = to_date(first.get("date")), to_date(second.get("date"))
            if (abs(float(first.get("amount", 0)) - float(second.get("amount", 0))) < 0.01 and d1 and d2
                    and abs((d2 - d1).days) <= 3):
                return True
    return False


def derive_order_facts(order: dict[str, Any] | None, *, as_of: date, matrix: RuleMatrix,
                       customer_ref: str | None = None, customer_type: str | None = None) -> dict[str, Any]:
    """Return ``{"order": {...}, "eligibility": {...}, "customer": {...}}`` fact namespaces.

    Unknown values are ``None`` so that rule conditions evaluate to *unknown*
    (-> "requires verification") instead of guessing.
    """
    is_care_plus_customer = customer_type == "care_plus"
    if not order:
        return {"order": {"exists": False if order is not None else None},
                "eligibility": {}, "customer": {"is_care_plus": is_care_plus_customer if customer_type else None}}

    p = matrix.param
    items = order.get("items") or []
    skus = [str(i.get("sku")) for i in items]
    product = matrix.products.get(skus[0]) if skus else None
    hazardous = any((matrix.products.get(s) and matrix.products[s].hazard_class) for s in skus)

    order_date = to_date(order.get("order_date"))
    eta = to_date(order.get("estimated_delivery_date"))
    dispatched = to_date(order.get("dispatched_date"))
    delivered = to_date(order.get("delivered_date"))
    delivered_ok = delivered is not None and delivered <= as_of
    dispatched_ok = dispatched is not None and dispatched <= as_of

    days_late = None
    if eta is not None:
        reference_end = delivered if delivered_ok and delivered else as_of
        days_late = business_days_between(eta, reference_end) if reference_end > eta else 0

    days_since_delivery = (as_of - delivered).days if delivered_ok and delivered else None
    care_plus = bool(order.get("care_plus")) or is_care_plus_customer

    charges = _charges(order)
    total = float(order.get("order_total") or 0)
    dup = duplicate_charge_verified(order)
    charged_sum = sum(float(t.get("amount", 0)) for t in charges)
    overcharge = any(float(t.get("amount", 0)) > total + 0.01 for t in charges) or (
        not dup and charged_sum - total > 0.01)
    last_charge = max((cast(date, to_date(t.get("date"))) for t in charges if t.get("date")), default=None)

    ret = order.get("return") or {}
    received = to_date(ret.get("received_date"))
    approved = to_date(ret.get("inspection_approved_date"))
    refund_issued = to_date(ret.get("refund_issued_date"))
    cancellation = order.get("cancellation") or {}
    cancel_req = to_date(cancellation.get("requested_date"))
    subscription = order.get("subscription") or {}
    renewal = to_date(subscription.get("renewal_date"))
    trace = order.get("trace") or {}

    # refund lateness (REF-POL-02 4.2/4.3/5.1)
    refund_late: bool | None
    if not ret:
        refund_late = None
    elif refund_issued and refund_issued <= as_of:
        refund_late = False
    elif approved and approved <= as_of:
        refund_late = (business_days_between(approved, as_of) or 0) > p("refund_issue_business_days")
    elif received and received <= as_of:
        refund_late = (business_days_between(received, as_of) or 0) > (
            p("return_inspection_business_days") + p("refund_issue_business_days"))
    else:
        refund_late = None

    refund_trace_due = None
    if refund_issued and refund_issued <= as_of:
        refund_trace_due = (business_days_between(refund_issued, as_of) or 0) >= p("refund_trace_after_business_days")

    warranty_months = (product.warranty_months if product and product.warranty_months else None)
    if care_plus and warranty_months:
        warranty_months = max(warranty_months, int(p("care_plus_coverage_months")))
    within_warranty = None
    if days_since_delivery is not None and warranty_months:
        within_warranty = days_since_delivery <= warranty_months * _DAYS_PER_MONTH

    refund_window = p("care_plus_refund_window_days") if care_plus else p("refund_window_days")

    order_facts = {
        "exists": True,
        "order_ref": order.get("order_ref"),
        "belongs_to_customer": (order.get("customer_ref") == customer_ref) if customer_ref else None,
        "order_total": total,
        "product_sku": skus[0] if skus else None,
        "shipping_method": order.get("shipping_method"),
        "status": order.get("status"),
        "delivered": delivered_ok,
        "dispatched": dispatched_ok,
        "business_days_late": days_late,
        "days_since_delivery": days_since_delivery,
        "days_since_order": (as_of - order_date).days if order_date else None,
        "is_hazardous": bool(hazardous),
        "duplicate_charge_verified": dup if charges else None,
        "overcharge_verified": overcharge if charges else None,
        "return_received": (received is not None and received <= as_of) if ret else False,
        "restocking_fee_applied": (float(ret.get("restocking_fee") or 0) > 0) if ret else None,
        "return_reason": ret.get("reason") if ret else None,
        "refund_issued": (refund_issued is not None and refund_issued <= as_of) if ret else False,
        "cancellation_confirmed": bool(cancellation.get("confirmed")) if cancellation else False,
        "charged_after_cancellation": (any(to_date(t.get("date")) and to_date(t.get("date")) > cancel_req  # type: ignore[operator]
                                           for t in charges) if cancel_req else False),
        "billing_period": subscription.get("plan") if subscription else None,
        "trace_completed": bool(trace.get("completed")) if trace else False,
        "replacement_count": int(order.get("replacement_count") or 0),
    }
    eligibility = {
        "within_doa_window": (days_since_delivery <= p("doa_report_days")) if days_since_delivery is not None else None,
        "within_defect_window": (days_since_delivery <= p("defect_refund_window_days")) if days_since_delivery is not None else None,
        "within_refund_window": (days_since_delivery <= refund_window) if days_since_delivery is not None else None,
        "within_warranty": within_warranty,
        "replacement_limit_reached": int(order.get("replacement_count") or 0) >= p("max_policy_replacements"),
        "delay_qualifies": (order.get("shipping_method") == "standard" and days_late is not None
                            and days_late > p("delay_comp_threshold_business_days")) if days_late is not None else None,
        "within_dispute_window": ((as_of - last_charge).days <= p("billing_dispute_window_days")) if last_charge else None,
        "within_cooling_off": (((as_of - renewal).days <= p("annual_cooling_off_days")) if renewal else None)
        if subscription.get("plan") == "annual" else (False if subscription else None),
        "refund_late": refund_late,
        "refund_trace_due": refund_trace_due,
        "careplus_claims_available": (int(order.get("careplus_claims_12m") or 0) < p("care_plus_accidental_claims_per_year"))
        if care_plus else None,
    }
    return {"order": order_facts, "eligibility": eligibility, "customer": {"is_care_plus": care_plus}}
