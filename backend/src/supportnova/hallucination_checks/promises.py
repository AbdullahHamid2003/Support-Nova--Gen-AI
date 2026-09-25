"""Unsupported-promise detection (SRS Step 34): refund/compensation promises, unsupported timelines and
amounts, unauthorised exceptions and other prohibited behaviour in customer-facing text - always judged
against the Python-validated decision, never against what the model believes."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from supportnova.rule_engine.models import RuleMatrix

_CONDITIONAL = re.compile(r"\b(once|after|when|upon|subject\s+to|provided|if|following)\b.{0,60}\b(verif|inspect|confirm|receiv|check|review|assess)", re.I)
_GUARANTEE = re.compile(r"\bguarantee[ds]?\b", re.I)

REFUND_CODES = ("PROMISE_REFUND_BEFORE_VERIFICATION",)
COMPENSATION_CODES = ("GUARANTEE_COMPENSATION", "CASH_COMPENSATION")
EXCEPTION_CODES = ("GRANT_POLICY_EXCEPTION",)


@dataclass
class Finding:
    code: str
    severity: str
    text: str
    message: str
    policy_refs: list[str]


def _sentence_around(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start), text.rfind("\n", 0, start)) + 1
    right_candidates = [p for p in (text.find(".", end), text.find("\n", end)) if p != -1]
    right = min(right_candidates) if right_candidates else len(text)
    return text[left:right + 1].strip()


def prohibited_behaviour(matrix: RuleMatrix, text: str, *, exclude: tuple[str, ...] = ()) -> list[Finding]:
    findings: list[Finding] = []
    for code, pa in matrix.prohibited_actions.items():
        if code in exclude:
            continue
        for pattern in pa.patterns:
            m = pattern.search(text or "")
            if m:
                findings.append(Finding(code, pa.severity, _sentence_around(text, m.start(), m.end())[:240],
                                        f"{pa.name}.", list(pa.policy_refs)))
                break
    return findings


def promise_findings(matrix: RuleMatrix, text: str, eligibility: dict[str, Any], *, reviewer_approved_exception: bool = False) -> list[Finding]:
    """Refund / compensation / exception promises checked against the validated eligibility."""
    out: list[Finding] = []
    refund_status = eligibility.get("refund")
    comp_status = eligibility.get("compensation")
    for code in REFUND_CODES:
        pa = matrix.prohibited_actions.get(code)
        for pattern in (pa.patterns if pa else ()):
            assert pa is not None  # the loop only iterates when the prohibited action exists
            m = pattern.search(text or "")
            if not m:
                continue
            sentence = _sentence_around(text, m.start(), m.end())
            conditional = bool(_CONDITIONAL.search(sentence))
            if refund_status == "requires_verification" and conditional:
                break  # "we will process the refund once eligibility is verified" is the policy-compliant wording
            if refund_status != "eligible":
                out.append(Finding(code, "critical", sentence[:240],
                                   f"Refund promised but validated refund eligibility is '{refund_status}'.", list(pa.policy_refs)))
            elif not conditional:
                out.append(Finding(code, "major", sentence[:240],
                                   "Refund stated without the required verification condition.", list(pa.policy_refs)))
            break
    for code in COMPENSATION_CODES:
        pa = matrix.prohibited_actions.get(code)
        for pattern in (pa.patterns if pa else ()):
            assert pa is not None
            m = pattern.search(text or "")
            if m:
                out.append(Finding(code, "critical", _sentence_around(text, m.start(), m.end())[:240],
                                   f"{pa.name} (validated compensation eligibility: '{comp_status}').", list(pa.policy_refs)))
                break
    if not reviewer_approved_exception:
        for code in EXCEPTION_CODES:
            pa = matrix.prohibited_actions.get(code)
            for pattern in (pa.patterns if pa else ()):
                assert pa is not None
                m = pattern.search(text or "")
                if m:
                    out.append(Finding(code, "critical", _sentence_around(text, m.start(), m.end())[:240],
                                       "Policy exception promised without approval.", list(pa.policy_refs)))
                    break
    for m in _GUARANTEE.finditer(text or ""):
        sentence = _sentence_around(text, m.start(), m.end())
        if not any(f.text == sentence[:240] for f in out):
            out.append(Finding("GUARANTEE_LANGUAGE", "major", sentence[:240],
                               "'Guarantee' language is not permitted for outcomes (CPN-POL-11 s8).", ["CPN-POL-11:8"]))
    return out


def _to_number(token: str, words: dict[str, int]) -> float | None:
    t = token.lower().strip()
    if t.isdigit():
        return float(t)
    for candidate in (t, t.replace("-", " "), t.replace(" ", "-")):
        if candidate in words:
            return float(words[candidate])
    return None


def _base_unit(unit: str) -> str:
    u = unit.lower()
    for base in ("hour", "day", "week", "month"):
        if base in u:
            return base
    return u


_HOURS = {"hour": 1, "day": 24, "week": 168, "month": 720}


def timeline_findings(matrix: RuleMatrix, text: str, allowed: list[dict[str, Any]]) -> tuple[list[Finding], list[dict[str, Any]]]:
    """Every duration/deadline in the text must match an allowed (policy or SLA) timeline.

    A mention matches when its length equals an allowed timeline after unit normalisation; a mention
    stated in business days must match a business-day timeline.
    """
    cfg = matrix.response_rules
    words = {str(k).lower(): int(v) for k, v in (cfg.get("number_words") or {}).items()}
    duration_re = re.compile(cfg.get("timeline_patterns", {}).get("duration", r"$^"), re.I)
    deadline_re = re.compile(cfg.get("timeline_patterns", {}).get("deadline", r"$^"), re.I)
    safe_ctx = re.compile(cfg.get("deadline_allowed_context", r"$^"), re.I)
    findings: list[Finding] = []
    seen: list[dict[str, Any]] = []
    for m in duration_re.finditer(text or ""):
        qty = _to_number(m.group(2), words)
        unit = _base_unit(m.group(4))
        business = bool(m.group(3) and re.match(r"(business|working)", m.group(3), re.I))
        match = None
        if qty is not None:
            for a in allowed:
                a_unit = _base_unit(str(a.get("unit", "")))
                if business and a_unit == "day" and "business" not in str(a.get("unit", "")):
                    continue
                if a_unit in _HOURS and unit in _HOURS and float(a.get("value", -1)) * _HOURS[a_unit] == qty * _HOURS[unit]:
                    match = a
                    break
        seen.append({"text": m.group(0), "value": qty, "unit": unit, "business": business,
                     "supported_by": match.get("source") if match else None})
        if not match:
            findings.append(Finding("UNSUPPORTED_TIMELINE", "major", _sentence_around(text, m.start(), m.end())[:240],
                                    f"Timeline '{m.group(0)}' is not supported by the applicable policy or SLA.", ["CHP-POL-01:6.1"]))
    for m in deadline_re.finditer(text or ""):
        sentence = _sentence_around(text, m.start(), m.end())
        if safe_ctx.search(sentence):
            continue
        seen.append({"text": m.group(0), "value": None, "unit": "deadline", "supported_by": None})
        findings.append(Finding("UNSUPPORTED_DEADLINE", "major", sentence[:240],
                                f"Deadline '{m.group(0)}' is not supported by policy (DEL-POL-04 s5.1 / CHP-POL-01 s6.1).",
                                ["DEL-POL-04:5.1", "CHP-POL-01:6.1"]))
    return findings, seen


def response_elements(matrix: RuleMatrix, text: str, key_terms: list[str], complaint_ref: str) -> dict[str, bool]:
    rules = matrix.response_rules.get("required_elements") or []
    lower = (text or "").lower()
    present: dict[str, bool] = {}
    for r in rules:
        element = r["element"]
        if r.get("method") == "overlap":
            hits = sum(1 for t in key_terms if t and t.lower() in lower)
            present[element] = (complaint_ref.lower() in lower) or hits >= int(r.get("min_key_terms", 2))
        else:
            present[element] = any(re.search(p, text or "", re.I) for p in r.get("patterns", []))
    return present


def tone_findings(matrix: RuleMatrix, text: str, tone: str) -> list[Finding]:
    cfg = matrix.response_rules
    out: list[Finding] = []
    words = len((text or "").split())
    for rule in cfg.get("tone_rules") or []:
        if rule["tone"] not in ("*", tone):
            continue
        check = rule["check"]
        if check == "max_words" and words > int(rule["value"]):
            out.append(Finding(rule["rule_id"], rule["severity"], f"{words} words",
                               f"Response has {words} words; the limit for this tone is {rule['value']}.", rule.get("policy_refs", [])))
        elif check == "no_contractions" and re.search(cfg.get("contraction_pattern", r"$^"), text or "", re.I):
            out.append(Finding(rule["rule_id"], rule["severity"], re.search(cfg["contraction_pattern"], text, re.I).group(0),  # type: ignore[union-attr]
                               "Formal tone must not use contractions.", rule.get("policy_refs", [])))
        elif check == "formal_salutation" and not any(re.search(p, text or "", re.I | re.M) for p in cfg.get("formal_salutations", [])):
            out.append(Finding(rule["rule_id"], rule["severity"], (text or "")[:40], "Formal tone requires a formal salutation.",
                               rule.get("policy_refs", [])))
        elif check == "min_empathy_markers":
            markers = len(re.findall(r"\b(sorry|apologi[sz]e|apologies|understand|frustrat|inconvenien|appreciate|regret)", text or "", re.I))
            if markers < int(rule["value"]):
                out.append(Finding(rule["rule_id"], rule["severity"], f"{markers} empathy markers",
                                   "Empathetic tone needs clearer acknowledgement of the customer's experience.", rule.get("policy_refs", [])))
        elif check == "professional_language":
            for p in cfg.get("unprofessional_patterns", []):
                m = re.search(p, text or "", re.I)
                if m:
                    out.append(Finding(rule["rule_id"], rule["severity"], m.group(0), "Unprofessional language.",
                                       rule.get("policy_refs", [])))
                    break
    return out
