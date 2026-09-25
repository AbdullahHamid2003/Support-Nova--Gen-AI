"""Simulated order ledger and named *order profiles*.

The SRS forbids live payment/CRM integration, so every order referenced by a
complaint is synthesised here. A profile builds one ledger record that makes a
scenario's facts true *relative to the complaint date* (the profile anchor):
e.g. ``in_transit_late_standard(bdays_late=[4, 8])`` produces an undelivered
standard-shipping order whose estimated delivery date lies exactly 4-8 business
days before the complaint. Business days are Monday-Friday (as in
``supportnova.core.timeutil``). Unit prices always come from config/products.yaml.

The ledger is a snapshot *as of the latest complaint that references the order*:
no event is dated after that complaint.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from supportnova.core.timeutil import add_business_days, business_days_between

from .catalog import Catalog
from .common import INVALID_ORDER_REF, pick_amount, pick_range, sub_rng

STANDARD_TRANSIT_BDAYS = 4
EXPRESS_TRANSIT_BDAYS = 2
EXPRESS_FEE = 14.99
STANDARD_FEE = 5.99
FREE_SHIPPING_FROM = 75.0
COMPANIONS: tuple[str, ...] = ("LUM-HUB-800", "LUM-CAM-210", "LUM-CAM-200", "LUM-AIR-900", "LUM-LCK-700", "LUM-TH-100")
LUMORA_ERROR_REASONS = frozenset({"defective", "damaged_on_arrival", "wrong_item"})


# ---------------------------------------------------------------------------
# Reference allocation
# ---------------------------------------------------------------------------
class RefAllocator:
    """Unique, deterministic LMR-###### order refs and TXN-######## transaction refs."""

    def __init__(self, seed: int) -> None:
        self.rng = sub_rng(seed, "refs")
        self.orders: set[str] = {INVALID_ORDER_REF}
        self.txns: set[str] = set()
        self.reserved_invalid: set[str] = {INVALID_ORDER_REF}

    def order_ref(self) -> str:
        while True:
            ref = f"LMR-{self.rng.randint(100000, 999999)}"
            if ref not in self.orders:
                self.orders.add(ref)
                return ref

    def txn_ref(self) -> str:
        while True:
            ref = f"TXN-{self.rng.randint(10000000, 99999999)}"
            if ref not in self.txns:
                self.txns.add(ref)
                return ref

    def unknown_order_ref(self) -> str:
        """A well-formed order reference that is guaranteed NOT to exist in the ledger."""
        ref = self.order_ref()
        self.reserved_invalid.add(ref)
        return ref


# ---------------------------------------------------------------------------
# Business-day helpers
# ---------------------------------------------------------------------------
def bday_back(day: date, n: int) -> date:
    """The business day ``n`` business days before ``day``."""
    current, count = day, 0
    while count < n:
        current -= timedelta(days=1)
        if current.weekday() < 5:
            count += 1
    return current


def bday_on_or_after(day: date) -> date:
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def latest_bday_with_count(end: date, n: int) -> date:
    """Latest business day ``e < end`` with ``business_days_between(e, end) == n`` (n >= 1)."""
    for k in range(1, 400):
        candidate = end - timedelta(days=k)
        if candidate.weekday() < 5 and business_days_between(candidate, end) == n:
            return candidate
    raise ValueError(f"cannot place a date {n} business days before {end}")


# ---------------------------------------------------------------------------
# Record construction
# ---------------------------------------------------------------------------
@dataclass
class OrderContext:
    """Everything a profile needs to synthesise one ledger record."""

    anchor: date
    customer_ref: str
    customer_type: str
    skus: list[str]
    rng: random.Random
    refs: RefAllocator
    catalog: Catalog


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _money(value: float) -> float:
    return round(value + 1e-9, 2)


def _items(ctx: OrderContext, qty: int = 1, min_total: float | None = None, extra: list[str] | None = None,
           bulk: bool = False) -> list[dict[str, Any]]:
    main = ctx.skus[0]
    items: list[dict[str, Any]] = [{"sku": main, "qty": int(qty), "unit_price": ctx.catalog.price(main)}]
    for sku in extra or []:
        items.append({"sku": sku, "qty": 1, "unit_price": ctx.catalog.price(sku)})
    if min_total:
        def subtotal() -> float:
            return sum(i["qty"] * i["unit_price"] for i in items)
        if bulk or ctx.customer_type == "business":
            while subtotal() < float(min_total):
                items[0]["qty"] += 1
        else:
            pool = [s for s in COMPANIONS if s not in {i["sku"] for i in items}]
            ctx.rng.shuffle(pool)
            while subtotal() < float(min_total) and pool:
                sku = pool.pop()
                items.append({"sku": sku, "qty": 1, "unit_price": ctx.catalog.price(sku)})
            while subtotal() < float(min_total):
                items[0]["qty"] += 1
    return items


def _subtotal(items: list[dict[str, Any]]) -> float:
    return _money(sum(i["qty"] * i["unit_price"] for i in items))


def _shipping_fee(method: str, subtotal: float, digital: bool = False) -> float:
    if digital:
        return 0.0
    if method == "express":
        return EXPRESS_FEE
    return 0.0 if subtotal >= FREE_SHIPPING_FROM else STANDARD_FEE


def _care_plus_default(ctx: OrderContext, care_plus: bool | None) -> bool:
    if care_plus is not None:
        return bool(care_plus)
    return ctx.customer_type == "care_plus"


