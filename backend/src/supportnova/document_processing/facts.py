"""Extract numeric policy facts from sections - used for conflict detection between documents
(SRS 1.8(10)) and for revised-policy impact analysis (SRS 1.8(4))."""

from __future__ import annotations

import difflib
import re
from dataclasses import asdict, dataclass
from typing import Any

from .parsers import ParsedSection

_DURATION = re.compile(r"\b(\d{1,4})\s*(business\s+days?|working\s+days?|calendar\s+days?|days?|hours?|months?|weeks?)\b", re.I)
_MONEY = re.compile(r"(?:\bUSD\s?|\$)(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{2}))?", re.I)
_PERCENT = re.compile(r"\b(\d{1,3})\s?(%|percent)\b", re.I)
_SENT = re.compile(r"(?<=[.!?])\s+")


@dataclass
class PolicyFact:
    section_id: str
    kind: str        # duration | money | percent | keyed
    value: float | str
    unit: str
    snippet: str
    key: str | None = None


def _norm_unit(unit: str) -> str:
    u = unit.lower().replace("working", "business")
    u = re.sub(r"\s+", "_", u)
    return u[:-1] if u.endswith("s") else u


def extract_facts(sections: list[ParsedSection], fact_keys: list[dict[str, Any]] | None = None) -> list[PolicyFact]:
    facts: list[PolicyFact] = []
    compiled = [(fk["key"], re.compile(fk["pattern"], re.I | re.S)) for fk in (fact_keys or [])]
    for section in sections:
        text = f"{section.heading}. {section.text}"
        for sentence in _SENT.split(section.text or ""):
            for m in _DURATION.finditer(sentence):
                facts.append(PolicyFact(section.section_id, "duration", float(m.group(1)), _norm_unit(m.group(2)),
                                        sentence.strip()[:240]))
            for m in _MONEY.finditer(sentence):
                amount = float(m.group(1).replace(",", "")) + (float("0." + m.group(2)) if m.group(2) else 0)
                facts.append(PolicyFact(section.section_id, "money", amount, "usd", sentence.strip()[:240]))
            for m in _PERCENT.finditer(sentence):
                facts.append(PolicyFact(section.section_id, "percent", float(m.group(1)), "percent", sentence.strip()[:240]))
        for key, pattern in compiled:
            for m in pattern.finditer(text):
                value = m.groupdict().get("value") or m.group(0)
                facts.append(PolicyFact(section.section_id, "keyed", value.strip().lower(), "", m.group(0)[:240], key))
    return facts


def facts_to_json(facts: list[PolicyFact]) -> list[dict[str, Any]]:
    return [asdict(f) for f in facts]


def diff_versions(old_sections: list[dict[str, Any]], new_sections: list[dict[str, Any]],
                  old_facts: list[dict[str, Any]], new_facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Section-by-section change list between two versions of the same document."""
    old_map = {s["section_id"]: s for s in old_sections}
    new_map = {s["section_id"]: s for s in new_sections}
    changes: list[dict[str, Any]] = []
    for sid in sorted(set(old_map) | set(new_map), key=lambda x: [int(p) if p.isdigit() else 0 for p in x.split(".")]):
        old, new = old_map.get(sid), new_map.get(sid)
        if old and not new:
            changes.append({"section_id": sid, "change": "removed", "heading": old["heading"]})
            continue
        if new and not old:
            changes.append({"section_id": sid, "change": "added", "heading": new["heading"]})
            continue
        assert old and new
        ratio = difflib.SequenceMatcher(None, old.get("text", ""), new.get("text", "")).ratio()
        of = sorted((f["kind"], f["unit"], f["value"]) for f in old_facts if f["section_id"] == sid and f["kind"] != "keyed")
        nf = sorted((f["kind"], f["unit"], f["value"]) for f in new_facts if f["section_id"] == sid and f["kind"] != "keyed")
        # a changed number (30 -> 21 days) is always a change, however similar the rest of the text is
        if ratio >= 0.995 and of == nf:
            continue
        removed = [x for x in of if x not in nf]
        added = [x for x in nf if x not in of]
        value_changes = []
        for r in removed:
            match = next((a for a in added if a[0] == r[0] and a[1] == r[1]), None)
            if match:
                value_changes.append({"kind": r[0], "unit": r[1], "old": r[2], "new": match[2]})
        changes.append({"section_id": sid, "change": "modified", "heading": new["heading"], "similarity": round(ratio, 3),
                        "value_changes": value_changes})
    return changes
