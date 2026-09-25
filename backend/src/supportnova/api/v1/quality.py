"""Model evaluation (GenAI vs Python vs expected) and the Adversarial Lab."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from supportnova.api.deps import db_session, require
from supportnova.core.config import get_settings
from supportnova.core.errors import ValidationFailed
from supportnova.database.models import EvaluationResult, EvaluationRun, User
from supportnova.genai_pipeline.fault_injection import PROFILES
from supportnova.reporting import builders
from supportnova.reporting.exports import render
from supportnova.services import datasets, lab
from supportnova.services import evaluation as ev
from supportnova.services.rules import rule_service
from supportnova.services.worker import worker

router = APIRouter(tags=["quality"])


# ------------------------------------------------------------------------------------------ evaluation
@router.get("/evaluation/datasets")
def list_datasets(user: User = Depends(require("evaluation:read"))) -> dict[str, Any]:
    return {"items": datasets.available(), "fault_profiles": PROFILES}


class EvaluationIn(BaseModel):
    dataset: str = "holdout"
    label: str = Field(default="", max_length=120)
    limit: int | None = Field(default=None, ge=1, le=datasets.MAX_RECORDS)
    fault_profile: str | None = None


@router.post("/evaluation/runs", status_code=202)
def start_run(body: EvaluationIn, user: User = Depends(require("evaluation:run")), db: Session = Depends(db_session)) -> dict[str, Any]:
    run = ev.start(db, dataset=body.dataset, records=None, label=body.label, limit=body.limit, fault_profile=body.fault_profile or None,
                   actor=user)
    return ev.run_json(run)


@router.post("/evaluation/runs/upload", status_code=202)
async def start_run_upload(file: UploadFile = File(...), label: str = Form(""), fault_profile: str = Form(""),
                           user: User = Depends(require("evaluation:run")), db: Session = Depends(db_session)) -> dict[str, Any]:
    """Evaluate an external (e.g. hidden) dataset file: JSON array, JSONL or the flattened CSV format."""
    data = await file.read()
    if len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise ValidationFailed("The dataset file is too large.")
    fmt = (file.filename or "").rsplit(".", 1)[-1].lower()
    records = datasets.parse(data, fmt)
    run = ev.start(db, dataset=None, records=records, label=label or (file.filename or "uploaded dataset"), limit=None,
                   fault_profile=fault_profile or None, actor=user)
    return ev.run_json(run)


@router.get("/evaluation/runs")
def list_runs(user: User = Depends(require("evaluation:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    rows = db.execute(select(EvaluationRun).order_by(EvaluationRun.id.desc()).limit(50)).scalars().all()
    return {"items": [ev.run_json(r) for r in rows]}


@router.get("/evaluation/runs/{run_id}")
def get_run(run_id: int, user: User = Depends(require("evaluation:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    return ev.run_json(ev.get_run(db, run_id))


@router.post("/evaluation/runs/{run_id}/cancel")
def cancel_run(run_id: int, user: User = Depends(require("evaluation:run")), db: Session = Depends(db_session)) -> dict[str, Any]:
    ev.get_run(db, run_id)
    ev.cancel(run_id)
    return {"id": run_id, "cancelling": True}


@router.get("/evaluation/runs/{run_id}/results")
def run_results(run_id: int, difficulty: str | None = None, mismatches_only: bool = False,
                page: int = Query(default=1, ge=1), page_size: int = Query(default=50, ge=1, le=500),
                user: User = Depends(require("evaluation:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    ev.get_run(db, run_id)
    q = select(EvaluationResult).where(EvaluationResult.run_id == run_id)
    if difficulty:
        q = q.where(EvaluationResult.difficulty_type == difficulty)
    rows = db.execute(q.order_by(EvaluationResult.case_id)).scalars().all()
    if mismatches_only:
        rows = [r for r in rows if any((r.comparison or {}).get(f, {}).get("ai_vs_python") == "mismatch" for f in ev.KEY_FIELDS)]
    total = len(rows)
    rows = rows[(page - 1) * page_size: page * page_size]
    return {"total": total, "page": page, "page_size": page_size, "items": [
        {"case_id": r.case_id, "difficulty_type": r.difficulty_type, "verification_status": r.verification_status,
         "verification_score": r.verification_score, "explanation": r.explanation, "expected": r.expected, "ai": r.ai,
         "python": r.python, "comparison": r.comparison, "complaint_ref": f"R{run_id}-{r.case_id}"[:20]} for r in rows]}


@router.get("/evaluation/runs/{run_id}/report")
def run_report(run_id: int, format: str = "pdf", user: User = Depends(require("reports:export")),
               db: Session = Depends(db_session)) -> Response:
    ev.get_run(db, run_id)
    report = builders.genai_python_comparison(db, rule_service.matrix(db), builders.ReportParams(run_id=run_id))
    content, media, ext = render(report, format)
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="evaluation-run-{run_id}.{ext}"'})


# ------------------------------------------------------------------------------------------ lab
@router.get("/lab/scenarios")
def lab_scenarios(user: User = Depends(require("lab:use"))) -> dict[str, Any]:
    return {"items": lab.scenarios(), "fault_profiles": PROFILES, "security_samples": lab.security_samples()}


class LabRunIn(BaseModel):
    scenario_id: str | None = None
    fault_profile: str | None = None
    title: str | None = Field(default=None, max_length=180)
    description: str | None = Field(default=None, max_length=8000)
    order_ref: str | None = None
    requested_resolution: str | None = None


@router.post("/lab/runs", status_code=202)
def lab_run(body: LabRunIn, user: User = Depends(require("lab:use")), db: Session = Depends(db_session)) -> dict[str, Any]:
    custom = None if body.scenario_id else {"title": body.title, "description": body.description, "order_ref": body.order_ref,
                                            "requested_resolution": body.requested_resolution or "none"}
    complaint, options = lab.create_run(db, actor=user, scenario_id=body.scenario_id, complaint=custom,
                                        fault_profile=body.fault_profile or None)
    db.commit()
    worker.submit(complaint.id, options)
    return {"complaint_ref": complaint.complaint_ref, "scenario_id": body.scenario_id, "fault_profile": options.fault_profile}


@router.post("/lab/runs/all", status_code=202)
def lab_run_all(user: User = Depends(require("lab:use")), db: Session = Depends(db_session)) -> dict[str, Any]:
    started = []
    for s in lab.scenarios():
        complaint, options = lab.create_run(db, actor=user, scenario_id=s["id"])
        db.commit()
        worker.submit(complaint.id, options)
        started.append({"complaint_ref": complaint.complaint_ref, "scenario_id": s["id"]})
    return {"items": started}


@router.get("/lab/runs")
def lab_runs(user: User = Depends(require("lab:use")), db: Session = Depends(db_session)) -> dict[str, Any]:
    items = lab.list_runs(db)
    return {"items": items, "met": sum(1 for i in items if i.get("met") is True),
            "not_met": sum(1 for i in items if i.get("met") is False)}


@router.post("/lab/document-scan")
async def lab_document_scan(file: UploadFile | None = File(default=None), sample: str = Form(""),
                            user: User = Depends(require("lab:use"))) -> dict[str, Any]:
    """Malicious-document test: parse + injection screening, without adding anything to the knowledge base."""
    if file is not None:
        return lab.document_scan(await file.read(), file.filename or "document")
    if not sample:
        raise ValidationFailed("Upload a document or choose a security sample.")
    path = lab.sample_path(sample)
    return lab.document_scan(path.read_bytes(), path.name)


@router.get("/lab/access-matrix")
def access_matrix(user: User = Depends(require("lab:use"))) -> dict[str, Any]:
    """Server-side RBAC matrix (every endpoint enforces these permissions; see tests/security)."""
    from supportnova.security.rbac import ROLE_NAMES, ROLE_PERMISSIONS
    perms = sorted({p for ps in ROLE_PERMISSIONS.values() for p in ps})
    return {"roles": [{"code": r, "name": ROLE_NAMES[r][0]} for r in ROLE_PERMISSIONS], "permissions": perms,
            "matrix": {r: {p: p in ps for p in perms} for r, ps in ROLE_PERMISSIONS.items()}}