def _record(ctx: OrderContext, *, items: list[dict[str, Any]], shipping_method: str, order_date: date,
            eta: date | None, dispatched: date | None, delivered: date | None, status: str,
            tracking: date | None, digital: bool = False, charges: list[tuple[date, float]] | None = None,
            refunds: list[tuple[date, float]] | None = None, care_plus: bool | None = None,
            replacement_count: int = 0, careplus_claims: int = 0, ret: dict[str, Any] | None = None,
            cancellation: dict[str, Any] | None = None, subscription: dict[str, Any] | None = None,
            trace: dict[str, Any] | None = None, order_total: float | None = None,
            double_charge: bool = False) -> dict[str, Any]:
    subtotal = _subtotal(items)
    fee = _shipping_fee(shipping_method, subtotal, digital)
    total = _money(order_total if order_total is not None else subtotal + fee)
    if double_charge and charges is None:
        charges = [(order_date, total), (min(order_date + timedelta(days=1), ctx.anchor), total)]
    transactions: list[dict[str, Any]] = []
    for when, amount in (charges if charges is not None else [(order_date, total)]):
        transactions.append({"txn_ref": ctx.refs.txn_ref(), "type": "charge", "amount": _money(amount),
                             "date": when.isoformat()})
    for when, amount in refunds or []:
        transactions.append({"txn_ref": ctx.refs.txn_ref(), "type": "refund", "amount": _money(amount),
                             "date": when.isoformat()})
    transactions.sort(key=lambda t: (t["date"], t["type"]))
    return {
        "order_ref": ctx.refs.order_ref(),
        "customer_ref": ctx.customer_ref,
        "items": items,
        "order_total": total,
        "shipping_method": shipping_method,
        "shipping_fee": fee,
        "order_date": order_date.isoformat(),
        "estimated_delivery_date": _iso(eta),
        "dispatched_date": _iso(dispatched),
        "delivered_date": _iso(delivered),
        "status": status,
        "tracking_last_update": _iso(tracking),
        "transactions": transactions,
        "care_plus": _care_plus_default(ctx, care_plus) if not digital else bool(care_plus),
        "replacement_count": int(replacement_count),
        "careplus_claims_12m": int(careplus_claims),
        "return": ret,
        "cancellation": cancellation,
        "subscription": subscription,
        "trace": trace,
    }


def _physical_timeline(ctx: OrderContext, delivered: date, shipping: str, late_bdays: int) -> tuple[date, date, date]:
    """(order_date, eta, dispatched) for an order delivered on ``delivered``."""
    eta = latest_bday_with_count(delivered, late_bdays) if late_bdays > 0 else bday_on_or_after(delivered)
    transit = EXPRESS_TRANSIT_BDAYS if shipping == "express" else STANDARD_TRANSIT_BDAYS
    order_date = bday_back(eta, transit)
    dispatched = order_date if shipping == "express" else add_business_days(order_date, 1)
    if dispatched > delivered:
        dispatched = delivered
    return order_date, eta, dispatched


# ---------------------------------------------------------------------------
# Profiles - delivered orders
# ---------------------------------------------------------------------------
def delivered_days_ago(ctx: OrderContext, days: Any = (1, 6), shipping: str = "standard", qty: int = 1,
                       min_total: float | None = None, extra: list[str] | None = None, bulk: bool = False,
                       late_bdays: Any = 0, care_plus: bool | None = None, replacement_count: int = 0,
                       careplus_claims: int = 0, double_charge: bool = False) -> dict[str, Any]:
    """Order delivered ``days`` calendar days before the complaint (optionally delivered late / charged twice)."""
    n = pick_range(ctx.rng, days)
    delivered = ctx.anchor - timedelta(days=n)
    late = pick_range(ctx.rng, late_bdays)
    order_date, eta, dispatched = _physical_timeline(ctx, delivered, shipping, late)
    items = _items(ctx, qty, min_total, extra, bulk)
    return _record(ctx, items=items, shipping_method=shipping, order_date=order_date, eta=eta,
                   dispatched=dispatched, delivered=delivered, status="delivered", tracking=delivered,
                   care_plus=care_plus, replacement_count=replacement_count, careplus_claims=careplus_claims,
                   double_charge=double_charge)


def delivered_recent(ctx: OrderContext, days: Any = (1, 6), **kw: Any) -> dict[str, Any]:
    """Delivered within the last few days."""
    return delivered_days_ago(ctx, days=days, **kw)


def delivered_within_doa(ctx: OrderContext, days: Any = (1, 7), **kw: Any) -> dict[str, Any]:
    """Delivered inside the 7-day damaged-on-arrival reporting window (RPL-POL-03 3.1)."""
    return delivered_days_ago(ctx, days=days, **kw)


def delivered_old(ctx: OrderContext, days: Any = (35, 80), **kw: Any) -> dict[str, Any]:
    """Delivered more than a month ago (outside the standard 30-day windows)."""
    return delivered_days_ago(ctx, days=days, **kw)


def delivered_months_ago(ctx: OrderContext, months: Any = (3, 10), **kw: Any) -> dict[str, Any]:
    """Delivered ``months`` months ago (warranty scenarios); jitter keeps dates varied."""
    m = pick_range(ctx.rng, months)
    days = round(m * 30.44) + ctx.rng.randint(-6, 6)
    return delivered_days_ago(ctx, days=max(days, 31), **kw)


