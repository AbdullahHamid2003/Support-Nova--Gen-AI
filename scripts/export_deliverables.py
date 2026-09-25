#!/usr/bin/env python
"""Export the SRS deliverable evidence from a running SupportNova database into ``reports/``.

    backend/.venv/Scripts/python.exe scripts/export_deliverables.py [--run-id N]

Produces (all generated from live data - nothing is typed in by hand):
* reports/genai_python_comparison/   Deliverable 8 - >=100 unseen holdout cases (PDF, Excel, CSV, summary.md)
* reports/complaint_intelligence/    Deliverable 9 (PDF, Excel)
* reports/security_adversarial/      Deliverable 10 (PDF, Excel, summary.md)
* reports/operations/                SRS Step 67 reports (analysis, departments, escalations, SLA, policy usage,
                                     resolution compliance, manual reviews) as PDF + Excel
* reports/rule_matrix/               Deliverable 5 (Excel, PDF, CSV, YAML)
* reports/genai_pipeline_evidence/   Deliverable 6 (provider & generation config, prompts, sample requests,
                                     structured responses, invalid responses and retry evidence)
* reports/python_validation_evidence/ Deliverable 7 (one worked example per validation type)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from sqlalchemy import func, select

from supportnova.core.config import get_settings
from supportnova.database.base import session_scope
from supportnova.database.models import (
    AIRun,
    Complaint,
    EvaluationRun,
    Prompt,
    User,
    ValidationCheck,
    ValidationResult,
)
from supportnova.reporting import builders
from supportnova.reporting.exports import render
from supportnova.services.rules import rule_service

OUT = ROOT / "reports"


def write(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8", newline="\n")
    else:
        path.write_bytes(content)
    print(f"  wrote {path.relative_to(ROOT)}")


def export_report(db: Any, matrix: Any, key: str, folder: str, params: builders.ReportParams, formats: tuple[str, ...]) -> Any:
    report = builders.build(db, matrix, key, params)
    for fmt in formats:
        content, _media, ext = render(report, fmt)
        write(OUT / folder / f"{key}.{ext}", content)
    return report


def comparison(db: Any, matrix: Any, run_id: int | None) -> None:
    q = select(EvaluationRun).where(EvaluationRun.status == "completed", EvaluationRun.n_cases >= 100)
    run = db.get(EvaluationRun, run_id) if run_id else db.execute(q.order_by(EvaluationRun.id.desc())).scalars().first()
    if run is None:
        print("  ! no completed evaluation run with >= 100 cases - start one from the Evaluation page first")
        return
    export_report(db, matrix, "genai-python-comparison", "genai_python_comparison", builders.ReportParams(run_id=run.id),
                  ("pdf", "xlsx", "csv"))
    m = run.metrics or {}
    head = m.get("headline", {})
    lines = [
        "# GenAI vs Python comparison - unseen holdout cases (SRS Deliverable 8)", "",
        f"* Evaluation run **#{run.id}** on dataset `{run.split}` - **{run.n_done} unseen cases** "
        f"(holdout scenarios never used for tuning the rules or prompts).",
        f"* GenAI provider / model: `{run.provider}` / `{run.model}`",
        f"* Prompt versions: `{json.dumps(run.prompt_versions)}` - ruleset hash `{run.ruleset_hash}`",
        f"* Duration: {run.duration_seconds} s (p50 {m.get('latency_ms', {}).get('p50')} ms / p95 {m.get('latency_ms', {}).get('p95')} ms "
        "per complaint, full pipeline)", "",
        "## Headline", "", "| Metric | Value |", "|---|---|",
    ]
    for k, v in head.items():
        lines.append(f"| {k.replace('_', ' ')} | {v if v is not None else '-'} |")
    lines += ["", "## Accuracy against the expected labels, per field", "",
              "| Field | Python (Pipeline 2) | GenAI (Pipeline 1) | GenAI-Python agreement | n |", "|---|---|---|---|---|"]
    for field, f in (m.get("fields") or {}).items():
        def p(x: Any) -> str:
            return "-" if x is None else f"{x * 100:.1f}%"
        lines.append(f"| {field} | {p(f.get('python_ok'))} | {p(f.get('ai_ok'))} | {p(f.get('ai_vs_python'))} | {f.get('n')} |")
    lines += ["", "## Safety nets", "", f"* Prompt injection: {m.get('prompt_injection')}", f"* Manual review: {m.get('manual_review')}",
              f"* Duplicates: {m.get('duplicates')} - repeats: {m.get('repeats')}", f"* Verification outcomes: {m.get('verification')}",
              "", "## By difficulty type", "", "| Type | n | Python all key fields right | GenAI all key fields right | Verified | Manual review |",
              "|---|---|---|---|---|---|"]
    for t, v in (m.get("by_difficulty") or {}).items():
        lines.append(f"| {t} | {v['n']} | {v['python_key_match']} | {v['ai_key_match']} | {v['verified']} | {v['review']} |")
    lines += ["", "The per-case table (complaint ID, expected / GenAI / Python category, department, urgency, escalation, policy "
              "reference, match, verification status and the explanation of every disagreement) is in "
              "`genai-python-comparison.pdf|xlsx|csv` next to this file.", ""]
    write(OUT / "genai_python_comparison" / "summary.md", "\n".join(lines))


def security(db: Any, matrix: Any) -> None:
    from supportnova.services import lab
    export_report(db, matrix, "security", "security_adversarial", builders.ReportParams(), ("pdf", "xlsx"))
    runs = lab.list_runs(db, limit=200)
    latest: dict[str, dict[str, Any]] = {}
    for r in runs:  # newest first: keep the latest run of each scenario
        latest.setdefault(r["scenario_id"] or r["complaint_ref"], r)
    lines = ["# Security and adversarial testing (SRS Deliverable 10)", "",
             "Each scenario in `config/adversarial_scenarios.yaml` is run through the production pipeline; fault profiles "
             "deliberately corrupt the GenAI output. The expectation column states what Python validation had to do.", "",
             "| Scenario | Group | Complaint | Verification | Injection | Checks that caught it | Expectation |", "|---|---|---|---|---|---|---|"]
    for r in sorted(latest.values(), key=lambda x: x.get("scenario_id") or ""):
        lines.append(f"| {r.get('scenario_id') or 'custom'} | {r.get('group')} | {r['complaint_ref']} | {r['verification_status']} | "
                     f"{'yes' if r['injection_detected'] else 'no'} | {', '.join(r.get('failed_checks', [])[:6]) or '-'} | "
                     f"{ {True: 'met', False: 'NOT met', None: '-'}[r.get('met')] } |")
    met = sum(1 for r in latest.values() if r.get("met") is True)
    lines += ["", f"**{met} of {len(latest)} scenarios met their expectations.**", "",
              "Automated tests for unauthorised access, CSRF, lockout, tenant isolation, upload validation, the append-only "
              "audit trigger and the injection corpora live in `tests/backend/api/test_security_api.py` and "
              "`tests/backend/unit/test_perception_security.py`.", ""]
    write(OUT / "security_adversarial" / "summary.md", "\n".join(lines))


def rule_matrix(db: Any) -> None:
    from supportnova.api.v1.rules import export_rules
    admin = db.execute(select(User).where(User.email == "admin@lumora.example")).scalar_one()
    for fmt in ("xlsx", "pdf", "csv", "yaml"):
        resp = export_rules(format=fmt, user=admin, db=db)
        write(OUT / "rule_matrix" / f"complaint_resolution_rule_matrix.{fmt}", bytes(resp.body))


def genai_evidence(db: Any) -> None:
    s = get_settings()
    folder = OUT / "genai_pipeline_evidence"
    config = {"provider": s.resolved_provider, "model": s.resolved_model, "api_key_configured": s.ai_configured,
              "api_key_location": "server-side only (AI_API_KEY in .env.secrets); never sent to the React frontend",
              "generation": {"temperature": s.ai_temperature, "max_output_tokens": s.ai_max_output_tokens, "timeout_seconds": s.ai_timeout_seconds,
                             "max_retries": s.ai_max_retries, "claude_effort": s.ai_effort, "claude_refusal_fallback": s.ai_refusal_fallback,
                             "structured_output": "JSON schema (schemas/ai/*.schema.json), validated again by jsonschema + Pydantic"},
              "providers_supported": ["openai (REST, default model gpt-4.1-mini)", "anthropic (official SDK, default model claude-opus-5)",
                                      "gemini (REST, default model gemini-2.5-flash)"]}
    write(folder / "provider_and_generation_config.json", json.dumps(config, indent=2))
    prompts = []
    for p in db.execute(select(Prompt)).scalars():
        for v in p.versions:
            prompts.append({"prompt_key": p.prompt_key, "version": v.version, "status": v.status, "sha256": v.sha256,
                            "output_schema": v.output_schema, "params": v.params, "changelog": v.changelog,
                            "system_template": v.system_template, "user_template": v.user_template})
    write(folder / "prompt_templates_and_versions.json", json.dumps(prompts, indent=2))

    def runs_for(complaint: Complaint) -> list[dict[str, Any]]:
        rows = db.execute(select(AIRun).where(AIRun.complaint_id == complaint.id).order_by(AIRun.id)).scalars().all()
        return [{"stage": r.stage, "attempt": r.attempt, "provider": r.provider, "model": r.model,
                 "prompt": f"{r.prompt_key}@{r.prompt_version}", "request": r.request, "parsed_ok": r.parsed_ok,
                 "error_type": r.error_type, "error_message": r.error_message, "latency_ms": r.latency_ms,
                 "fault_injection": r.fault_injection, "response_text": r.response_text} for r in rows]
    normal = db.execute(select(Complaint).where(Complaint.source == "dataset", Complaint.verification_status.in_(["Verified", "Human Verified"]))
                        .order_by(Complaint.id)).scalars().first()
    if normal:
        write(folder / "sample_request_and_structured_response.json", json.dumps({"complaint_ref": normal.complaint_ref,
                                                                                  "attempts": runs_for(normal)}, indent=2, default=str))
    examples: dict[str, dict[str, Any]] = {}  # newest example of each kind of invalid output
    for run, complaint in db.execute(select(AIRun, Complaint).join(Complaint, Complaint.id == AIRun.complaint_id)
                                     .where(AIRun.parsed_ok.is_(False)).order_by(AIRun.id.desc())).tuples():
        kind = run.fault_injection or run.error_type or "invalid_output"
        if kind not in examples:
            examples[kind] = {"kind": kind, "complaint_ref": complaint.complaint_ref, "attempts": runs_for(complaint)}
    if examples:
        write(folder / "invalid_response_and_retry.json", json.dumps({
            "explanation": ("Each example's attempt 1 was rejected by the structured-output validator (jsonschema + Pydantic); the "
                            "errors were sent back to the model as a correction and the retry was accepted. The invalid outputs were "
                            "produced on purpose by the Lab fault profiles, which are recorded on every attempt (fault_injection)."),
            "examples": list(examples.values())}, indent=2, default=str))
    stats = dict(db.execute(select(AIRun.parsed_ok, func.count()).group_by(AIRun.parsed_ok)).tuples().all())
    write(folder / "attempt_statistics.json", json.dumps({"valid_attempts": stats.get(True, 0), "invalid_attempts": stats.get(False, 0)}, indent=2))


EVIDENCE_TYPES = [
    ("Complaint classification validation", ["CLS-001", "CLS-002"]), ("Routing validation", ["RTE-001", "RTE-002"]),
    ("Priority validation", ["PRI-001", "PRI-002", "PRI-003"]), ("Escalation validation", ["ESC-001", "ESC-002", "ESC-004"]),
    ("Policy validation", ["POL-001", "POL-002", "POL-003", "POL-006"]), ("Resolution validation", ["RES-001", "RES-002", "RES-004"]),
    ("Source traceability", ["HAL-001", "HAL-004", "SCH-004"]), ("Unsupported promise detection", ["RSP-002", "RSP-003", "RSP-004"]),
    ("Contradiction detection", ["RES-004", "POL-006"]), ("Schema validation", ["SCH-001", "SCH-002", "SCH-003"]),
]


def python_evidence(db: Any) -> None:
    folder = OUT / "python_validation_evidence"
    lines = ["# Python ground-truth validation evidence (SRS Deliverable 7)", "",
             "One real example per validation type, taken from the database: the check, what the rules expected, what the "
             "GenAI proposed, and the outcome. Every complaint listed can be opened in the UI.", ""]
    dump: list[dict[str, Any]] = []
    for title, codes in EVIDENCE_TYPES:
        lines += [f"## {title}", ""]
        for code in codes:
            row = db.execute(select(ValidationCheck, ValidationResult.complaint_id).join(ValidationResult, ValidationResult.id == ValidationCheck.result_id)
                             .where(ValidationCheck.code == code, ValidationCheck.status == "fail").order_by(ValidationCheck.id.desc())).first()
            if row is None:
                row = db.execute(select(ValidationCheck, ValidationResult.complaint_id).join(ValidationResult, ValidationResult.id == ValidationCheck.result_id)
                                 .where(ValidationCheck.code == code).order_by(ValidationCheck.id.desc())).first()
            if row is None:
                continue
            ch, cid = row
            c = db.get(Complaint, cid)
            lines.append(f"* **{ch.code} {ch.name}** ({ch.severity}) - `{c.complaint_ref if c else cid}` -> **{ch.status}**: {ch.message}")
            dump.append({"type": title, "code": ch.code, "name": ch.name, "severity": ch.severity, "status": ch.status,
                         "complaint_ref": c.complaint_ref if c else None, "message": ch.message, "expected": ch.expected, "actual": ch.actual,
                         "rule_refs": ch.rule_refs, "policy_refs": ch.policy_refs})
        lines.append("")
    write(folder / "README.md", "\n".join(lines))
    write(folder / "examples.json", json.dumps(dump, indent=2, default=str))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run-id", type=int, default=None, help="evaluation run for Deliverable 8 (default: latest with >= 100 cases)")
    args = ap.parse_args()
    with session_scope() as db:
        matrix = rule_service.matrix(db)
        print("Deliverable 8 - GenAI vs Python comparison")
        comparison(db, matrix, args.run_id)
        print("Deliverable 9 - complaint intelligence")
        export_report(db, matrix, "complaint-intelligence", "complaint_intelligence", builders.ReportParams(), ("pdf", "xlsx"))
        print("Deliverable 10 - security and adversarial testing")
        security(db, matrix)
        print("SRS Step 67 - operational reports")
        for key in ("complaint-analysis", "department-performance", "escalations", "sla-status", "policy-usage",
                    "resolution-compliance", "manual-reviews"):
            export_report(db, matrix, key, "operations", builders.ReportParams(), ("pdf", "xlsx"))
        print("Deliverable 5 - Rule Matrix")
        rule_matrix(db)
        print("Deliverable 6 - GenAI pipeline evidence")
        genai_evidence(db)
        print("Deliverable 7 - Python validation evidence")
        python_evidence(db)


if __name__ == "__main__":
    main()
