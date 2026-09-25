"""Text stored by older analyses is served in the current wording; new text passes through unchanged."""

from __future__ import annotations

import pytest

from supportnova.api.wording import current_wording


@pytest.mark.parametrize(("stored", "shown"), [
    ("GenAI output matches the complaint_analysis.v1 JSON schema (required fields, types, enums).",
     "The AI answer is complete and well-formed."),
    ("GenAI sentiment Negative; lexicon sentiment Neutral (score 0.0). Sentiment never drives urgency.",
     "AI sentiment Negative; rule check Neutral (score 0.0). Sentiment never changes urgency."),
    ("Applicability disagreements: ESC-SOP-12:4.2 (GenAI Applicable, Python Not Applicable)",
     "Applicability disagreements: ESC-SOP-12:4.2 (AI: Applicable, rules: Not Applicable)"),
    ("Refund eligibility: GenAI eligible, rules not_eligible.", "Refund eligibility: AI eligible, rules not_eligible."),
    ("Escalated to Supervisor Review by ESC-038 (enforced by Python - GenAI missed it).",
     "Escalated to Supervisor Review by ESC-038; the AI missed it, the rules require it."),
    ("Python ground-truth validation: Manual Review, score 89.1/100 (1 failed, 3 warnings).",
     "Rule check: Manual Review, score 89.1/100 (1 failed, 3 warnings)."),
    ("Sent to the manual review queue: GenAI and Python disagree on category; Critical validation check failed.",
     "Sent to manual review: AI and rules disagree on the category; A critical check failed."),
    ("GenAI analysis by openai/gpt-4.1-mini with prompt complaint_analysis v1.2.0: 1 attempt(s).",
     "AI analysis by openai/gpt-4.1-mini (prompt complaint_analysis v1.2.0), 1 attempt(s)."),
    ("Category ACC accepted, but the Python rules could not independently confirm it.",
     "Category ACC accepted, but the rules could not independently confirm it."),
    ("Python classifier confidence 'low' - not used as reference; provisional GenAI classification pending manual review",
     "Rule confidence: low. The AI category is used until a reviewer confirms it."),
    ("Lexicon sentiment (informational)", "Keyword-based estimate, for information only"),
    ("Rule classification (category_rules)", "Rule classification"),
    ("RTE-001 Primary department matches the routing rules; PRI-001 Urgency meets the rule-matrix level; "
     "ESC-001 Mandatory escalation enforced",
     "RTE-001 Primary department matches the routing rules; PRI-001 Urgency matches the rules; "
     "ESC-001 Required escalation identified"),
    ("Sensitive case (SAF; signals: ) - human approval required.", "Sensitive case (SAF). A person must approve it."),
])
def test_legacy_text_is_served_in_the_current_wording(stored: str, shown: str) -> None:
    assert current_wording(stored) == shown


def test_current_text_is_unchanged() -> None:
    for text in ("Rule check: Verified, score 95.2/100 (0 failed, 1 warnings).", "Urgency too low: AI High, rules require Critical.",
                 "", None):
        assert current_wording(text) == text