def delivered_late(ctx: OrderContext, bdays_late: Any = (4, 8), days: Any = (0, 2), shipping: str = "standard",
                   **kw: Any) -> dict[str, Any]:
    """Delivered ``days`` ago but ``bdays_late`` business days after the estimated date."""
    return delivered_days_ago(ctx, days=days, shipping=shipping, late_bdays=bdays_late, **kw)


def marked_delivered(ctx: OrderContext, days: Any = (1, 4), **kw: Any) -> dict[str, Any]:
    """Carrier marked the parcel delivered ``days`` ago (the customer says it never arrived)."""
    return delivered_days_ago(ctx, days=days, **kw)


# ---------------------------------------------------------------------------
# Profiles - orders in transit / not dispatched / lost
# ---------------------------------------------------------------------------
def in_transit(ctx: OrderContext, bdays_to_eta: Any = (1, 3), shipping: str = "standard", qty: int = 1,
               min_total: float | None = None, extra: list[str] | None = None, bulk: bool = False) -> dict[str, Any]:
    """Dispatched and on its way; the estimated delivery date is still in the future."""
    n = min(max(pick_range(ctx.rng, bdays_to_eta), 1), 3)
    eta = add_business_days(ctx.anchor, n)
    transit = EXPRESS_TRANSIT_BDAYS if shipping == "express" else STANDARD_TRANSIT_BDAYS
    order_date = bday_back(eta, transit + 1)
    dispatched = min(add_business_days(order_date, 1), ctx.anchor)
    tracking = max(dispatched, ctx.anchor - timedelta(days=1))
    items = _items(ctx, qty, min_total, extra, bulk)
    return _record(ctx, items=items, shipping_method=shipping, order_date=order_date, eta=eta,
                   dispatched=dispatched, delivered=None, status="in_transit", tracking=tracking)


def in_transit_late_standard(ctx: OrderContext, bdays_late: Any = (4, 8), qty: int = 1,
                             min_total: float | None = None, extra: list[str] | None = None, bulk: bool = False,
                             stale_bdays: Any = 0) -> dict[str, Any]:
    """Standard-shipping order still in transit ``bdays_late`` business days after its estimate."""
    n = pick_range(ctx.rng, bdays_late)
    eta = latest_bday_with_count(ctx.anchor, n)
    order_date = bday_back(eta, STANDARD_TRANSIT_BDAYS)
    dispatched = add_business_days(order_date, 1)
    stale = pick_range(ctx.rng, stale_bdays)
    tracking = bday_back(ctx.anchor, stale) if stale else max(dispatched, ctx.anchor - timedelta(days=ctx.rng.randint(1, 2)))
    items = _items(ctx, qty, min_total, extra, bulk)
    return _record(ctx, items=items, shipping_method="standard", order_date=order_date, eta=eta,
                   dispatched=dispatched, delivered=None, status="in_transit", tracking=tracking)


def late_express(ctx: OrderContext, bdays_late: Any = (1, 3), delivered: bool = False, qty: int = 1,
                 min_total: float | None = None, extra: list[str] | None = None) -> dict[str, Any]:
    """Express order that missed its 1-2 business-day estimate (delivered late or still in transit)."""
    n = pick_range(ctx.rng, bdays_late)
    items = _items(ctx, qty, min_total, extra)
    if delivered:
        when = ctx.anchor - timedelta(days=ctx.rng.randint(0, 2))
        eta = latest_bday_with_count(when, n)
        order_date = bday_back(eta, EXPRESS_TRANSIT_BDAYS)
        return _record(ctx, items=items, shipping_method="express", order_date=order_date, eta=eta,
                       dispatched=order_date, delivered=when, status="delivered", tracking=when)
    eta = latest_bday_with_count(ctx.anchor, n)
    order_date = bday_back(eta, EXPRESS_TRANSIT_BDAYS)
    tracking = max(order_date, ctx.anchor - timedelta(days=1))
    return _record(ctx, items=items, shipping_method="express", order_date=order_date, eta=eta,
                   dispatched=order_date, delivered=None, status="in_transit", tracking=tracking)


def not_dispatched(ctx: OrderContext, days: Any = (1, 3), cancellation: bool = True, confirmed: bool = False,
                   qty: int = 1, extra: list[str] | None = None) -> dict[str, Any]:
    """Order still being processed (not dispatched), optionally with a cancellation request."""
    n = pick_range(ctx.rng, days)
    order_date = ctx.anchor - timedelta(days=n)
    eta = add_business_days(order_date, STANDARD_TRANSIT_BDAYS)
    items = _items(ctx, qty, None, extra)
    cancel = None
    if cancellation:
        requested = min(order_date + timedelta(days=ctx.rng.randint(0, 1)), ctx.anchor)
        cancel = {"requested_date": requested.isoformat(), "confirmed": bool(confirmed)}
    return _record(ctx, items=items, shipping_method="standard", order_date=order_date, eta=eta,
                   dispatched=None, delivered=None, status="processing", tracking=None, cancellation=cancel)


