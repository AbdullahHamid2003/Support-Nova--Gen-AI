"""End-to-end dataset generation.

Phases
------
1. **Draft** every complaint instance of every scenario (and every chain step):
   pick the complaint date, customer, channel, product and order profile, build the
   ledger record, render title/description/supporting information and register
   the slot facts.
2. **Assign IDs** in chronological order (``CMP-00001..`` dev, ``EVL-00001..`` holdout).
3. **Finalise** drafts in date order: copy exact/near duplicates from their (already
   final) source, insert previous-complaint references, compute complaint facts and
   history, run ``label_declared`` on the declared facts, and assemble the record.
4. **Check** the intended resolution rule, scenario expectations and the lexical
   coherence of every declared signal.
"""

from __future__ import annotations

import random
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

# backend/src is put on sys.path by the package __init__ (dataset.common.ensure_backend_path)
from supportnova.rule_engine.loader import load_matrix
from supportnova.rule_engine.reference import label_declared

from .catalog import Catalog
from .common import (
    CHANNEL_WEIGHTS,
    DEV_END,
    DEV_START,
    EMOTIONS,
    HOLDOUT_END,
    HOLDOUT_START,
    INVALID_ORDER_REF,
    RESOLVED_STATUSES,
    TONES,
    UNRESOLVED_STATUSES,
    sub_rng,
    weighted_choice,
)
from .customers import CustomerPool, build_customers
from .ledger import OrderContext, RefAllocator, background_order, build_order
from .lexicon import SignalDetector
from .records import (
    PRIVACY_SIGNALS,
    SAFETY_SIGNALS,
    SECURITY_SIGNALS,
    is_valid_order_ref,
    jsonable,
    label_projection,
    manual_review_expected,
)
from .render import PREV_PLACEHOLDER, Renderer, RenderLog, adapt_channel
from .scenarios import Scenario, ScenarioBank, Variant
from .textutil import complaint_text, tokens

STYLE_SENTIMENT = {"calm": "Neutral", "polite": "Neutral", "frustrated": "Negative", "angry": "Strongly Negative"}
STYLE_EMOTIONS = {"calm": [], "polite": [], "frustrated": ["Frustration"], "angry": ["Anger", "Frustration"]}
IMAGE_NAMES = ("photo_{n}.jpg", "IMG_{d}{n}.jpg", "{p}_damage_{n}.jpg", "{p}_{n}.jpeg", "picture_{n}.png")
AGENT_LIMIT_USD = 25.0


@dataclass
class Draft:
    """One complaint in the making."""

    pool: str
    scenario: Scenario
    variant: Variant
    variant_index: int
    instance: int
    scenario_id: str
    dt: datetime
    rng: random.Random
    customer: dict[str, Any]
    channel: str
    style: str
    requested_resolution: str
    include: dict[str, bool]
    params: dict[str, Any]
    product_sku: str | None
    product2_sku: str | None
    order: dict[str, Any] | None           # ledger record used for slot values (may be another customer's)
    order_mode: str
    order_ref_text: str | None             # order reference as written (valid, unknown or malformed)
    signals: list[str]
    lexical_traps: list[str]
    tags: list[str]
    difficulty_type: str
    intended_rule: str | None
    expect: dict[str, Any]
    chain_key: str | None = None
    step_index: int | None = None
    link: str = "original"
    link_target: Draft | None = None
    root: Draft | None = None
    cite_target: Draft | None = None
    prior_cases: list[Draft] = field(default_factory=list)
    seed_status: str = "New"
    title: str = ""
    description: str = ""
    supporting: str = ""
    txn_ref: str | None = None
    product_service: str = ""
    attachments: list[dict[str, str]] = field(default_factory=list)
    log: RenderLog = field(default_factory=RenderLog)
    renderer: Renderer | None = None
    complaint_id: str | None = None
    previous_reference: str | None = None
    record: dict[str, Any] | None = None


def _resolve_param(rng: random.Random, value: Any) -> Any:
    if isinstance(value, list):
        if len(value) == 2 and all(isinstance(v, int) for v in value) and value[0] <= value[1]:
            return rng.randint(value[0], value[1])
        return rng.choice(value)
    return value


