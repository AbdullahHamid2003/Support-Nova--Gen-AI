"""Prompt-injection and manipulation screening for untrusted text (SRS Steps 50-51, 1.8(8)).

Complaint text and uploaded documents are untrusted DATA. This screener does not
decide the outcome of a complaint; it (1) flags suspicious spans so they can be
isolated/annotated in the GenAI prompt, (2) forces manual review, (3) lets the
validation pipeline check that the GenAI output did not follow the instruction,
and (4) quarantines instruction-bearing chunks in knowledge-base documents.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import asdict, dataclass, field

from .sanitization import count_invisible

_F = re.IGNORECASE | re.DOTALL


@dataclass(frozen=True)
class _Pattern:
    type: str
    severity: str
    regex: re.Pattern[str]
    description: str


PATTERNS: tuple[_Pattern, ...] = (
    _Pattern("instruction_override", "high", re.compile(
        r"(?<!never\s)(?<!not\s)(?<!n't\s)(?<!cannot\s)\b(ignore|disregard|forget|override|bypass|skip)\s+(all\s+|any\s+|of\s+)?"
        r"((the|your|my|these|those|previous|prior|above|earlier|system|existing|current|standard|usual)\s+)*(\w+\s+){0,2}?"
        r"(instructions?|rules|rule\s+matrix|prompts?|guidelines|polic(y|ies)|directives|constraints|programming|restrictions)\b", _F),
        "Attempts to override the system's instructions or rules."),
    _Pattern("instruction_override", "high", re.compile(
        r"\bignore\s+(the\s+|this\s+|all\s+(of\s+)?(the\s+)?)?(text|content|message|details?|words?|rest)\s+(below|above|that\s+follows)\b"
        r"|\bignore\s+(everything|anything)\s+(below|above|else)\b"
        r"|\byour\s+(instructions|rules|guidelines|polic(y|ies)|prompt|training)\s+(are|is)\s+(outdated|obsolete|wrong|out\s+of\s+date|no\s+longer\s+valid|superseded)\b", _F),
        "Tells the system to ignore part of the complaint or that its rules no longer apply."),
    _Pattern("role_hijack", "high", re.compile(
        r"\bas\s+an?\s+(ai|assistant|language\s+model|llm|bot|chatbot)\b.{0,30}?\byou\s+(must|should|have\s+to|are\s+(required|supposed|obliged)\s+to)\b"
        r"|\bthe\s+only\s+(helpful|correct|acceptable|right|valid)\s+(answer|response|outcome|resolution)\s+(here\s+)?is\b", _F),
        "Appeals to the model's role to dictate an outcome."),
    _Pattern("instruction_override", "high", re.compile(
        r"\b(do\s+not|don'?t)\s+follow\s+(your|the|any)\s+(rules|instructions|polic(y|ies))|\bnew\s+instructions?\s*:", _F),
        "Attempts to replace the system's instructions."),
    _Pattern("role_hijack", "high", re.compile(
        r"\byou\s+are\s+(now|no\s+longer)\b|\bfrom\s+now\s+on,?\s+you\b|\bact\s+as\s+(an?\s+)?(admin(istrator)?|system|developer|"
        r"supervisor|manager|refund\s+bot)\b|\bpretend\s+(to\s+be|you\s+are)\b|\b(developer|god|dan|jailbreak)\s+mode\b", _F),
        "Attempts to change the assistant's role."),
    _Pattern("fake_system_message", "high", re.compile(
        r"(^|\n)\s*(system|assistant|developer|admin(istrator)?|supportnova|ai)\s*(message|note|override|instruction|prompt)?\s*[:>\]]"
        r"|\[(system|admin|internal|override)[^\]]{0,30}\]|<<\s*sys\s*>>|#{2,}\s*(system|instructions?)\b"
        r"|\b(begin|end)\s+(of\s+)?(system|admin|complaint|instructions?)\b|<\|(im_start|im_end|endoftext|system)\|>|\[/?INST\]", _F),
        "Text formatted as a system/administrator message."),
    _Pattern("tag_injection", "high", re.compile(
        r"<\s*/?\s*(system|instruction|prompt|complaint[\w-]*|evidence|context|assistant|user|untrusted[\w-]*)\b[^>]{0,80}>", _F),
        "Markup that tries to break out of the untrusted-data boundary."),
    _Pattern("output_manipulation", "high", re.compile(
        r"\b(mark|set|classify|label|flag|tag|record|categori[sz]e)\s+(this|the|my|every|all)\s+(complaint|case|ticket|request)s?\s+as\b"
        r"|\bset\s+(the\s+)?(\w+\s+)?(priority|urgency|status|category|department|escalation(\s+level)?|verification|validation)"
        r"(\s+[\w']+){0,4}?\s+(to|as|=)\s"
        r"|\"(category|priority|urgency|department|escalation_required|refund_eligibility|verification\w*)\"\s*:"
        r"|\b(respond|reply|answer|output)\s+(only\s+)?(with|in)\s+(json|the\s+following)\b"
        r"|\btreat\s+(this|the)\s+(document|complaint|message|text|note)\s+as\s+(the\s+)?(highest|top|primary|official|approved)", _F),
        "Attempts to dictate the structured output or the evidence precedence."),
    _Pattern("fake_system_message", "high", re.compile(
        r"\b(system|admin(istrator)?|developer|root|ops|operations|supervisor|manager|staff|internal)\s+(override|instruction|directive|command)s?\b"
        r"|(?:^|\n|[.!?]\s+)\s*(system|admin(istrator)?|developer|supportnova)\s*:\s", _F),
        "Text posing as a system or administrator directive."),
    _Pattern("tag_injection", "high", re.compile(r"<!--.{0,400}?-->", _F),
        "Hidden markup comment inside the complaint."),
    _Pattern("output_manipulation", "high", re.compile(
        r"\b(refund_eligibility|escalation_required|escalation_level|verification_status|priority|urgency|department|category)"
        r"\s*=\s*[\"']?\w+"
        r"|\b(write|say|state|include|put)\b[^\n]{0,40}[\"“][^\"”\n]{4,200}[\"”][^\n]{0,20}\b(in|into)\s+(your|the)\s+(answer|reply|response|email|message)\b"
        r"|\bin\s+your\s+(reply|answer|response),?\s+(write|say|state|repeat|confirm|include)\b"
        r"|\brepeat\s+after\s+me\b|\bword\s+for\s+word\b"
        r"|\b(classify|categori[sz]e|label)\s+(this|it)\s+as\s+(a\s+|an\s+)?\w+(\s+\w+)?\s+(hazard|incident|emergency|breach|p0|critical)\b", _F),
        "Dictates the output, the response wording or a risk classification."),
    _Pattern("output_manipulation", "medium", re.compile(
        r"\bthe\s+(correct|right|real|actual|proper)\s+(department|priority|category|urgency|escalation(\s+level)?|subcategory)\s+(is|should\s+be)\b", _F),
        "Tells the system what the classification should be."),
    _Pattern("code_injection", "high", re.compile(
        r"\b(drop|truncate)\s+table\s+\w+|\bdelete\s+from\s+\w+\s+where\b|\binsert\s+into\s+\w+\s*\(|\bunion\s+(all\s+)?select\b"
        r"|['\"]\s*\)?\s*;\s*--|\bor\s+1\s*=\s*1\b|<\s*script\b|\bjavascript\s*:", _F),
        "Code or SQL injection payload."),
    _Pattern("security_bypass", "high", re.compile(
        r"\bsecurity\s+(steps|checks|procedures?|measures|questions)\s+(are|is)\s+(optional|unnecessary|not\s+needed|not\s+required)", _F),
        "Asks for security controls to be skipped."),
    _Pattern("security_bypass", "medium", re.compile(
        r"\b(switch|turn)\s+off\s+(the\s+|my\s+)?(two[- ]factor|2fa|mfa|multi[- ]factor)"
        r"|\b(disable|bypass|skip)\s+(the\s+|my\s+)?(two[- ]factor|2fa|mfa|multi[- ]factor|identity\s+(check|verification)|security\s+(checks?|steps?))"
        r"|\b(email|send|text|give)\s+me\s+(the\s+|my\s+)?(backup|recovery)\s+codes?"
        r"|\b(do\s+not|don'?t)\s+(lock|secure|freeze)\s+(the|my)\s+account", _F),
        "Asks for account-security controls to be relaxed."),
    _Pattern("concealment", "high", re.compile(
        r"\b(never|do\s+not|don'?t)\s+(reveal|show|disclose|mention|display)\s+(this|these|the)\s+(instruction|note|message|section|text)s?\b"
        r"|\bdo\s+not\s+show\s+this\b.{0,30}\b(reviewer|human|staff|agent)", _F),
        "Asks automated systems to hide instructions from humans."),
    _Pattern("data_exfiltration", "high", re.compile(
        r"\b(disclose|reveal|share|send|provide)\b.{0,40}\b(other|another)\s+customers?'?s?\b"
        r"|\b(print|show|list|give|tell|disclose|reveal|share|send|provide|display|output)\b.{0,60}\b(of\s+)?(the\s+)?"
        r"(last|previous|other|another|every|all)\s+(customers?|users?|clients?)\b(?!\s+(service|support|care|experience|team|agent))", _F),
        "Asks for other customers' data to be disclosed."),
    _Pattern("directive_to_system", "high", re.compile(
        r"\balways\s+(approve|grant|issue|offer|authori[sz]e)\b.{0,40}?\b(refunds?|compensation|credits?|replacements?|exceptions?)", _F),
        "Blanket instruction to approve outcomes."),
    _Pattern("directive_to_system", "high", re.compile(
        r"\b(ai|assistant|bot|chatbot|model|system|algorithm|automated\s+system|llm)\b.{0,60}?\b(approve|grant|issue|authori[sz]e|process)\b"
        r".{0,40}?\b(refund|compensation|credit|replacement|exception|voucher|payment|claim|warranty)"
        r"|\b(automatically|immediately)\s+(approve|grant|issue|authori[sz]e)\b.{0,30}?\b(refund|compensation|credit|replacement|claim)"
        r"|\byou\s+(must|are\s+(required|obligated|instructed)\s+to|have\s+to|shall)\s+(approve|grant|issue|give|pay|refund|compensate)\b"
        r"|\b(your|the)\s+(ai|assistant|bot|chatbot|model|system|algorithm)\s+(must|should|shall|needs?\s+to|has\s+to|will)\s+"
        r"(comply|obey|follow|approve|grant|accept)\b"
        r"|\binstructions?\s+for\s+(the\s+)?(assistant|ai|model|system|bot|llm)\b"
        r"|\b(decode|decrypt|translate)\b.{0,20}\b(and|then)\s+(follow|execute|obey|apply|run)\b"
        r"|\b(apply|approve|process|close|resolve|issue|grant|refund|pay|ship)\b.{0,40}\bwithout\s+(any\s+)?(\w+\s+)?(review|checks?|verification|approval)\b"
        r"|\bmark\s+(my|the|this)\s+[\w+]+(\s+\w+)?\s+as\s+(active|approved|paid|eligible|verified|covered)\b", _F),
        "Instructs the system to approve an outcome."),
    _Pattern("fake_authority", "high", re.compile(
        r"\b(agent|advisor|adviser|representative|support|lumora)\s*\(\s*(lumora|support|staff|agent)\s*\)\s*:[^\n]{0,160}"
        r"\b(approved|authori[sz]ed|guarantee[ds]?|no\s+need\s+to\s+return|will\s+refund)\b", _F),
        "Quoted 'staff' statement granting an outcome that cannot be verified."),
    _Pattern("fake_authority", "high", re.compile(
        r"[(\[]\s*(internal|staff(\s+only)?|admin|ops|internal\s+use(\s+only)?)\s*[)\]]\s*:", _F),
        "Text formatted as an internal staff note inside a customer message."),
    _Pattern("fake_authority", "medium", re.compile(
        r"\b(this\s+is|i\s+am|i'm)\s+\w+(\s+\w+)?\s+(from|at|with|in)\s+(the\s+)?lumora\s+(billing|support|finance|accounts?|"
        r"management|security|operations|returns|warranty|logistics|customer\s+care|team|office|department)\b", _F),
        "Claims to be company staff writing through the customer channel."),
    _Pattern("directive_to_system", "high", re.compile(
        r"\bno\s+(further\s+|additional\s+|more\s+)?(checks?|verification|review|approval|validation)s?\s+(is\s+|are\s+)?"
        r"(needed|required|necessary)\b|\b(skip|bypass)\s+(the\s+|all\s+|any\s+)?(checks?|verification|review|approval|validation)\b", _F),
        "Tells the system to skip its checks."),
    _Pattern("directive_to_system", "medium", re.compile(
        r"\b(close|resolve|mark)\s+(this|the)\s+(ticket|case|complaint)\s+(as\s+)?(resolved|closed|complete[d]?|verified|approved)\b"
        r"|\b(apply|issue|add|post)\s+(a|an|the)\s+([a-z]{3}\s*|[$£€]\s*)?[\d.,]+\s+(goodwill\s+|courtesy\s+)?"
        r"(credit|refund|voucher|compensation)\s+to\s+(the|this|my)\s+account\b", _F),
        "Dictates the outcome the case should be given."),
    _Pattern("directive_to_system", "high", re.compile(
        r"\b(assistant|ai|chat\s?bot|bot|model|llm|gpt|claude)\s*[:,]\s*(please\s+)?(output|say|state|write|respond|reply|mark|set|"
        r"classify|approve|confirm|declare|print|return|record)\s+(that\s+)?(i\b|i'm|i\s+am|this|my|the\s+(complaint|case|customer|"
        r"refund|priority|urgency))", _F),
        "Addresses the AI directly and dictates what it should output."),
    _Pattern("policy_override_claim", "medium", re.compile(
        r"\b(the\s+|your\s+)?(polic(y|ies)|rules|terms)\s+(do|does)\s*(not|n't)\s+apply\s+to\s+(me|us|this|my)\b", _F),
        "Claims the organisation's policies do not apply to this customer."),
    _Pattern("fake_authority", "medium", re.compile(
        r"\b(pre-?approved|already\s+approved|authori[sz]ation\s+code|approval\s+code|override\s+code|admin\s+code)\b"
        r"|\b(i\s+am|this\s+is|i'm)\s+(a|an|the)?\s*(lumora\s+)?(employee|manager|supervisor|admin(istrator)?|ceo|director|developer|staff\s+member)\b"
        r"|\b(authori[sz]ed|approved|signed\s+off)\s+by\s+(the\s+)?(manager|ceo|supervisor|director|head\s+of)"
        r"|\binternal\s+(note|memo|instruction)\b|\bnote\s+to\s+(the\s+)?(ai|assistant|model|agent|system|reviewer)\b"
        r"|\bthis\s+is\s+an?\s+(internal|staff|employee|authori[sz]ed|official)\s+(request|instruction|order|matter)\b"
        r"|\b(staff|employee|agent)\s+(id|number|no\.?)\s*[:#]?\s*\d{3,}", _F),
        "Claims authority or approval that cannot be verified."),
    _Pattern("prompt_exfiltration", "medium", re.compile(
        r"\b(reveal|show|print|repeat|display|tell\s+me)\s+(me\s+)?(your|the)\s+(system\s+)?(prompt|instructions|rules|configuration)\b", _F),
        "Attempts to extract system instructions."),
)

_B64 = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
_B64_RUN = re.compile(r"(?:[A-Za-z0-9+/]{16,}={0,2}\s+){1,6}[A-Za-z0-9+/]{8,}={0,2}")  # payload split by spaces
_POLICY_ID = re.compile(r"\b(?:[A-Z]{3}-(?:POL|SOP|RUL|GDL|FAQ|TPL)|(?:FAQ|TPL|GDL|SOP|POL|RUL)-[A-Z]{3})-\d{2}\b")
SEVERITY_WEIGHT = {"high": 0.6, "medium": 0.3, "low": 0.1}


_SECTION_AFTER = re.compile(r"[^\n.]{0,40}?\b(?:section|sec\.?|§|s\.)\s*(\d{1,2}(?:\.\d{1,2}){0,3})\b", re.IGNORECASE)


_VERSION_AFTER = re.compile(r"\s*,?\s*(?:v|version\s*)(\d{1,2}(?:\.\d{1,2})?)\b", re.IGNORECASE)


def unknown_policy_findings(text: str, known_doc_ids: set[str], section_keys: set[str] | None = None,
                            versions: dict[str, set[str]] | None = None) -> list[InjectionFinding]:
    """Fake policy statements: cited policy IDs, versions or sections that do not exist in the knowledge base."""
    out: list[InjectionFinding] = []
    body = text or ""
    for m in _POLICY_ID.finditer(body):
        doc_id = m.group(0).upper()
        if doc_id not in known_doc_ids:
            out.append(InjectionFinding("fake_policy_reference", "high", m.group(0), m.start(), m.end(),
                                        f"Cites {doc_id}, which is not a Lumora policy document - claims based on it are not valid."))
            continue
        ver = _VERSION_AFTER.match(body, m.end())
        if ver and versions is not None:
            cited = ver.group(1) if "." in ver.group(1) else ver.group(1) + ".0"
            known = versions.get(doc_id, set())
            if cited not in known and ver.group(1) not in known:
                out.append(InjectionFinding("fake_policy_reference", "high", body[m.start():ver.end()], m.start(), ver.end(),
                                            f"{doc_id} has no version {ver.group(1)} (known: {', '.join(sorted(known)) or 'none'})."))
                continue
        sec = _SECTION_AFTER.match(body, m.end())
        if sec and section_keys is not None:
            key = f"{doc_id}:{sec.group(1)}"
            if key not in section_keys and not any(k.startswith(key + ".") for k in section_keys):
                out.append(InjectionFinding("fake_policy_reference", "high", body[m.start():sec.end()], m.start(), sec.end(),
                                            f"{doc_id} has no section {sec.group(1)} - the cited entitlement does not exist."))
    return out


def with_findings(report: InjectionReport, extra: list[InjectionFinding]) -> InjectionReport:
    """Merge additional findings (e.g. knowledge-base checks) into a report and recompute the risk."""
    if not extra:
        return report
    findings = report.findings + extra
    score = 1.0
    for f in findings:
        score *= 1 - SEVERITY_WEIGHT.get(f.severity, 0.1)
    risk = 1 - score
    return InjectionReport(findings=findings, risk_score=risk,
                           is_suspicious=any(f.severity == "high" for f in findings) or risk >= 0.5)


@dataclass
class InjectionFinding:
    type: str
    severity: str
    text: str
    start: int
    end: int
    description: str


@dataclass
class InjectionReport:
    findings: list[InjectionFinding] = field(default_factory=list)
    risk_score: float = 0.0
    is_suspicious: bool = False

    def to_dict(self) -> dict[str, object]:
        return {"findings": [asdict(f) for f in self.findings], "risk_score": round(self.risk_score, 3),
                "is_suspicious": self.is_suspicious, "types": sorted({f.type for f in self.findings})}


def _decode_b64(candidate: str) -> str | None:
    try:
        raw = base64.b64decode(candidate + "=" * (-len(candidate) % 4), validate=False)
    except (binascii.Error, ValueError):
        return None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    printable = sum(ch.isprintable() or ch.isspace() for ch in text)
    return text if text and printable / len(text) > 0.9 else None


def scan(text: str, *, original: str | None = None) -> InjectionReport:
    """Scan normalised text (and the original, for hidden characters) for injection patterns."""
    findings: list[InjectionFinding] = []
    body = text or ""
    for pat in PATTERNS:
        for m in pat.regex.finditer(body):
            snippet = body[m.start():m.end()].strip()
            if not snippet:
                continue
            findings.append(InjectionFinding(pat.type, pat.severity, snippet[:200], m.start(), m.end(), pat.description))
    for m in list(_B64.finditer(body)) + list(_B64_RUN.finditer(body)):
        decoded = _decode_b64(re.sub(r"\s+", "", m.group(0)))
        if decoded:
            inner = scan(decoded)
            severity = "high" if inner.is_suspicious else "medium"
            findings.append(InjectionFinding("encoded_payload", severity, m.group(0)[:60] + "...", m.start(), m.end(),
                                             "Encoded (base64) content" + (" containing instructions." if inner.is_suspicious
                                                                           else ".")))
    if original and "<" in original:
        # markup (e.g. an HTML comment) is stripped during normalisation, so the model never sees it - but a
        # hidden instruction is still an attack worth flagging for review
        for pat in PATTERNS:
            if pat.type not in ("tag_injection", "fake_system_message", "output_manipulation", "directive_to_system"):
                continue
            for m in pat.regex.finditer(original):
                snippet = original[m.start():m.end()].strip()
                if snippet and snippet not in body:
                    findings.append(InjectionFinding(pat.type, pat.severity, snippet[:200], 0, 0,
                                                     pat.description + " (hidden in markup removed during normalisation)"))
    hidden = count_invisible(original or "")
    if hidden >= 3:
        findings.append(InjectionFinding("hidden_characters", "medium", f"{hidden} invisible characters", 0, 0,
                                         "Invisible/zero-width characters were removed from the text."))
    # de-duplicate overlapping findings of the same type
    findings.sort(key=lambda f: (f.start, -f.end))
    unique: list[InjectionFinding] = []
    for f in findings:
        if any(u.type == f.type and u.start <= f.start and f.end <= u.end and f.end > 0 for u in unique):
            continue
        unique.append(f)
    score = 1.0
    for f in unique:
        score *= 1 - SEVERITY_WEIGHT.get(f.severity, 0.1)
    risk = 1 - score
    suspicious = any(f.severity == "high" for f in unique) or risk >= 0.5
    return InjectionReport(findings=unique, risk_score=risk, is_suspicious=suspicious)


def annotate(text: str, report: InjectionReport) -> str:
    """Wrap flagged spans so the GenAI prompt can show them as quoted, inert customer text."""
    spans = sorted({(f.start, f.end, f.type) for f in report.findings if f.end > f.start}, key=lambda s: s[0])
    if not spans:
        return text
    out: list[str] = []
    cursor = 0
    for start, end, kind in spans:
        if start < cursor:
            continue
        out.append(text[cursor:start])
        out.append(f"[[FLAGGED-CUSTOMER-TEXT type={kind}]]{text[start:end]}[[/FLAGGED-CUSTOMER-TEXT]]")
        cursor = end
    out.append(text[cursor:])
    return "".join(out)