def cancel_ignored_dispatched(ctx: OrderContext, days: Any = (4, 9), confirmed: bool = False,
                              qty: int = 1) -> dict[str, Any]:
    """Cancellation requested on the order day, but the order was dispatched anyway."""
    n = pick_range(ctx.rng, days)
    order_date = ctx.anchor - timedelta(days=n)
    dispatched = add_business_days(order_date, 1)
    eta = add_business_days(order_date, STANDARD_TRANSIT_BDAYS)
    delivered = eta if eta <= ctx.anchor else None
    items = _items(ctx, qty)
    cancel = {"requested_date": order_date.isoformat(), "confirmed": bool(confirmed)}
    return _record(ctx, items=items, shipping_method="standard", order_date=order_date, eta=eta,
                   dispatched=dispatched, delivered=delivered, status="delivered" if delivered else "in_transit",
                   tracking=delivered or dispatched, cancellation=cancel)


def lost_no_updates(ctx: OrderContext, bdays_since_update: Any = (8, 14), qty: int = 1,
                    min_total: float | None = None, extra: list[str] | None = None, bulk: bool = False,
                    trace_open: bool = False, double_charge: bool = False) -> dict[str, Any]:
    """Dispatched order with no tracking update for 7+ business days (DEL-POL-04 6.1)."""
    n = pick_range(ctx.rng, bdays_since_update)
    tracking = bday_back(ctx.anchor, n)
    dispatched = bday_back(tracking, ctx.rng.randint(1, 2))
    order_date = bday_back(dispatched, 1)
    eta = add_business_days(order_date, STANDARD_TRANSIT_BDAYS)
    items = _items(ctx, qty, min_total, extra, bulk)
    trace = None
    if trace_open:
        trace = {"opened_date": bday_back(ctx.anchor, ctx.rng.randint(1, 3)).isoformat(), "completed": False}
    return _record(ctx, items=items, shipping_method="standard", order_date=order_date, eta=eta,
                   dispatched=dispatched, delivered=None, status="in_transit", tracking=tracking, trace=trace,
                   double_charge=double_charge)


def trace_completed(ctx: OrderContext, trace_bdays: Any = (6, 9), qty: int = 1, min_total: float | None = None,
                    extra: list[str] | None = None, bulk: bool = False) -> dict[str, Any]:
    """Carrier trace finished without locating the parcel (DEL-POL-04 6.2)."""
    n = pick_range(ctx.rng, trace_bdays)
    opened = bday_back(ctx.anchor, n)
    tracking = bday_back(opened, ctx.rng.randint(7, 9))
    dispatched = bday_back(tracking, 1)
    order_date = bday_back(dispatched, 1)
    eta = add_business_days(order_date, STANDARD_TRANSIT_BDAYS)
    items = _items(ctx, qty, min_total, extra, bulk)
    trace = {"opened_date": opened.isoformat(), "completed": True}
    return _record(ctx, items=items, shipping_method="standard", order_date=order_date, eta=eta,
                   dispatched=dispatched, delivered=None, status="lost", tracking=tracking, trace=trace)


# ---------------------------------------------------------------------------
# Profiles - billing
# ---------------------------------------------------------------------------
def _ordered_days_ago(ctx: OrderContext, n: int, qty: int = 1, extra: list[str] | None = None,
                      shipping: str = "standard", min_total: float | None = None,
                      bulk: bool = False) -> tuple[list[dict[str, Any]], date, date, date, date | None, str]:
    order_date = ctx.anchor - timedelta(days=n)
    transit = EXPRESS_TRANSIT_BDAYS if shipping == "express" else STANDARD_TRANSIT_BDAYS
    eta = add_business_days(order_date, transit)
    dispatched = add_business_days(order_date, 1) if shipping == "standard" else order_date
    delivered = eta if eta <= ctx.anchor else None
    status = "delivered" if delivered else ("in_transit" if dispatched <= ctx.anchor else "processing")
    return _items(ctx, qty, min_total, extra, bulk), order_date, eta, dispatched, delivered, status


def duplicate_charge(ctx: OrderContext, days: Any = (3, 25), gap_days: Any = (0, 2), qty: int = 1,
                     extra: list[str] | None = None, min_total: float | None = None,
                     bulk: bool = False) -> dict[str, Any]:
    """Two identical charges for one order, at most 2 days apart (verifiable duplicate, BIL-POL-05 4.1)."""
    n = pick_range(ctx.rng, days)
    items, order_date, eta, dispatched, delivered, status = _ordered_days_ago(ctx, n, qty, extra, "standard",
                                                                                min_total, bulk)
    gap = min(pick_range(ctx.rng, gap_days), n)
    subtotal = _subtotal(items)
    total = _money(subtotal + _shipping_fee("standard", subtotal))
    second = min(order_date + timedelta(days=gap), ctx.anchor)
    return _record(ctx, items=items, shipping_method="standard", order_date=order_date, eta=eta,
                   dispatched=dispatched if dispatched <= ctx.anchor else None, delivered=delivered,
                   status=status, tracking=delivered or (dispatched if dispatched <= ctx.anchor else None),
                   charges=[(order_date, total), (second, total)])


def duplicate_charge_old(ctx: OrderContext, days: Any = (68, 110), **kw: Any) -> dict[str, Any]:
    """Duplicate charge raised after the 60-day billing dispute window."""
    return duplicate_charge(ctx, days=days, **kw)


def single_charge(ctx: OrderContext, days: Any = (3, 25), qty: int = 1, extra: list[str] | None = None,
                  shipping: str = "standard") -> dict[str, Any]:
    """Ordinary order with exactly one charge equal to the order total."""
    n = pick_range(ctx.rng, days)
    items, order_date, eta, dispatched, delivered, status = _ordered_days_ago(ctx, n, qty, extra, shipping)
    return _record(ctx, items=items, shipping_method=shipping, order_date=order_date, eta=eta,
                   dispatched=dispatched if dispatched <= ctx.anchor else None, delivered=delivered,
                   status=status, tracking=delivered or (dispatched if dispatched <= ctx.anchor else None))


