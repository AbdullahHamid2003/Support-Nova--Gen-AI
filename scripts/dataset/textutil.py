"""Text helpers: canonical complaint text, normalisation, value formatting and similarity."""

from __future__ import annotations

import random
import re
from datetime import date

_CURLY = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", " ": " "}
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December")
_MONTHS_SHORT = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
                 10: "ten", 11: "eleven", 12: "twelve"}

DATE_STYLES: tuple[str, ...] = ("d_month", "month_d", "mon_d", "d_th_month", "month_dth", "d_month_y", "weekday_d_month")
AMOUNT_STYLES: tuple[str, ...] = ("usd_int", "dollar_int", "dollar_cents", "usd_cents")


def complaint_text(title: str | None, description: str | None, supporting: str | None) -> str:
    """Canonical text fed to the labeler: title, description and supporting information joined by newlines."""
    return "\n".join(part for part in (title or "", description or "", supporting or "") if part)


def clean_quotes(text: str) -> str:
    """Replace typographic quotes/dashes with ASCII so rule regexes (``didn't``) match."""
    for bad, good in _CURLY.items():
        text = text.replace(bad, good)
    return text


def normalize(text: str) -> str:
    """Lower-case, ASCII-quoted text used for lexical signal detection."""
    return clean_quotes(text or "").lower()


def tokens(text: str) -> set[str]:
    """Token set used for Jaccard similarity."""
    return set(_TOKEN_RE.findall(normalize(text)))


def jaccard(a: set[str], b: set[str]) -> float:
    """Token-set Jaccard similarity (0 when both are empty)."""
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def ordinal(n: int) -> str:
    """1 -> 1st, 2 -> 2nd, 11 -> 11th ..."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def fmt_date(value: date, style: str) -> str:
    """Render a calendar date the way a customer would write it."""
    month = _MONTHS[value.month - 1]
    if style == "d_month":
        return f"{value.day} {month}"
    if style == "month_d":
        return f"{month} {value.day}"
    if style == "mon_d":
        return f"{_MONTHS_SHORT[value.month - 1]} {value.day}"
    if style == "d_th_month":
        return f"{ordinal(value.day)} {month}"
    if style == "month_dth":
        return f"{month} {ordinal(value.day)}"
    if style == "d_month_y":
        return f"{value.day} {month} {value.year}"
    if style == "weekday_d_month":
        return f"{_WEEKDAYS[value.weekday()]} {value.day} {month}"
    raise ValueError(f"Unknown date style {style!r}")


def fmt_amount(value: float, style: str) -> str:
    """Render a USD amount (``USD 179``, ``$179``, ``$179.00``, ``USD 179.00``)."""
    whole = abs(value - round(value)) < 0.005
    if style == "usd_int":
        return f"USD {value:,.0f}" if whole else f"USD {value:,.2f}"
    if style == "dollar_int":
        return f"${value:,.0f}" if whole else f"${value:,.2f}"
    if style == "dollar_cents":
        return f"${value:,.2f}"
    if style == "usd_cents":
        return f"USD {value:,.2f}"
    raise ValueError(f"Unknown amount style {style!r}")


def fmt_duration(days: int, rng: random.Random, allow_words: bool = True) -> str:
    """Render an exact calendar-day duration as days, weeks or months (never approximated)."""
    if days <= 0:
        raise ValueError("durations must be positive")
    if days % 30 == 0 and days >= 60:
        count, unit = days // 30, "months"
    elif days % 7 == 0 and 14 <= days <= 63:
        count, unit = days // 7, "weeks"
    else:
        count, unit = days, "days" if days != 1 else "day"
    number = _NUMBER_WORDS.get(count) if allow_words and count in _NUMBER_WORDS and rng.random() < 0.3 else None
    return f"{number or count} {unit}"


def fmt_hours(hours: float) -> str:
    """Render an outage duration in hours."""
    return f"{hours:g} hours"
