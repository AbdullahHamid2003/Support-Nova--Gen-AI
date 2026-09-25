"""FINAL END-TO-END TEST (brief section 78) - every stage of the chain is asserted in order:

create -> store -> preprocess -> retrieve -> AI analysis -> structured JSON validation -> ground-truth validation
-> policy / routing / urgency / priority / resolution / eligibility / escalation validation -> hallucination check
-> unsupported-promise check -> response -> agent guidance -> audit record -> UI payload -> manual review
-> dashboard -> export/report. Plus the other E2E journeys: escalation, resolution, document upload, versioning.
"""

from __future__ import annotations

from typing import Any

from tests.conftest import wait_for_pipeline

API = "/api/v1"


def _checks(detail: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["code"]: c for c in detail["validation"]["checks"]}


def test_complete_complaint_chain(client, auth) -> None:  # type: ignore[no-untyped-def]
    admin, customer, reviewer, agent = auth("admin"), auth("customer"), auth("reviewer"), auth("agent")
    before = client.get(f"{API}/dashboard", headers=admin).json()["overview"]["total"]

    # 1-2. create + store (as the customer, through the public API)
    body = {"title": "Power station smoking while charging", "description": "Yesterday my PowerCell power station started to "
            "smell of burning plastic and smoke came out of the vent while it was charging next to my daughter's bed. I unplugged "
            "it. I want a replacement and compensation.", "channel": "web_form", "requested_resolution": "replacement"}
    r = client.post(f"{API}/complaints", json=body, headers=customer)
    assert r.status_code == 202
    ref = r.json()["complaint_ref"]
    progress = wait_for_pipeline(client, ref, customer)
    assert progress["done"] and not progress["failed"]
    d = client.get(f"{API}/complaints/{ref}", headers=admin).json()
    assert d["title"] == body["title"] and d["processing_stage"] == "completed"

    # 3. preprocess
    pre = d["preprocessing"]
    assert pre["normalized_text"] and pre["classification"]["candidates"]
    assert "fire_event" in pre["signals"] or "overheating" in pre["signals"]

    # 4. retrieve relevant knowledge
    evidence = d["analysis"]["retrieval"]["evidence"]
    assert evidence and any(e["doc_id"].startswith("SAF") for e in evidence)
    assert all(e["status"] == "Active" for e in evidence), "only approved active versions are evidence"

    # 5. AI analysis (answered by the suite's offline test double) + 6. structured JSON validation
    assert d["analysis"]["status"] == "completed" and d["analysis"]["provider"] == "offline-test-llm"
    runs = client.get(f"{API}/complaints/{ref}/ai-runs", headers=admin).json()["items"]
    assert runs and any(x["stage"] == "analysis" and x["parsed_ok"] for x in runs)
    checks = _checks(d)
    assert checks["SCH-001"]["status"] == "pass"

    # 7-14. ground-truth validation dimensions all ran
    for code in ("CLS-001", "RTE-001", "PRI-001", "PRI-002", "POL-001", "POL-002", "RES-001", "RES-002", "ELG-001", "ELG-002",
                 "ELG-003", "ESC-001", "ESC-002"):
        assert code in checks, code
    vd = d["validation"]["validated_decision"]
    assert vd["classification"]["category"] == "SAF"
    assert vd["urgency"] == "Critical" and vd["priority"] == "P0"
    assert vd["escalation"]["required"] is True
    assert vd["policy_refs"]

    # 15. hallucination check + 16. unsupported promise check
    for code in ("HAL-001", "HAL-002", "HAL-004", "RSP-002", "RSP-006", "SEC-001"):
        assert code in checks, code

    # 17. generate response + 18. agent guidance
    response = d["responses"][0]
    assert response["body"] and response["validation"] is not None
    assert vd["agent_guidance"]["validated"]

    # 19. audit record
    audit = client.get(f"{API}/complaints/{ref}/audit", headers=admin).json()["items"]
    actions = {a["action"] for a in audit}
    assert {"complaint.created", "complaint.processed"} <= actions

    # 20. show result in UI (the API payload the case page renders; the SPA is served by the same app when built)
    assert d["verification_status"] in ("Verified", "Manual Review") and d["verification_score"] is not None
    customer_view = client.get(f"{API}/complaints/{ref}", headers=customer).json()
    assert customer_view["status"] and "validation" not in customer_view

    # 21. manual review if needed (safety cases always need a human)
    assert d["verification_status"] == "Manual Review" and d["review"]
    review_id = d["review"]["id"]
    assert client.post(f"{API}/reviews/{review_id}/claim", headers=reviewer).status_code == 200
    act = client.post(f"{API}/reviews/{review_id}/actions", json={"action": "approve", "comment": "Safety escalation confirmed."},
                      headers=reviewer)
    assert act.status_code == 200, act.text
    d = client.get(f"{API}/complaints/{ref}", headers=admin).json()
    assert d["verification_status"] == "Human Verified"
    assert d["review"]["status"] == "completed" and d["review"]["final_decision"] == "approved"

    # escalation + resolution journey
    assert d["status"] == "Escalated" and d["escalations"]
    resp = d["responses"][0]
    if resp["status"] in ("ready", "approved"):
        sent = client.post(f"{API}/complaints/{ref}/responses/{resp['id']}/send", headers=agent)
        assert sent.status_code == 200, sent.text
    for status in ("In Progress", "Resolved"):
        r = client.post(f"{API}/complaints/{ref}/status", json={"status": status, "note": "e2e"}, headers=admin)
        assert r.status_code == 200, r.text
    d = client.get(f"{API}/complaints/{ref}", headers=admin).json()
    assert d["status"] == "Resolved" and d["resolved_at"]

    # 22. dashboard updated
    after = client.get(f"{API}/dashboard", headers=admin).json()["overview"]
    assert after["total"] == before + 1

    # 23. export / report
    pdf = client.get(f"{API}/complaints/{ref}/report.pdf", headers=admin)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    csv = client.get(f"{API}/reports/complaint-analysis", params={"format": "csv"}, headers=admin)
    assert csv.status_code == 200 and ref in csv.text, csv.text[:300]
    xlsx = client.get(f"{API}/complaints-export", params={"format": "xlsx"}, headers=admin)
    assert xlsx.status_code == 200 and xlsx.content[:2] == b"PK"

    # the whole journey is in the immutable, verifiable audit chain
    assert client.get(f"{API}/audit/verify", headers=admin).json()["valid"] is True