def charged_correctly(ctx: OrderContext, days: Any = (3, 20), **kw: Any) -> dict[str, Any]:
    """The charge equals the order total (the customer's 'wrong amount' is explained by the ledger)."""
    return single_charge(ctx, days=days, **kw)


def charge_old(ctx: OrderContext, days: Any = (66, 120), **kw: Any) -> dict[str, Any]:
    """Ordinary charge older than the 60-day billing dispute window."""
    return single_charge(ctx, days=days, **kw)


def overcharged(ctx: OrderContext, days: Any = (3, 20), diff: Any = (10, 40), qty: int = 1,
                extra: list[str] | None = None, shipping: str = "standard") -> dict[str, Any]:
    """The card was charged more than the order total (verifiable overcharge, BIL-POL-05 4.2)."""
    n = pick_range(ctx.rng, days)
    items, order_date, eta, dispatched, delivered, status = _ordered_days_ago(ctx, n, qty, extra, shipping)
    subtotal = _subtotal(items)
    total = _money(subtotal + _shipping_fee(shipping, subtotal))
    extra_amount = pick_amount(ctx.rng, diff)
    return _record(ctx, items=items, shipping_method=shipping, order_date=order_date, eta=eta,
                   dispatched=dispatched if dispatched <= ctx.anchor else None, delivered=delivered,
                   status=status, tracking=delivered or (dispatched if dispatched <= ctx.anchor else None),
                   charges=[(order_date, total + extra_amount)])


# ---------------------------------------------------------------------------
# Profiles - returns and refunds
# ---------------------------------------------------------------------------
def _refund_amount(items: list[dict[str, Any]], fee: float, reason: str, restocking: float = 0.0) -> float:
    subtotal = _subtotal(items)
    base = subtotal + (fee if reason in LUMORA_ERROR_REASONS else 0.0)
    return _money(base - restocking)


def refund_issued_bd_ago(ctx: OrderContext, bdays: Any = (10, 15), reason: str = "defective",
                         qty: int = 1) -> dict[str, Any]:
    """Return inspected and refund issued ``bdays`` business days before the complaint."""
    n = pick_range(ctx.rng, bdays)
    issued = latest_bday_with_count(ctx.anchor, n)
    approved = bday_back(issued, ctx.rng.randint(1, 3))
    received = bday_back(approved, ctx.rng.randint(1, 2))
    requested = received - timedelta(days=ctx.rng.randint(3, 6))
    delivered = requested - timedelta(days=ctx.rng.randint(3, 10))
    order_date, eta, dispatched = _physical_timeline(ctx, delivered, "standard", 0)
    items = _items(ctx, qty)
    fee = _shipping_fee("standard", _subtotal(items))
    amount = _refund_amount(items, fee, reason)
    ret = {"requested_date": requested.isoformat(), "received_date": received.isoformat(),
           "inspection_approved_date": approved.isoformat(), "refund_issued_date": issued.isoformat(),
           "refund_amount": amount, "restocking_fee": 0.0, "reason": reason}
    return _record(ctx, items=items, shipping_method="standard", order_date=order_date, eta=eta,
                   dispatched=dispatched, delivered=delivered, status="returned", tracking=delivered,
                   refunds=[(issued, amount)], ret=ret)


def return_received_late(ctx: OrderContext, mode: str = "approved", bdays: Any = (7, 11),
                         reason: str = "changed_mind", qty: int = 1) -> dict[str, Any]:
    """Return received (and possibly approved) but the refund is past the 5-business-day target."""
    n = pick_range(ctx.rng, bdays)
    approved: date | None = None
    if mode == "approved":
        approved_on = latest_bday_with_count(ctx.anchor, max(n, 6))
        received = bday_back(approved_on, ctx.rng.randint(1, 2))
        approved = approved_on
    else:
        received = latest_bday_with_count(ctx.anchor, max(n, 9))
    requested = received - timedelta(days=ctx.rng.randint(2, 4))
    delivered = requested - timedelta(days=ctx.rng.randint(2, 5))
    order_date, eta, dispatched = _physical_timeline(ctx, delivered, "standard", 0)
    items = _items(ctx, qty)
    fee = _shipping_fee("standard", _subtotal(items))
    ret = {"requested_date": requested.isoformat(), "received_date": received.isoformat(),
           "inspection_approved_date": _iso(approved), "refund_issued_date": None,
           "refund_amount": _refund_amount(items, fee, reason), "restocking_fee": 0.0, "reason": reason}
    return _record(ctx, items=items, shipping_method="standard", order_date=order_date, eta=eta,
                   dispatched=dispatched, delivered=delivered, status="returned", tracking=delivered, ret=ret)


