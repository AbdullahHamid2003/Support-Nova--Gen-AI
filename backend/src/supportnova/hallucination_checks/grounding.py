"""Traceability / hallucination checks (SRS Step 35): every important generated fact must be traceable
to the customer complaint, approved policy, the knowledge base or the rule matrix."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from supportnova.complaint_processing.text import content_tokens, stem

_POLICY_ID = re.compile(r"\b[A-Z]{3}-(?:POL|SOP|RUL|GDL|FAQ|TPL|COM)-\d{2}\b")
_REF_IDS = re.compile(r"\b(?:LMR-\d{6}|TXN-\d{8}|CMP-\d{5,})\b", re.IGNORECASE)
_AMOUNT = re.compile(r"(?:\$|usd\s?)\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?", re.IGNORECASE)

# Words that narrate what the customer did or felt, or point at a source. A model paraphrases them freely
# ("the customer strongly dislikes ..." for "I HATE it"), so they are not facts that need a source; the facts
# themselves (products, events, amounts, times) still have to be traceable.
_NARRATION = frozenset(stem(w) for w in (
    "customer customers client user complaint complains complained report reports reported state states stated say "
    "says said mention mentions mentioned request requests requested demand demands demanded ask asks asked want "
    "wants wanted claim claims claimed express expresses expressed describe describes described indicate indicates "
    "indicated note notes noted strongly very really dislike dislikes like likes hate hates love loves unhappy upset "
    "frustrated angry disappointed concern concerned issue issues problem problems relate relates related regarding "
    "per according policy policies section guideline guidelines procedure procedures sop rule rules document").split())


def normalize_value(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def overlap(statement: str, source: str, *, ignore: frozenset[str] = frozenset()) -> float:
    """Share of the statement's content tokens (minus ``ignore``) that also occur in the source."""
    stmt = {t for t in content_tokens(statement) if t not in ignore}
    if not stmt:
        return 1.0
    src = set(content_tokens(source))
    return len(stmt & src) / len(stmt)


@dataclass
class ClaimVerdict:
    statement: str
    source_type: str
    source_ref: str | None
    supported: bool
    support_score: float
    note: str


def verify_claims(claims: list[dict[str, Any]], *, complaint_text: str, evidence: dict[str, str],
                  facts_text: str, decision_text: str, policy_exists: Any) -> list[ClaimVerdict]:
    verdicts: list[ClaimVerdict] = []
    for c in claims:
        stmt, stype, sref = c.get("statement", ""), c.get("source_type", ""), c.get("source_ref")
        if stype == "complaint":
            score = overlap(stmt, complaint_text, ignore=_NARRATION)
            ok, note = score >= 0.5, "compared with the complaint text"
        elif stype == "policy":
            if sref and sref in evidence:
                score = overlap(stmt, evidence[sref], ignore=_NARRATION)
                ok, note = score >= 0.35, f"compared with evidence {sref}"
            elif sref and policy_exists(sref):
                score, ok, note = 0.5, True, f"{sref} exists in the knowledge base"
            else:
                score, ok, note = 0.0, False, f"source '{sref}' is not retrieved evidence or an existing policy"
        elif stype == "metadata":
            score = overlap(stmt, facts_text, ignore=_NARRATION)
            ok, note = score >= 0.4, "compared with verified system facts"
        elif stype in ("rule", "validated_decision"):
            score = overlap(stmt, decision_text + " " + complaint_text, ignore=_NARRATION)
            ok, note = score >= 0.35, "compared with the validated decision"
        else:
            score, ok, note = 0.0, False, "unknown source type"
        verdicts.append(ClaimVerdict(stmt, stype, sref, ok, round(score, 2), note))
    return verdicts


def ungrounded_entities(entities: list[dict[str, Any]], *, complaint_text: str, facts_text: str) -> list[dict[str, Any]]:
    """Entities whose value does not appear in the complaint or verified facts."""
    haystack = normalize_value(complaint_text + " " + facts_text)
    missing = []
    for e in entities:
        value = normalize_value(str(e.get("value", "")))
        if not value:
            continue
        if value in haystack:
            continue
        # paraphrased names: accept when most words appear
        if (e.get("type") in ("product", "service", "location", "person", "department", "other")
                and overlap(str(e.get("value")), complaint_text + " " + facts_text) >= 0.5):
            continue
        missing.append(e)
    return missing


def referenced_ids(text: str) -> list[str]:
    return sorted({m.group(0).upper() for m in _REF_IDS.finditer(text or "")})


def referenced_policy_ids(text: str) -> list[str]:
    return sorted(set(_POLICY_ID.findall(text or "")))


def amounts_in(text: str) -> list[float]:
    out = []
    for m in _AMOUNT.finditer(text or ""):
        out.append(float(m.group(1).replace(",", "")) + (float("0." + m.group(2)) if m.group(2) else 0.0))
    return out