def test_customer_clarification_loop(client, auth) -> None:  # type: ignore[no-untyped-def]
    customer, admin = auth("customer"), auth("admin")
    r = client.post(f"{API}/complaints", json={"title": "Refund not received", "description": "I returned my purifier a while ago "
                    "and still have not received my refund. Please check.", "channel": "web_form", "requested_resolution": "refund"},
                    headers=customer)
    ref = r.json()["complaint_ref"]
    wait_for_pipeline(client, ref, customer)
    d = client.get(f"{API}/complaints/{ref}", headers=admin).json()
    assert d["validation"]["validated_decision"]["missing_information"]
    r = client.post(f"{API}/complaints/{ref}/clarify", json={"information": "The order number is on my email.", "order_ref": None},
                    headers=customer)
    assert r.status_code == 202
    wait_for_pipeline(client, ref, customer)
    history = client.get(f"{API}/complaints/{ref}/timeline", headers=admin).json()["events"]
    assert any(e["event_type"] == "complaint.clarified" for e in history)


def test_document_upload_and_policy_versioning_journey(client, auth) -> None:  # type: ignore[no-untyped-def]
    admin = auth("admin")
    text = ("---\ndoc_id: TST-POL-90\ntitle: Test Accessibility Policy\ndoc_type: policy\nversion: '1.0'\nstatus: Active\n"
            "effective_date: 2026-01-01\n---\n# Test Accessibility Policy\n\n## 1 Purpose\n\nThis policy explains accessible support "
            "options for customers.\n\n## 2 Large print\n\nLarge print manuals are sent within 5 business days of a request.\n")
    r = client.post(f"{API}/documents", files={"file": ("TST-POL-90_v1.0.md", text.encode(), "text/markdown")},
                    data={"doc_id": "TST-POL-90", "title": "Test Accessibility Policy", "doc_type": "policy", "version": "1.0",
                          "status": "Active", "effective_date": "2026-01-01"}, headers=admin)
    assert r.status_code == 201, r.text
    v2 = text.replace("version: '1.0'", "version: '1.1'").replace("5 business days", "2 business days")
    r = client.post(f"{API}/documents", files={"file": ("TST-POL-90_v1.1.md", v2.encode(), "text/markdown")},
                    data={"doc_id": "TST-POL-90", "title": "Test Accessibility Policy", "doc_type": "policy", "version": "1.1",
                          "status": "Active", "effective_date": "2026-02-01"}, headers=admin)
    assert r.status_code == 201, r.text
    doc = client.get(f"{API}/documents/TST-POL-90", headers=admin).json()
    assert {v["version"]: v["status"] for v in doc["versions"]} == {"1.0": "Previous", "1.1": "Active"}
    impact = client.get(f"{API}/documents/TST-POL-90/impact", headers=admin).json()["impacts"]
    assert any(c["section_id"] == "2" for i in impact for c in i["changed_sections"])
    hits = client.get(f"{API}/knowledge/search", params={"q": "large print manual business days"}, headers=admin).json()["evidence"]
    assert any(e["doc_id"] == "TST-POL-90" and e["version"] == "1.1" for e in hits)
    assert not any(e["doc_id"] == "TST-POL-90" and e["version"] == "1.0" for e in hits)
