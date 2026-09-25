"""Deterministic perception for the Python Ground-Truth Pipeline: signals, entities,
rule-based classification and lexicon sentiment. Everything is driven by the Rule
Matrix configuration (signals.yaml, category_rules.yaml, products.yaml)."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any

from supportnova.rule_engine.models import RuleMatrix

from .text import find_phrase, phrase_regex

# ============================== signals =====================================


@dataclass
class SignalHit:
    name: str
    label: str
    evidence: list[str]


def detect_signals(matrix: RuleMatrix, text: str) -> dict[str, SignalHit]:
    lower = (text or "").lower()
    cues = frozenset(matrix.negation_cues)
    hits: dict[str, SignalHit] = {}
    for name, sig in matrix.signals.items():
        evidence: list[str] = []
        for term in sig.terms:
            for start, end in find_phrase(lower, term, cues, matrix.negation_window):
                evidence.append(text[start:end])
                break
        for pattern in sig.patterns:
            m = pattern.search(text or "")
            if m:
                evidence.append(m.group(0)[:80])
        if evidence:
            hits[name] = SignalHit(name, sig.label, sorted(set(evidence))[:6])
    return hits


# ============================== entities ====================================

_ORDER = re.compile(r"\bLMR-\d{6}\b", re.IGNORECASE)
_ORDER_LOOSE = re.compile(r"\border\s*(?:number|no\.?|#|ref(?:erence)?)?\s*[:#]?\s*(?:LMR-?)?(\d{6})\b", re.IGNORECASE)
_TXN = re.compile(r"\bTXN-\d{8}\b", re.IGNORECASE)
_CMP = re.compile(r"\bCMP-\d{5,}\b", re.IGNORECASE)
_AMOUNT = re.compile(r"(?:(?:\$|usd\s?)\s?(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?)|(?:\b(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d{1,2}))?\s?(?:usd|dollars)\b)",
                     re.IGNORECASE)
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_ISO = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_DATE_DM = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?:,?\s+(20\d{2}))?\b",
                      re.IGNORECASE)
_DATE_MD = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d{2}))?\b",
                      re.IGNORECASE)
_DATE_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b")
_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                 "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fourteen": 14, "fifteen": 15, "twenty": 20,
                 "thirty": 30, "several": 3, "few": 3, "couple": 2}
_DURATION = re.compile(r"\b(\d{1,3}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fourteen|fifteen|twenty|thirty|several|few|couple(?:\s+of)?)"
                       r"\s+(?:more\s+|full\s+|whole\s+|business\s+|working\s+|calendar\s+)?(hours?|days?|weeks?|months?)\b", re.IGNORECASE)
_ELAPSED_CONTEXT = re.compile(r"^\s*(ago|since|later|now|already|past|late|overdue|without|and\s+still|of\s+waiting)", re.IGNORECASE)
_OUTAGE_CONTEXT = re.compile(r"(outage|down|offline|unavailable|not\s+recording|no\s+recordings|couldn'?t\s+access|cannot\s+access|can'?t\s+access)",
                             re.IGNORECASE)
_UNIT_DAYS = {"hour": 1 / 24, "day": 1, "week": 7, "month": 30}


@dataclass
class Entity:
    type: str
    value: str
    normalized: Any = None
    start: int = 0
    end: int = 0


@dataclass
class EntityResult:
    entities: list[Entity] = field(default_factory=list)
    order_refs: list[str] = field(default_factory=list)
    transaction_refs: list[str] = field(default_factory=list)
    complaint_refs: list[str] = field(default_factory=list)
    amounts: list[float] = field(default_factory=list)
    dates: list[str] = field(default_factory=list)
    product_skus: list[str] = field(default_factory=list)
    max_elapsed_days: float | None = None
    outage_hours: float | None = None
    requested_compensation_amount: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _num(token: str) -> float:
    token = token.lower().replace("couple of", "couple").strip()
    return float(_NUMBER_WORDS.get(token, token)) if not token.isdigit() else float(token)


def _mk_date(year: int | None, month: int, day: int, ref: date) -> date | None:
    try:
        candidate = date(year or ref.year, month, day)
    except ValueError:
        return None
    if year is None and candidate > ref + timedelta(days=31):
        candidate = date(candidate.year - 1, month, day)
    return candidate


def extract_entities(matrix: RuleMatrix, text: str, *, reference_date: date | None = None) -> EntityResult:
    ref = reference_date or date.today()
    out = EntityResult()
    body = text or ""
    lower = body.lower()

    def add(kind: str, m: re.Match[str], normalized: Any = None, value: str | None = None) -> None:
        out.entities.append(Entity(kind, value or m.group(0), normalized, m.start(), m.end()))

    for m in _ORDER.finditer(body):
        ref_id = m.group(0).upper()
        if ref_id not in out.order_refs:
            out.order_refs.append(ref_id)
            add("order_id", m, ref_id)
    for m in _ORDER_LOOSE.finditer(body):
        ref_id = f"LMR-{m.group(1)}"
        if ref_id not in out.order_refs:
            out.order_refs.append(ref_id)
            add("order_id", m, ref_id)
    for m in _TXN.finditer(body):
        out.transaction_refs.append(m.group(0).upper())
        add("transaction_id", m, m.group(0).upper())
    for m in _CMP.finditer(body):
        out.complaint_refs.append(m.group(0).upper())
        add("complaint_reference", m, m.group(0).upper())
    for m in _AMOUNT.finditer(body):
        whole = m.group(1) or m.group(3)
        cents = m.group(2) or m.group(4)
        if not whole:
            continue
        amount = float(whole.replace(",", "")) + (float(f"0.{cents}") if cents else 0.0)
        # ignore obvious non-amount numbers attached to identifiers
        if body[max(0, m.start() - 4):m.start()].upper().endswith(("LMR-", "TXN-", "CMP-")):
            continue
        out.amounts.append(amount)
        add("amount", m, amount)
        # compensation association: keyword right after the amount (before any other amount) or just before it
        nxt = _AMOUNT.search(body, m.end())
        after = lower[m.end():min(m.end() + 35, nxt.start() if nxt else len(lower))]
        before = lower[max(0, m.start() - 30):m.start()]
        comp_kw = r"compensat|credit|voucher|goodwill|for\s+(my|the)\s+(trouble|inconvenience|time)"
        if re.search(r"^\W*(\w+\W+){0,3}?(" + comp_kw + r")", after) or re.search(r"(" + comp_kw + r"|pay\s+me)\W+(of\W+)?$", before):
            out.requested_compensation_amount = max(out.requested_compensation_amount or 0.0, amount)
    for m in _DATE_ISO.finditer(body):
        d = _mk_date(int(m.group(1)), int(m.group(2)), int(m.group(3)), ref)
        if d:
            out.dates.append(d.isoformat())
            add("date", m, d.isoformat())
    for m in _DATE_DM.finditer(body):
        d = _mk_date(int(m.group(3)) if m.group(3) else None, _MONTHS[m.group(2)[:3].lower()], int(m.group(1)), ref)
        if d:
            out.dates.append(d.isoformat())
            add("date", m, d.isoformat())
    for m in _DATE_MD.finditer(body):
        d = _mk_date(int(m.group(3)) if m.group(3) else None, _MONTHS[m.group(1)[:3].lower()], int(m.group(2)), ref)
        if d and d.isoformat() not in out.dates:
            out.dates.append(d.isoformat())
            add("date", m, d.isoformat())
    for m in _DATE_NUM.finditer(body):
        d = _mk_date(int(m.group(3)), int(m.group(2)), int(m.group(1)), ref)
        if d:
            out.dates.append(d.isoformat())
            add("date", m, d.isoformat())
    for m in _DURATION.finditer(body):
        qty = _num(m.group(1).split()[0] if m.group(1).lower().startswith("couple") else m.group(1))
        unit = m.group(2).lower().rstrip("s")
        days = qty * _UNIT_DAYS.get(unit, 1)
        after = body[m.end():m.end() + 20]
        before = body[max(0, m.start() - 20):m.start()].lower()
        if _ELAPSED_CONTEXT.search(after) or re.search(r"(over|more\s+than|almost|nearly|for|waited|waiting)\s*$", before):
            out.max_elapsed_days = max(out.max_elapsed_days or 0.0, days)
        window = lower[max(0, m.start() - 80):m.end() + 80]
        if _OUTAGE_CONTEXT.search(window):
            out.outage_hours = max(out.outage_hours or 0.0, days * 24)
        add("duration", m, round(days, 3))
    if out.dates:
        for iso in out.dates:
            elapsed = (ref - date.fromisoformat(iso)).days
            if 0 <= elapsed <= 400:
                out.max_elapsed_days = max(out.max_elapsed_days or 0.0, float(elapsed))
    # products: longest alias first to avoid "lock" swallowing "smart lock"
    aliases: list[tuple[str, str]] = []
    for sku, product in matrix.products.items():
        for alias in (product.name.lower(), *product.aliases):
            aliases.append((alias.lower(), sku))
    aliases.sort(key=lambda a: -len(a[0]))
    taken: list[tuple[int, int]] = []
    for alias, sku in aliases:
        for m in phrase_regex(alias).finditer(lower):
            if any(s <= m.start() < e or s < m.end() <= e for s, e in taken):
                continue
            taken.append((m.start(), m.end()))
            if sku not in out.product_skus:
                out.product_skus.append(sku)
            kind = "service" if matrix.products[sku].type in ("subscription", "service", "software") else "product"
            # one entity per product: adjacent aliases of the same SKU ("Spark" + "Smart Plug") form one mention
            same = next((x for x in out.entities if x.type == kind and x.normalized == sku), None)
            if same is None:
                out.entities.append(Entity(kind, body[m.start():m.end()], sku, m.start(), m.end()))
            elif m.start() - same.end in (0, 1) or same.start - m.end() in (0, 1):
                same.start, same.end = min(same.start, m.start()), max(same.end, m.end())
                same.value = body[same.start:same.end]
    return out


# ============================== classification ===============================


@dataclass
class ClassificationCandidate:
    subcategory: str
    category: str
    score: float
    matched: list[str]


@dataclass
class ClassificationResult:
    primary: str | None
    primary_category: str | None
    score: float
    secondary: list[str]
    candidates: list[ClassificationCandidate]
    ambiguous: bool
    confidence: str  # high | medium | low | none
    precedence_applied: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify(matrix: RuleMatrix, title: str, body: str, signals: set[str], product_skus: list[str]) -> ClassificationResult:
    settings = matrix.category_settings
    title_mult = settings.get("title_multiplier", 1.3)
    lower_title, lower_body = (title or "").lower(), (body or "").lower()
    cues = frozenset(matrix.negation_cues)
    candidates: list[ClassificationCandidate] = []
    for sub_code, rule in matrix.category_rules.items():
        sub = matrix.subcategories.get(sub_code)
        if not sub or not sub.is_active:
            continue
        score = 0.0
        matched: list[str] = []
        # longest terms first; a shorter term only scores where it is not part of a longer matched term
        # ("still has not arrived" must not also score "has not arrived" and "not arrived")
        covered_t: list[tuple[int, int]] = []
        covered_b: list[tuple[int, int]] = []
        for term, weight in sorted(rule.terms.items(), key=lambda kv: -len(kv[0])):
            hits_t = find_phrase(lower_title, term, cues, matrix.negation_window)
            hits_b = find_phrase(lower_body, term, cues, matrix.negation_window)
            new_t = [h for h in hits_t if not any(s <= h[0] and h[1] <= e for s, e in covered_t)]
            new_b = [h for h in hits_b if not any(s <= h[0] and h[1] <= e for s, e in covered_b)]
            covered_t.extend(hits_t)
            covered_b.extend(hits_b)
            if new_t or new_b:
                score += weight * (title_mult if new_t else 1.0)
                matched.append(term)
        for term, weight in rule.negative.items():
            if find_phrase(lower_title + " " + lower_body, term):
                score -= weight
        for sig, weight in rule.signal_boosts.items():
            if sig in signals:
                score += weight
                matched.append(f"signal:{sig}")
        for sku, weight in rule.product_boosts.items():
            if sku in product_skus:
                score += weight
                matched.append(f"product:{sku}")
        if score > 0:
            candidates.append(ClassificationCandidate(sub_code, sub.category, round(score, 2), matched))
    candidates.sort(key=lambda c: (-c.score, c.subcategory))
    min_score = settings.get("min_score", 3.0)
    if not candidates or candidates[0].score < min_score:
        return ClassificationResult(candidates[0].subcategory if candidates else None,
                                    candidates[0].category if candidates else None,
                                    candidates[0].score if candidates else 0.0, [], candidates[:6], True, "none")
    top = candidates[0]
    primary = top
    precedence_applied = None
    # risk-first precedence (RTE-RUL-14 s5 / CHP-POL-01 s3.2)
    order = list(matrix.routing_precedence)

    def group_rank(c: ClassificationCandidate) -> int:
        for i, key in enumerate(order):
            if key in (c.subcategory, c.category):
                return i
        return len(order)

    prec_min = settings.get("precedence_min_score", 4.0)
    # risk groups (safety, account security, privacy) always win when detected; lower-precedence groups
    # (billing > product > delivery > warranty) must also carry a fair share of the evidence
    absolute_groups = int(settings.get("absolute_precedence_groups", 3))
    prec_ratio = settings.get("precedence_ratio", 0.0)
    for c in candidates[1:]:
        if (c.score >= prec_min and group_rank(c) < group_rank(primary)
                and (group_rank(c) < absolute_groups or c.score >= prec_ratio * top.score)):
            primary = c
    if primary is not top:
        precedence_applied = f"{primary.subcategory} outranks {top.subcategory} by risk precedence (RTE-RUL-14:5)"
    sec_min = settings.get("secondary_min_score", 4.0)
    ratio = settings.get("secondary_ratio", 0.35)
    secondary: list[str] = []
    for c in candidates:
        if c is primary or len(secondary) >= int(settings.get("max_secondary", 3)):
            continue
        # relative to the primary, or strong on its own (a very strong safety score must not hide a clear second issue)
        strong = settings.get("secondary_strong_score", 5.0)
        if (c.score >= sec_min and (c.score >= ratio * max(primary.score, top.score) or c.score >= strong)
                and c.category != primary.category and c.category not in {primary.category, *(s[:3] for s in secondary)}):
            secondary.append(c.subcategory)
    runner = next((c for c in candidates if c is not primary), None)
    margin = settings.get("ambiguity_margin", 0.15)
    ambiguous = bool(runner and runner.category != primary.category and precedence_applied is None
                     and (primary.score - runner.score) <= margin * primary.score)
    confidence = "high" if primary.score >= 8 and not ambiguous else "medium" if primary.score >= 5 else "low"
    return ClassificationResult(primary.subcategory, primary.category, primary.score, secondary, candidates[:6],
                                ambiguous, confidence, precedence_applied)


# ============================== sentiment ====================================


@dataclass
class SentimentResult:
    label: str
    score: float
    negative_terms: list[str]
    positive_terms: list[str]


def lexicon_sentiment(matrix: RuleMatrix, text: str) -> SentimentResult:
    cfg = matrix.sentiment_config
    lower = (text or "").lower()
    neg_terms, pos_terms = [], []
    score = 0.0
    for term, weight in (cfg.get("negative") or {}).items():
        if find_phrase(lower, str(term)):
            score += float(weight)
            neg_terms.append(str(term))
    for term, weight in (cfg.get("positive") or {}).items():
        if find_phrase(lower, str(term), frozenset(matrix.negation_cues)):
            score -= float(weight)
            pos_terms.append(str(term))
    exclam = min(3, max(0, (text or "").count("!") - 1))
    score += exclam * float(cfg.get("exclamation_boost", 0.5))
    caps = [w for w in re.findall(r"\b[A-Z]{4,}\b", text or "") if w not in {"LUMORA", "USD", "CMP", "LMR", "TXN"}]
    score += min(5, len(caps)) * float(cfg.get("caps_word_boost", 0.6))
    th = cfg.get("thresholds") or {}
    if score >= float(th.get("strongly_negative", 5.0)):
        label = "Strongly Negative"
    elif score >= float(th.get("negative", 1.2)):
        label = "Negative"
    elif score <= float(th.get("positive", -1.0)):
        label = "Positive"
    else:
        label = "Neutral"
    return SentimentResult(label, round(score, 2), neg_terms, pos_terms)