def return_received_recent(ctx: OrderContext, bdays: Any = (1, 3), approved: bool = False,
                           reason: str = "changed_mind", qty: int = 1) -> dict[str, Any]:
    """Return received a few business days ago - the refund is still within the policy timeline."""
    n = pick_range(ctx.rng, bdays)
    received = latest_bday_with_count(ctx.anchor, n)
    approved_on = add_business_days(received, 1) if approved and n >= 2 else None
    requested = received - timedelta(days=ctx.rng.randint(2, 4))
    delivered = requested - timedelta(days=ctx.rng.randint(2, 6))
    order_date, eta, dispatched = _physical_timeline(ctx, delivered, "standard", 0)
    items = _items(ctx, qty)
    fee = _shipping_fee("standard", _subtotal(items))
    ret = {"requested_date": requested.isoformat(), "received_date": received.isoformat(),
           "inspection_approved_date": _iso(approved_on), "refund_issued_date": None,
           "refund_amount": _refund_amount(items, fee, reason), "restocking_fee": 0.0, "reason": reason}
    return _record(ctx, items=items, shipping_method="standard", order_date=order_date, eta=eta,
                   dispatched=dispatched, delivered=delivered, status="returned", tracking=delivered, ret=ret)


def return_not_received(ctx: OrderContext, days: Any = (5, 12), reason: str = "changed_mind",
                        qty: int = 1) -> dict[str, Any]:
    """The customer shipped the return but Lumora has not recorded receiving it."""
    n = pick_range(ctx.rng, days)
    requested = ctx.anchor - timedelta(days=n)
    delivered = requested - timedelta(days=ctx.rng.randint(2, 8))
    order_date, eta, dispatched = _physical_timeline(ctx, delivered, "standard", 0)
    items = _items(ctx, qty)
    fee = _shipping_fee("standard", _subtotal(items))
    ret = {"requested_date": requested.isoformat(), "received_date": None, "inspection_approved_date": None,
           "refund_issued_date": None, "refund_amount": _refund_amount(items, fee, reason),
           "restocking_fee": 0.0, "reason": reason}
    return _record(ctx, items=items, shipping_method="standard", order_date=order_date, eta=eta,
                   dispatched=dispatched, delivered=delivered, status="delivered", tracking=delivered, ret=ret)


def restocking_fee(ctx: OrderContext, reason: str = "changed_mind", return_day: Any = (15, 18),
                   care_plus: bool | None = None, qty: int = 1) -> dict[str, Any]:
    """Refund issued minus a 10% restocking fee (return requested after day 14)."""
    day = pick_range(ctx.rng, return_day)
    lag = ctx.rng.randint(1, 3)
    issued = bday_back(ctx.anchor, lag)
    approved = bday_back(issued, 1)
    received = bday_back(approved, 1)
    requested = received - timedelta(days=2)
    delivered = requested - timedelta(days=day)
    order_date, eta, dispatched = _physical_timeline(ctx, delivered, "standard", 0)
    items = _items(ctx, qty)
    fee = _shipping_fee("standard", _subtotal(items))
    restock = _money(0.10 * _subtotal(items))
    amount = _refund_amount(items, fee, reason, restock)
    ret = {"requested_date": requested.isoformat(), "received_date": received.isoformat(),
           "inspection_approved_date": approved.isoformat(), "refund_issued_date": issued.isoformat(),
           "refund_amount": amount, "restocking_fee": restock, "reason": reason}
    return _record(ctx, items=items, shipping_method="standard", order_date=order_date, eta=eta,
                   dispatched=dispatched, delivered=delivered, status="returned", tracking=delivered,
                   refunds=[(issued, amount)], ret=ret, care_plus=care_plus)


def shipping_fee_deducted(ctx: OrderContext, reason: str = "defective", qty: int = 1) -> dict[str, Any]:
    """Express order refunded for the item price only - the USD 14.99 express fee was kept."""
    lag = ctx.rng.randint(1, 3)
    issued = bday_back(ctx.anchor, lag)
    approved = bday_back(issued, 1)
    received = bday_back(approved, 1)
    requested = received - timedelta(days=3)
    delivered = requested - timedelta(days=ctx.rng.randint(3, 9))
    order_date, eta, dispatched = _physical_timeline(ctx, delivered, "express", 0)
    items = _items(ctx, qty)
    subtotal = _subtotal(items)
    ret = {"requested_date": requested.isoformat(), "received_date": received.isoformat(),
           "inspection_approved_date": approved.isoformat(), "refund_issued_date": issued.isoformat(),
           "refund_amount": subtotal, "restocking_fee": 0.0, "reason": reason}
    return _record(ctx, items=items, shipping_method="express", order_date=order_date, eta=eta,
                   dispatched=dispatched, delivered=delivered, status="returned", tracking=delivered,
                   refunds=[(issued, subtotal)], ret=ret)


# ---------------------------------------------------------------------------
# Profiles - subscriptions and services
# ---------------------------------------------------------------------------
_PLAN_PRICES = {("SVC-CLOUD", "annual"): 99.00, ("SVC-CLOUD", "monthly"): 9.99,
                ("SVC-CARE", "annual"): 129.00, ("SVC-CARE", "monthly"): 12.99}


def _subscription_record(ctx: OrderContext, plan: str, start: date, renewal: date, charges: list[tuple[date, float]],
                         auto_renew: bool = True, cancellation: dict[str, Any] | None = None) -> dict[str, Any]:
    sku = ctx.skus[0] if ctx.skus and ctx.skus[0] in ("SVC-CLOUD", "SVC-CARE") else "SVC-CLOUD"
    price = _PLAN_PRICES[(sku, plan)]
    items = [{"sku": sku, "qty": 1, "unit_price": price}]
    sub = {"plan": plan, "renewal_date": renewal.isoformat(), "auto_renew": bool(auto_renew)}
    return _record(ctx, items=items, shipping_method="standard", order_date=start, eta=start, dispatched=start,
                   delivered=start, status="delivered", tracking=start, digital=True, charges=charges,
                   care_plus=(sku == "SVC-CARE"), subscription=sub, cancellation=cancellation, order_total=price)


