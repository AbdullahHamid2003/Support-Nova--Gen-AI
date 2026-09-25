"""Shared fixtures for the SupportNova test suite.

* Unit tests need nothing but the repository (Rule Matrix YAML, knowledge-base files, dataset).
* Integration / API / E2E tests use a dedicated PostgreSQL database (TEST_DATABASE_URL, default the
  local dev cluster's ``supportnova_test``). The schema is rebuilt from the Alembic migrations at the
  start of the session and seeded exactly like a first run (roles, Rule Matrix, prompts, knowledge
  base, demo users, customers and order ledger). If the database is unreachable those tests are skipped.
* Every GenAI call is answered by an offline test double (tests/support/offline_llm.py), so the suite is
  deterministic, needs no API key and never spends a paid API's credit. The application itself has no
  stand-in model: without AI_API_KEY its GenAI step reports "not configured" (see test_ai_not_configured).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://supportnova:postgres@127.0.0.1:5433/supportnova_test")
DEMO_PASSWORD = "Lumora#Demo2026"
USERS = {
    "admin": "admin@lumora.example", "manager": "manager@lumora.example", "reviewer": "reviewer@lumora.example",
    "agent": "agent@lumora.example", "customer": "customer@lumora.example",
}

# configure the application before any supportnova module reads its settings
os.environ.update({
    "DATABASE_URL": TEST_DB, "AI_PROVIDER": "openai", "APP_ENV": "test", "SEED_DATASET_ON_STARTUP": "false",
    "SEED_SIMULATE_LIFECYCLE": "false", "DEMO_PASSWORD": DEMO_PASSWORD, "RATE_LIMIT_PER_MINUTE": "100000",
    "LOGIN_RATE_LIMIT_PER_MINUTE": "100000", "SLA_MONITOR_INTERVAL_SECONDS": "3600", "BACKGROUND_WORKERS": "2",
    "STORAGE_DIR": tempfile.mkdtemp(prefix="supportnova-test-"),
    # hermetic: never read the developer's .env (it may hold a real API key) - this path does not exist
    "SUPPORTNOVA_ENV_FILE": str(ROOT / "tests" / ".env.none"),
})
for _name in ("AI_API_KEY", "AI_MODEL", "AI_BASE_URL", "EMBEDDING_API_KEY", "EMBEDDING_PROVIDER", "SECRET_KEY"):
    os.environ.pop(_name, None)

from supportnova.genai_pipeline import providers  # noqa: E402 - after the environment is configured
from tests.support.offline_llm import OfflineLLM  # noqa: E402

providers.use_provider(OfflineLLM())


def _db_available() -> bool:
    try:
        import psycopg
        url = TEST_DB.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(url, connect_timeout=3):
            return True
    except Exception:
        return False


DB_AVAILABLE = _db_available()
needs_db = pytest.mark.skipif(not DB_AVAILABLE, reason=f"PostgreSQL test database not reachable ({TEST_DB})")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        path = str(item.fspath)
        if any(part in path for part in ("integration", "api", "e2e")):
            item.add_marker(needs_db)


@pytest.fixture(scope="session")
def matrix() -> Any:
    from supportnova.rule_engine.loader import load_matrix
    return load_matrix()


@pytest.fixture(scope="session")
def database() -> Iterator[str]:
    """Fresh schema from migrations + first-run seed (once per session)."""
    if not DB_AVAILABLE:
        pytest.skip("PostgreSQL test database not reachable")
    import psycopg

    from supportnova.core.config import get_settings
    from supportnova.database.base import reset_engine, session_scope
    get_settings.cache_clear()
    reset_engine(TEST_DB)
    with psycopg.connect(TEST_DB.replace("postgresql+psycopg://", "postgresql://"), autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")
    reset_engine(TEST_DB)
    from supportnova.database.migrate import upgrade_to_head
    upgrade_to_head()
    from supportnova.services import seed
    with session_scope() as db:
        seed.seed_reference(db)
    with session_scope() as db:
        seed.seed_users(db)
    yield TEST_DB


@pytest.fixture(scope="session")
def client(database: str) -> Iterator[Any]:
    from fastapi.testclient import TestClient

    from supportnova.main import create_app
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture(scope="session")
def tokens(client: Any) -> dict[str, str]:
    out = {}
    for role, email in USERS.items():
        r = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
        assert r.status_code == 200, r.text
        out[role] = r.json()["access_token"]
    # tests authenticate with explicit Bearer headers; the login's session cookie must not linger on the shared
    # client, or "unauthenticated" requests in later tests would silently carry the last user's session
    client.cookies.clear()
    return out


@pytest.fixture(scope="session")
def auth(tokens: dict[str, str]) -> Callable[[str], dict[str, str]]:
    def headers(role: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {tokens[role]}"}
    return headers


def wait_for_pipeline(client: Any, ref: str, headers: dict[str, str], timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.time() + timeout
    while time.time() < deadline:
        p = client.get(f"/api/v1/complaints/{ref}/pipeline", headers=headers).json()
        if p.get("done"):
            return p
        time.sleep(0.2)
    raise AssertionError(f"pipeline for {ref} did not finish in {timeout}s")


@pytest.fixture(scope="session")
def submit(client: Any, auth: Callable[[str], dict[str, str]]) -> Callable[..., dict[str, Any]]:
    """Submit a complaint through the public API and return the finished case detail."""
    counter = {"n": 0}

    def _submit(title: str, description: str, *, role: str = "agent", **fields: Any) -> dict[str, Any]:
        counter["n"] += 1
        payload = {"title": title, "description": description, "channel": fields.pop("channel", "web_form"),
                   "customer_type": fields.pop("customer_type", "individual"), **fields}
        h = auth(role)
        r = client.post("/api/v1/complaints", json=payload, headers=h)
        assert r.status_code == 202, r.text
        ref = r.json()["complaint_ref"]
        wait_for_pipeline(client, ref, h)
        detail = client.get(f"/api/v1/complaints/{ref}", headers=auth("admin")).json()
        return detail
    return _submit


def failed_checks(detail: dict[str, Any]) -> set[str]:
    return {c["code"] for c in (detail.get("validation") or {}).get("checks", []) if c["status"] == "fail"}


def check(detail: dict[str, Any], code: str) -> dict[str, Any]:
    for c in (detail.get("validation") or {}).get("checks", []):
        if c["code"] == code:
            return c
    raise AssertionError(f"check {code} not found")


@pytest.fixture(scope="session")
def make_order(database: str) -> Callable[..., str]:
    """Insert a simulated ledger order (dates relative to today) for a customer; returns the order ref."""
    from datetime import date

    from sqlalchemy import select

    from supportnova.database.base import session_scope
    from supportnova.database.models import Customer, Order
    from supportnova.services.lab import build_order
    seq = {"n": 0}

    def _make(sku: str, *, customer_ref: str = "CUST-10001", price: float = 179.0, **spec: Any) -> str:
        seq["n"] += 1
        ref = f"LMR-97{seq['n']:04d}"
        with session_scope() as db:
            cust = db.execute(select(Customer).where(Customer.customer_ref == customer_ref)).scalar_one()
            record = build_order({"sku": sku, **spec}, ref, customer_ref, date.today(), price)
            row = db.execute(select(Order).where(Order.order_ref == ref)).scalar_one_or_none() or Order(order_ref=ref)
            row.customer_id, row.order_date, row.order_total, row.status, row.data = (
                cust.id, date.fromisoformat(record["order_date"]), record["order_total"], record["status"], record)
            db.add(row)
        return ref
    return _make
