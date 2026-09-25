"""Slot rendering and channel adaptation.

Templates use ``{token}`` or ``{token:arg}`` slots. Every slot that inserts a fact
(amount, date, duration, outage length, product, reference) is *registered* in a
:class:`RenderLog`; complaint facts (``max_amount``, ``max_elapsed_days``,
``has_date`` ...) and the expected entities are computed from these
registrations - never by parsing the rendered text.

Tokens::

    {first_name} {last_name} {full_name} {city} {company} {email} {last4} {qty}
    {product} {product:short} {product:full}  {product2} {product2:short} {product2:full}
    {order_ref}                     order reference as the customer wrote it
    {txn} {txn:1} {txn:2} {txn:refund}
    {date:<field>|c-N}              calendar date (order field, or N days before the complaint)
    {amt:<field>|<param>|<number>}  USD amount written by the customer
    {comp:<param>|<number>}         USD amount demanded as compensation
    {dur:<field>|<param>|<number>}  "N days/weeks/months" (used before "ago"/"since"; registers max_elapsed_days)
    {age:<field>|<param>|<number>}  same wording for "N weeks old" / "for N days" (not an elapsed fact)
    {hours:<param>|<number>}        stated outage duration
    {num:<param>|<number>}          plain number   {param:<name>} raw parameter text
    {prev_ref}                      previous complaint reference (filled after ID assignment)
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from .catalog import Catalog
from .ledger import order_amounts, order_dates, order_txns
from .textutil import fmt_amount, fmt_date, fmt_duration, fmt_hours

PREV_PLACEHOLDER = "\u0000PREV\u0000"
TOKEN_RE = re.compile(
    r"\{(first_name|last_name|full_name|city|company|email|last4|qty|product2|product|order_ref|txn|date|amt"
    r"|comp|dur|age|hours|num|param|prev_ref)(?::([^{}]*))?\}"
)


class RenderError(ValueError):
    """Raised when a template references a value the scenario does not provide."""


@dataclass
class RenderLog:
    """Facts registered while rendering one complaint."""

    entities: list[tuple[str, str]] = field(default_factory=list)
    amounts: list[float] = field(default_factory=list)
    comp_amounts: list[float] = field(default_factory=list)
    elapsed_days: list[int] = field(default_factory=list)
    outage_hours: list[float] = field(default_factory=list)
    has_date: bool = False
    product_skus: list[str] = field(default_factory=list)
    order_ref_used: bool = False
    txns_used: list[str] = field(default_factory=list)
    prev_ref_used: bool = False

    def entity(self, etype: str, value: str) -> None:
        if value and (etype, value) not in self.entities:
            self.entities.append((etype, value))


class Renderer:
    """Render templates for one complaint with consistent formatting choices."""

    def __init__(self, *, rng: random.Random, catalog: Catalog, customer: dict[str, Any],
                 complaint_date: date, order: dict[str, Any] | None, order_ref_text: str | None,
                 params: dict[str, Any], product_sku: str | None, product2_sku: str | None) -> None:
        self.rng = rng
        self.catalog = catalog
        self.customer = customer
        self.complaint_date = complaint_date
        self.order = order
        self.order_ref_text = order_ref_text
        self.params = params
        self.product_sku = product_sku
        self.product2_sku = product2_sku
        self.date_style = rng.choice(("d_month", "month_d", "d_month", "month_d", "mon_d", "d_th_month",
                                      "month_dth", "d_month_y", "weekday_d_month"))
        self.amount_style = rng.choice(("usd_int", "dollar_int", "dollar_cents", "usd_cents", "dollar_int"))
        self._mentions: dict[tuple[str, str], str] = {}
        self._dates = order_dates(order) if order else {}
        self._amounts = order_amounts(order) if order else {}
        self._txns = order_txns(order) if order else {}
        self.log = RenderLog()

    # ---- value lookups ---------------------------------------------------------
    def _number(self, arg: str) -> float:
        if arg in self.params:
            return float(self.params[arg])
        if arg in self._amounts:
            return float(self._amounts[arg])
        try:
            return float(arg)
        except ValueError as exc:
            raise RenderError(f"no numeric value for {arg!r}") from exc

    def _date_value(self, arg: str) -> date:
        if arg.startswith("c-") or arg.startswith("c+"):
            offset = int(arg[2:]) if arg[1] == "-" else -int(arg[2:])
            return self.complaint_date - timedelta(days=offset)
        if arg in self._dates:
            return self._dates[arg]
        if arg in self.params:
            return self.complaint_date - timedelta(days=int(self.params[arg]))
        raise RenderError(f"no date value for {arg!r}")

    def _duration_days(self, arg: str) -> int:
        if arg in self._dates:
            return (self.complaint_date - self._dates[arg]).days
        if arg in self.params:
            return int(self.params[arg])
        try:
            return int(arg)
        except ValueError as exc:
            raise RenderError(f"no duration value for {arg!r}") from exc

    def _product(self, which: str, variant: str | None) -> str:
        sku = self.product_sku if which == "product" else self.product2_sku
        if not sku:
            raise RenderError(f"template uses {{{which}}} but the scenario has no {which}")
        info = self.catalog.get(sku)
        key = (which, variant or "default")
        if key not in self._mentions:
            if variant == "short":
                self._mentions[key] = self.catalog.short(sku, self.rng)
            elif variant == "full":
                self._mentions[key] = info.name
            else:
                self._mentions[key] = self.catalog.mention(sku, self.rng)
        text = self._mentions[key]
        self.log.entity(info.entity_type, text)
        if sku not in self.log.product_skus:
            self.log.product_skus.append(sku)
        return text

    # ---- token rendering ---------------------------------------------------------
    def _token(self, match: re.Match[str]) -> str:
        name, arg = match.group(1), match.group(2)
        c = self.customer
        if name in ("first_name", "last_name", "full_name", "email"):
            return str(c[name])
        if name == "city":
            self.log.entity("location", c["city"])
            return str(c["city"])
        if name == "company":
            return str(c.get("company") or f"{c['last_name']} Holdings")
        if name == "last4":
            return str(self.params.get("last4", f"{self.rng.randint(0, 9999):04d}"))
        if name == "qty":
            items = (self.order or {}).get("items") or [{"qty": self.params.get("qty", 1)}]
            return str(items[0]["qty"])
        if name in ("product", "product2"):
            return self._product(name, arg)
        if name == "order_ref":
            if not self.order_ref_text:
                raise RenderError("template uses {order_ref} but the complaint has no order reference")
            self.log.order_ref_used = True
            self.log.entity("order_id", self.order_ref_text)
            return self.order_ref_text
        if name == "txn":
            key = arg or "last"
            if key not in self._txns:
                raise RenderError(f"no transaction {key!r} on the order")
            ref = self._txns[key]
            self.log.txns_used.append(ref)
            self.log.entity("transaction_id", ref)
            return ref
        if name == "date":
            value = fmt_date(self._date_value(arg or ""), self.date_style)
            self.log.has_date = True
            self.log.entity("date", value)
            return value
        if name in ("amt", "comp"):
            amount = self._number(arg or "")
            text = fmt_amount(amount, self.amount_style)
            self.log.amounts.append(amount)
            if name == "comp":
                self.log.comp_amounts.append(amount)
            self.log.entity("amount", text)
            return text
        if name == "dur":
            days = self._duration_days(arg or "")
            self.log.elapsed_days.append(days)
            self.log.has_date = True
            return fmt_duration(days, self.rng)
        if name == "age":
            return fmt_duration(self._duration_days(arg or ""), self.rng)
        if name == "hours":
            hours = self._number(arg or "")
            self.log.outage_hours.append(hours)
            return fmt_hours(hours)
        if name == "num":
            number = self._number(arg or "")
            return f"{number:g}"
        if name == "param":
            if arg not in self.params:
                raise RenderError(f"no parameter {arg!r}")
            return str(self.params[arg])
        if name == "prev_ref":
            self.log.prev_ref_used = True
            return PREV_PLACEHOLDER
        raise RenderError(f"unknown token {name}")  # pragma: no cover - regex restricts names

    def render(self, template: str) -> str:
        """Render one template string (with "a"/"an" agreement before product mentions)."""
        text = TOKEN_RE.sub(self._token, template or "").strip()
        for mention in set(self._mentions.values()):
            if mention[:1].lower() in "aeio":
                text = re.sub(r"\b([Aa]) (" + re.escape(mention) + ")", r"\1n \2", text)
        return text


# ---------------------------------------------------------------------------
# Channel adaptation
# ---------------------------------------------------------------------------
_EMAIL_GREETINGS = {
    "calm": ("Hello,", "Hi Lumora team,", "Hi there,", "Dear Lumora Support,", "Good morning,"),
    "polite": ("Dear Lumora Support,", "Hello Lumora team,", "Good afternoon,", "Hi, I hope you are well."),
    "frustrated": ("Hello,", "Hi,", "To the Lumora support team,"),
    "angry": ("To whom it may concern,", "Lumora,", ""),
}
_EMAIL_SIGNOFFS = {
    "calm": ("Thanks,\n{first_name}", "Kind regards,\n{full_name}", "Best,\n{first_name}"),
    "polite": ("Many thanks,\n{first_name}", "Thank you in advance,\n{full_name}", "Warm regards,\n{full_name}\n{city}"),
    "frustrated": ("Regards,\n{full_name}", "{first_name}", "Waiting for your reply,\n{full_name}"),
    "angry": ("{full_name}", "{first_name} {last_name}", ""),
}
_CHAT_PREFIX = {
    "calm": ("", "Hi. ", "Hello - "),
    "polite": ("Hi there. ", "Hello - ", ""),
    "frustrated": ("", "Hi. "),
    "angry": ("",),
}
_PHONE_PREFIX = ("[Transcribed phone call] ", "(Phone call, transcribed) ", "[Call transcript] ")
_SOCIAL_PREFIX = ("@LumoraHome ", "@LumoraHome ", "Message to @LumoraHome: ")


def adapt_channel(body: str, title: str, channel: str, style: str, renderer: Renderer) -> str:
    """Wrap a rendered body the way the channel would deliver it (greeting, sign-off, transcript tag)."""
    rng = renderer.rng
    business = renderer.customer.get("customer_type") == "business" and renderer.customer.get("company")
    if channel == "email":
        greeting = rng.choice(_EMAIL_GREETINGS[style])
        signoff = renderer.render(rng.choice(_EMAIL_SIGNOFFS[style]))
        if business and signoff:
            signoff = f"{signoff}\n{renderer.customer['company']}"
        parts = [p for p in (greeting, body, signoff) if p]
        return "\n\n".join(parts)
    if channel == "chat":
        return rng.choice(_CHAT_PREFIX[style]) + body
    if channel == "phone":
        return rng.choice(_PHONE_PREFIX) + body
    if channel == "social_media":
        return rng.choice(_SOCIAL_PREFIX) + body
    if channel == "uploaded":
        closing = renderer.render("Yours faithfully,\n{full_name}\n{city}")
        if business:
            closing = f"{closing}\n{renderer.customer['company']}"
        return f"Re: {title}\n\nDear Sir or Madam,\n\n{body}\n\n{closing}"
    return body
