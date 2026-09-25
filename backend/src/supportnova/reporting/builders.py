"""Report builders (SRS Step 67 + Deliverables 8-10). Each builder queries live data and returns a
format-neutral `Report`; `exports.render` turns it into CSV, Excel or PDF."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from supportnova.core.config import get_settings
from supportnova.core.errors import NotFound
from supportnova.core.timeutil import utcnow
from supportnova.database.models import (
    AIRun,
    AuditLog,
    Complaint,
    DocumentChunk,
    DocumentVersion,
    Escalation,
    EvaluationResult,
    EvaluationRun,
    Review,
    ReviewAction,
    SlaRecord,
    ValidationCheck,
    ValidationResult,
)
from supportnova.reporting.exports import Report, Section, Table
from supportnova.rule_engine.models import RuleMatrix
from supportnova.services import analytics as an

OPEN = ("Resolved", "Closed")


@dataclass
class ReportParams:
    date_from: date | None = None
    date_to: date | None = None
    department: str | None = None
    category: str | None = None
    run_id: int | None = None
    source: str | None = None  # default: operational complaints

    def describe(self) -> str:
        parts = []
        if self.date_from or self.date_to:
            parts.append(f"{self.date_from or '...'} to {self.date_to or '...'}")
        if self.department:
            parts.append(f"department {self.department}")
        if self.category:
            parts.append(f"category {self.category}")
        return ", ".join(parts) or "all operational complaints"


def _scope(params: ReportParams) -> list[Any]:
    conds: list[Any] = [Complaint.source.in_(an.OPERATIONAL) if not params.source else Complaint.source == params.source]
    if params.date_from:
        conds.append(Complaint.created_at >= datetime.combine(params.date_from, time.min).astimezone())
    if params.date_to:
        conds.append(Complaint.created_at < datetime.combine(params.date_to + timedelta(days=1), time.min).astimezone())
    if params.department:
        conds.append(Complaint.department_code == params.department)
    if params.category:
        conds.append(Complaint.category_code == params.category)
    return conds


def _complaints(db: Session, params: ReportParams) -> list[Complaint]:
    return list(db.execute(select(Complaint).where(*_scope(params)).order_by(Complaint.created_at)).scalars())


def _latest_results(db: Session, ids: list[int]) -> dict[int, ValidationResult]:
    if not ids:
        return {}
    latest = select(func.max(ValidationResult.id)).where(ValidationResult.complaint_id.in_(ids)).group_by(ValidationResult.complaint_id)
    return {v.complaint_id: v for v in db.execute(select(ValidationResult).where(ValidationResult.id.in_(latest))).scalars()}


def _dist_table(matrix: RuleMatrix, title: str, dimension: str, values: list[str | None]) -> Table:
    counts = Counter(values)
    total = sum(counts.values()) or 1
    rows = [[an.label(matrix, dimension, k), n, f"{100 * n / total:.1f}%"] for k, n in counts.most_common()]
    return Table([title, "Complaints", "Share"], rows, title=f"By {title.lower()}", widths=[80, 30, 30])


def _meta(params: ReportParams) -> dict[str, Any]:
    s = get_settings()
    return {"Scope": params.describe(), "AI model": f"{s.resolved_provider} ({s.resolved_model})"
            + ("" if s.ai_configured else " - not configured, AI step off")}


# ============================================================================== 1. complaint analysis
def complaint_analysis(db: Session, matrix: RuleMatrix, p: ReportParams) -> Report:
    cs = _complaints(db, p)
    resolved = [c for c in cs if c.resolved_at]
    hours = [(an._aware(c.resolved_at) - an._aware(c.created_at)).total_seconds() / 3600 for c in resolved]  # type: ignore[operator]
    kpis = Section("Summary", metrics=[
        ("Complaints", len(cs)), ("Open", sum(c.status not in OPEN for c in cs)), ("Resolved/closed", sum(c.status in OPEN for c in cs)),
        ("Escalated", sum(c.escalation_required for c in cs)), ("Verified", sum(c.verification_status in ("Verified", "Human Verified") for c in cs)),
        ("Manual review", sum(c.verification_status == "Manual Review" for c in cs)), ("Repeat", sum(c.is_repeat for c in cs)),
        ("Duplicates", sum(c.is_duplicate for c in cs)),
        ("Avg resolution (h)", round(sum(hours) / len(hours), 1) if hours else None),
        ("Avg verification score", round(sum(c.verification_score or 0 for c in cs) / len(cs), 1) if cs else None),
        ("Manipulation attempts", sum(c.injection_detected for c in cs)), ("Channels", len({c.channel for c in cs})),
    ])
    dist = Section("Distributions", tables=[
        _dist_table(matrix, "Category", "category", [c.category_code for c in cs]),
        _dist_table(matrix, "Subcategory", "subcategory", [c.subcategory_code for c in cs]),
        _dist_table(matrix, "Product", "product", [c.product_sku for c in cs]),
        _dist_table(matrix, "Urgency", "urgency", [c.urgency for c in cs]),
        _dist_table(matrix, "Priority", "priority", [c.priority for c in cs]),
        _dist_table(matrix, "Sentiment", "sentiment", [c.sentiment for c in cs]),
        _dist_table(matrix, "Channel", "channel", [c.channel for c in cs]),
        _dist_table(matrix, "Status", "status", [c.status for c in cs]),
    ])
    shown = cs[-500:]
    note = [f"Latest {len(shown)} of {len(cs)} complaints; the full list is available from Complaints > Export."] if len(cs) > len(shown) else []
    listing = Section("Complaint register", paragraphs=note, tables=[Table(
        ["Complaint", "Date", "Category", "Department", "Urgency", "Priority", "Sentiment", "Status", "Verification", "Score"],
        [[c.complaint_ref, c.created_at.date().isoformat(), an.label(matrix, "subcategory", c.subcategory_code),
          an.label(matrix, "department", c.department_code), c.urgency, c.priority, c.sentiment, c.status, c.verification_status,
          c.verification_score] for c in shown], widths=[20, 18, 40, 36, 14, 12, 20, 20, 22, 12])])
    return Report("Complaint analysis report", [kpis, dist, listing], subtitle="Volume, classification and outcome of complaints",
                  meta=_meta(p))


# ============================================================================== 2. department performance
def department_performance(db: Session, matrix: RuleMatrix, p: ReportParams) -> Report:
    cs = _complaints(db, p)
    agg: dict[str, dict[str, Any]] = {}
    for c in cs:
        a = agg.setdefault(c.department_code or "-", {"n": 0, "open": 0, "resolved": 0, "esc": 0, "breach": 0, "hours": [], "scores": [],
                                                      "review": 0, "support": 0})
        a["n"] += 1
        a["open"] += c.status not in OPEN
        a["resolved"] += c.status in OPEN
        a["esc"] += bool(c.escalation_required)
        a["breach"] += c.sla_state == "Breached"
        a["review"] += c.verification_status == "Manual Review"
        if c.resolved_at:
            a["hours"].append((an._aware(c.resolved_at) - an._aware(c.created_at)).total_seconds() / 3600)  # type: ignore[operator]
        if c.verification_score is not None:
            a["scores"].append(c.verification_score)
    results = _latest_results(db, [c.id for c in cs])
    for vr in results.values():
        for d in (vr.validated_decision or {}).get("supporting_departments", []):
            agg.setdefault(d, {"n": 0, "open": 0, "resolved": 0, "esc": 0, "breach": 0, "hours": [], "scores": [], "review": 0, "support": 0})
            agg[d]["support"] += 1
    rows = []
    for code, a in sorted(agg.items(), key=lambda kv: -kv[1]["n"]):
        rows.append([an.label(matrix, "department", code), a["n"], a["support"], a["open"], a["resolved"], a["esc"], a["breach"],
                     f"{100 * a['breach'] / a['n']:.1f}%" if a["n"] else "-", a["review"],
                     round(sum(a["hours"]) / len(a["hours"]), 1) if a["hours"] else None,
                     round(sum(a["scores"]) / len(a["scores"]), 1) if a["scores"] else None])
    agents = db.execute(select(Complaint.assigned_agent_id, func.count()).where(*_scope(p), Complaint.assigned_agent_id.is_not(None))
                        .group_by(Complaint.assigned_agent_id)).all()
    from supportnova.database.models import User
    agent_rows = []
    for aid, n in sorted(agents, key=lambda x: -x[1]):
        u = db.get(User, aid)
        mine = [c for c in cs if c.assigned_agent_id == aid]
        agent_rows.append([u.full_name if u else aid, u.department.name if u and u.department else "-", n,
                           sum(c.status in OPEN for c in mine), sum(c.sla_state == "Breached" for c in mine)])
    return Report("Department performance report", [
        Section("Departments", tables=[Table(["Department", "Primary", "Supporting", "Open", "Resolved", "Escalated", "SLA breached",
                                              "Breach rate", "Manual review", "Avg resolution h", "Avg score"], rows)]),
        Section("Agent workload", tables=[Table(["Agent", "Department", "Assigned", "Resolved", "SLA breached"], agent_rows)]),
    ], subtitle="Volume, throughput, SLA adherence and verification scores by department", meta=_meta(p))


# ============================================================================== 3. escalations
def escalations(db: Session, matrix: RuleMatrix, p: ReportParams) -> Report:
    cs = {c.id: c for c in _complaints(db, p)}
    escs = [e for e in db.execute(select(Escalation).order_by(Escalation.created_at)).scalars() if e.complaint_id in cs]
    by_level = Counter(e.level for e in escs)
    by_rule: Counter[str] = Counter(r for e in escs for r in (e.rule_ids or []))
    by_source = Counter(e.source for e in escs)
    missed = 0
    results = _latest_results(db, list(cs))
    for vr in results.values():
        row = next((r for r in (vr.comparison or {}).get("rows", []) if r["field"] == "escalation_required"), None)
        if row and row["python"] and not row["ai"]:
            missed += 1
    return Report("Escalation report", [
        Section("Summary", metrics=[("Escalations", len(escs)), ("Complaints escalated", len({e.complaint_id for e in escs})),
                                    ("Open", sum(e.status == "open" for e in escs)), ("Resolved", sum(e.status == "resolved" for e in escs)),
                                    ("Enforced by rules (AI missed)", missed), ("SLA-triggered", by_source.get("sla", 0))]),
        Section("Breakdown", tables=[
            Table(["Escalation level", "Count"], [[k, v] for k, v in sorted(by_level.items(), key=lambda kv: -matrix.level_rank(kv[0]))],
                  title="By level"),
            Table(["Escalation rule", "Fired"], [[k, v] for k, v in by_rule.most_common(40)], title="By rule"),
            Table(["Source", "Count"], [[k, v] for k, v in by_source.most_common()], title="By source"),
        ]),
        Section("Escalation register", tables=[Table(["Complaint", "Created", "Level", "Source", "Rules", "Departments", "Reason", "Status"],
            [[cs[e.complaint_id].complaint_ref, e.created_at.date().isoformat(), e.level, e.source, e.rule_ids, e.departments, e.reason, e.status]
             for e in escs[-400:]], widths=[20, 18, 32, 12, 24, 30, 70, 14])]),
    ], subtitle="Required and manual escalations, with the rules behind them", meta=_meta(p))


# ============================================================================== 4. SLA
def sla_status(db: Session, matrix: RuleMatrix, p: ReportParams) -> Report:
    cs = {c.id: c for c in _complaints(db, p)}
    recs = [r for r in db.execute(select(SlaRecord)).scalars() if r.complaint_id in cs]
    table: dict[str, Counter[str]] = defaultdict(Counter)
    for r in recs:
        table[r.priority][r.resolution_state] += 1
    now = utcnow()
    risky = sorted((r for r in recs if r.resolution_state in ("At Risk", "Breached") and cs[r.complaint_id].status not in OPEN),
                   key=lambda r: an._aware(r.resolution_due_at))  # type: ignore[arg-type,return-value]
    return Report("SLA status report", [
        Section("Summary", metrics=[("Tracked", len(recs)), ("On track", sum(r.resolution_state == "On Track" for r in recs)),
                                    ("At risk", sum(r.resolution_state == "At Risk" for r in recs)),
                                    ("Breached", sum(r.resolution_state == "Breached" for r in recs)),
                                    ("Met", sum(r.resolution_state == "Met" for r in recs)),
                                    ("First response met", sum(1 for r in recs if r.first_response_at
                                                               and cast(datetime, an._aware(r.first_response_at))
                                                               <= cast(datetime, an._aware(r.first_response_due_at))))]),
        Section("By priority", tables=[Table(["Priority", "First response target h", "Resolution target h", "On Track", "At Risk", "Breached", "Met"],
            [[pr, matrix.sla_rules[pr].first_response_hours if pr in matrix.sla_rules else None,
              matrix.sla_rules[pr].resolution_hours if pr in matrix.sla_rules else None,
              t["On Track"], t["At Risk"], t["Breached"], t["Met"]] for pr, t in sorted(table.items())])]),
        Section("Open complaints at risk or breached", tables=[Table(["Complaint", "Priority", "Department", "Due", "Hours to due", "State", "Status"],
            [[cs[r.complaint_id].complaint_ref, r.priority, an.label(matrix, "department", cs[r.complaint_id].department_code),
              an._aware(r.resolution_due_at).strftime("%Y-%m-%d %H:%M"),  # type: ignore[union-attr]
              round((an._aware(r.resolution_due_at) - now).total_seconds() / 3600, 1),  # type: ignore[operator]
              r.resolution_state, cs[r.complaint_id].status] for r in risky[:300]])]),
    ], subtitle="Service-level targets from SLA-RUL-15 applied to every analysed complaint", meta=_meta(p))


# ============================================================================== 5. policy usage
def policy_usage(db: Session, matrix: RuleMatrix, p: ReportParams) -> Report:
    usage = an.policy_usage(db)
    versions = db.execute(select(DocumentVersion).order_by(DocumentVersion.document_id, DocumentVersion.id)).scalars().all()
    quarantined = db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.is_quarantined)) or 0
    cs = _complaints(db, p)
    results = _latest_results(db, [c.id for c in cs])
    outdated: Counter[str] = Counter()
    for vr in results.values():
        for ap in (vr.validated_decision or {}).get("applicability", []):
            if ap.get("applicability") == "Outdated":
                outdated[f"{ap.get('doc_id')} v{ap.get('version')} s{ap.get('section_id')}"] += 1
    return Report("Policy usage report", [
        Section("Summary", metrics=[("Documents", len({v.document_id for v in versions})), ("Versions", len(versions)),
                                    ("Active versions", sum(v.status == "Active" for v in versions)),
                                    ("Superseded/previous", sum(v.status in ("Superseded", "Previous") for v in versions)),
                                    ("Quarantined document sections", quarantined),
                                    ("Outdated sections used as background", sum(outdated.values()))]),
        Section("Most used policy sections", tables=[Table(["Document", "Section", "Cited by AI", "Required by rules", "Retrieved"],
            [[u["doc_id"], u["section"], u["ai"], u["rule"], u["retrieval"]] for u in usage])]),
        Section("Outdated versions used as background only (never as the basis)", tables=[Table(["Reference", "Occurrences"], [[k, v] for k, v in outdated.most_common()])]),
        Section("Document versions", tables=[Table(["Document", "Version", "Status", "Effective", "Format", "Sections", "Chunks"],
            [[v.document.doc_id, v.version, v.status, v.effective_date, v.file_format, v.section_count, v.chunk_count] for v in versions])]),
    ], subtitle="Which policies, SOPs and rule documents support complaint decisions", meta=_meta(p))


# ============================================================================== 6. resolution compliance
COMPLIANCE_CODES = ("RES-001", "RES-002", "RES-003", "RES-004", "ELG-001", "ELG-002", "ELG-003", "RSP-002", "RSP-003", "RSP-004",
                    "RSP-006", "MIS-001", "MIS-002", "ESC-001", "ESC-002")


def resolution_compliance(db: Session, matrix: RuleMatrix, p: ReportParams) -> Report:
    cs = {c.id: c for c in _complaints(db, p)}
    results = _latest_results(db, list(cs))
    checks = db.execute(select(ValidationCheck).where(ValidationCheck.result_id.in_([v.id for v in results.values()]),
                                                      ValidationCheck.code.in_(COMPLIANCE_CODES))).scalars().all() if results else []
    by_code: dict[str, Counter[str]] = defaultdict(Counter)
    names: dict[str, str] = {}
    failures = []
    rid_to_cid = {v.id: v.complaint_id for v in results.values()}
    for ch in checks:
        by_code[ch.code][ch.status] += 1
        names[ch.code] = matrix.validation_check(ch.code).get("name") or ch.name  # current display name
        if ch.status == "fail":
            failures.append([cs[rid_to_cid[ch.result_id]].complaint_ref, ch.code, names[ch.code], ch.message])
    applicable = sum(sum(v for k, v in c.items() if k != "not_applicable") for c in by_code.values())
    passed = sum(c["pass"] for c in by_code.values())
    return Report("Resolution compliance report", [
        Section("Summary", metrics=[("Complaints validated", len(results)), ("Compliance checks", applicable),
                                    ("Pass rate", f"{100 * passed / applicable:.1f}%" if applicable else "-"),
                                    ("Unsupported promises caught", by_code["RSP-002"]["fail"]),
                                    ("Prohibited actions caught", by_code["RES-002"]["fail"] + by_code["RSP-006"]["fail"]),
                                    ("Eligibility corrections", sum(by_code[c]["fail"] for c in ("ELG-001", "ELG-002", "ELG-003")))]),
        Section("Compliance checks", tables=[Table(["Check", "Name", "Pass", "Warn", "Fail", "N/A", "Pass rate"],
            [[code, names.get(code, code), c["pass"], c["warn"], c["fail"], c["not_applicable"],
              f"{100 * c['pass'] / max(1, c['pass'] + c['warn'] + c['fail']):.1f}%"] for code, c in sorted(by_code.items())])]),
        Section("Failures (corrected or sent to manual review)", tables=[Table(["Complaint", "Check", "Name", "Detail"], failures[-400:],
                                                                                widths=[20, 14, 50, 110])]),
    ], subtitle="Whether AI resolutions, eligibility and customer commitments followed the rules",
        meta=_meta(p))


# ============================================================================== 7. AI vs rules comparison
DELIVERABLE_8 = ["Complaint", "Expected category", "AI category", "Rules category", "AI department", "Rules department",
                 "AI urgency", "Rules urgency", "AI escalation", "Rules escalation", "Policy reference", "Match",
                 "Verification", "Explanation of disagreement"]


def _comparison_row(ref: str, expected_cat: str | None, comp: dict[str, Any], vd: dict[str, Any], status: str) -> list[Any]:
    rows = {r["field"]: r for r in comp.get("rows", [])}

    def g(field: str, side: str) -> Any:
        return (rows.get(field) or {}).get(side)
    key = ("subcategory", "department", "urgency", "escalation_level")
    mismatches = [f for f in key if (rows.get(f) or {}).get("match") == "mismatch"]
    explanation = "; ".join(f"{f.replace('_', ' ')}: AI {g(f, 'ai')!s} vs rules {g(f, 'python')!s}"
                            + (f" ({rows[f].get('explanation')})" if rows[f].get("explanation") else "") for f in mismatches) or "-"
    return [ref, expected_cat, f"{g('category', 'ai')}/{g('subcategory', 'ai')}", f"{g('category', 'python')}/{g('subcategory', 'python')}",
            g("department", "ai"), g("department", "python"), g("urgency", "ai"), g("urgency", "python"), g("escalation_level", "ai"),
            g("escalation_level", "python"), ", ".join((vd.get("policy_refs") or [])[:3]), "Match" if not mismatches else "Mismatch",
            status, explanation]


def genai_python_comparison(db: Session, matrix: RuleMatrix, p: ReportParams) -> Report:
    rows: list[list[Any]] = []
    field_stats: dict[str, Counter[str]] = defaultdict(Counter)
    subtitle = "Operational complaints"
    banner = None
    if p.run_id:
        run = db.get(EvaluationRun, p.run_id)
        if run is None:
            raise NotFound(f"Evaluation run {p.run_id} not found.")
        subtitle = f"Evaluation run #{run.id} on the '{run.split}' dataset ({run.n_cases} unseen cases, AI {run.provider}/{run.model})"
        for r in db.execute(select(EvaluationResult).where(EvaluationResult.run_id == run.id).order_by(EvaluationResult.case_id)).scalars():
            exp = r.expected or {}
            rows.append(_comparison_row(r.case_id, f"{exp.get('category')}/{exp.get('subcategory')}", r.comparison or {}, r.python or {},
                                        r.verification_status))
            for row in (r.comparison or {}).get("rows", []):
                field_stats[row["field"]][row["match"]] += 1
    else:
        cs = _complaints(db, p)
        results = _latest_results(db, [c.id for c in cs])
        for c in cs:
            vr = results.get(c.id)
            if vr is None:
                continue
            rows.append(_comparison_row(c.complaint_ref, None, vr.comparison or {}, vr.validated_decision or {}, c.verification_status))
            for row in (vr.comparison or {}).get("rows", []):
                field_stats[row["field"]][row["match"]] += 1
    agreement = [[f, c["match"], c["partial"], c["mismatch"], f"{100 * c['match'] / max(1, sum(c.values())):.1f}%"]
                 for f, c in field_stats.items()]
    return Report("AI vs rules comparison report", [
        Section("Summary", metrics=[("Cases compared", len(rows)), ("Full key-field match", sum(r[11] == "Match" for r in rows)),
                                    ("Mismatch", sum(r[11] == "Mismatch" for r in rows)),
                                    ("Verified", sum(r[12] in ("Verified", "Human Verified") for r in rows)),
                                    ("Manual review", sum(r[12] == "Manual Review" for r in rows))]),
        Section("Field agreement", tables=[Table(["Field", "Match", "Partial", "Mismatch", "Agreement"], agreement)]),
        Section("Case comparison", tables=[Table(DELIVERABLE_8, rows, widths=[16, 20, 22, 22, 16, 16, 12, 12, 22, 22, 26, 13, 18, 60])]),
    ], subtitle=subtitle, meta=_meta(p), banner=banner,
        notes=["The rules decide the final outcome; the AI columns show what the AI proposed."])


# ============================================================================== 8. manual reviews
def manual_reviews(db: Session, matrix: RuleMatrix, p: ReportParams) -> Report:
    cs = {c.id: c for c in _complaints(db, p)}
    reviews = [r for r in db.execute(select(Review).order_by(Review.created_at)).scalars() if r.complaint_id in cs]
    reasons: Counter[str] = Counter(code for r in reviews for code in (r.reason_codes or []))
    outcomes = Counter(r.final_decision or r.status for r in reviews)
    actions = db.execute(select(ReviewAction.action, func.count()).where(ReviewAction.review_id.in_([r.id for r in reviews]))
                         .group_by(ReviewAction.action)).all() if reviews else []
    rule_names = {r["code"]: f"{r.get('rule_id')} {r.get('name')}" for r in matrix.review_rules}
    rule_names["pipeline_error"] = "Processing error"
    turnaround = [(an._aware(r.completed_at) - an._aware(r.created_at)).total_seconds() / 3600 for r in reviews if r.completed_at]  # type: ignore[operator]
    return Report("Manual review report", [
        Section("Summary", metrics=[("Reviews", len(reviews)), ("Pending", sum(r.status == "pending" for r in reviews)),
                                    ("In review", sum(r.status == "in_review" for r in reviews)),
                                    ("Completed", sum(r.status == "completed" for r in reviews)),
                                    ("Avg turnaround (h)", round(sum(turnaround) / len(turnaround), 1) if turnaround else None)]),
        Section("Why complaints needed review", tables=[
            Table(["Reason", "Name", "Cases"], [[k, rule_names.get(k, k), v] for k, v in reasons.most_common()]),
            Table(["Outcome", "Cases"], [[k, v] for k, v in outcomes.most_common()], title="Outcomes"),
            Table(["Reviewer action", "Count"], [[k, v] for k, v in actions], title="Reviewer actions")]),
        Section("Review register", tables=[Table(["Complaint", "Created", "Priority", "Reasons", "Status", "Decision", "Actions"],
            [[cs[r.complaint_id].complaint_ref, r.created_at.date().isoformat(), r.priority, r.reason_codes, r.status, r.final_decision,
              ", ".join(a.action for a in r.actions)] for r in reviews[-400:]])]),
    ], subtitle="Cases sent to human reviewers and what they decided", meta=_meta(p))


# ============================================================================== 9. complaint intelligence
def complaint_intelligence(db: Session, matrix: RuleMatrix, p: ReportParams) -> Report:
    base = complaint_analysis(db, matrix, p)
    cs = _complaints(db, p)
    results = _latest_results(db, [c.id for c in cs])
    alerts = an.trend_alerts(db, matrix)
    disagreements: Counter[str] = Counter()
    for vr in results.values():
        for row in (vr.comparison or {}).get("rows", []):
            if row["match"] == "mismatch":
                disagreements[row["field"]] += 1
    repeat_customers = Counter(c.customer.customer_ref for c in cs if c.is_repeat and c.customer)
    usage = an.policy_usage(db)[:15]
    sections = [base.sections[0], Section("Distributions", tables=[t for t in base.sections[1].tables
                                                                  if t.title in ("By category", "By priority", "By sentiment")]),
                Section("Department routing", tables=[_dist_table(matrix, "Department", "department", [c.department_code for c in cs])]),
                Section("Escalations and SLA risk", metrics=[
                    ("Escalated", sum(c.escalation_required for c in cs)),
                    ("Critical management", sum(c.escalation_level == "Critical Management Escalation" for c in cs)),
                    ("SLA at risk (open)", sum(c.sla_state == "At Risk" and c.status not in OPEN for c in cs)),
                    ("SLA breached (open)", sum(c.sla_state == "Breached" and c.status not in OPEN for c in cs))],
                    tables=[_dist_table(matrix, "Escalation level", "escalation", [c.escalation_level for c in cs if c.escalation_required])]),
                Section("Repeat complaints", metrics=[("Repeat complaints", sum(c.is_repeat for c in cs)),
                                                      ("Customers with repeats", len(repeat_customers))],
                        tables=[Table(["Customer", "Repeat complaints"], [[k, v] for k, v in repeat_customers.most_common(15)])]),
                Section("Policy usage", tables=[Table(["Document", "Section", "AI", "Rules"], [[u["doc_id"], u["section"], u["ai"], u["rule"]]
                                                                                              for u in usage])]),
                Section("AI vs rules disagreements", tables=[Table(["Field", "Mismatches"],
                                                                [[k.replace("_", " "), v] for k, v in disagreements.most_common()])]),
                Section("Manual-review cases", metrics=[("Manual review", sum(c.verification_status == "Manual Review" for c in cs)),
                                                        ("Human verified", sum(c.verification_status == "Human Verified" for c in cs))]),
                Section("Emerging trends", bullets=[a["message"] for a in alerts] or ["No statistically notable trend in the current window."])]
    return Report("Complaint intelligence report", sections, subtitle="Patterns, risks and disagreements across the complaint base",
                  meta=_meta(p), banner=base.banner)


# ============================================================================== 10. security & adversarial
def security(db: Session, matrix: RuleMatrix, p: ReportParams) -> Report:
    all_cs = db.execute(select(Complaint).where(Complaint.injection_detected.is_(True))).scalars().all()
    lab = db.execute(select(Complaint).where(Complaint.source == "lab").order_by(Complaint.created_at)).scalars().all()
    quarantined = db.execute(select(DocumentChunk).where(DocumentChunk.is_quarantined)).scalars().all()
    auth_fail = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action.in_(["auth.login_failed", "auth.locked"]))) or 0
    denied = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "access.denied")) or 0
    faults = db.execute(select(AIRun.fault_injection, AIRun.parsed_ok, func.count()).where(AIRun.fault_injection.is_not(None))
                        .group_by(AIRun.fault_injection, AIRun.parsed_ok)).all()
    from supportnova.services import lab as lab_service
    lab_rows = []
    met = 0
    for c in lab:
        exp = lab_service.expectation_report(db, c)
        met += exp.get("met") is True
        lab_rows.append([c.complaint_ref, c.dataset_case_id or "custom", c.title[:60], exp.get("fault_profile"), c.injection_detected,
                         c.verification_status, c.verification_score, ", ".join(exp.get("failed_checks", [])[:6]),
                         {True: "Met", False: "Not met", None: "-"}[exp.get("met")]])
    return Report("Security and adversarial testing report", [
        Section("Summary", metrics=[("Complaints with manipulation attempts", len(all_cs)), ("Adversarial lab runs", len(lab)),
                                    ("Lab runs blocked from auto-verification", sum(c.verification_status != "Verified" for c in lab)),
                                    ("Quarantined document sections", len(quarantined)), ("Failed logins / lockouts", auth_fail),
                                    ("Denied access attempts", denied)]),
        Section("Adversarial lab results", metrics=[("Scenario runs", len(lab_rows)), ("Expectations met", met)],
                tables=[Table(["Complaint", "Scenario", "Title", "Deliberate defect", "Manipulation", "Verification", "Score",
                               "Failed checks (caught)", "Expectation"], lab_rows,
                              widths=[18, 20, 50, 28, 14, 22, 12, 50, 18])]),
        Section("Deliberate defect outcomes", tables=[Table(["Deliberate defect", "Valid answer", "AI attempts"],
                                                                 [[f, ok, n] for f, ok, n in faults])]),
        Section("Quarantined document sections", tables=[Table(["Document section", "Reason"],
                                                                    [[q.chunk_uid, q.quarantine_reason] for q in quarantined])]),
        Section("Controls", bullets=[
            "Complaint text is marked as untrusted and screened for manipulation before the AI sees it.",
            "Document sections with hidden instructions are quarantined and never used as policy evidence.",
            "Every AI answer is checked for completeness and re-checked against the rules; the AI cannot approve itself.",
            "Personal data is removed before text is sent to the AI; credentials are never requested; the AI key never reaches the browser.",
            "Role-based access is enforced on the server for every request; the audit log is tamper-evident and append-only."]),
    ], subtitle="Prompt injection, unsupported requests, fake policies, malicious documents and access control", meta=_meta(p))


REPORTS: dict[str, tuple[str, Callable[[Session, RuleMatrix, ReportParams], Report]]] = {
    "complaint-analysis": ("Complaint analysis", complaint_analysis),
    "department-performance": ("Department performance", department_performance),
    "escalations": ("Escalations", escalations),
    "sla-status": ("SLA status", sla_status),
    "policy-usage": ("Policy usage", policy_usage),
    "resolution-compliance": ("Resolution compliance", resolution_compliance),
    "genai-python-comparison": ("AI vs rules comparison", genai_python_comparison),
    "manual-reviews": ("Manual reviews", manual_reviews),
    "complaint-intelligence": ("Complaint intelligence", complaint_intelligence),
    "security": ("Security & adversarial testing", security),
}


def build(db: Session, matrix: RuleMatrix, key: str, params: ReportParams) -> Report:
    if key not in REPORTS:
        raise NotFound(f"Unknown report '{key}'.")
    return REPORTS[key][1](db, matrix, params)
