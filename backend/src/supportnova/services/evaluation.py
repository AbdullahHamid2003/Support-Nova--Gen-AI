"""Model evaluation over unseen complaints (SRS Deliverable 8, hidden-dataset readiness).

A run imports every case of a dataset as a sandboxed complaint (source ``evaluation``, refs
``R<run>-<case>``), processes it through the *production* pipeline, then scores three things
against the dataset's expected labels: the GenAI proposal (Pipeline 1), the Python ground truth
(Pipeline 2) and their agreement. Expected labels are read only here - never by the pipeline.
Each customer's cases are processed chronologically (customers in parallel, see services/batch.py), so
repeat/duplicate detection sees history exactly as production would.
"""

from __future__ import annotations

import threading
import time
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from supportnova.audit import service as audit
from supportnova.core.config import get_settings
from supportnova.core.errors import Conflict, NotFound, ValidationFailed
from supportnova.core.logging import get_logger
from supportnova.core.timeutil import to_datetime, utcnow
from supportnova.database.base import session_scope
from supportnova.database.models import (
    Analysis,
    Complaint,
    Customer,
    EvaluationResult,
    EvaluationRun,
    User,
    ValidationResult,
)
from supportnova.genai_pipeline.fault_injection import PROFILES
from supportnova.genai_pipeline.prompts import active_prompt
from supportnova.services import datasets
from supportnova.services.batch import run_by_customer
from supportnova.services.complaints import create_complaint
from supportnova.services.pipeline import PipelineOptions, process_complaint
from supportnova.services.rules import rule_service

log = get_logger(__name__)
_running: dict[int, threading.Thread] = {}
_cancel: set[int] = set()

# field -> (kind) ; kind "exact" or "set"
FIELDS: dict[str, str] = {
    "category": "exact", "subcategory": "exact", "department": "exact", "supporting_departments": "set", "urgency": "exact",
    "priority": "exact", "escalation_required": "exact", "escalation_level": "exact", "refund_eligibility": "exact",
    "replacement_eligibility": "exact", "compensation_eligibility": "exact", "follow_up_type": "exact",
    "resolution_rule": "exact", "policy_references": "set", "missing_information": "set",
}
KEY_FIELDS = ("category", "subcategory", "department", "urgency", "priority", "escalation_level")


def _ai_values(out: dict[str, Any] | None) -> dict[str, Any]:
    if not out:
        return {}
    return {
        "category": out.get("issue_category"), "subcategory": out.get("subcategory"), "department": out.get("department"),
        "supporting_departments": sorted(out.get("supporting_departments") or []), "urgency": out.get("urgency"),
        "priority": out.get("priority"), "escalation_required": out.get("escalation_required"),
        "escalation_level": out.get("escalation_level"),
        "refund_eligibility": (out.get("refund_eligibility") or {}).get("status"),
        "replacement_eligibility": (out.get("replacement_eligibility") or {}).get("status"),
        "compensation_eligibility": (out.get("compensation_eligibility") or {}).get("status"),
        "follow_up_type": out.get("follow_up_type"), "resolution_rule": None,
        "policy_references": sorted({f"{p.get('policy_id')}:{p.get('section')}" for p in out.get("policy_references") or []}),
        "missing_information": sorted({m.get("field") for m in out.get("missing_information") or [] if m.get("field")}),
        "prompt_injection": bool(out.get("manipulation_detected")),
    }


def _python_values(vd: dict[str, Any] | None) -> dict[str, Any]:
    if not vd:
        return {}
    cls, esc, elig = vd.get("classification") or {}, vd.get("escalation") or {}, vd.get("eligibility") or {}
    return {
        # Python's own classification (the final decision may carry a provisional GenAI label when Python is unsure)
        "category": cls.get("python_category", cls.get("category")) if cls.get("source") == "ai_unconfirmed" else cls.get("category"),
        "subcategory": cls.get("python_primary", cls.get("subcategory")) if cls.get("source") == "ai_unconfirmed" else cls.get("subcategory"),
        "classification_source": cls.get("source"), "department": vd.get("department"),
        "supporting_departments": sorted(vd.get("supporting_departments") or []), "urgency": vd.get("urgency"),
        "priority": vd.get("priority"), "escalation_required": esc.get("required"), "escalation_level": esc.get("level"),
        "refund_eligibility": elig.get("refund"), "replacement_eligibility": elig.get("replacement"),
        "compensation_eligibility": elig.get("compensation"), "follow_up_type": (vd.get("follow_up") or {}).get("type"),
        "resolution_rule": (vd.get("selected_rule") or {}).get("rule_id"), "policy_references": sorted(vd.get("policy_refs") or []),
        "missing_information": sorted({m.get("field") for m in vd.get("missing_information") or [] if m.get("field")}),
    }


