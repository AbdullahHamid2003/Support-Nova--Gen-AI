"""Prompt context construction for both GenAI stages.

Trust separation (SRS Step 50): stable instructions + reference data (trusted) live in the system
prompt; retrieved evidence and verified system facts are labelled reference data; the complaint is
wrapped in a per-request random tag (<complaint_{nonce}>) so customer text cannot close the element,
is PII-redacted, and has screened injection spans annotated.
"""

from __future__ import annotations

import json
import secrets
from datetime import date
from typing import Any

from supportnova.knowledge_base.retriever import RetrievalResult
from supportnova.knowledge_base.store import KnowledgeSnapshot
from supportnova.rule_engine.models import RuleMatrix

# Approved policies the analysis prompt always receives as reference data, whether or not retrieval surfaces them
URGENCY_POLICY = "SLA-RUL-15"   # section 5: urgency levels
ROUTING_POLICY = "RTE-RUL-14"   # sections 3-5: routing table, multi-department routing, precedence


def catalog(matrix: RuleMatrix, snapshot: KnowledgeSnapshot | None) -> dict[str, list[str]]:
    """The codes the GenAI output may use - fed into the structured-output schema as enums."""
    return {"categories": [c.code for c in matrix.categories.values() if c.is_active],
            "subcategories": [s.code for s in matrix.subcategories.values() if s.is_active],
            "departments": [d.code for d in matrix.departments.values() if d.is_active],
            "actions": list(matrix.actions), "follow_up_types": list(matrix.follow_up_types),
            "policies": sorted(snapshot.versions) if snapshot is not None else []}


def reference_values(matrix: RuleMatrix, snapshot: KnowledgeSnapshot | None, as_of: date) -> dict[str, str]:
    cats = matrix.categories
    # "subcategory SAF-OVH (category SAF - Safety): name - description" so the two codes cannot be confused
    taxonomy = "\n".join(
        f"subcategory {s.code} (category {s.category} - {cats[s.category].name if s.category in cats else s.category}): "
        f"{s.name} - {s.description}"
        for s in sorted(matrix.subcategories.values(), key=lambda s: s.code) if s.is_active)
    departments = "\n".join(f"{d.code} | {d.name}: {d.description}" for d in matrix.departments.values() if d.is_active)
    actions = "\n".join(f"{a.code}: {a.name}" for a in matrix.actions.values())
    levels = "\n".join(f"{lv.rank}. {lv.name}" for lv in matrix.escalation_levels)
    guide_lines = ["Priority matrix (urgency x impact):"]
    for urgency, row in matrix.priority_matrix.items():
        guide_lines.append(f"- {urgency}: " + ", ".join(f"{impact} impact -> {prio}" for impact, prio in row.items()))
    routing_lines: list[str] = []
    if snapshot is not None:
        active = snapshot.active_version(URGENCY_POLICY, as_of)
        if active:
            for sid in ("5", "5.1", "5.2", "5.3", "5.4", "6"):
                if sid in active.section_text:
                    guide_lines.append(f"[{URGENCY_POLICY} s{sid} {active.sections.get(sid, '')}] {active.section_text[sid][:500]}")
        routing = snapshot.active_version(ROUTING_POLICY, as_of)
        if routing:
            for sid in ("3", "4", "4.1", "4.2", "4.3", "4.4", "5"):
                if sid in routing.section_text:
                    routing_lines.append(f"[{ROUTING_POLICY} v{routing.version} s{sid} {routing.sections.get(sid, '')}]\n"
                                         f"{routing.section_text[sid]}")
    return {"taxonomy": taxonomy, "departments": departments, "actions": actions, "escalation_levels": levels,
            "priority_guide": "\n".join(guide_lines), "follow_up_types": "\n".join(matrix.follow_up_types),
            "routing_policy": "\n".join(routing_lines) or "(the routing policy is not available)"}


def evidence_block(retrieval: RetrievalResult, only: set[str] | None = None) -> str:
    items = []
    for e in retrieval.evidence:
        if only is not None and e.evidence_id not in only:
            continue
        page = f' page="{e.page_start}"' if e.page_start else ""
        items.append(f'<item id="{e.evidence_id}" policy_id="{e.doc_id}" title="{e.title}" version="{e.version}" '
                     f'type="{e.doc_type}" status="{e.status}" section="{e.section_id}" heading="{e.heading}"{page}>\n{e.text}\n</item>')
    return "\n".join(items) or "(no approved evidence was retrieved)"


def conflicts_block(retrieval: RetrievalResult) -> str:
    if not retrieval.conflicts:
        return "none"
    return "\n".join(f"- {c['explanation']} Use the prevailing source." for c in retrieval.conflicts)


