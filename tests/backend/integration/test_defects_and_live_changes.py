"""Deliberate-defect tests (brief section 65), live modification (section 64), hidden-dataset readiness
(section 62), revised policy + document versioning and the evaluation runner."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
API = "/api/v1"


def _poll(client, url: str, headers: dict[str, str], done, timeout: float = 120.0) -> Any:  # type: ignore[no-untyped-def]
    deadline = time.time() + timeout
    while time.time() < deadline:
        data = client.get(url, headers=headers).json()
        if done(data):
            return data
        time.sleep(0.5)
    raise AssertionError(f"timeout waiting for {url}")


# ---------------------------------------------------------------- deliberate defects
def test_every_adversarial_scenario_is_caught(client, auth) -> None:  # type: ignore[no-untyped-def]
    """Each lab scenario corrupts the GenAI output (fault profiles) or attacks the input; Python must catch all of them."""
    h = auth("admin")
    started = client.post(f"{API}/lab/runs/all", headers=h).json()["items"]
    refs = {s["complaint_ref"] for s in started}
    assert len(refs) >= 15

    def finished(data: dict[str, Any]) -> bool:
        mine = [i for i in data["items"] if i["complaint_ref"] in refs]
        return len(mine) == len(refs) and all(i["state"] in ("completed", "failed") for i in mine)
    runs = _poll(client, f"{API}/lab/runs", h, finished)
    mine = [i for i in runs["items"] if i["complaint_ref"] in refs]
    not_met = {i["scenario_id"]: [x for x in i["items"] if not x["ok"]] for i in mine if i["met"] is False}
    assert not not_met, not_met
    # no corrupted output is ever auto-verified
    assert all(i["verification_status"] != "Verified" for i in mine if i["fault_profile"] and i["fault_profile"] != "invalid_json")


@pytest.mark.parametrize("profile,check_code", [
    ("missed_escalation", "ESC-001"), ("wrong_department", "RTE-001"), ("hallucinated_policy", "SCH-004"),
    ("unsupported_refund", "RSP-002"), ("prohibited_action", "RSP-006"), ("hallucinated_entity", "HAL-002"),
])
def test_fault_profile_on_custom_complaint(client, auth, profile: str, check_code: str) -> None:  # type: ignore[no-untyped-def]
    h = auth("admin")
    body = {"title": "Power station overheating", "description": "My PowerCell power station got extremely hot while charging and "
            "the case is swelling. My kids were in the room.", "fault_profile": profile}
    ref = client.post(f"{API}/lab/runs", json=body, headers=h).json()["complaint_ref"]
    detail = _poll(client, f"{API}/complaints/{ref}", h, lambda d: d["processing_stage"] in ("completed", "failed"))
    statuses = {c["code"]: c["status"] for c in detail["validation"]["checks"]}
    assert statuses.get(check_code) == "fail", (profile, {k: v for k, v in statuses.items() if v == "fail"})
    assert detail["verification_status"] == "Manual Review"


# ---------------------------------------------------------------- live modification
def _simulate(client, h, **body: Any) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    r = client.post(f"{API}/rules/simulate", json=body, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


def test_changing_a_rule_parameter_changes_the_decision(client, auth, make_order) -> None:  # type: ignore[no-untyped-def]
    h = auth("admin")
    order = make_order("LUM-SPK-500", customer_ref="CUST-10040", price=99.0, ordered_days_ago=30, delivered_days_ago=25)
    text = {"title": "Return for refund", "description": f"I changed my mind about the Halo speaker from order {order}. It is "
            "unopened and I would like to return it for a refund.", "order_ref": order, "requested_resolution": "refund"}
    before = _simulate(client, h, **text)["decision"]["eligibility"]["refund"]
    assert before in ("eligible", "requires_verification")
    r = client.put(f"{API}/rule-parameters/refund_window_days", json={"value": 21, "reason": "test: REF-POL-02 v2.1"}, headers=h)
    assert r.status_code == 200 and r.json()["value"] == 21
    try:
        after = _simulate(client, h, **text)["decision"]["eligibility"]["refund"]
        assert after == "not_eligible", "25 days is now outside the 21-day window"
    finally:
        client.put(f"{API}/rule-parameters/refund_window_days", json={"value": 30, "reason": "test restore"}, headers=h)


def test_rule_edit_preview_validates_without_saving(client, auth) -> None:  # type: ignore[no-untyped-def]
    h = auth("admin")
    rule = client.get(f"{API}/rules/escalation/ESC-010", headers=h).json()
    revision = client.post(f"{API}/rules/validate", headers=h).json()["ruleset_hash"]
    audit_before = client.get(f"{API}/audit", params={"page_size": 1}, headers=h).json()["total"]
    broken = {**rule["body"], "level": "Galactic Escalation"}  # not a configured escalation level
    r = client.post(f"{API}/rules/validate", json={"rule_type": "escalation", "rule_id": "ESC-010", "body": broken}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["preview"] is True and r.json()["valid"] is False and r.json()["issues"]
    fine = client.post(f"{API}/rules/validate", json={"rule_type": "escalation", "rule_id": "ESC-010", "body": rule["body"]}, headers=h)
    assert fine.json()["valid"] is True
    # nothing was written: same live matrix, the stored rule unchanged, no audit entry
    assert client.post(f"{API}/rules/validate", headers=h).json()["ruleset_hash"] == revision
    assert client.get(f"{API}/rules/escalation/ESC-010", headers=h).json()["version"] == rule["version"]
    assert client.get(f"{API}/audit", params={"page_size": 1}, headers=h).json()["total"] == audit_before
    # saving the same broken body is refused with the same integrity issues
    saved = client.put(f"{API}/rules/escalation/ESC-010", json={"body": broken}, headers=h)
    assert saved.status_code == 422


def test_disabling_an_escalation_rule_changes_validation(client, auth) -> None:  # type: ignore[no-untyped-def]
    h = auth("admin")
    text = {"title": "Lawyer involved", "description": "You refused my warranty claim for the thermostat. My solicitor will take "
            "legal action if this is not reviewed within a week."}
    fired = _simulate(client, h, **text)["decision"]["escalation"]["fired"]
    assert fired
    rule_id = fired[0]["rule_id"]
    r = client.post(f"{API}/rules/escalation/{rule_id}/active", json={"active": False}, headers=h)
    assert r.status_code == 200, r.text
    try:
        after = [f["rule_id"] for f in _simulate(client, h, **text)["decision"]["escalation"]["fired"]]
        assert rule_id not in after
    finally:
        client.post(f"{API}/rules/escalation/{rule_id}/active", json={"active": True}, headers=h)


def test_new_category_without_code_changes(client, auth) -> None:  # type: ignore[no-untyped-def]
    """Hidden-dataset readiness: an authorised user adds a category + subcategory + routing at runtime."""
    h = auth("admin")
    depts = {d["code"] for d in client.get(f"{API}/taxonomy", headers=h).json().get("departments", [])}
    r = client.post(f"{API}/taxonomy/categories", json={"code": "ENV", "name": "Environment & Recycling",
                                                        "description": "E-waste take-back and recycling"}, headers=h)
    assert r.status_code in (201, 422), r.text
    body = {"code": "ENV-RCY", "name": "Recycling Take-Back", "category": "ENV", "description": "Take-back of old devices",
            "department": "DEPT-LOG" if "DEPT-LOG" in depts or not depts else sorted(depts)[0],
            "keywords": {"recycle": 4, "recycling": 4, "take-back": 5, "take back": 5, "e-waste": 5, "old device": 3}}
    r = client.post(f"{API}/taxonomy/subcategories", json=body, headers=h)
    assert r.status_code in (201, 422), r.text
    sim = _simulate(client, h, title="Recycling my old thermostat", description="How do I use the take-back scheme to recycle my old "
                    "thermostat? It is e-waste and I do not want to throw it away.")
    assert sim["classification"]["primary"] == "ENV-RCY"
    assert sim["decision"]["department"]


# ---------------------------------------------------------------- revised policy & versioning
def test_revised_policy_upload_versioning_and_impact(client, auth) -> None:  # type: ignore[no-untyped-def]
    h = auth("admin")
    path = ROOT / "data" / "hidden_test_ready" / "documents" / "REF-POL-02_v2.1.pdf"
    preview = client.post(f"{API}/documents/preview", files={"file": (path.name, path.read_bytes(), "application/pdf")}, headers=h)
    assert preview.status_code == 200 and preview.json()["detected_metadata"].get("doc_id") == "REF-POL-02"
    meta = {"doc_id": "REF-POL-02", "title": "Refund Policy", "doc_type": "policy", "version": "2.1", "status": "Active",
            "effective_date": "2026-09-15", "owner_department": "DEPT-RET", "topics": "refunds,returns"}
    r = client.post(f"{API}/documents", files={"file": (path.name, path.read_bytes(), "application/pdf")}, data=meta, headers=h)
    assert r.status_code == 201, r.text
    doc = client.get(f"{API}/documents/REF-POL-02", headers=h).json()
    statuses = {v["version"]: v["status"] for v in doc["versions"]}
    assert statuses["2.1"] == "Active" and statuses["2.0"] in ("Previous", "Superseded")
    impact = client.get(f"{API}/documents/REF-POL-02/impact", headers=h).json()["impacts"]
    latest = next(i for i in impact if i["version"] == "2.1")
    changed = {c["section_id"] for c in latest["changed_sections"]}
    assert {"3.1", "3.2", "4.3"} <= changed
    params = {p["key"]: p for p in latest["affected_parameters"]}
    assert params["refund_window_days"]["out_of_sync"] and float(params["refund_window_days"]["suggested_value"]) == 21
    search = client.get(f"{API}/knowledge/search", params={"q": "refund window days return", "subcategory": "REF-REQ"}, headers=h).json()
    ref_versions = {e["version"] for e in search["evidence"] if e["doc_id"] == "REF-POL-02"}
    assert ref_versions == {"2.1"}, "only the active version is primary evidence"


def test_malicious_document_upload_is_quarantined(client, auth) -> None:  # type: ignore[no-untyped-def]
    h = auth("admin")
    path = ROOT / "knowledge_base" / "security_samples" / "MAL-DOC-99_v1.0.docx"
    scan = client.post(f"{API}/lab/document-scan", data={"sample": path.name}, headers=h).json()
    assert scan["quarantined_sections"]


# ---------------------------------------------------------------- evaluation & hidden datasets
def test_evaluation_run_on_unseen_holdout(client, auth) -> None:  # type: ignore[no-untyped-def]
    h = auth("admin")
    r = client.post(f"{API}/evaluation/runs", json={"dataset": "holdout", "label": "pytest", "limit": 12}, headers=h)
    assert r.status_code == 202, r.text
    run = _poll(client, f"{API}/evaluation/runs/{r.json()['id']}", h, lambda d: d["status"] in ("completed", "failed", "cancelled"), 300)
    assert run["status"] == "completed", run.get("error")
    head = run["metrics"]["headline"]
    assert head["cases"] == 12 and head["python_key_field_accuracy"] is not None
    results = client.get(f"{API}/evaluation/runs/{run['id']}/results", headers=h).json()
    assert results["total"] == 12
    pdf = client.get(f"{API}/evaluation/runs/{run['id']}/report", params={"format": "pdf"}, headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_hidden_dataset_upload_with_minimal_columns(client, auth) -> None:  # type: ignore[no-untyped-def]
    h = auth("admin")
    csv_text = ("complaint_id,title,description\n"
                "HID-1,Late parcel,My parcel is two weeks late and tracking has not moved since last Monday.\n"
                "HID-2,Recycling question,Can I send my old hub back through a take-back or recycling scheme please?\n"
                "HID-3,Charged twice,I was charged twice for the same order and need the duplicate charge reversed.\n")
    r = client.post(f"{API}/evaluation/runs/upload", files={"file": ("hidden.csv", csv_text.encode(), "text/csv")},
                    data={"label": "hidden-format"}, headers=h)
    assert r.status_code == 202, r.text
    run = _poll(client, f"{API}/evaluation/runs/{r.json()['id']}", h, lambda d: d["status"] in ("completed", "failed"), 180)
    assert run["status"] == "completed" and run["n_done"] == 3