def _match(kind: str, a: Any, b: Any) -> str:
    if kind == "set":
        x, y = set(map(str, a or [])), set(map(str, b or []))
        if x == y:
            return "match"
        return "partial" if x & y else "mismatch"
    return "match" if a == b else "mismatch"


def score_case(expected: dict[str, Any] | None, ai: dict[str, Any], py: dict[str, Any]) -> dict[str, Any]:
    rows = {}
    for field, kind in FIELDS.items():
        entry: dict[str, Any] = {"ai": ai.get(field), "python": py.get(field), "ai_vs_python": _match(kind, ai.get(field), py.get(field))
                                 if ai else None}
        if expected and field in expected:
            exp = sorted(expected[field]) if kind == "set" and isinstance(expected[field], list) else expected[field]
            entry["expected"] = exp
            entry["ai_ok"] = _match(kind, ai.get(field), exp) if ai else None
            entry["python_ok"] = _match(kind, py.get(field), exp)
        rows[field] = entry
    return rows


def _explain(case: dict[str, Any], expected: dict[str, Any] | None) -> str:
    parts = []
    for field in (*KEY_FIELDS, "escalation_required", "refund_eligibility", "compensation_eligibility"):
        row = case.get(field) or {}
        if row.get("ai_vs_python") == "mismatch":
            reason = ""
            if expected and row.get("python_ok") == "match":
                reason = " - the rules match the expected label"
            elif expected and row.get("ai_ok") == "match":
                reason = " - the AI matches the expected label (gap in the rules)"
            parts.append(f"{field.replace('_', ' ')}: AI '{row.get('ai')}' vs rules '{row.get('python')}'{reason}")
    return "; ".join(parts) or "The AI and the rules agree on all key fields."


# ------------------------------------------------------------------------------------------ runs
def start(db: Session, *, dataset: str | None, records: list[dict[str, Any]] | None, label: str, limit: int | None,
          fault_profile: str | None, actor: User) -> EvaluationRun:
    if fault_profile and fault_profile not in PROFILES:
        raise ValidationFailed(f"Unknown fault profile '{fault_profile}'.")
    if any(t.is_alive() for t in _running.values()):
        raise Conflict("An evaluation run is already in progress; wait for it to finish or cancel it.")
    if records is None:
        path = datasets.resolve(dataset or "holdout")
        if not path.exists():
            raise ValidationFailed(f"Dataset file {path.name} does not exist yet - run scripts/generate_dataset.py.")
        records = datasets.read_path(path)
    if limit:
        records = records[: max(1, limit)]
    settings = get_settings()
    from supportnova.genai_pipeline.providers import get_provider
    provider = get_provider()
    prompts = {k: active_prompt(db, k).version for k in ("complaint_analysis", "customer_communication")}
    run = EvaluationRun(status="queued", split=dataset or "upload", label=label[:120] or f"{dataset or 'upload'} evaluation",
                        provider=provider.name, model=provider.model, fault_injection=fault_profile,
                        prompt_versions=prompts, ruleset_hash=rule_service.matrix(db).ruleset_hash, n_cases=len(records),
                        created_by_id=actor.id, metrics={"settings": {"ai_max_retries": settings.ai_max_retries}})
    db.add(run)
    db.flush()
    audit.record(db, action="evaluation.started", entity_type="evaluation_run", entity_id=run.id, actor=actor,
                 summary=f"Evaluation run on {run.split} ({len(records)} cases, {provider.name}/{provider.model})",
                 details={"fault_profile": fault_profile, "prompts": prompts})
    db.commit()
    thread = threading.Thread(target=_execute, args=(run.id, records, fault_profile, actor.id),
                              name=f"evaluation-{run.id}", daemon=True)
    _running[run.id] = thread
    thread.start()
    return run


def cancel(run_id: int) -> None:
    _cancel.add(run_id)


def is_running(run_id: int) -> bool:
    t = _running.get(run_id)
    return bool(t and t.is_alive())


