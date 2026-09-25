"""Offline stand-in for the GenAI provider - TEST SUITE ONLY, never part of the application.

The test suite must be deterministic and must not spend a paid API's credit, so every GenAI call in
the tests is answered by this class instead of OpenAI / Anthropic / Gemini. It is a black box like a
real model: it reads ONLY the rendered prompt text the pipeline sends (the reference data in the system
prompt, the evidence and the complaint in the user prompt) and returns JSON for the requested schema.
It never reads the Rule Matrix rules, so the Python validation pipeline stays independent of it.

Its answers are simple heuristics (word overlap with the taxonomy, a deliberately tone-sensitive urgency
guess, citations copied from the top evidence) - good enough to exercise every validation path.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from supportnova.complaint_processing.text import STOPWORDS, stem, tokenize
from supportnova.genai_pipeline.providers.base import AIProvider, AIRequest, AIResponse

ROOT = Path(__file__).resolve().parents[2]

_SYNONYMS = {
    "arriv": ["deliver"], "late": ["delay"], "tracking": ["deliver", "shipment"], "parcel": ["package"],
    "charg": ["bill", "charge"], "money": ["refund"], "reimburs": ["refund"], "hack": ["unauthor", "access"],
    "smok": ["fire", "overheat"], "burn": ["fire", "overheat"], "hot": ["overheat"], "spark": ["electr"],
    "shock": ["electr"], "hurt": ["injur"], "rude": ["unprofession"], "technician": ["install"],
    "password": ["login"], "log": ["login"], "wifi": ["connect"], "offline": ["connect"], "crash": ["app"],
    "subscript": ["renew"], "footag": ["data", "privacy"], "unsubscrib": ["market", "consent"],
    "warranti": ["warranti", "claim"], "broken": ["damag", "malfunct"], "crack": ["damag"],
}
_NEG = {"angry", "furious", "terrible", "worst", "ridiculous", "unacceptable", "awful", "horrible", "disgusted",
        "useless", "pathetic", "joke", "scam", "outraged", "livid", "disappointed", "frustrated", "fed"}
_CRITICAL = ("fire", "smoke", "burn", "spark", "shock", "injur", "hospital", "hacked", "unauthori", "unlocked",
             "breach", "leak", "stranger")
_URGENT_WORDS = ("urgent", "asap", "immediately", "right now", "today")
_GREETING_LINE = re.compile(r"^(dear|hi|hello|hey|to whom it may concern|good (morning|afternoon|evening))\b(\s+[\w.'&-]+){0,4}\s*[,.!]?$", re.I)
_SIGN_OFF_LINE = re.compile(r"^((warm|kind|best|many)\s+)?(regards|wishes|thanks)\b|^(thank you|cheers|sincerely|yours)\b.{0,30}$", re.I)
_GREETING_LEAD = re.compile(r"^(good (morning|afternoon|evening)|hi( there| team)?|hello( there| team)?)[,.!]\s*", re.I)
_SIGN_OFF_TAIL = re.compile(r"\s*\b(many thanks|thanks|thank you|cheers|regards)[.!]?\s*$", re.I)
_SUBJECT_LINE = re.compile(r"^(re|fwd?|subject)\s*:", re.I)
_FLAG_MARK = re.compile(r"\[\[/?FLAGGED-CUSTOMER-TEXT[^\]]*\]\]")
_ESCALATION_ACTIONS = {"Critical Management Escalation": "ESCALATE_CRITICAL_MANAGEMENT", "Specialist Team": "ESCALATE_SPECIALIST_TEAM",
                       "Compliance Review": "ESCALATE_COMPLIANCE", "Department Manager": "ESCALATE_DEPARTMENT_MANAGER",
                       "Supervisor Review": "ESCALATE_SUPERVISOR"}


# ------------------------------------------------------------------ text helpers
def _stems(text: str) -> list[str]:
    out: list[str] = []
    for tok in tokenize(text):
        if tok in STOPWORDS or len(tok) < 3:
            continue
        s = stem(tok)
        out.append(s)
        out.extend(_SYNONYMS.get(s, []))
    return out


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if len(s.strip()) > 3]


def _body(text: str) -> str:
    """The complaint without its salutation and sign-off - what an extractive summary draws on."""
    lines = [ln.strip() for ln in (text or "").splitlines()]
    while lines and (not lines[0] or _GREETING_LINE.match(lines[0]) or _SUBJECT_LINE.match(lines[0])):
        lines.pop(0)
    for i, ln in enumerate(lines):
        if _SIGN_OFF_LINE.match(ln):
            lines = lines[:i]
            break
    body = _SIGN_OFF_TAIL.sub("", _GREETING_LEAD.sub("", " ".join(ln for ln in lines if ln)))
    return body or (text or "")


@lru_cache(maxsize=1)
def _product_aliases() -> tuple[str, ...]:
    data = yaml.safe_load((ROOT / "config" / "products.yaml").read_text(encoding="utf-8"))
    items = data.get("products", data) if isinstance(data, dict) else data
    return tuple(sorted({a.strip() for p in items for a in p.get("aliases", []) if len(a.strip()) > 2 and " " not in a.strip()},
                        key=len, reverse=True))


def _without_product_names(text: str) -> str:
    """One-word product names written as proper nouns ("my Spark stopped") are names, not symptoms."""
    for name in _product_aliases():
        text = re.sub(rf"\b{re.escape(name[:1].upper() + name[1:].lower())}\b", " ", text)
    return text


# ------------------------------------------------------------------ prompt parsing
def _tag(text: str, name: str) -> str:
    m = re.search(rf"<{name}>\n?(.*?)\n?</{name}>", text, re.S)
    return m.group(1) if m else ""


def _complaint(user: str) -> tuple[str, dict[str, str], str]:
    m = re.search(r'<complaint_(\w+) id="([^"]*)">\n?(.*?)\n?</complaint_\1>', user, re.S)
    if not m:
        return "", {}, ""
    block = m.group(3)
    head, _, text = block.partition("Complaint text:\n")
    fields = {k.strip(): v.strip() for k, _, v in (ln.partition(":") for ln in head.splitlines() if ":" in ln)}
    return m.group(2), fields, text


def _field(fields: dict[str, str], prefix: str) -> str:
    value = next((v for k, v in fields.items() if k.startswith(prefix)), "")
    return "" if value in ("(not provided)", "none") else value


def _taxonomy(system: str) -> list[dict[str, str]]:
    rx = re.compile(r"^subcategory (\S+) \(category (\S+) - (.+?)\): (.+?) - (.*)$")
    return [{"code": m[1], "category": m[2], "category_name": m[3], "name": m[4], "description": m[5]}
            for m in (rx.match(ln) for ln in _tag(system, "taxonomy").splitlines()) if m]


def _departments(system: str) -> list[dict[str, str]]:
    rx = re.compile(r"^(\S+) \| ([^:]+): (.*)$")
    return [{"code": m[1], "name": m[2], "description": m[3]}
            for m in (rx.match(ln) for ln in _tag(system, "departments").splitlines()) if m]


def _actions(system: str) -> list[dict[str, str]]:
    rx = re.compile(r"^([A-Z0-9_]+): (.*)$")
    return [{"code": m[1], "name": m[2]} for m in (rx.match(ln) for ln in _tag(system, "action_catalog").splitlines()) if m]


def _priority(system: str) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    guide = _tag(system, "urgency_and_priority")
    matrix: dict[str, dict[str, str]] = {}
    for m in re.finditer(r"^- (\w+): (.+)$", guide, re.M):
        matrix[m[1]] = {i: p for i, p in re.findall(r"(\w+) impact -> (P\d)", m[2])}
    definitions = {m[1]: m[2] for m in re.finditer(r"^\[SLA-RUL-15 s5\.\d (Critical|High|Medium|Low)\] (.*)$", guide, re.M)}
    return matrix, definitions


def _evidence(user: str) -> list[dict[str, str]]:
    rx = re.compile(r'<item id="([^"]+)" policy_id="([^"]+)" title="[^"]*" version="[^"]*" type="([^"]*)" status="[^"]*" '
                    r'section="([^"]*)" heading="([^"]*)"[^>]*>\n(.*?)\n</item>', re.S)
    return [{"evidence_id": m[1], "doc_id": m[2], "doc_type": m[3], "section_id": m[4], "heading": m[5], "text": m[6]}
            for m in rx.finditer(_tag(user, "evidence"))]


# ------------------------------------------------------------------ the stand-in
class OfflineLLM(AIProvider):
    name = "offline-test-llm"

    def __init__(self) -> None:
        super().__init__("offline-test-llm-1")

    def generate(self, request: AIRequest) -> AIResponse:
        payload = self._analysis(request) if request.stage == "analysis" else self._communication(request)
        text = json.dumps(payload)
        return AIResponse(text=text, provider=self.name, model=self.model, latency_ms=1,
                          input_tokens=len(request.system.split()) + len(request.user.split()),
                          output_tokens=len(text.split()), stop_reason="end_turn")

    # ---------------------------------------------------------------- analysis
    def _analysis(self, request: AIRequest) -> dict[str, Any]:
        complaint_id, fields, raw = _complaint(request.user)
        flagged = "[[FLAGGED-CUSTOMER-TEXT" in raw
        clean = _FLAG_MARK.sub("", raw)
        lines = clean.splitlines()
        title = _field(fields, "Title")
        description = "\n".join(lines[1:]) if lines and lines[0].strip() == title.strip() else clean
        order_ref = _field(fields, "Order reference")
        product_text = _field(fields, "Product/service")
        text = clean
        lower = text.lower()
        words = Counter(_stems(_without_product_names(text) + " " + _without_product_names(title)))

        taxonomy = _taxonomy(request.system)
        departments = _departments(request.system)
        actions = _actions(request.system)
        priority_matrix, urgency_definitions = _priority(request.system)
        evidence = _evidence(request.user)

        docs = {t["code"]: Counter(_stems(f"{t['name']} {t['name']} {t['description']} {t['category_name']}")) for t in taxonomy}
        df: Counter[str] = Counter()
        for c in docs.values():
            df.update(set(c))
        n = max(len(docs), 1)
        scores = {code: sum(math.log(1 + n / df[t]) * min(words[t], 3) for t in c if t in words) for code, c in docs.items()}
        ranked = sorted(taxonomy, key=lambda t: -scores.get(t["code"], 0.0))
        primary = ranked[0] if ranked else {"code": "", "name": "Unclassified", "category": "", "category_name": "", "description": ""}
        secondary = [t for t in ranked[1:4] if scores.get(t["code"], 0) >= 0.6 * max(scores.get(primary["code"], 0), 1e-9)
                     and t["category"] != primary["category"] and scores.get(t["code"], 0) > 2][:1]

        neg = sum(1 for w in tokenize(lower) if w in _NEG) + max(0, text.count("!") - 1) + len(re.findall(r"\b[A-Z]{4,}\b", text)) // 2
        sentiment = "Strongly Negative" if neg >= 4 else "Negative" if neg >= 1 else (
            "Positive" if "thank" in lower and neg == 0 and "not" not in lower else "Neutral")
        policy_level = self._policy_urgency(urgency_definitions, primary, words)
        if any(k in lower for k in _CRITICAL):
            urgency, impact = "Critical", "High"
        elif sentiment == "Strongly Negative" or any(k in lower for k in _URGENT_WORDS):
            urgency, impact = "High", "Medium"          # deliberately tone-driven: the validator must catch it
        elif policy_level:
            urgency, impact = policy_level, "Medium" if policy_level in ("High", "Medium") else "Low"
        elif sentiment == "Negative":
            urgency, impact = "Medium", "Medium"
        else:
            urgency, impact = "Medium", "Low"
        priority = (priority_matrix.get(urgency) or {}).get(impact, "P2")

        cat_words = Counter(_stems(f"{primary['category_name']} {primary['name']} {primary.get('description', '')}"))
        dept = max(departments, key=lambda d: sum(min(cat_words[t], 2) for t in set(_stems(d["name"] + " " + d["description"]))),
                   default={"code": ""})
        supporting: list[str] = []
        for s in secondary:
            sw = Counter(_stems(f"{s['category_name']} {s['name']}"))
            d2 = max(departments, key=lambda d: sum(min(sw[t], 2) for t in set(_stems(d["name"] + " " + d["description"]))),
                     default=None)
            if d2 and d2["code"] != dept["code"]:
                supporting.append(d2["code"])

        cited = [e for e in evidence if e.get("doc_type") in ("policy", "rules", "sop")][:3] or evidence[:2]
        citations = [{"policy_id": e["doc_id"], "section": e["section_id"], "evidence_id": e["evidence_id"],
                      "applicability": "Applicable" if i < 2 else "Conditionally Applicable",
                      "reason": f"Retrieved section '{e['heading']}' matches the complaint topic."} for i, e in enumerate(cited)]

        evidence_words = Counter(_stems(" ".join(e["text"] for e in evidence[:4])))
        action_df: Counter[str] = Counter()
        for a in actions:
            action_df.update(set(_stems(a["name"])))
        n_actions = max(len(actions), 1)

        def action_score(a: dict[str, str]) -> float:
            toks = set(_stems(a["name"]))
            total = sum(math.log(1 + n_actions / action_df[t]) * (1.6 * min(evidence_words[t], 2) + 0.6 * min(words[t], 2)) for t in toks)
            return total / max(1, len(toks) ** 0.5)
        money = re.compile(r"CREDIT|VOUCHER|COMPENSAT|GOODWILL|REFUND")
        ranked_actions = sorted((a for a in actions if not a["code"].startswith("ESCALATE_") and not money.search(a["code"])),
                                key=lambda a: -action_score(a))
        top_score = action_score(ranked_actions[0]) if ranked_actions else 0.0
        chosen = [a for a in ranked_actions[:5] if action_score(a) >= 0.45 * top_score][:4]
        by_code = {a["code"]: a for a in actions}
        defaults = []
        if re.search(r"\bLMR-\d{6}\b", text, re.I) or order_ref:
            defaults.append("VERIFY_ORDER")
        if re.search(r"\bTXN-\d{8}\b", text, re.I) or re.search(r"\bcharg|\bbilled|\bpayment", lower):
            defaults.append("CHECK_TRANSACTION")
        if primary.get("category") == "TEC":
            defaults.append("REMOTE_TROUBLESHOOTING")
        if primary.get("category") == "ACC":
            defaults.append("VERIFY_ACCOUNT")
        if re.search(r"refund", lower) and re.search(r"still|waiting|not (yet )?(received|arrived)|late|where is", lower):
            defaults.append("CHECK_REFUND_STATUS")
        for code in defaults:
            if code in by_code and all(a["code"] != code for a in chosen):
                chosen.insert(0, by_code[code])
        steps = [{"action_code": a["code"], "description": a["name"],
                  "policy_ref": f"{cited[0]['doc_id']}:{cited[0]['section_id']}" if cited else None} for a in chosen[:5]]

        order_refs = re.findall(r"\bLMR-\d{6}\b", text, re.I)
        amounts = re.findall(r"(?:\$|usd\s?)\s?\d+(?:\.\d{2})?", text, re.I)
        entities = [{"type": "order_id", "value": o} for o in order_refs] + [{"type": "amount", "value": a} for a in amounts[:3]]
        if product_text:
            entities.append({"type": "product", "value": product_text})

        wants_refund = bool(re.search(r"refund|money back", lower))
        wants_replacement = bool(re.search(r"replace|new one|exchange", lower))
        wants_comp = bool(re.search(r"compensat|voucher|credit|free month", lower))

        def elig(flag: bool) -> dict[str, Any]:
            return {"status": "requires_verification" if flag else "not_applicable",
                    "reason": "Needs verification against policy." if flag else "Not requested.", "policy_ref": None}

        legal = bool(re.search(r"lawyer|legal action|sue\b|court|regulator", lower))
        dept_codes = {d["code"] for d in departments}
        for needed, flag in (("DEPT-BIL", wants_refund or wants_comp or "charg" in words), ("DEPT-CMP", legal)):
            if flag and needed in dept_codes and needed != dept["code"] and needed not in supporting:
                supporting.append(needed)
        level = ("Critical Management Escalation" if urgency == "Critical" and re.search(r"fire|injur|hospital", lower)
                 else "Specialist Team" if urgency == "Critical" else "Compliance Review" if legal else "No Escalation")
        escalate = level != "No Escalation"
        if _ESCALATION_ACTIONS.get(level) in by_code:
            steps.append({"action_code": _ESCALATION_ACTIONS[level], "description": f"Escalate: {level}", "policy_ref": None})
        summary_src = _sentences(_body(description)) or [title]
        summary = " ".join(summary_src[:2])[:400]
        missing, questions = [], []
        if not order_refs and not order_ref and primary["category"] in ("PRD", "DEL", "REF", "WAR"):
            missing.append({"field": "order_reference", "reason": "No order reference was provided."})
            questions.append("Could you share the order reference (format LMR-######) for this purchase?")
        return {
            "schema_version": "1.0", "complaint_id": complaint_id, "summary": summary,
            "key_facts": [s[:200] for s in summary_src[:3]],
            "primary_issue": {"label": primary["name"], "category": primary["category"], "subcategory": primary["code"],
                              "evidence_quote": summary_src[0][:200] if summary_src else None},
            "secondary_issues": [{"label": s["name"], "category": s["category"], "subcategory": s["code"], "evidence_quote": None}
                                 for s in secondary],
            "issue_category": primary["category"], "subcategory": primary["code"], "sentiment": sentiment,
            "emotion_indicators": ["Anger"] if sentiment == "Strongly Negative" else ["Frustration"] if sentiment == "Negative" else [],
            "urgency": urgency, "urgency_rationale": "Keyword and tone heuristic.", "impact": impact, "priority": priority,
            "entities": entities, "department": dept["code"], "supporting_departments": supporting,
            "policy_references": citations,
            "policy_id": citations[0]["policy_id"] if citations else None,
            "policy_section": citations[0]["section"] if citations else None,
            "resolution_steps": steps,
            "refund_eligibility": elig(wants_refund), "replacement_eligibility": elig(wants_replacement),
            "compensation_eligibility": {"status": "requires_verification" if wants_comp else "not_applicable",
                                         "type": "store_credit" if wants_comp else None, "amount_usd": None,
                                         "reason": "Needs verification against policy." if wants_comp else "Not requested.",
                                         "policy_ref": None},
            "escalation_required": escalate, "escalation_level": level,
            "escalation_reason": "Risk keywords detected." if escalate else None,
            "escalation_notes": ({"summary": summary, "key_facts": [s[:160] for s in summary_src[:2]],
                                  "reason": "Risk keywords detected.", "actions_taken": ["Complaint analysed"],
                                  "relevant_policy": [f"{c['policy_id']}:{c['section']}" for c in citations[:2]],
                                  "required_next_action": "Specialist review of the complaint."} if escalate else None),
            "response_type": "Apology and Resolution Update", "follow_up_required": True,
            "follow_up_type": "Request for additional information" if missing else "Resolution confirmation",
            "missing_information": missing, "clarification_questions": questions,
            "agent_guidance": ["Verify the customer and order details before confirming any outcome.",
                               "Do not promise a refund or compensation before verification."],
            "claims": [{"statement": summary[:200], "source_type": "complaint", "source_ref": "complaint"}]
                      + ([{"statement": cited[0]["text"][:160], "source_type": "policy", "source_ref": cited[0]["evidence_id"]}]
                         if cited else []),
            "manipulation_detected": flagged,
            "manipulation_notes": "Security screening flagged instruction-like text." if flagged else None,
        }

    @staticmethod
    def _policy_urgency(definitions: dict[str, str], primary: dict[str, Any], words: Counter[str]) -> str | None:
        target = Counter(_stems(f"{primary.get('name', '')} {primary.get('category_name', '')}"))
        best, best_score = None, 0.0
        for level, text in definitions.items():
            d = set(_stems(text))
            score = sum(1.0 for t in target if t in d) + 0.2 * sum(1 for t in words if t in d and words[t] > 1)
            if score > best_score:
                best, best_score = level, score
        return best if best_score >= 1.0 else None

    # ---------------------------------------------------------------- communication
    def _communication(self, request: AIRequest) -> dict[str, Any]:
        user = request.user
        complaint_id, fields, raw = _complaint(user)
        tone = _tag(user, "tone").strip() or "professional"
        name = _tag(user, "customer_name").strip() or "Customer"
        try:
            d = json.loads(_tag(user, "validated_decision"))
        except ValueError:
            d = {}
        timelines = [ln[2:].split(" (")[0] for ln in _tag(user, "supported_timelines").splitlines()
                     if ln.startswith("- ") and not ln.startswith(("- First response target", "- Resolution target", "- (no timelines"))][:1]
        questions = [ln[2:] for ln in _tag(user, "clarification_questions").splitlines() if ln.startswith("- ") and ln != "- none"]
        follow = _tag(user, "follow_up").strip()
        refund_requested = "refund" in _field(fields, "Requested resolution").lower() or "refund" in raw.lower()
        issue = (d.get("issue") or "your issue").lower()
        formal = tone == "formal"
        lines = [f"Dear {name}," if formal or tone == "professional" else f"Hello {name},", ""]
        lines.append(f"Thank you for contacting Lumora about complaint {complaint_id}. We have reviewed your report regarding {issue}.")
        if tone in ("empathetic", "professional"):
            lines.append("We are sorry for the inconvenience this has caused and we understand how frustrating it is.")
        elif formal:
            lines.append("We regret the inconvenience this matter has caused.")
        if d.get("safety_issue"):
            lines.append("For your safety, please stop using the product and disconnect it from power only if it is safe to do so. "
                         "Please do not post or courier the device; our Product Safety team will arrange a safe collection.")
        for step in (d.get("next_steps_for_customer") or [])[:3]:
            lines.append(f"Next step: {step}.")
        elig = d.get("eligibility") or {}
        if elig.get("refund") == "eligible":
            lines.append("Based on our records you qualify for a refund, which will be processed once the verification steps above are complete.")
        elif elig.get("refund") == "requires_verification":
            lines.append("Your refund request will be assessed once we have verified the details of your order.")
        elif elig.get("refund") == "not_eligible" and refund_requested:
            lines.append("Unfortunately the refund you requested is not available under our refund policy.")
        if elig.get("compensation") == "eligible" and elig.get("compensation_amount_usd"):
            lines.append(f"Your order qualifies for a USD {elig['compensation_amount_usd']:.0f} store credit under our policy, applied after verification.")
        if timelines:
            lines.append(f"Timeline: {timelines[0]}.")
        if questions:
            lines.append("To help us resolve this, please reply with:")
            lines.extend(f"- {q}" for q in questions[:3])
        if d.get("escalated"):
            lines.append("Your case has been passed to a specialist team for priority review, and they will contact you.")
        lines += ["", "Yours sincerely," if formal else "Kind regards,", "Lumora Customer Care"]
        body = "\n".join(lines)
        if tone == "concise":
            keep = [lines[0], lines[2], *[ln for ln in lines if ln.startswith(("Next step", "- ", "Timeline"))][:3], "Lumora Customer Care"]
            body = "\n".join(keep)
        follow_type = follow.split(" due in ")[0] if follow and follow != "none" else None
        return {
            "schema_version": "1.0", "complaint_id": complaint_id, "tone": tone,
            "subject": f"Update on your complaint {complaint_id}", "customer_response": body,
            "follow_up_message": (f"Hello {name}, this is a follow-up on complaint {complaint_id}: {follow_type}." if follow_type else None),
            "claims": [{"statement": f"Complaint {complaint_id} concerns {issue}.", "source_type": "validated_decision",
                        "source_ref": "validated_decision"}],
        }
