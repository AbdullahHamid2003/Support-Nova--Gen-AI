"""Without an API key the product never fabricates GenAI output: the GenAI step is recorded as failed with
``not_configured``, no customer response is drafted, the case goes to manual review, and the Python
ground-truth decision - here a safety escalation - is still enforced."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from supportnova.genai_pipeline import providers
from tests.conftest import check


@pytest.fixture
def without_api_key() -> Iterator[None]:
    test_double = providers.get_provider()
    providers.use_provider(None)            # the configured provider: AI_PROVIDER=openai with no AI_API_KEY
    try:
        yield
    finally:
        providers.use_provider(test_double)


def test_no_api_key_means_no_ai_output_and_manual_review(without_api_key, submit, client, auth) -> None:  # type: ignore[no-untyped-def]
    d = submit("Power station started smoking", "My PowerCell power station started smoking while charging last night and "
               "left a burn mark on the floor. What should I do now?", customer_ref="CUST-10033")
    assert d["processing_stage"] == "completed"
    assert d["analysis"]["status"] == "invalid_output" and d["analysis"]["output"] is None
    assert (d["analysis"]["provider"], d["analysis"]["model"]) == ("openai", "gpt-4.1-mini")
    sch = check(d, "SCH-001")
    assert sch["status"] == "fail" and "not configured" in sch["message"]
    assert d["verification_status"] == "Manual Review"
    assert d["responses"] == []                                    # nothing is drafted without a model
    vd = d["validation"]["validated_decision"]
    assert vd["safety"] is True and vd["escalation"]["required"]    # the Python decision is still enforced
    runs = client.get(f"/api/v1/complaints/{d['complaint_ref']}/ai-runs", headers=auth("admin")).json()["items"]
    assert {r["stage"] for r in runs} == {"analysis", "communication"}
    assert all(r["error_type"] == "not_configured" and not r["parsed_ok"] for r in runs)
    assert len(runs) == 2                                          # a missing key is not retried