def _customer(db: Session, rec: dict[str, Any]) -> Customer | None:
    ref = (rec.get("customer_ref") or "").strip().upper()
    if not ref:
        return None
    row = db.execute(select(Customer).where(Customer.customer_ref == ref)).scalar_one_or_none()
    if row is None:
        row = Customer(customer_ref=ref[:16], full_name=str(rec.get("customer_name") or ref)[:160],
                       email=f"{ref.lower()}@customers.lumora.invalid", customer_type=rec.get("customer_type") or "individual")
        db.add(row)
        db.flush()
    return row


def _execute(run_id: int, records: list[dict[str, Any]], fault_profile: str | None, actor_id: int) -> None:
    started = time.perf_counter()
    try:
        with session_scope() as db:
            run = db.get(EvaluationRun, run_id)
            assert run is not None
            run.status = "running"
        ordered = sorted(records, key=lambda r: (str(r.get("complaint_date") or ""), str(r.get("complaint_id"))))
        case_ids = {str(r.get("complaint_id")).upper() for r in ordered}
        prefix = f"R{run_id}-"

        def evaluate(rec: dict[str, Any]) -> None:
            _evaluate_case(run_id, prefix, rec, case_ids, fault_profile, actor_id)
            with session_scope() as db:
                db.execute(update(EvaluationRun).where(EvaluationRun.id == run_id).values(n_done=EvaluationRun.n_done + 1))

        run_by_customer(ordered, evaluate, workers=get_settings().batch_workers, stop=lambda: run_id in _cancel)
        with session_scope() as db:
            run = db.get(EvaluationRun, run_id)
            assert run is not None
            results = db.execute(select(EvaluationResult).where(EvaluationResult.run_id == run_id)).scalars().all()
            run.metrics = {**(run.metrics or {}), **compute_metrics(results)}
            run.status = "cancelled" if run_id in _cancel else "completed"
            run.duration_seconds = round(time.perf_counter() - started, 1)
            run.completed_at = utcnow()
            audit.record(db, action="evaluation.completed", entity_type="evaluation_run", entity_id=run_id,
                         summary=f"Evaluation run {run.status}: {run.n_done}/{run.n_cases} cases",
                         details={"headline": run.metrics.get("headline")})
    except Exception as exc:  # pragma: no cover - defensive
        log.error("evaluation run failed", exc_info=True)
        with session_scope() as db:
            run = db.get(EvaluationRun, run_id)
            if run is not None:
                run.status, run.error = "failed", str(exc)[:1000]
                run.duration_seconds = round(time.perf_counter() - started, 1)
    finally:
        _cancel.discard(run_id)


