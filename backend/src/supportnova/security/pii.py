"""Sensitive-data redaction applied before any text leaves the server for a GenAI provider
and before it is written to AI-run logs (SRS 1.5 privacy/confidentiality, security report)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_CARD = re.compile(r"(?<![\w-])(?:\d[ -]?){12,18}\d(?![\w-])")
_CVV = re.compile(r"\b(cvv|cvc|cvv2|security\s+code)\s*(is|:|=|-)?\s*\d{3,4}\b", re.IGNORECASE)
_PASSWORD = re.compile(r"\b(password|passcode|passwd|pwd|pin)\s*(is|was|:|=|-)\s*\S+", re.IGNORECASE)
_OTP = re.compile(r"\b(one[- ]time\s+(code|password)|otp|verification\s+code|2fa\s+code|auth(entication)?\s+code)\s*(is|was|:|=|-)?\s*\d{4,8}\b",
                  re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b")
_PHONE = re.compile(r"(?<![\w-])(\+?\d[\d\s().-]{8,16}\d)(?![\w-])")


def _luhn_ok(number: str) -> bool:
    digits = [int(d) for d in number if d.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


@dataclass
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def redact(text: str, *, keep_emails: bool = False) -> RedactionResult:
    counts: dict[str, int] = {}

    def bump(kind: str) -> None:
        counts[kind] = counts.get(kind, 0) + 1

    def card(m: re.Match[str]) -> str:
        raw = m.group(0)
        if not _luhn_ok(raw):
            return raw
        bump("payment_card")
        return f"[CARD ending {''.join(c for c in raw if c.isdigit())[-4:]}]"

    value = _CARD.sub(card, text or "")

    def sub(pattern: re.Pattern[str], kind: str, replacement: str, value: str) -> str:
        def repl(_m: re.Match[str]) -> str:
            bump(kind)
            return replacement
        return pattern.sub(repl, value)

    value = sub(_CVV, "cvv", "[CVV REDACTED]", value)
    value = sub(_OTP, "one_time_code", "[ONE-TIME CODE REDACTED]", value)
    value = sub(_PASSWORD, "password", "[PASSWORD REDACTED]", value)
    if not keep_emails:
        value = sub(_EMAIL, "email", "[EMAIL]", value)

    def phone(m: re.Match[str]) -> str:
        digits = sum(c.isdigit() for c in m.group(0))
        if 10 <= digits <= 15:
            bump("phone")
            return "[PHONE]"
        return m.group(0)

    value = _PHONE.sub(phone, value)
    return RedactionResult(text=value, counts=counts)


def contains_sensitive(text: str) -> dict[str, int]:
    """Counts of sensitive tokens that must never be echoed back in customer-facing text."""
    return redact(text, keep_emails=True).counts