def annual_renewal_days_ago(ctx: OrderContext, days: Any = (3, 12), years: Any = (1, 2)) -> dict[str, Any]:
    """Annual plan that auto-renewed ``days`` days before the complaint."""
    n = pick_range(ctx.rng, days)
    renewal = ctx.anchor - timedelta(days=n)
    start = renewal - timedelta(days=365 * pick_range(ctx.rng, years))
    sku = ctx.skus[0] if ctx.skus and ctx.skus[0] in ("SVC-CLOUD", "SVC-CARE") else "SVC-CLOUD"
    return _subscription_record(ctx, "annual", start, renewal, [(renewal, _PLAN_PRICES[(sku, "annual")])])


def monthly_subscription(ctx: OrderContext, months: Any = (3, 14), last_charge_days: Any = (2, 20)) -> dict[str, Any]:
    """Monthly plan with its two most recent monthly charges."""
    renewal = ctx.anchor - timedelta(days=pick_range(ctx.rng, last_charge_days))
    start = renewal - timedelta(days=30 * pick_range(ctx.rng, months))
    sku = ctx.skus[0] if ctx.skus and ctx.skus[0] in ("SVC-CLOUD", "SVC-CARE") else "SVC-CLOUD"
    price = _PLAN_PRICES[(sku, "monthly")]
    return _subscription_record(ctx, "monthly", start, renewal, [(renewal - timedelta(days=30), price), (renewal, price)])


def cancelled_then_charged(ctx: OrderContext, plan: str = "monthly", cancel_days: Any = (12, 26)) -> dict[str, Any]:
    """Confirmed cancellation, yet a further charge was taken afterwards (CAN-POL-06 5.1)."""
    cancel = ctx.anchor - timedelta(days=pick_range(ctx.rng, cancel_days))
    after = min(cancel + timedelta(days=ctx.rng.randint(3, 10)), ctx.anchor)
    sku = ctx.skus[0] if ctx.skus and ctx.skus[0] in ("SVC-CLOUD", "SVC-CARE") else "SVC-CLOUD"
    price = _PLAN_PRICES[(sku, plan)]
    before = cancel - timedelta(days=ctx.rng.randint(8, 20)) if plan == "monthly" else cancel - timedelta(days=200)
    start = before - timedelta(days=90 if plan == "monthly" else 165)
    charges = [(before, price), (after, price)]
    return _subscription_record(ctx, plan, start, after, charges, auto_renew=False,
                                cancellation={"requested_date": cancel.isoformat(), "confirmed": True})


def cancelled_not_confirmed(ctx: OrderContext, plan: str = "monthly", cancel_days: Any = (12, 26)) -> dict[str, Any]:
    """The customer asked to cancel but the cancellation was never confirmed; charges continued."""
    record = cancelled_then_charged(ctx, plan=plan, cancel_days=cancel_days)
    record["cancellation"]["confirmed"] = False
    record["subscription"]["auto_renew"] = True
    return record


def subscription_no_cancellation(ctx: OrderContext, plan: str = "monthly") -> dict[str, Any]:
    """Active subscription with no cancellation on record (the customer believes they cancelled)."""
    if plan == "annual":
        return annual_renewal_days_ago(ctx, days=(5, 40))
    return monthly_subscription(ctx)


def install_completed(ctx: OrderContext, days: Any = (2, 20)) -> dict[str, Any]:
    """Pro Install appointment completed ``days`` days ago."""
    n = pick_range(ctx.rng, days)
    appointment = ctx.anchor - timedelta(days=n)
    order_date = appointment - timedelta(days=ctx.rng.randint(5, 12))
    items = [{"sku": "SVC-INSTALL", "qty": 1, "unit_price": ctx.catalog.price("SVC-INSTALL")}]
    return _record(ctx, items=items, shipping_method="standard", order_date=order_date, eta=appointment,
                   dispatched=appointment, delivered=appointment, status="delivered", tracking=appointment,
                   digital=True)


def install_missed(ctx: OrderContext, days: Any = (1, 6)) -> dict[str, Any]:
    """Pro Install appointment date has passed but the visit never happened."""
    n = pick_range(ctx.rng, days)
    appointment = ctx.anchor - timedelta(days=n)
    order_date = appointment - timedelta(days=ctx.rng.randint(5, 12))
    items = [{"sku": "SVC-INSTALL", "qty": 1, "unit_price": ctx.catalog.price("SVC-INSTALL")}]
    return _record(ctx, items=items, shipping_method="standard", order_date=order_date, eta=appointment,
                   dispatched=None, delivered=None, status="processing", tracking=None, digital=True)


def high_value(ctx: OrderContext, base: str = "delivered_days_ago", min_total: float = 500,
               **kw: Any) -> dict[str, Any]:
    """Any ``base`` profile with an order total of at least ``min_total`` (500 / 1500 / business 2500)."""
    if base not in PROFILES or base == "high_value":
        raise KeyError(f"high_value: unknown base profile {base!r}")
    return PROFILES[base](ctx, min_total=min_total, **kw)


