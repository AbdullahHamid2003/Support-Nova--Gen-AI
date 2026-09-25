"""Boundary tests (SRS 1.10 item 11): each limit is probed on both sides of its edge."""

from __future__ import annotations

import pytest

from supportnova.core.errors import ValidationFailed
from supportnova.rule_engine.conditions import EvalContext, evaluate
from supportnova.security.files import DOCUMENT_TYPES, validate_upload

API = "/api/v1"
OK_TITLE = "Plug stopped working"
OK_DESCRIPTION = "My smart plug stopped working after the last app update and will not switch on."


def _words(n: int) -> str:
    """Realistic text of exactly n characters."""
    return ("My plug stopped working again today. " * (n // 36 + 1))[:n]


def _field_errors(client, auth, **fields) -> set[str]:  # type: ignore[no-untyped-def]
    body = {"title": OK_TITLE, "description": OK_DESCRIPTION, **fields}
    r = client.post(f"{API}/complaints/validate", json=body, headers=auth("customer"))
    assert r.status_code == 200, r.text
    return {e["field"] for e in r.json()["errors"]}


@pytest.mark.parametrize(("title", "rejected"), [("Plug", True), ("Plugs", False), (_words(180), False), (_words(181), True)])
def test_title_length_edges(client, auth, title: str, rejected: bool) -> None:  # type: ignore[no-untyped-def]
    assert ("title" in _field_errors(client, auth, title=title)) is rejected


def test_title_over_the_hard_cap_is_a_field_error_not_a_crash(client, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{API}/complaints/validate", json={"title": "x" * 201, "description": OK_DESCRIPTION}, headers=auth("customer"))
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "title"


@pytest.mark.parametrize(("description", "rejected"), [
    ("", True), ("   \n\t  ", True), ("It is broken, help me", False), ("It is broken, help", True),
    ("x" * 30, True), (_words(8000), False), (_words(8001), True),
])
def test_description_length_edges(client, auth, description: str, rejected: bool) -> None:  # type: ignore[no-untyped-def]
    # at least 20 characters and 4 words ("It is broken, help me" has 21; "It is broken, help" 18; 30 x's is one
    # word); at most 8000 characters; whitespace only counts as empty
    assert ("description" in _field_errors(client, auth, description=description)) is rejected


def test_description_over_the_hard_cap_is_a_field_error_not_a_crash(client, auth) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{API}/complaints", json={"title": OK_TITLE, "description": _words(10001)}, headers=auth("customer"))
    assert r.status_code == 422 and r.json()["error"]["details"][0]["field"] == "description"


def test_customer_precheck_uses_the_profile_customer_type(client, auth) -> None:  # type: ignore[no-untyped-def]
    # the customer form has no customer-type field; the precheck must agree with submission, which uses the profile
    assert "customer_type" not in _field_errors(client, auth)


def test_malformed_body_is_a_field_error_not_a_crash(client, auth) -> None:  # type: ignore[no-untyped-def]
    h = auth("customer")
    assert client.post(f"{API}/complaints/validate", content=b"{not json", headers={**h, "content-type": "application/json"}).status_code == 422
    assert client.post(f"{API}/complaints/validate", json=["a", "list"], headers=h).status_code == 422


@pytest.mark.parametrize(("order_ref", "malformed"), [("LMR-12345", True), ("LMR-123456", False), ("ORDER-1", True)])
def test_order_reference_format(client, auth, order_ref: str, malformed: bool) -> None:  # type: ignore[no-untyped-def]
    r = client.post(f"{API}/complaints/validate", json={"title": OK_TITLE, "description": OK_DESCRIPTION, "order_ref": order_ref},
                    headers=auth("customer"))
    format_errors = [e for e in r.json()["errors"] if e["field"] == "order_ref" and "format" in e["message"].lower()]
    assert bool(format_errors) is malformed


@pytest.mark.parametrize(("days", "inside"), [(0, True), (29, True), (30, True), (31, False), (365, False)])
def test_refund_window_edge(matrix, days: int, inside: bool) -> None:  # type: ignore[no-untyped-def]
    window = {"fact": "order.days_since_delivery", "op": "lte", "value": "$param:refund_window_days"}
    assert matrix.parameters["refund_window_days"].value == 30
    assert evaluate(window, EvalContext(matrix=matrix, facts={"order": {"days_since_delivery": days}}, signals=set())) is inside


def test_upload_size_edge() -> None:
    limit = 2048
    body = b"%PDF-1.7\n" + b"0" * (limit - 9)
    assert len(body) == limit
    validate_upload("policy.pdf", body, allowed=DOCUMENT_TYPES, max_bytes=limit)          # exactly at the limit
    with pytest.raises(ValidationFailed):
        validate_upload("policy.pdf", body + b"0", allowed=DOCUMENT_TYPES, max_bytes=limit)  # one byte over
    with pytest.raises(ValidationFailed):
        validate_upload("policy.pdf", b"", allowed=DOCUMENT_TYPES, max_bytes=limit)          # empty


@pytest.mark.parametrize(("params", "status"), [
    ({"page_size": 200}, 200), ({"page_size": 201}, 422), ({"page_size": 0}, 422), ({"page": 0}, 422), ({"page": 9999}, 200),
])
def test_list_pagination_limits(client, auth, params: dict[str, int], status: int) -> None:  # type: ignore[no-untyped-def]
    r = client.get(f"{API}/complaints", params=params, headers=auth("admin"))
    assert r.status_code == status, r.text
    if params.get("page") == 9999:
        assert r.json()["items"] == []  # past the end: an empty page, not an error
