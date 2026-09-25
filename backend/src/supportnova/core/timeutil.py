"""Time helpers. Business days are Monday-Friday (public holidays are not modelled; documented limitation)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta


def utcnow() -> datetime:
    return datetime.now(UTC)


def to_date(value: date | datetime | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return date.fromisoformat(text[:10])


def to_datetime(value: date | datetime | str | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def business_days_between(start: date | None, end: date | None) -> int | None:
    """Number of business days after ``start`` up to and including ``end`` (0 if end <= start)."""
    if start is None or end is None:
        return None
    if end <= start:
        return 0
    days = 0
    current = start
    while current < end:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days += 1
    return days


def add_business_days(start: date, days: int) -> date:
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current
