"""Manual review queue endpoints (SRS Steps 57-59)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from supportnova.api.deps import db_session, require
from supportnova.api.serializers import complaint_summary, iso, review_reasons_view
from supportnova.database.models import Complaint, User
from supportnova.services import reviews as svc
from supportnova.services.pipeline import PipelineOptions
from supportnova.services.rules import rule_service
from supportnova.services.worker import worker

router = APIRouter(tags=["reviews"])


def _review_json(db: Session, review: Any, matrix: Any) -> dict[str, Any]:
    complaint = db.get(Complaint, review.complaint_id)
    return {"id": review.id, "status": review.status, "reason_codes": review.reason_codes,
            "reasons": review_reasons_view(matrix, review.reasons),
            "priority": review.priority, "assigned_to_id": review.assigned_to_id, "created_at": iso(review.created_at),
            "started_at": iso(review.started_at), "completed_at": iso(review.completed_at), "final_decision": review.final_decision,
            "complaint": complaint_summary(complaint, matrix) if complaint else None,
            "actions": [{"action": a.action, "comment": a.comment, "actor": a.actor_label, "at": iso(a.created_at), "payload": a.payload}
                        for a in review.actions]}


@router.get("/reviews")
def review_queue(status: str | None = None, reason: str | None = None, mine: bool = False, include_lab: bool = False,
                 page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=200),
                 user: User = Depends(require("review:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    matrix = rule_service.matrix(db)
    rows, total = svc.queue(db, status=status, reason=reason, assigned_to=user.id if mine else None, include_lab=include_lab,
                            limit=page_size, offset=(page - 1) * page_size)
    reasons: dict[str, int] = {}
    all_rows, _ = svc.queue(db, status=status, include_lab=include_lab, limit=100000)
    for r in all_rows:
        for code in r.reason_codes or []:
            reasons[code] = reasons.get(code, 0) + 1
    return {"items": [_review_json(db, r, matrix) for r in rows], "total": total, "page": page, "page_size": page_size,
            "reason_counts": reasons}


@router.get("/reviews/{review_id}")
def get_review(review_id: int, user: User = Depends(require("review:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    return _review_json(db, svc.get_review(db, review_id), rule_service.matrix(db))


@router.post("/reviews/{review_id}/claim")
def claim_review(review_id: int, user: User = Depends(require("review:act")), db: Session = Depends(db_session)) -> dict[str, Any]:
    review = svc.claim(db, svc.get_review(db, review_id), user)
    db.commit()
    return _review_json(db, review, rule_service.matrix(db))


class ReviewActionIn(BaseModel):
    action: str
    comment: str = Field(default="", max_length=2000)
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/reviews/{review_id}/actions")
def review_action(review_id: int, body: ReviewActionIn, user: User = Depends(require("review:act")),
                  db: Session = Depends(db_session)) -> dict[str, Any]:
    review = svc.get_review(db, review_id)
    followup = svc.act(db, review, user, action=body.action, payload=body.payload, comment=body.comment)
    db.commit()
    reprocess = followup.get("reprocess")
    if reprocess:
        worker.submit(review.complaint_id, PipelineOptions(trigger=reprocess.get("trigger", "review"), actor_id=user.id,
                                                           tone=reprocess.get("tone"),
                                                           classification_override=reprocess.get("classification_override"),
                                                           link_duplicates=False))
    return {"review": _review_json(db, review, rule_service.matrix(db)), "followup": followup}
