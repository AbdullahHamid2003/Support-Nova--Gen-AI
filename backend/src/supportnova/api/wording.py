"""Current wording for text stored before the plain-language update (older check results and timeline entries).

Stored records are never rewritten - they are the record of what was said at the time. Only the text served to
the UI is normalised, so older and newer cases read the same way. The audit log is never touched.
"""

from __future__ import annotations

import re

# review-reason names written into older timeline entries -> current names (rules/complaint_rules/review_rules.yaml)
_REVIEW_REASONS = {
    "GenAI and Python disagree on category": "AI and rules disagree on the category",
    "Critical validation check failed": "A critical check failed",
    "Verification score below threshold": "Verification score too low",
    "Policy support missing": "No policy supports the decision",
    "Ambiguous complaint": "Unclear complaint",
    "Escalation unclear": "Escalation level unclear",
    "Policy contradiction in evidence": "Conflicting policy information",
    "Sensitive complaint requires human approval": "Sensitive case needs human approval",
    "Invalid GenAI output after retries": "No usable AI answer",
    "Prompt injection or manipulation attempt": "Attempt to manipulate the AI",
    "Customer response contains unsupported promises": "Response makes unsupported promises",
    "Unsupported (hallucinated) claims": "Unsupported claims",
    "Category not in the approved taxonomy": "Unknown category",
    "Order reference not found or not owned by the customer": "Order not found for this customer",
}
# check names written into older review-reason details ("CODE name") -> current names (rules/validation_policy.yaml)
_CHECK_NAMES = {
    "CLS-001 Category matches the Python rule classification": "CLS-001 Category matches the rules",
    "CLS-002 Subcategory matches the Python rule classification": "CLS-002 Subcategory matches the rules",
    "CLS-003 Secondary issues detected": "CLS-003 Secondary issues identified",
    "CLS-004 Sentiment agrees with the deterministic lexicon": "CLS-004 Sentiment matches the rule check",
    "CLS-005 Entities found by Python extraction are captured": "CLS-005 Reference numbers captured",
    "ELG-001 Refund eligibility validated": "ELG-001 Refund eligibility matches the rules",
    "ELG-002 Replacement eligibility validated": "ELG-002 Replacement eligibility matches the rules",
    "ELG-003 Compensation eligibility and amount validated": "ELG-003 Compensation and amount match the rules",
    "ESC-001 Mandatory escalation enforced": "ESC-001 Required escalation identified",
    "ESC-002 Escalation level meets the rule level": "ESC-002 Escalation level meets the rules",
    "ESC-003 No unjustified escalation": "ESC-003 No unnecessary escalation",
    "ESC-004 Escalation notes contain all required elements": "ESC-004 Escalation notes are complete",
    "HAL-001 Claims traceable to complaint": "HAL-001 Claims backed by the complaint, policies or rules",
    "HAL-002 Extracted entities appear in the complaint": "HAL-002 Extracted details appear in the complaint",
    "HAL-003 Summary facts grounded": "HAL-003 Summary sticks to the facts",
    "HAL-004 Policy references in text are valid": "HAL-004 Policies named in the text exist",
    "MIS-001 Required missing information identified": "MIS-001 Missing information identified",
    "MIS-002 Clarification questions cover blocking gaps": "MIS-002 Questions ask for the missing information",
    "POL-001 At least one policy reference cited": "POL-001 At least one policy cited",
    "POL-002 Cited policies are Active (no outdated policy as primary basis)": "POL-002 No outdated policy cited",
    "POL-003 Cited policies are supported by retrieved evidence": "POL-003 Cited policies are in the case evidence",
    "POL-004 Rule-matrix policy references covered": "POL-004 Policies required by the rules are cited",
    "POL-005 Policy applicability labels agree with Python": "POL-005 Policy applicability matches the rules",
    "POL-006 Policy precedence respected in conflicts": "POL-006 Higher-ranking policy followed in conflicts",
    "PRI-001 Urgency meets the rule-matrix level": "PRI-001 Urgency matches the rules",
    "PRI-004 AI urgency and priority are mutually consistent": "PRI-004 AI priority fits its urgency and impact",
    "RSP-001 Response contains required elements": "RSP-001 Response includes the required parts",
    "RSP-004 Amounts traceable to case facts or entitlements": "RSP-004 Amounts and references match the case",
    "RSP-005 Requested tone respected": "RSP-005 Requested tone used",
    "RSP-006 No prohibited behaviour in customer text": "RSP-006 No prohibited statements in the response",
    "RSP-007 Follow-up message validated": "RSP-007 Follow-up message is safe to send",
    "SCH-001 GenAI output matches the JSON schema": "SCH-001 AI answer is complete and well-formed",
    "SCH-002 Category and subcategory exist in the taxonomy": "SCH-002 Category and subcategory are valid",
    "SCH-003 Department IDs are valid": "SCH-003 Departments are valid",
    "SCH-004 Policy IDs and sections exist in the knowledge base": "SCH-004 Cited policies exist",
    "SCH-005 Escalation fields are internally consistent": "SCH-005 Escalation details are consistent",
    "SCH-006 Action codes exist in the action catalog": "SCH-006 Resolution steps use known actions",
    "SEC-001 Output not influenced by embedded instructions": "SEC-001 AI ignored instructions in the complaint",
    "SEC-002 Sensitive data not echoed in customer text": "SEC-002 No sensitive data in the response",
    "SEC-003 Untrusted-input screening result": "SEC-003 Complaint screened for manipulation",
}
# older sentence forms -> the forms the current code writes (specific patterns first, generic terms last)
_REPLACEMENTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"; signals: \)"), ")"),
    (re.compile(r"\) - human approval required\.$"), "). A person must approve it."),
    (re.compile(r"^Rule classification \(category_rules\)$"), "Rule classification"),
    (re.compile(r"^Python classifier confidence '(\w+)' - not used as reference; provisional GenAI classification pending manual review$"),
     r"Rule confidence: \1. The AI category is used until a reviewer confirms it."),
    (re.compile(r"^Python classifier confidence '(\w+)' - used provisionally; the GenAI category has no supporting evidence in the complaint, pending manual review$"),
     r"Rule confidence: \1. The rules' best match is used until a reviewer confirms it; the AI category has no support in the complaint."),
    (re.compile(r"^Python classifier confidence '(\w+)' - used provisionally, pending manual review$"),
     r"Rule confidence: \1. The rules' best match is used until a reviewer confirms it."),
    (re.compile(r"^Lexicon sentiment \(informational\)$"), "Keyword-based estimate, for information only"),
    (re.compile(r"GenAI output matches the complaint_analysis\.v\d+ JSON schema \([^)]*\)\.?"),
     "The AI answer is complete and well-formed."),
    (re.compile(r"GenAI priority is consistent with its own urgency x impact\.?"), "AI priority fits its own urgency and impact."),
    (re.compile(r"; lexicon sentiment "), "; rule check "),
    (re.compile(r"Sentiment never drives urgency"), "Sentiment never changes urgency"),
    (re.compile(r"\(GenAI ([A-Za-z ]+?), Python ([A-Za-z ]+?)\)"), r"(AI: \1, rules: \2)"),
    (re.compile(r"not identified by GenAI:"), "the AI missed:"),
    (re.compile(r" \(enforced by Python - GenAI missed it\)"), "; the AI missed it, the rules require it"),
    (re.compile(r"^Python ground-truth validation:"), "Rule check:"),
    (re.compile(r"^Sent to the manual review queue:"), "Sent to manual review:"),
    (re.compile(r"^GenAI analysis by (\S+) with prompt (\S+) v(\S+): (\d+) attempt\(s\)"), r"AI analysis by \1 (prompt \2 v\3), \4 attempt(s)"),
    (re.compile(r"\bPython (?:rules?|ground[- ]truth|decision|classification|classifier)\b"), "rules"),
    (re.compile(r"\bGenAI\b"), "AI"),
    (re.compile(r"\bPython\b"), "rules"),
]
_LEGACY = re.compile("|".join(["GenAI", "Python", "lexicon sentiment", "Lexicon sentiment", "manual review queue", re.escape("(category_rules)"),
                               *map(re.escape, _REVIEW_REASONS), *map(re.escape, _CHECK_NAMES),
                               re.escape(" - human approval required.")]))


def current_wording(text: str | None) -> str | None:
    """``text`` in the current wording; text without legacy terms is returned unchanged."""
    if not text or not _LEGACY.search(text):
        return text
    for old, new in (*_CHECK_NAMES.items(), *_REVIEW_REASONS.items()):
        text = text.replace(old, new)
    for pattern, replacement in _REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text