def careplus_claims(ctx: OrderContext, n: int = 2, months: Any = (3, 12), **kw: Any) -> dict[str, Any]:
    """Care+-covered device delivered ``months`` ago with ``n`` accidental-damage claims in the last 12 months."""
    return delivered_months_ago(ctx, months=months, careplus_claims=n, care_plus=True, **kw)


def background_order(ctx: OrderContext) -> dict[str, Any]:
    """A random delivered order with no complaint (fills the ledger)."""
    return delivered_days_ago(ctx, days=(10, 500))


PROFILES: dict[str, Callable[..., dict[str, Any]]] = {
    fn.__name__: fn for fn in (
        delivered_days_ago, delivered_recent, delivered_within_doa, delivered_old, delivered_months_ago,
        delivered_late, marked_delivered, in_transit, in_transit_late_standard, late_express, not_dispatched,
        cancel_ignored_dispatched, lost_no_updates, trace_completed, duplicate_charge, duplicate_charge_old,
        single_charge, charged_correctly, charge_old, overcharged, refund_issued_bd_ago, return_received_late,
        return_received_recent, return_not_received, restocking_fee, shipping_fee_deducted,
        annual_renewal_days_ago, monthly_subscription, cancelled_then_charged, cancelled_not_confirmed,
        subscription_no_cancellation, install_completed, install_missed, high_value, careplus_claims,
    )
}


def build_order(name: str, ctx: OrderContext, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Run the named profile. Raises ``KeyError`` for unknown profiles."""
    if name not in PROFILES:
        raise KeyError(f"Unknown order profile {name!r}")
    return PROFILES[name](ctx, **(params or {}))


# ---------------------------------------------------------------------------
# Slot values derived from a ledger record (used by the renderer)
# ---------------------------------------------------------------------------
def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def order_dates(order: dict[str, Any]) -> dict[str, date]:
    """Named calendar dates of a record (``delivered``, ``eta``, ``renewal`` ...)."""
    ret = order.get("return") or {}
    cancel = order.get("cancellation") or {}
    sub = order.get("subscription") or {}
    trace = order.get("trace") or {}
    charges = [t for t in order.get("transactions", []) if t["type"] == "charge"]
    refunds = [t for t in order.get("transactions", []) if t["type"] == "refund"]
    raw: dict[str, date | None] = {
        "order": _d(order.get("order_date")),
        "eta": _d(order.get("estimated_delivery_date")),
        "dispatched": _d(order.get("dispatched_date")),
        "delivered": _d(order.get("delivered_date")),
        "appointment": _d(order.get("estimated_delivery_date")),
        "tracking": _d(order.get("tracking_last_update")),
        "return_requested": _d(ret.get("requested_date")),
        "return_received": _d(ret.get("received_date")),
        "inspection_approved": _d(ret.get("inspection_approved_date")),
        "refund_issued": _d(ret.get("refund_issued_date")),
        "cancel_requested": _d(cancel.get("requested_date")),
        "renewal": _d(sub.get("renewal_date")),
        "trace_opened": _d(trace.get("opened_date")),
        "charge": _d(charges[-1]["date"]) if charges else None,
        "charge1": _d(charges[0]["date"]) if charges else None,
        "charge2": _d(charges[1]["date"]) if len(charges) > 1 else None,
        "refund_txn": _d(refunds[-1]["date"]) if refunds else None,
    }
    return {k: v for k, v in raw.items() if v is not None}


def order_amounts(order: dict[str, Any]) -> dict[str, float]:
    """Named amounts of a record (``total``, ``unit_price``, ``refund_amount`` ...)."""
    items = order.get("items") or []
    ret = order.get("return") or {}
    charges = [t for t in order.get("transactions", []) if t["type"] == "charge"]
    subtotal = _subtotal(items) if items else 0.0
    raw: dict[str, float | None] = {
        "total": order.get("order_total"),
        "subtotal": subtotal,
        "unit_price": items[0]["unit_price"] if items else None,
        "item_total": _money(items[0]["unit_price"] * items[0]["qty"]) if items else None,
        "shipping_fee": order.get("shipping_fee") or None,
        "charge": charges[-1]["amount"] if charges else None,
        "charge1": charges[0]["amount"] if charges else None,
        "charge2": charges[1]["amount"] if len(charges) > 1 else None,
        "total_charged": _money(sum(t["amount"] for t in charges)) if charges else None,
        "overcharge": _money(charges[-1]["amount"] - order["order_total"]) if charges else None,
        "refund_amount": ret.get("refund_amount"),
        "restocking_fee": ret.get("restocking_fee") or None,
        "expected_refund": _money(ret["refund_amount"] + (ret.get("restocking_fee") or 0)) if ret.get(
            "refund_amount") is not None else None,
        "paid_for_item": _money(subtotal + (order.get("shipping_fee") or 0)) if items else None,
    }
    return {k: float(v) for k, v in raw.items() if v is not None and float(v) > 0}


def order_txns(order: dict[str, Any]) -> dict[str, str]:
    """Named transaction references: ``1``/``2`` (charges in date order), ``last``, ``refund``."""
    charges = [t for t in order.get("transactions", []) if t["type"] == "charge"]
    refunds = [t for t in order.get("transactions", []) if t["type"] == "refund"]
    named: dict[str, str] = {}
    for i, txn in enumerate(charges, start=1):
        named[str(i)] = txn["txn_ref"]
    if charges:
        named["last"] = charges[-1]["txn_ref"]
    if refunds:
        named["refund"] = refunds[-1]["txn_ref"]
    return named