def _fmt_dt(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cap(text: str) -> str:
    """Upper-case the first letter (a slot such as ``{age:...}`` may start a sentence)."""
    return text[0].upper() + text[1:] if text and text[0].islower() else text


class DatasetBuilder:
    """Generate the dev and holdout datasets from the scenario bank."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.matrix = load_matrix()
        self.catalog = Catalog(self.matrix)
        self.detector = SignalDetector()
        self.scenarios = ScenarioBank(self.matrix, self.detector.names).load()
        self.customers = build_customers(seed)
        self.customer_pool = CustomerPool(self.customers)
        self.refs = RefAllocator(seed)
        self.orders: dict[str, dict[str, Any]] = {}
        self.drafts: list[Draft] = []
        self.failures: list[str] = []
        self.coherence: list[dict[str, Any]] = []
        self.render_errors: list[str] = []

    # ------------------------------------------------------------------ phase 1
    def _random_datetime(self, rng: random.Random, start: date, end: date) -> datetime:
        day = start + timedelta(days=rng.randint(0, (end - start).days))
        hour = rng.choice((7, 8, 9, 9, 10, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22))
        return datetime.combine(day, time(hour, rng.randint(0, 59), rng.randint(0, 59)), tzinfo=UTC)

    def _window(self, pool: str) -> tuple[date, date]:
        return (HOLDOUT_START, HOLDOUT_END) if pool == "holdout" else (DEV_START, DEV_END)

    def _channel(self, rng: random.Random, allowed: list[str] | None) -> str:
        return weighted_choice(rng, CHANNEL_WEIGHTS, allowed or None)

    def _merged_include(self, scenario: Scenario, variant: Variant) -> dict[str, bool]:
        include = dict(scenario.include)
        include.update({k: bool(v) for k, v in variant.include.items()})
        return include

    def _params(self, rng: random.Random, scenario: Scenario, variant: Variant, sku: str | None) -> dict[str, Any]:
        """Scenario + variant parameters; ranges/choices are resolved, per-SKU maps pick the product's entry."""
        merged = dict(scenario.params)
        merged.update(variant.params)
        resolved: dict[str, Any] = {}
        for key, value in merged.items():
            if isinstance(value, dict):
                value = value.get(sku or "", value.get("default"))
            resolved[key] = _resolve_param(rng, value)
        return resolved

    def _build_order(self, scenario: Scenario, variant: Variant, rng: random.Random, anchor: date,
                     customer: dict[str, Any], product_sku: str | None, include: dict[str, bool]
                     ) -> tuple[dict[str, Any] | None, str | None]:
        """Returns (ledger record used for slots, order reference text)."""
        mode = scenario.order_mode
        if mode == "invalid_reference":
            return None, INVALID_ORDER_REF
        if mode == "unknown_reference":
            return None, self.refs.unknown_order_ref()
        if mode == "malformed_reference":
            digits = f"{rng.randint(100000, 999999)}"
            fmt = scenario.malformed_ref or rng.choice(("LMR-{d5}", "LMR {d6}", "LMR{d6}", "#{d6}", "LMR-{d6}X"))
            return None, fmt.replace("{d5}", digits[:5]).replace("{d6}", digits)
        profile = scenario.order_profile
        if profile is None or not (include.get("order_reference") or include.get("transaction_reference")):
            return None, None
        owner = customer
        if mode == "other_customer":
            owner = self.customer_pool.other_than(rng, customer["customer_ref"])
        skus = [product_sku] if product_sku else []
        ctx = OrderContext(anchor=anchor, customer_ref=owner["customer_ref"], customer_type=owner["customer_type"],
                           skus=skus, rng=rng, refs=self.refs, catalog=self.catalog)
        order = build_order(profile["name"], ctx, profile["params"])
        self.orders[order["order_ref"]] = order
        return order, (order["order_ref"] if include.get("order_reference") else None)

    def _new_draft(self, scenario: Scenario, variant: Variant, vi: int, k: int, rng: random.Random, dt: datetime,
                   customer: dict[str, Any], *, pool: str, scenario_id: str, product_sku: str | None,
                   product2_sku: str | None, order: dict[str, Any] | None, order_ref_text: str | None,
                   params: dict[str, Any]) -> Draft:
        include = self._merged_include(scenario, variant)
        channels = variant.channels or scenario.channels
        difficulty = variant.difficulty_type or scenario.difficulty_type
        if scenario.kind == "chain" and variant.link != "original":
            difficulty = variant.difficulty_type or variant.link
        expect = dict(scenario.expect)
        expect.update(variant.expect)
        return Draft(
            pool=pool, scenario=scenario, variant=variant, variant_index=vi, instance=k, scenario_id=scenario_id,
            dt=dt, rng=rng, customer=customer, channel=self._channel(rng, channels), style=variant.style,
            requested_resolution=variant.requested_resolution or scenario.requested_resolution, include=include,
            params=params, product_sku=product_sku, product2_sku=product2_sku, order=order,
            order_mode=scenario.order_mode, order_ref_text=order_ref_text,
            signals=[s for s in dict.fromkeys(scenario.signals + variant.signals_add) if s not in variant.signals_remove],
            lexical_traps=list(dict.fromkeys(scenario.lexical_traps + variant.lexical_traps)),
            tags=list(dict.fromkeys(scenario.tags + variant.tags)), difficulty_type=difficulty,
            intended_rule=variant.intended_rule or scenario.intended_rule, expect=expect,
            seed_status=variant.seed_status,
        )

    def _pick_products(self, rng: random.Random, scenario: Scenario, variant: Variant) -> tuple[str | None, str | None]:
        products = variant.products or scenario.products
        sku = rng.choice(products) if products else None
        others = [p for p in scenario.product2 if p != sku]
        sku2 = rng.choice(others) if others else None
        return sku, sku2

    def _single(self, scenario: Scenario) -> None:
        for vi, variant in enumerate(scenario.variants):
            for k in range(variant.count):
                rng = sub_rng(self.seed, scenario.scenario_id, vi, k)
                start, end = self._window(scenario.pool)
                dt = self._random_datetime(rng, start, end)
                types = variant.customer_types or scenario.customer_types
                customer = self.customer_pool.pick(rng, types, scenario.subcategory)
                sku, sku2 = self._pick_products(rng, scenario, variant)
                include = self._merged_include(scenario, variant)
                order, ref_text = self._build_order(scenario, variant, rng, dt.date(), customer, sku, include)
                params = self._params(rng, scenario, variant, sku)
                draft = self._new_draft(scenario, variant, vi, k, rng, dt, customer, pool=scenario.pool,
                                        scenario_id=scenario.scenario_id, product_sku=sku, product2_sku=sku2,
                                        order=order, order_ref_text=ref_text, params=params)
                self._render(draft)
                self.drafts.append(draft)

    def _chain(self, scenario: Scenario) -> None:
        rng = sub_rng(self.seed, scenario.scenario_id, "chain")
        steps = scenario.variants
        pools = [v.pool or scenario.pool for v in steps]
        offsets: list[int] = []
        running = 0
        for v in steps:
            running += v.gap_days if offsets else 0
            offsets.append(running)
        span = offsets[-1]
        if pools[-1] == "holdout":
            last = self._random_datetime(rng, HOLDOUT_START, HOLDOUT_END)
        else:
            start, end = self._window(pools[-1])
            last = self._random_datetime(rng, start + timedelta(days=span), end)
        first_day = last.date() - timedelta(days=span)
        if first_day < DEV_START:
            raise ValueError(f"[{scenario.scenario_id}] chain does not fit in the dev window")
        types = scenario.customer_types
        customer = self.customer_pool.pick(rng, types, scenario.subcategory)
        sku, sku2 = self._pick_products(rng, scenario, steps[0])
        include = self._merged_include(scenario, steps[0])
        order, ref_text = self._build_order(scenario, steps[0], rng, first_day, customer, sku, include)
        base_params = self._params(rng, scenario, steps[0], sku)
        chain_drafts: list[Draft] = []
        for i, variant in enumerate(steps):
            srng = sub_rng(self.seed, scenario.scenario_id, "step", i)
            day = first_day + timedelta(days=offsets[i])
            dt = datetime.combine(day, time(srng.randint(7, 22), srng.randint(0, 59), srng.randint(0, 59)),
                                  tzinfo=UTC)
            if i > 0 and dt <= chain_drafts[-1].dt:
                dt = chain_drafts[-1].dt + timedelta(hours=srng.randint(2, 20))
            params = dict(base_params)
            params.update({k: _resolve_param(srng, v) for k, v in variant.params.items()})
            sid = variant.scenario_id or scenario.scenario_id
            draft = self._new_draft(scenario, variant, i, 0, srng, dt, customer, pool=pools[i], scenario_id=sid,
                                    product_sku=sku, product2_sku=sku2, order=order,
                                    order_ref_text=ref_text if self._merged_include(scenario, variant).get(
                                        "order_reference") else None, params=params)
            draft.chain_key = scenario.scenario_id
            draft.step_index = i
            draft.link = variant.link
            draft.root = chain_drafts[0] if chain_drafts else None
            if variant.link in ("exact_duplicate", "near_duplicate"):
                draft.link_target = chain_drafts[variant.of if variant.of is not None else 0]
            cases = [d for d in chain_drafts if d.link in ("original", "repeat")]
            draft.prior_cases = cases
            if variant.cite_previous or variant.cite is not None:
                if variant.cite is not None:
                    draft.cite_target = chain_drafts[variant.cite]
                else:
                    draft.cite_target = cases[-1] if cases else chain_drafts[-1]
            if variant.link in ("original", "repeat"):
                self._render(draft)
            chain_drafts.append(draft)
        self.drafts.extend(chain_drafts)

    # ------------------------------------------------------------------ rendering
    def _render(self, draft: Draft) -> None:
        v = draft.variant
        renderer = Renderer(rng=draft.rng, catalog=self.catalog, customer=draft.customer,
                            complaint_date=draft.dt.date(), order=draft.order, order_ref_text=draft.order_ref_text,
                            params=draft.params, product_sku=draft.product_sku, product2_sku=draft.product2_sku)
        draft.renderer = renderer
        sid = draft.scenario_id
        try:
            title = _cap(renderer.render(v.title))
            body = _cap(renderer.render(v.body))
            supporting = renderer.render(v.supporting)
        except Exception as exc:  # surfaced as a generation failure with the scenario id
            self.render_errors.append(f"[{sid}] render error: {exc}")
            title, body, supporting = v.title, v.body, v.supporting
        extras: list[str] = []
        order = draft.order
        order_ref_missing = (draft.include.get("order_reference") and draft.order_ref_text
                             and not renderer.log.order_ref_used)
        # e-mail, chat, phone ... carry no reference field, so the reference must be in the text
        if order_ref_missing and (draft.channel not in ("web_form", "mobile_app") or draft.rng.random() < 0.45):
            extras.append(renderer.render("Order reference: {order_ref}"))
        if draft.include.get("transaction_reference") and order:
            key = str(draft.params.get("txn_key", "last"))
            if not renderer.log.txns_used:
                extras.append(renderer.render(f"Transaction: {{txn:{key}}}"))
            draft.txn_ref = renderer.log.txns_used[0] if renderer.log.txns_used else None
        elif renderer.log.txns_used:
            draft.txn_ref = renderer.log.txns_used[0]
        if draft.include.get("photo") and not self.detector.found(complaint_text(title, body, supporting), "photo_evidence"):
            extras.append(draft.rng.choice(("Photos attached.", "Photos attached below.", "See attached photos.")))
            if "photo_evidence" not in draft.signals:
                draft.signals.append("photo_evidence")
        if draft.include.get("photo") and "photo_evidence" not in draft.signals:
            draft.signals.append("photo_evidence")
        if extras:
            supporting = " ".join(p for p in [supporting, *extras] if p)
        draft.title = title
        draft.supporting = supporting
        draft.description = adapt_channel(body, title, draft.channel, draft.style, renderer)
        draft.log = renderer.log
        # product field as the customer filled it in
        if v.product_service is not None:
            draft.product_service = renderer.render(v.product_service) if v.product_service else ""
        elif draft.include.get("product") and draft.product_sku:
            mentions = [value for etype, value in renderer.log.entities if etype in ("product", "service")]
            draft.product_service = mentions[0] if mentions else self.catalog.mention(draft.product_sku, draft.rng)
        else:
            draft.product_service = ""
        if draft.product_service and draft.product_sku and draft.product_sku not in renderer.log.product_skus:
            renderer.log.product_skus.append(draft.product_sku)
        draft.attachments = self._attachments(draft)

    def _attachments(self, draft: Draft) -> list[dict[str, str]]:
        files: list[dict[str, str]] = []
        rng = draft.rng
        if draft.include.get("photo"):
            stem = (draft.product_sku or "item").split("-")[1].lower() if draft.product_sku else "item"
            for n in range(1, rng.randint(1, 3) + 1):
                name = rng.choice(IMAGE_NAMES).format(n=n, d=draft.dt.strftime("%m%d"), p=stem)
                files.append({"file_name": name, "content_type": "image/png" if name.endswith(".png") else "image/jpeg"})
        if draft.channel == "uploaded":
            ext = rng.choice(("pdf", "pdf", "docx"))
            ctype = "application/pdf" if ext == "pdf" else (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            files.append({"file_name": f"complaint_letter_{draft.customer['last_name'].lower()}.{ext}",
                          "content_type": ctype})
        for extra in draft.variant.attachments or []:
            files.append({"file_name": str(extra["file_name"]), "content_type": str(extra["content_type"])})
        return files

    # ------------------------------------------------------------------ phase 2
    def _assign_ids(self) -> None:
        for pool, prefix in (("dev", "CMP"), ("holdout", "EVL")):
            ordered = sorted((d for d in self.drafts if d.pool == pool),
                             key=lambda d: (d.dt, d.scenario_id, d.variant_index, d.instance))
            for n, draft in enumerate(ordered, start=1):
                draft.complaint_id = f"{prefix}-{n:05d}"

    # ------------------------------------------------------------------ phase 3
    def _apply_near_duplicate(self, draft: Draft, source: Draft) -> None:
        rng = draft.rng
        text = source.description
        title = source.title
        for edit in draft.variant.edits or ["resend_prefix"]:
            if edit == "resend_prefix":
                text = rng.choice(("Sending this again as I have not had a reply. ", "Resending my message below. ",
                                   "Re-sending in case this did not come through. ")) + text
            elif edit == "update_suffix":
                text = text + rng.choice(("\n\nAny update would be appreciated.", "\n\nPlease let me know.",
                                          "\n\nI would appreciate a quick answer."))
            elif edit == "chase_suffix":
                text = text + rng.choice(("\n\nStill waiting on this one.", "\n\nCan someone pick this up please?"))
            elif edit == "typo":
                for good, bad in (("received", "recieved"), ("the ", "teh "), ("because", "becuase"),
                                  ("definitely", "definately"), ("until", "untill"), ("which", "wich")):
                    if good in text:
                        text = text.replace(good, bad, 1)
                        break
            elif edit == "drop_last_sentence":
                parts = re.split(r"(?<=[.!?])\s+", text.strip())
                if len(parts) > 3:
                    text = " ".join(parts[:-1])
            elif edit == "swap_greeting":
                text = text.replace("Hello,", "Hi,", 1) if "Hello," in text else text.replace("Hi", "Hello", 1)
            elif edit == "lowercase_start" and text[:1].isupper():
                text = text[0].lower() + text[1:]
        draft.title = title if rng.random() < 0.6 else f"{title} (resent)"
        draft.description = text
        draft.supporting = source.supporting
        draft.attachments = [dict(a) for a in source.attachments]
        draft.channel = source.channel
        draft.product_service = source.product_service
        draft.txn_ref = source.txn_ref
        draft.log = self._copy_log(source.log)
        draft.signals = list(dict.fromkeys(source.signals + draft.variant.signals_add))

    @staticmethod
    def _copy_log(log: RenderLog) -> RenderLog:
        """Copy of a source log for a resubmission (its references are already resolved in the text)."""
        return RenderLog(entities=list(log.entities), amounts=list(log.amounts), comp_amounts=list(log.comp_amounts),
                         elapsed_days=list(log.elapsed_days), outage_hours=list(log.outage_hours),
                         has_date=log.has_date, product_skus=list(log.product_skus),
                         order_ref_used=log.order_ref_used, txns_used=list(log.txns_used))

    def _copy_exact(self, draft: Draft, source: Draft) -> None:
        draft.title = source.title
        draft.description = source.description
        draft.supporting = source.supporting
        draft.attachments = [dict(a) for a in source.attachments]
        draft.channel = source.channel
        draft.product_service = source.product_service
        draft.txn_ref = source.txn_ref
        draft.log = self._copy_log(source.log)
        draft.signals = list(source.signals)
        draft.style = source.style

    def _history(self, draft: Draft) -> dict[str, Any]:
        cases = draft.prior_cases
        cited = draft.cite_target
        return {
            "prior_same_issue_count": len(cases),
            "unresolved_prior_same_issue": sum(1 for c in cases if c.seed_status in UNRESOLVED_STATUSES),
            "references_resolved_complaint": bool(cited is not None and cited.seed_status in RESOLVED_STATUSES),
        }

    def _facts(self, draft: Draft) -> dict[str, Any]:
        log = draft.log
        has_product = bool(draft.product_service) or bool(log.product_skus)
        return {
            "has_order_reference": is_valid_order_ref(draft.order_ref_text),
            "has_transaction_reference": bool(draft.txn_ref),
            "has_product": has_product,
            "product_sku": draft.product_sku if has_product else None,
            "has_photo_evidence": bool(draft.include.get("photo")),
            "has_date": bool(log.has_date),
            "word_count": len(draft.description.split()),
            "max_amount": max(log.amounts) if log.amounts else None,
            "requested_compensation_amount": max(log.comp_amounts) if log.comp_amounts else None,
            "max_elapsed_days": max(log.elapsed_days) if log.elapsed_days else None,
            "outage_hours": max(log.outage_hours) if log.outage_hours else None,
            "requested_resolution": draft.requested_resolution,
            "channel": draft.channel,
        }

    def _label_order(self, draft: Draft) -> dict[str, Any] | None:
        """Ledger record the labeler sees (mirrors records.resolve_order)."""
        if draft.order_mode in ("invalid_reference", "unknown_reference"):
            return {}
        if draft.order_mode == "malformed_reference":
            return None
        if is_valid_order_ref(draft.order_ref_text):
            return draft.order
        if draft.txn_ref and draft.order:
            return draft.order
        return None

    def _finalize(self, draft: Draft) -> None:
        if draft.link == "exact_duplicate" and draft.link_target is not None:
            self._copy_exact(draft, draft.link_target)
        elif draft.link == "near_duplicate" and draft.link_target is not None:
            self._apply_near_duplicate(draft, draft.link_target)
        literal_prev = draft.params.get("prev_ref_literal")
        if draft.log.prev_ref_used or PREV_PLACEHOLDER in draft.description + draft.title + draft.supporting:
            if literal_prev:
                ref = str(literal_prev)
            elif draft.cite_target is not None and draft.cite_target.complaint_id:
                ref = draft.cite_target.complaint_id
            else:
                raise ValueError(f"[{draft.scenario_id}] {{prev_ref}} used without a cited complaint")
            draft.title = draft.title.replace(PREV_PLACEHOLDER, ref)
            draft.description = draft.description.replace(PREV_PLACEHOLDER, ref)
            draft.supporting = draft.supporting.replace(PREV_PLACEHOLDER, ref)
            draft.log.entity("complaint_reference", ref)
            draft.previous_reference = ref
        elif draft.cite_target is not None and draft.cite_target.complaint_id:
            draft.previous_reference = draft.cite_target.complaint_id
        if literal_prev:
            draft.previous_reference = str(literal_prev)
        if draft.previous_reference and draft.link != "exact_duplicate" and "repeat_indicator" not in draft.signals:
            draft.signals.append("repeat_indicator")
        text = complaint_text(draft.title, draft.description, draft.supporting)
        facts = self._facts(draft)
        history = self._history(draft)
        signals = list(dict.fromkeys(draft.signals))
        secondary = draft.scenario.secondary
        label_order = self._label_order(draft)
        declared_input = {
            "complaint_date": _fmt_dt(draft.dt), "customer_ref": draft.customer["customer_ref"],
            "customer_type": draft.customer["customer_type"], "order": label_order, "complaint_facts": facts,
            "signals": signals, "history": history, "text": text,
            "primary_subcategory": draft.scenario.subcategory,
            "secondary_subcategories": [s["subcategory"] for s in secondary],
        }
        label = label_projection(label_declared(self.matrix, declared_input))
        self._check(draft, label, facts)
        self._coherence(draft, text, signals)
        draft.record = self._record(draft, label, facts, history, signals, label_order, text)

    # ------------------------------------------------------------------ checks
    def _check(self, draft: Draft, label: dict[str, Any], facts: dict[str, Any]) -> None:
        where = f"[{draft.scenario_id} v{draft.variant_index}.{draft.instance} {draft.complaint_id}]"
        if draft.intended_rule and label["resolution_rule"] != draft.intended_rule:
            self.failures.append(f"{where} intended {draft.intended_rule} but got {label['resolution_rule']}")
        exp = dict(draft.expect)
        if draft.difficulty_type == "emotional_low_priority":
            exp.setdefault("priority_in", ["P3"])
        if draft.difficulty_type == "calm_critical":
            exp.setdefault("priority_in", ["P0", "P1"])
        if draft.difficulty_type == "vip_minor":
            exp.setdefault("priority_in", ["P3"])
        if "priority_in" in exp and label["priority"] not in exp["priority_in"]:
            self.failures.append(f"{where} priority {label['priority']} not in {exp['priority_in']}")
        if "escalation_level" in exp and label["escalation_level"] != exp["escalation_level"]:
            self.failures.append(f"{where} escalation {label['escalation_level']} != {exp['escalation_level']}")
        for rid in exp.get("escalation_rules_include", []):
            if rid not in label["escalation_rules"]:
                self.failures.append(f"{where} escalation rule {rid} did not fire ({label['escalation_rules']})")
        for rid in exp.get("escalation_rules_exclude", []):
            if rid in label["escalation_rules"]:
                self.failures.append(f"{where} escalation rule {rid} fired unexpectedly")
        for mi in exp.get("missing_information_include", []):
            if mi not in label["missing_information"]:
                self.failures.append(f"{where} missing info {mi} not detected ({label['missing_information']})")
        for key in ("refund_eligibility", "replacement_eligibility", "compensation_eligibility"):
            if key in exp and label[key] != exp[key]:
                self.failures.append(f"{where} {key} {label[key]} != {exp[key]}")
        if draft.difficulty_type == "vip_minor" and draft.customer["customer_type"] != "vip":
            self.failures.append(f"{where} vip_minor scenario assigned to a non-VIP customer")

    def _coherence(self, draft: Draft, text: str, signals: list[str]) -> None:
        """Lexical self-check: declared signals must be expressed; undeclared hits are reported."""
        detected = self.detector.detect(text)
        missing = [s for s in signals if not self.detector.found_any(text, s)]
        negated_only = [s for s in signals if s not in detected and s not in missing]
        undeclared = sorted(detected - set(signals))
        traps = [s for s in undeclared if s in draft.lexical_traps]
        unexplained = [s for s in undeclared if s not in draft.lexical_traps]
        if missing or negated_only or unexplained or traps:
            self.coherence.append({
                "complaint_id": draft.complaint_id, "scenario_id": draft.scenario_id,
                "declared_not_found": missing, "declared_negated_only": negated_only,
                "undeclared_lexical_hits": unexplained, "deliberate_lexical_traps": traps,
                "evidence": {s: self.detector.evidence(text, s) for s in unexplained + traps},
            })

    # ------------------------------------------------------------------ records
    def _tags(self, draft: Draft, label: dict[str, Any], facts: dict[str, Any], history: dict[str, Any],
              signals: list[str], order: dict[str, Any] | None) -> list[str]:
        tags = set(draft.tags)
        tags.add(draft.difficulty_type)
        sigs = set(signals)
        secondary = draft.scenario.secondary
        if secondary:
            tags.add("multi_issue")
            if len(secondary) >= 2:
                tags.add("three_plus_issues")
        if label["subcategory"] == "ACC-UNA" or sigs & SECURITY_SIGNALS:
            tags.add("security")
        if label["category"] == "PRV" or sigs & PRIVACY_SIGNALS:
            tags.add("privacy")
        if label["category"] == "SAF" or sigs & SAFETY_SIGNALS:
            tags.add("safety")
        for sig in ("legal_threat", "media_threat", "chargeback_threat", "policy_exception_request",
                    "embedded_policy_claim"):
            if sig in sigs:
                tags.add(sig)
        if order and order.get("order_total"):
            total = float(order["order_total"])
            if total >= 500:
                tags.add("high_value")
            if total >= 1500:
                tags.add("high_value_1500")
            if total >= 2500 and draft.customer["customer_type"] == "business":
                tags.add("high_value_business")
        refund_asked = draft.requested_resolution == "refund" or "refund_request" in sigs
        if refund_asked and label["refund_eligibility"] == "not_eligible":
            tags.add("unsupported_refund")
        comp_amount = facts.get("requested_compensation_amount")
        comp_asked = draft.requested_resolution == "compensation" or "compensation_request" in sigs or comp_amount
        if comp_asked:
            status = label["compensation_eligibility"]
            if status in ("not_eligible", "not_applicable"):
                tags.add("unsupported_compensation")
            elif comp_amount is not None:
                entitled = label.get("compensation_amount_usd")
                limit = float(entitled) if status == "eligible" and entitled is not None else AGENT_LIMIT_USD
                if float(comp_amount) > limit:
                    tags.add("unsupported_compensation")
        if draft.style == "angry" and label["priority"] == "P3":
            tags.add("emotional_low_priority")
        if draft.style in ("calm", "polite") and label["priority"] in ("P0", "P1"):
            tags.add("calm_critical")
        if draft.customer["customer_type"] == "vip" and label["priority"] == "P3":
            tags.add("vip_minor")
        if label["escalation_required"]:
            tags.add("escalated")
        if label["missing_information"]:
            tags.add("missing_info")
        if label["blocking_missing_information"]:
            tags.add("blocking_missing_info")
        if draft.link in ("repeat", "near_duplicate", "exact_duplicate"):
            tags.add(draft.link)
        if history["references_resolved_complaint"]:
            tags.add("reopened")
        if history["unresolved_prior_same_issue"] >= 2:
            tags.add("repeat_unresolved_2plus")
        if history["unresolved_prior_same_issue"] >= 3:
            tags.add("repeat_unresolved_3plus")
        if draft.order_mode in ("invalid_reference", "unknown_reference"):
            tags.add("invalid_order_reference")
        if draft.order_mode == "malformed_reference":
            tags.add("malformed_order_reference")
        if draft.order_mode == "other_customer":
            tags.add("order_ownership_mismatch")
        if draft.params.get("prev_ref_literal"):
            tags.add("invalid_complaint_reference")
        if draft.scenario.prompt_injection:
            tags.add("prompt_injection")
        if draft.chain_key and draft.link == "original":
            tags.add("chain_original")
        for trap in draft.lexical_traps:
            tags.add(f"lexical_trap:{trap}")
        return sorted(tags)

    def _entities(self, draft: Draft, text: str) -> list[dict[str, str]]:
        """Slot-registered entities present in the final text, plus product/service mentions written literally.

        Entities are ordered by first appearance; every value is an exact substring of the text.
        """
        found: list[tuple[str, str]] = [(t, v) for t, v in draft.log.entities if v in text]
        covered: list[tuple[int, int]] = []
        for _, value in found:
            start = 0
            while (idx := text.find(value, start)) >= 0:
                covered.append((idx, idx + len(value)))
                start = idx + len(value)
        for sku, mention, _, _ in self.catalog.scan_mentions(text, covered):
            item = (self.catalog.get(sku).entity_type, mention)
            if item not in found:
                found.append(item)
        found.sort(key=lambda item: text.find(item[1]))
        return [{"type": etype, "value": value} for etype, value in found]

    def _emotions(self, draft: Draft) -> list[str]:
        base = list(draft.variant.emotions) if draft.variant.emotions is not None else list(STYLE_EMOTIONS[draft.style])
        if draft.variant.emotions is None:
            base += draft.scenario.emotions_add
        return [e for e in EMOTIONS if e in set(base)]

    def _tone(self, draft: Draft) -> str:
        rng = sub_rng(self.seed, draft.scenario_id, draft.variant_index, draft.instance, "tone")
        if draft.channel == "uploaded" or draft.customer["customer_type"] == "business":
            weights = {"formal": 45, "professional": 30, "concise": 20, "empathetic": 5}
        elif draft.style == "angry":
            weights = {"empathetic": 45, "professional": 30, "formal": 10, "concise": 15}
        elif draft.style == "frustrated":
            weights = {"empathetic": 35, "professional": 35, "concise": 20, "formal": 10}
        else:
            weights = {"professional": 40, "concise": 25, "empathetic": 20, "formal": 15}
        return weighted_choice(rng, weights, list(TONES))

    def _record(self, draft: Draft, label: dict[str, Any], facts: dict[str, Any], history: dict[str, Any],
                signals: list[str], label_order: dict[str, Any] | None, text: str) -> dict[str, Any]:
        scenario = draft.scenario
        real_order = label_order if label_order else None
        tags = self._tags(draft, label, facts, history, signals, real_order)
        render = Renderer(rng=random.Random(0), catalog=self.catalog, customer=draft.customer,
                          complaint_date=draft.dt.date(), order=draft.order, order_ref_text=draft.order_ref_text,
                          params=draft.params, product_sku=draft.product_sku, product2_sku=draft.product2_sku)
        primary_issue = render.render(scenario.primary_issue.replace("{product}", "{product:full}"))
        entities = self._entities(draft, text)
        product_sku = facts.get("product_sku")
        if not product_sku and real_order and real_order.get("items"):
            product_sku = real_order["items"][0]["sku"]
        link_id = draft.link_target.complaint_id if draft.link_target else None
        expected = {
            "primary_issue": primary_issue,
            "secondary_issues": [
                {"label": s["label"], "category": self.matrix.category_of(s["subcategory"]),
                 "subcategory": s["subcategory"]} for s in scenario.secondary],
            "category": label["category"],
            "subcategory": label["subcategory"],
            "sentiment": draft.variant.sentiment or STYLE_SENTIMENT[draft.style],
            "emotion_indicators": self._emotions(draft),
            "urgency": label["urgency"],
            "impact": label["impact"],
            "priority": label["priority"],
            "entities": entities,
            "department": label["department"],
            "supporting_departments": label["supporting_departments"],
            "policy_references": label["policy_references"],
            "resolution_rule": label["resolution_rule"],
            "required_actions": label["required_actions"],
            "refund_eligibility": label["refund_eligibility"],
            "replacement_eligibility": label["replacement_eligibility"],
            "compensation_eligibility": label["compensation_eligibility"],
            "compensation_amount_usd": label["compensation_amount_usd"],
            "escalation_required": label["escalation_required"],
            "escalation_level": label["escalation_level"],
            "escalation_rules": label["escalation_rules"],
            "follow_up_required": label["follow_up_required"],
            "follow_up_type": label["follow_up_type"],
            "missing_information": label["missing_information"],
            "blocking_missing_information": label["blocking_missing_information"],
            "is_duplicate_of": link_id if draft.link == "exact_duplicate" else None,
            "is_near_duplicate_of": link_id if draft.link == "near_duplicate" else None,
            "is_repeat_of": draft.root.complaint_id if draft.link == "repeat" and draft.root else None,
            "prompt_injection": bool(scenario.prompt_injection),
            "manual_review_expected": manual_review_expected(
                prompt_injection=bool(scenario.prompt_injection), tags=tags, category=label["category"],
                signals=signals, blocking_missing=bool(label["blocking_missing_information"])),
        }
        order_field = draft.order_ref_text if draft.include.get("order_reference") or draft.order_mode != "normal" else None
        return jsonable({
            "complaint_id": draft.complaint_id,
            "title": draft.title,
            "description": draft.description,
            "customer_ref": draft.customer["customer_ref"],
            "customer_name": draft.customer["full_name"],
            "customer_type": draft.customer["customer_type"],
            "product_service": draft.product_service,
            "product_sku": product_sku,
            "order_reference": order_field,
            "transaction_reference": draft.txn_ref,
            "channel": draft.channel,
            "complaint_date": _fmt_dt(draft.dt),
            "previous_complaint_reference": draft.previous_reference,
            "preferred_contact_method": "chat" if draft.channel == "chat" and draft.rng.random() < 0.4 else
            draft.customer["preferred_contact_method"],
            "requested_resolution": draft.requested_resolution,
            "supporting_information": draft.supporting,
            "attachments": draft.attachments,
            "requested_tone": self._tone(draft),
            "seed_status": draft.seed_status,
            "declared": {"signals": signals, "complaint_facts": facts, "history": history},
            "expected": expected,
            "difficulty_type": draft.difficulty_type,
            "tags": tags,
            "scenario_id": draft.scenario_id,
            "split": draft.pool,
        })

    # ------------------------------------------------------------------ orchestration
    def _background_orders(self, count: int = 160) -> None:
        devices = self.catalog.device_skus()
        for i in range(count):
            rng = sub_rng(self.seed, "background", i)
            customer = self.customers[rng.randrange(len(self.customers))]
            ctx = OrderContext(anchor=DEV_END - timedelta(days=rng.randint(0, 120)),
                               customer_ref=customer["customer_ref"], customer_type=customer["customer_type"],
                               skus=[rng.choice(devices)], rng=rng, refs=self.refs, catalog=self.catalog)
            order = background_order(ctx)
            self.orders[order["order_ref"]] = order

    def build(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Generate everything; returns (dev records, holdout records)."""
        for scenario in self.scenarios:
            if scenario.kind == "chain":
                self._chain(scenario)
            else:
                self._single(scenario)
        self._background_orders()
        self._assign_ids()
        for draft in sorted(self.drafts, key=lambda d: (d.dt, d.pool, d.complaint_id or "")):
            self._finalize(draft)
        dev = sorted((d.record for d in self.drafts if d.pool == "dev" and d.record), key=lambda r: r["complaint_id"])
        holdout = sorted((d.record for d in self.drafts if d.pool == "holdout" and d.record),
                         key=lambda r: r["complaint_id"])
        self._uniqueness(dev + holdout)
        return dev, holdout

    def _uniqueness(self, records: list[dict[str, Any]]) -> None:
        seen: dict[str, str] = {}
        for record in records:
            key = complaint_text(record["title"], record["description"], "")
            dup_of = record["expected"]["is_duplicate_of"]
            if key in seen and not dup_of:
                self.failures.append(f"[{record['scenario_id']} {record['complaint_id']}] text identical to {seen[key]}")
            seen.setdefault(key, record["complaint_id"])

    def ledger(self) -> list[dict[str, Any]]:
        return sorted(self.orders.values(), key=lambda o: (o["customer_ref"], o["order_date"], o["order_ref"]))

    def stats(self) -> dict[str, Any]:
        """Small generation statistics block for the summary."""
        return {"scenarios": len(self.scenarios), "complaints": len(self.drafts),
                "styles": dict(sorted(Counter(d.style for d in self.drafts).items())),
                "vocabulary_size": len(set().union(*(tokens(d.description) for d in self.drafts))) if self.drafts else 0,
                "ledger_orders": len(self.orders)}