def _evaluate_case(run_id: int, prefix: str, rec: dict[str, Any], case_ids: set[str], fault_profile: str | None,
                   actor_id: int) -> None:
    case_id = str(rec.get("complaint_id") or "").upper()[:20]
    expected = rec.get("expected") or None
    prev = (rec.get("previous_complaint_reference") or "").strip().upper()
    mapped_prev = f"{prefix}{prev}"[:20] if prev and prev in case_ids else (prev or None)
    t0 = time.perf_counter()
    complaint_id: int | None = None
    intake_error = None
    try:
        with session_scope() as db:
            customer = _customer(db, rec)
            submitter = db.get(User, actor_id)
            complaint = create_complaint(db, datasets.to_submission(rec, previous_ref=mapped_prev), submitted_by=submitter,
                                         customer=customer, source="evaluation", created_at=to_datetime(rec.get("complaint_date")),
                                         dataset_case_id=case_id, complaint_ref=f"{prefix}{case_id}"[:20],
                                         skip_duplicate_check=True, lenient=True)
            complaint_id = complaint.id
    except ValidationFailed as exc:
        intake_error = f"Rejected at intake: {exc.message} " + "; ".join(d.get("message", "") for d in (exc.details or []))
    outcome: dict[str, Any] = {}
    if complaint_id is not None:
        outcome = process_complaint(complaint_id, PipelineOptions(trigger="evaluation", fault_profile=fault_profile, actor_id=actor_id,
                                                                  auto_assign=False))
    latency = round((time.perf_counter() - t0) * 1000)
    if complaint_id is not None and rec.get("seed_status"):
        # world state for later cases (e.g. a prior complaint that had been resolved) - not a label
        from supportnova.services.seed import apply_seed_status
        with session_scope() as db:
            c0 = db.get(Complaint, complaint_id)
            if c0 is not None:
                apply_seed_status(db, c0, rec.get("seed_status"), full=False)
    with session_scope() as db:
        ai_out, vd, status, score, dup, rep, injection = None, None, "Rejected", None, None, None, False
        if complaint_id is not None:
            c = db.get(Complaint, complaint_id)
            assert c is not None
            analysis = db.execute(select(Analysis).where(Analysis.complaint_id == c.id).order_by(Analysis.id.desc())).scalars().first()
            vr = db.execute(select(ValidationResult).where(ValidationResult.complaint_id == c.id)
                            .order_by(ValidationResult.id.desc())).scalars().first()
            ai_out = analysis.output if analysis else None
            vd = vr.validated_decision if vr else None
            status, score, injection = c.verification_status, c.verification_score, c.injection_detected
            if c.is_duplicate and c.duplicate_of_id:
                other = db.get(Complaint, c.duplicate_of_id)
                dup = other.dataset_case_id if other else None
                status = "Duplicate"
            if c.is_repeat and c.repeat_of_id:
                other = db.get(Complaint, c.repeat_of_id)
                rep = other.dataset_case_id if other else None
        ai, py = _ai_values(ai_out), _python_values(vd)
        comparison = score_case(expected, ai, py) if (ai or py) else {}
        special: dict[str, Any] = {"prompt_injection": {"detected": injection, "ai_flagged": ai.get("prompt_injection")},
                                   "duplicate_of": dup, "repeat_of": rep, "latency_ms": latency, "intake_error": intake_error,
                                   "pipeline_ok": outcome.get("ok") if outcome else False}
        if expected:
            special["prompt_injection"]["expected"] = bool(expected.get("prompt_injection"))
            special["manual_review"] = {"expected": bool(expected.get("manual_review_expected")), "actual": status == "Manual Review"}
            exp_dup = expected.get("is_duplicate_of") or expected.get("is_near_duplicate_of")
            special["duplicate_expected"] = exp_dup
            special["repeat_expected"] = expected.get("is_repeat_of")
        comparison["_special"] = special
        db.add(EvaluationResult(run_id=run_id, case_id=case_id, difficulty_type=str(rec.get("difficulty_type") or "")[:40],
                                expected={k: expected.get(k) for k in (*FIELDS, "prompt_injection", "manual_review_expected",
                                                                       "is_duplicate_of", "is_near_duplicate_of", "is_repeat_of")}
                                if expected else {},
                                ai=ai, python=py, comparison=comparison, verification_status=status, verification_score=score,
                                explanation=intake_error or ("Linked as duplicate of " + str(dup) if dup else _explain(comparison, expected))))


