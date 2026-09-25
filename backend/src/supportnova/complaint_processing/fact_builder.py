"""Build the Python Ground-Truth Pipeline's view of a complaint (text-derived + system facts).

Everything here is deterministic and independent of the GenAI output: signals, entities, rule-based
classification, lexicon sentiment, order-ledger facts and complaint history become the fact model
the Rule Matrix is evaluated against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from supportnova.rule_engine.conditions import EvalContext
from supportnova.rule_engine.models import RuleMatrix

from .order_facts import derive_order_facts
from .perception import (
    ClassificationResult,
    EntityResult,
    SentimentResult,
    SignalHit,
    classify,
    detect_signals,
    extract_entities,
    lexicon_sentiment,
)
from .text import phrase_regex

MONETARY_SUBCATEGORIES = {"REF-REQ", "REF-DLY", "REF-PAR", "BIL-DUP", "BIL-INC", "BIL-RFM", "BIL-SUB", "BIL-CAN", "DEL-LST"}


@dataclass
class Perception:
    text: str
    signals: dict[str, SignalHit]
    entities: EntityResult
    classification: ClassificationResult
    sentiment: SentimentResult
    facts: dict[str, Any]
    order_ref: str | None
    product_sku: str | None
    notes: list[str] = field(default_factory=list)

    def context(self, matrix: RuleMatrix, subcategory: str | None = None,
                secondary: list[str] | None = None) -> EvalContext:
        import copy

        return EvalContext(matrix=matrix, facts=copy.deepcopy(self.facts), signals=set(self.signals),
                           text=self.text.lower(), subcategory=subcategory, secondary_subcategories=list(secondary or []))

    def signal_summary(self) -> dict[str, list[str]]:
        return {k: v.evidence for k, v in self.signals.items()}


def match_product(matrix: RuleMatrix, text: str) -> str | None:
    lower = (text or "").lower()
    best: tuple[int, str] | None = None
    for sku, product in matrix.products.items():
        for alias in (product.name.lower(), *product.aliases):
            if alias and phrase_regex(alias).search(lower) and (best is None or len(alias) > best[0]):
                best = (len(alias), sku)
    return best[1] if best else None


def build_perception(matrix: RuleMatrix, *, title: str, description: str, supporting_info: str = "",
                     product_text: str = "", order_ref: str | None = None, transaction_ref: str | None = None,
                     customer_ref: str | None = None, customer_type: str | None = None,
                     requested_resolution: str | None = None, channel: str | None = None,
                     has_image_attachment: bool = False, complaint_date: date | None = None,
                     order: dict[str, Any] | None = None, order_lookup_attempted: bool = False,
                     history: dict[str, Any] | None = None) -> Perception:
    as_of = complaint_date or date.today()
    full_text = "\n".join(p for p in (title, description, supporting_info) if p)
    signals = detect_signals(matrix, full_text)
    entities = extract_entities(matrix, full_text + ("\n" + product_text if product_text else ""), reference_date=as_of)
    product_sku = match_product(matrix, product_text) or (entities.product_skus[0] if entities.product_skus else None)
    ref = (order_ref or "").strip().upper() or (entities.order_refs[0] if entities.order_refs else None)
    derived = derive_order_facts(order if order_lookup_attempted or order else None, as_of=as_of, matrix=matrix,
                                 customer_ref=customer_ref, customer_type=customer_type)
    if derived["order"].get("product_sku") and not product_sku:
        product_sku = derived["order"]["product_sku"]
    classification = classify(matrix, title, "\n".join([description, supporting_info, product_text]), set(signals),
                              [s for s in [product_sku, *entities.product_skus] if s])
    sentiment = lexicon_sentiment(matrix, full_text)
    word_count = len((description or "").split())
    complaint_facts = {
        "customer_type": customer_type,
        "channel": channel,
        "requested_resolution": requested_resolution,
        "word_count": word_count,
        "has_order_reference": bool(ref),
        "has_transaction_reference": bool((transaction_ref or "").strip()) or bool(entities.transaction_refs),
        "has_product": bool((product_text or "").strip()) or bool(entities.product_skus) or bool(product_sku),
        "product_sku": product_sku,
        "product_line": matrix.products[product_sku].line if product_sku and product_sku in matrix.products else None,
        "has_photo_evidence": has_image_attachment or "photo_evidence" in signals,
        "has_date": bool(entities.dates) or entities.max_elapsed_days is not None,
        "max_amount": max(entities.amounts) if entities.amounts else None,
        "requested_compensation_amount": entities.requested_compensation_amount,
        "max_elapsed_days": entities.max_elapsed_days,
        "outage_hours": entities.outage_hours,
    }
    history = dict(history or {})
    history.setdefault("prior_same_issue_count", 0)
    history.setdefault("unresolved_prior_same_issue", 0)
    history.setdefault("references_resolved_complaint", False)
    claimed = complaint_facts["max_amount"]
    if classification.primary in MONETARY_SUBCATEGORIES and derived["order"].get("order_total"):
        claimed = max(float(claimed or 0), float(derived["order"]["order_total"]))
    facts = {
        "complaint": complaint_facts,
        "order": derived["order"],
        "eligibility": derived["eligibility"],
        "customer": derived["customer"],
        "history": history,
        "case": {"claimed_amount": claimed},
        "classification": {"score": classification.score, "confidence": classification.confidence},
    }
    return Perception(text=full_text, signals=signals, entities=entities, classification=classification,
                      sentiment=sentiment, facts=facts, order_ref=ref, product_sku=product_sku)
