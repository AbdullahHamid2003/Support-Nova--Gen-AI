"""Batch processing keeps each customer's complaints in date order while customers run in parallel."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from supportnova.services.batch import customer_groups, run_by_customer


def _records() -> list[dict[str, Any]]:
    return [{"complaint_id": f"CMP-{i:03d}", "customer_ref": f"cust-{i % 4}" if i % 5 else ""} for i in range(40)]


def test_groups_follow_the_first_complaint_and_keep_order() -> None:
    groups = customer_groups(_records())
    assert [g[0]["complaint_id"] for g in groups] == sorted(g[0]["complaint_id"] for g in groups)
    for g in groups:
        assert [r["complaint_id"] for r in g] == sorted(r["complaint_id"] for r in g)
        assert len({r["customer_ref"].upper() for r in g}) == 1
    assert all(len(g) == 1 for g in groups if not g[0]["customer_ref"])     # no customer: nothing to order against


def test_parallel_run_processes_everything_in_customer_order() -> None:
    seen: dict[str, list[str]] = {}
    lock = threading.Lock()
    threads: set[str] = set()

    def handle(rec: dict[str, Any]) -> None:
        time.sleep(0.002)
        with lock:
            seen.setdefault(rec["customer_ref"].upper() or rec["complaint_id"], []).append(rec["complaint_id"])
            threads.add(threading.current_thread().name)

    run_by_customer(_records(), handle, workers=4)
    assert sum(len(v) for v in seen.values()) == 40
    assert all(v == sorted(v) for v in seen.values())
    assert len(threads) > 1


def test_stop_and_errors() -> None:
    calls: list[str] = []
    run_by_customer(_records(), lambda r: calls.append(r["complaint_id"]), workers=1, stop=lambda: len(calls) >= 3)
    assert len(calls) == 3

    def fail(rec: dict[str, Any]) -> None:
        if rec["complaint_id"] == "CMP-007":
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        run_by_customer(_records(), fail, workers=3)
