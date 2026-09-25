"""Batch processing for dataset imports and evaluation runs: parallel across customers, in date order per customer.

A complaint's history checks, repeat detection and previous-complaint link only look at the same customer's
earlier complaints, so different customers are independent. Each worker takes one customer's complaints in
date order while other customers run at the same time. The GenAI calls dominate the time per complaint, so
throughput grows with BATCH_WORKERS - up to the AI vendor's rate limits.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

Record = dict[str, Any]


def customer_groups(records: list[Record]) -> list[list[Record]]:
    """Records (already in date order) grouped by customer; groups ordered by their first complaint."""
    groups: dict[str, list[Record]] = {}
    for rec in records:
        key = str(rec.get("customer_ref") or "").strip().upper() or f"#{rec.get('complaint_id')}"
        groups.setdefault(key, []).append(rec)
    return list(groups.values())


def run_by_customer(records: list[Record], handle: Callable[[Record], None], *, workers: int,
                    stop: Callable[[], bool] = lambda: False) -> None:
    """Call ``handle`` for every record; an exception from ``handle`` is re-raised once all workers finish."""

    def run(group: list[Record]) -> None:
        for rec in group:
            if stop():
                return
            handle(rec)

    groups = customer_groups(records)
    if workers <= 1:
        for group in groups:
            run(group)
        return
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="batch") as pool:
        futures = [pool.submit(run, group) for group in groups]
    for future in futures:
        future.result()