# ------------------------------------------------------------------------------------------ metrics
def compute_metrics(results: Sequence[EvaluationResult]) -> dict[str, Any]:
    n = len(results)
    per_field: dict[str, dict[str, Any]] = {}
    for field in FIELDS:
        c: Counter[str] = Counter()
        for r in results:
            row = (r.comparison or {}).get(field)
            if not row:
                continue
            for side in ("ai_ok", "python_ok", "ai_vs_python"):
                if row.get(side) is not None:
                    c[f"{side}:{row[side]}"] += 1
                    c[f"{side}:n"] += 1
        per_field[field] = {
            side: round(c[f"{side}:match"] / c[f"{side}:n"], 4) if c[f"{side}:n"] else None for side in ("ai_ok", "python_ok", "ai_vs_python")}
        per_field[field]["n"] = c["python_ok:n"] or c["ai_vs_python:n"]
    statuses = Counter(r.verification_status for r in results)
    specials = [(r.comparison or {}).get("_special", {}) for r in results]
    inj_exp = [s for s in specials if "expected" in (s.get("prompt_injection") or {})]
    tp = sum(1 for s in inj_exp if s["prompt_injection"]["expected"] and s["prompt_injection"]["detected"])
    fn = sum(1 for s in inj_exp if s["prompt_injection"]["expected"] and not s["prompt_injection"]["detected"])
    fp = sum(1 for s in inj_exp if not s["prompt_injection"]["expected"] and s["prompt_injection"]["detected"])
    mr = [s["manual_review"] for s in specials if "manual_review" in s]
    mr_tp = sum(1 for m in mr if m["expected"] and m["actual"])
    dup_cases = [s for s in specials if s.get("duplicate_expected")]
    rep_cases = [s for s in specials if s.get("repeat_expected")]
    caught = 0
    ai_wrong = 0
    for r in results:
        rows = r.comparison or {}
        wrong = [f for f in KEY_FIELDS if (rows.get(f) or {}).get("ai_ok") == "mismatch"]
        if wrong:
            ai_wrong += 1
            fixed = all((rows.get(f) or {}).get("python_ok") == "match" for f in wrong)
            if fixed or r.verification_status == "Manual Review":
                caught += 1
    by_type: dict[str, dict[str, Any]] = defaultdict(lambda: {"n": 0, "python_key_match": 0, "ai_key_match": 0, "verified": 0, "review": 0})
    for r in results:
        rows = r.comparison or {}
        t = by_type[r.difficulty_type or "unspecified"]
        t["n"] += 1
        t["python_key_match"] += all((rows.get(f) or {}).get("python_ok") in ("match", None) for f in KEY_FIELDS)
        t["ai_key_match"] += all((rows.get(f) or {}).get("ai_ok") in ("match", None) for f in KEY_FIELDS)
        t["verified"] += r.verification_status in ("Verified", "Human Verified")
        t["review"] += r.verification_status == "Manual Review"
    latencies = sorted(s.get("latency_ms", 0) for s in specials)

    def pct(q: float) -> int | None:
        return latencies[min(len(latencies) - 1, int(q * len(latencies)))] if latencies else None
    key_py = [per_field[f]["python_ok"] for f in KEY_FIELDS if per_field[f]["python_ok"] is not None]
    key_ai = [per_field[f]["ai_ok"] for f in KEY_FIELDS if per_field[f]["ai_ok"] is not None]
    key_agree = [per_field[f]["ai_vs_python"] for f in KEY_FIELDS if per_field[f]["ai_vs_python"] is not None]
    return {
        "headline": {
            "cases": n, "python_key_field_accuracy": round(sum(key_py) / len(key_py), 4) if key_py else None,
            "ai_key_field_accuracy": round(sum(key_ai) / len(key_ai), 4) if key_ai else None,
            "ai_python_key_agreement": round(sum(key_agree) / len(key_agree), 4) if key_agree else None,
            "verified_rate": round((statuses.get("Verified", 0)) / n, 4) if n else None,
            "manual_review_rate": round(statuses.get("Manual Review", 0) / n, 4) if n else None,
            "ai_errors_caught": caught, "ai_cases_with_key_errors": ai_wrong,
            "ai_error_catch_rate": round(caught / ai_wrong, 4) if ai_wrong else None,
        },
        "fields": per_field, "verification": dict(statuses),
        "prompt_injection": {"expected": sum(1 for s in inj_exp if s["prompt_injection"]["expected"]), "detected_tp": tp, "missed": fn,
                             "false_positives": fp, "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
                             "precision": round(tp / (tp + fp), 4) if (tp + fp) else None},
        "manual_review": {"expected": sum(m["expected"] for m in mr), "actual": sum(m["actual"] for m in mr), "both": mr_tp,
                          "recall": round(mr_tp / sum(m["expected"] for m in mr), 4) if sum(m["expected"] for m in mr) else None},
        "duplicates": {"expected": len(dup_cases), "linked": sum(1 for s in dup_cases if s.get("duplicate_of"))},
        "repeats": {"expected": len(rep_cases), "detected": sum(1 for s in rep_cases if s.get("repeat_of"))},
        "by_difficulty": {k: v for k, v in sorted(by_type.items())},
        "latency_ms": {"p50": pct(0.5), "p95": pct(0.95), "max": latencies[-1] if latencies else None},
        "rejected_at_intake": sum(1 for s in specials if s.get("intake_error")),
    }


def run_json(run: EvaluationRun) -> dict[str, Any]:
    return {"id": run.id, "status": run.status if not (run.status == "running" and not is_running(run.id)) else "interrupted",
            "split": run.split, "label": run.label, "provider": run.provider, "model": run.model,
            "fault_injection": run.fault_injection, "prompt_versions": run.prompt_versions, "ruleset_hash": run.ruleset_hash,
            "n_cases": run.n_cases, "n_done": run.n_done, "metrics": run.metrics, "error": run.error,
            "duration_seconds": run.duration_seconds, "created_at": run.created_at.isoformat() if run.created_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None}


def get_run(db: Session, run_id: int) -> EvaluationRun:
    run = db.get(EvaluationRun, run_id)
    if run is None:
        raise NotFound(f"Evaluation run {run_id} not found.")
    return run