def verified_facts(*, complaint: dict[str, Any], customer: dict[str, Any] | None, order: dict[str, Any] | None,
                   order_ref: str | None, order_found: bool | None, history: list[dict[str, Any]], matrix: RuleMatrix) -> str:
    lines = [f"complaint_reference: {complaint.get('complaint_ref')}",
             f"submitted: {complaint.get('complaint_date')}",
             f"channel: {complaint.get('channel')}",
             f"customer_type: {complaint.get('customer_type')}"]
    if customer:
        lines.append(f"customer_reference: {customer.get('customer_ref')}")
    if order_ref and order_found is False:
        lines.append(f"order_ledger: order reference {order_ref} was NOT found in the order ledger.")
    elif order:
        items = ", ".join(f"{i.get('qty', 1)} x {matrix.products[i['sku']].name if i.get('sku') in matrix.products else i.get('sku')} "
                          f"(USD {i.get('unit_price')})" for i in order.get("items", []))
        lines.append(f"order_ledger: {order.get('order_ref')} | items: {items} | total USD {order.get('order_total')} | "
                     f"shipping: {order.get('shipping_method')} | ordered {order.get('order_date')} | estimated delivery "
                     f"{order.get('estimated_delivery_date')} | dispatched {order.get('dispatched_date')} | delivered "
                     f"{order.get('delivered_date')} | status {order.get('status')} | care_plus {bool(order.get('care_plus'))} | "
                     f"previous replacements {order.get('replacement_count', 0)}")
        for t in order.get("transactions", [])[:6]:
            lines.append(f"  transaction {t.get('txn_ref')}: {t.get('type')} USD {t.get('amount')} on {t.get('date')}")
        if order.get("return"):
            r = order["return"]
            lines.append(f"  return: requested {r.get('requested_date')}, received {r.get('received_date')}, inspection approved "
                         f"{r.get('inspection_approved_date')}, refund issued {r.get('refund_issued_date')} (USD {r.get('refund_amount')}), "
                         f"restocking fee USD {r.get('restocking_fee') or 0}, reason {r.get('reason')}")
        if order.get("cancellation"):
            lines.append(f"  cancellation: requested {order['cancellation'].get('requested_date')}, confirmed {order['cancellation'].get('confirmed')}")
        if order.get("subscription"):
            s = order["subscription"]
            lines.append(f"  subscription: {s.get('plan')} plan, renewal {s.get('renewal_date')}, auto-renew {s.get('auto_renew')}")
        if order.get("trace"):
            lines.append(f"  carrier trace: opened {order['trace'].get('opened_date')}, completed {order['trace'].get('completed')}")
    else:
        lines.append("order_ledger: no order reference supplied.")
    if history:
        lines.append("complaint_history (last 90 days, same customer):")
        for h in history[:6]:
            lines.append(f"  {h['complaint_ref']} on {h['date']}: {h.get('subcategory') or 'unclassified'} - status {h['status']}"
                         + (f" - order {h['order_ref']}" if h.get("order_ref") else ""))
    else:
        lines.append("complaint_history: no previous complaints in the last 90 days.")
    return "\n".join(lines)


def complaint_block(complaint: dict[str, Any], text_for_model: str) -> str:
    return "\n".join([
        f"Title: {complaint.get('title', '')}",
        f"Product/service (as entered): {complaint.get('product_text') or '(not provided)'}",
        f"Order reference (as entered): {complaint.get('order_ref') or '(not provided)'}",
        f"Transaction reference (as entered): {complaint.get('transaction_ref') or '(not provided)'}",
        f"Previous complaint reference (as entered): {complaint.get('previous_complaint_ref') or '(not provided)'}",
        f"Requested resolution: {complaint.get('requested_resolution') or 'none'}",
        f"Attachments: {complaint.get('attachments_summary') or 'none'}",
        "Complaint text:",
        text_for_model,
    ])


def new_nonce() -> str:
    return secrets.token_hex(4)


def decision_block(validated: dict[str, Any], matrix: RuleMatrix) -> str:
    v = validated
    elig = v["eligibility"]
    prohibited = []
    for code in v["prohibited_actions"]:
        pa = matrix.prohibited_actions.get(code)
        prohibited.append(pa.name if pa else (matrix.actions[code].name if code in matrix.actions else code))
    data = {
        "issue": v["classification"].get("subcategory_name"), "category": v["classification"].get("category_name"),
        "department": matrix.departments[v["department"]].name if v.get("department") in matrix.departments else v.get("department"),
        "priority": v["priority"], "escalated": v["escalation"]["required"], "escalation_level": v["escalation"]["level"],
        "eligibility": {"refund": elig["refund"], "replacement": elig["replacement"], "compensation": elig["compensation"],
                        "compensation_type": elig.get("compensation_type"), "compensation_amount_usd": elig.get("compensation_amount_usd")},
        "next_steps_for_customer": v["customer_steps"], "do_not": prohibited,
        "safety_issue": v.get("safety", False), "summary": v.get("summary", ""),
    }
    return json.dumps(data, indent=2)
