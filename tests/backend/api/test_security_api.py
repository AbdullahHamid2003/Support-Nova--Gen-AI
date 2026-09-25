"""Authentication, server-side RBAC, CSRF, tenant isolation, lockout, headers, audit immutability."""

from __future__ import annotations

import pytest

from tests.conftest import DEMO_PASSWORD, TEST_DB

API = "/api/v1"

PROTECTED = ["/dashboard", "/complaints", "/reviews", "/documents", "/rules", "/analytics/overview", "/audit", "/users", "/lab/scenarios"]

# (path, roles allowed) - everything else must get 403
MATRIX = [
    ("/audit/verify", {"admin"}),
    ("/users", {"admin", "manager"}),
    ("/system/info", {"admin"}),
    ("/reviews", {"agent", "reviewer", "manager", "admin"}),
    ("/analytics/overview", {"reviewer", "manager", "admin"}),
    ("/reports", {"reviewer", "manager", "admin"}),
    ("/evaluation/runs", {"reviewer", "manager", "admin"}),
    ("/lab/scenarios", {"reviewer", "admin"}),
    ("/documents", {"agent", "reviewer", "manager", "admin"}),
    ("/rules", {"agent", "reviewer", "manager", "admin"}),
    ("/prompts", {"agent", "reviewer", "manager", "admin"}),  # read-only transparency; edits need prompts:manage
]


@pytest.mark.parametrize("path", PROTECTED)
def test_unauthenticated_requests_are_rejected(client, path: str) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{API}{path}")
    assert r.status_code == 401
    assert r.json()["error"]["code"] in ("authentication_required", "not_authenticated", "authentication_failed")


@pytest.mark.parametrize(("path", "allowed"), MATRIX)
def test_role_permission_matrix_enforced_server_side(client, auth, path: str, allowed: set[str]) -> None:  # type: ignore[no-untyped-def]
    for role in ("customer", "agent", "reviewer", "manager", "admin"):
        r = client.get(f"{API}{path}", headers=auth(role))
        if role in allowed:
            assert r.status_code == 200, (role, path, r.text[:200])
        else:
            assert r.status_code == 403, (role, path, r.status_code)


def test_denied_access_is_audited(client, auth) -> None:  # type: ignore[no-untyped-def]
    client.get(f"{API}/audit/verify", headers=auth("customer"))
    entries = client.get(f"{API}/audit", params={"action": "access.denied"}, headers=auth("admin")).json()["items"]
    assert any("/audit/verify" in e["entity_id"] for e in entries)


def test_customer_sees_only_own_complaints(client, auth, submit) -> None:  # type: ignore[no-untyped-def]
    other = submit("Somebody else's complaint", "My Nexus hub keeps disconnecting from wifi every evening since the update.",
                   customer_ref="CUST-10090")
    r = client.get(f"{API}/complaints/{other['complaint_ref']}", headers=auth("customer"))
    assert r.status_code == 404, "no information leak about other customers' cases"
    own = client.get(f"{API}/complaints", headers=auth("customer")).json()
    assert all(i["complaint_ref"] != other["complaint_ref"] for i in own["items"])
    # customer view never exposes validation internals
    mine = submit("My own complaint", "My Beam bulbs flicker all the time and one stopped working after a week.", role="customer")
    detail = client.get(f"{API}/complaints/{mine['complaint_ref']}", headers=auth("customer")).json()
    assert "validation" not in detail and "analysis" not in detail and "preprocessing" not in detail
    progress = client.get(f"{API}/complaints/{mine['complaint_ref']}/pipeline", headers=auth("customer")).json()
    assert "score" not in progress and "verification_status" not in progress


def test_cookie_session_requires_csrf_header(client) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient
    c: TestClient = client
    login = c.post(f"{API}/auth/login", json={"email": "agent@lumora.example", "password": DEMO_PASSWORD})
    assert login.status_code == 200
    csrf = login.json()["csrf_token"]
    body = {"title": "CSRF check", "description": "This request comes from a cookie session and must carry the CSRF token.",
            "channel": "web_form", "customer_type": "individual"}
    no_token = c.post(f"{API}/complaints/validate", json=body)  # cookies only
    assert no_token.status_code == 403
    ok = c.post(f"{API}/complaints/validate", json=body, headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 200
    c.post(f"{API}/auth/logout", headers={"X-CSRF-Token": csrf})
    c.cookies.clear()


def test_account_lockout_after_failed_logins(client) -> None:  # type: ignore[no-untyped-def]
    for _ in range(5):
        r = client.post(f"{API}/auth/login", json={"email": "reviewer2@lumora.example", "password": "wrong-password"})
        assert r.status_code == 401
    locked = client.post(f"{API}/auth/login", json={"email": "reviewer2@lumora.example", "password": DEMO_PASSWORD})
    assert locked.status_code == 401 and locked.json()["error"]["code"] == "account_locked"
    client.cookies.clear()


def test_security_headers(client) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{API}/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert "ai_api_key" not in r.text.lower()


def test_ai_key_never_exposed(client, auth) -> None:  # type: ignore[no-untyped-def]
    for path in ("/config/public", "/ai/status", "/system/info"):
        text = client.get(f"{API}{path}", headers=auth("admin")).text.lower()
        assert "api_key" not in text or '"api_key"' not in text
        assert "sk-" not in text


def test_executable_upload_rejected(client, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{API}/documents/preview", files={"file": ("policy.pdf", b"MZ\x90\x00\x03 fake exe", "application/pdf")},
                    headers=auth("admin"))
    assert r.status_code == 422


def test_audit_log_is_append_only_in_the_database(client, auth) -> None:  # type: ignore[no-untyped-def]
    import psycopg
    result = client.get(f"{API}/audit/verify", headers=auth("admin")).json()
    assert result["valid"] is True and result["checked"] > 0
    url = TEST_DB.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(url, autocommit=True) as conn:
        with pytest.raises(psycopg.Error):
            conn.execute("UPDATE audit_logs SET summary = 'tampered' WHERE id = (SELECT min(id) FROM audit_logs)")
        with pytest.raises(psycopg.Error):
            conn.execute("DELETE FROM audit_logs")
    assert client.get(f"{API}/audit/verify", headers=auth("admin")).json()["valid"] is True


def test_demo_accounts_are_public_only_while_enabled(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from supportnova.core.config import get_settings

    r = client.get(f"{API}/auth/demo-accounts")  # no session: the login page needs it
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is True and body["password"] == DEMO_PASSWORD
    assert {a["role"] for a in body["accounts"]} == {"admin", "manager", "reviewer", "agent", "customer"}
    monkeypatch.setattr(get_settings(), "seed_demo_users", False)
    assert client.get(f"{API}/auth/demo-accounts").json() == {"enabled": False, "password": None, "accounts": []}


def test_spoofed_forwarded_for_does_not_bypass_login_rate_limit(client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from supportnova.core.config import get_settings

    monkeypatch.setattr(get_settings(), "login_rate_limit_per_minute", 3)
    codes = [client.post(f"{API}/auth/login", json={"email": "nobody@lumora.example", "password": "wrong-password"},
                         headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code for i in range(6)]
    assert 429 in codes, codes  # every attempt counts against the real peer, whatever the header claims
