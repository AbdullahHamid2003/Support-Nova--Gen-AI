"""Complaint history, duplicate / near-duplicate and repeat-complaint detection (SRS Steps 52-54)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from supportnova.core.config import get_settings
from supportnova.database.models import Complaint
from supportnova.knowledge_base.embeddings import from_bytes, similarity_vectors
from supportnova.rule_engine.models import RuleMatrix

RESOLVED_STATES = ("Resolved", "Closed")
OPERATIONAL_SOURCES = ("web", "api", "dataset")


def history_scope(complaint: Complaint) -> list[Any]:
    """Which complaints count as this complaint's history. Operational complaints never see evaluation
    or adversarial-lab records. An evaluation case arrives into the live system: it sees the existing
    operational history (read-only) plus earlier cases of its own run (refs share the run prefix),
    never other runs."""
    if complaint.source == "evaluation":
        prefix = complaint.complaint_ref.split("-", 1)[0] + "-"
        return [or_(Complaint.source.in_(OPERATIONAL_SOURCES),
                    and_(Complaint.source == "evaluation", Complaint.complaint_ref.like(prefix + "%")))]
    if complaint.source == "lab":
        return [Complaint.source.in_((*OPERATIONAL_SOURCES, "lab"))]
    return [Complaint.source.in_(OPERATIONAL_SOURCES)]


def complaint_text(c: Complaint) -> str:
    return f"{c.title}\n{c.description_normalized or c.description}"


def analyse_history(db: Session, complaint: Complaint, *, primary_subcategory: str | None, order_ref: str | None,
                    matrix: RuleMatrix, signals: set[str]) -> dict[str, Any]:
    settings = get_settings()
    window = int(matrix.param("repeat_window_days"))
    out: dict[str, Any] = {"prior_same_issue_count": 0, "unresolved_prior_same_issue": 0, "references_resolved_complaint": False,
                           "exact_duplicate_of": None, "near_duplicate_of": None, "near_duplicate_similarity": None,
                           "repeat_of": None, "history": [], "related": []}
    vec = from_bytes(complaint.embedding)
    if vec is None:
        vec = similarity_vectors([complaint_text(complaint)])[0]
    previous_ref = (complaint.previous_complaint_ref or "").upper() or None
    if previous_ref:
        ref_row = db.execute(select(Complaint).where(Complaint.complaint_ref == previous_ref, *history_scope(complaint))
                             ).scalar_one_or_none()
        out["previous_reference_found"] = ref_row is not None
        if ref_row is not None and ref_row.status in RESOLVED_STATES:
            out["references_resolved_complaint"] = True
    if complaint.customer_id is None:
        return out
    anchor = complaint.complaint_date or complaint.created_at
    rows = db.execute(select(Complaint).where(Complaint.customer_id == complaint.customer_id, Complaint.id != complaint.id,
                                              *history_scope(complaint),
                                              Complaint.complaint_date <= anchor,
                                              Complaint.complaint_date >= anchor - timedelta(days=window))
                      .order_by(Complaint.complaint_date.desc()).limit(50)).scalars().all()
    if not rows:
        return out
    vectors = []
    for r in rows:
        v = from_bytes(r.embedding)
        vectors.append(v if v is not None and v.shape == vec.shape else similarity_vectors([complaint_text(r)])[0])
    sims = np.vstack(vectors) @ vec
    same_issue: list[tuple[Complaint, float]] = []
    for r, sim in zip(rows, sims, strict=True):
        sim = float(sim)
        out["history"].append({"complaint_ref": r.complaint_ref, "date": (r.complaint_date or r.created_at).date().isoformat(),
                               "subcategory": r.subcategory_code, "status": r.status, "order_ref": r.order_ref,
                               "similarity": round(sim, 3)})
        if r.text_hash and r.text_hash == complaint.text_hash and out["exact_duplicate_of"] is None:
            out["exact_duplicate_of"] = r.complaint_ref
            continue
        if sim >= settings.near_duplicate_threshold and out["near_duplicate_of"] is None:
            out["near_duplicate_of"], out["near_duplicate_similarity"] = r.complaint_ref, round(sim, 3)
            continue
        related = (previous_ref == r.complaint_ref
                   or (order_ref and r.order_ref and order_ref.upper() == r.order_ref.upper())
                   or (primary_subcategory and r.subcategory_code == primary_subcategory)
                   or (primary_subcategory and r.category_code and matrix.category_of(primary_subcategory) == r.category_code
                       and sim >= settings.repeat_similarity_threshold))
        if related:
            same_issue.append((r, sim))
    out["related"] = [{"complaint_ref": r.complaint_ref, "status": r.status, "similarity": round(s, 3)} for r, s in same_issue]
    out["prior_same_issue_count"] = len(same_issue)
    out["unresolved_prior_same_issue"] = sum(1 for r, _ in same_issue if r.status not in RESOLVED_STATES)
    if same_issue:
        out["repeat_of"] = same_issue[0][0].complaint_ref
        if not out["references_resolved_complaint"] and "repeat_indicator" in signals:
            resolved = [r for r, _ in same_issue if r.status in RESOLVED_STATES and r.resolved_at is not None
                        and (anchor - r.resolved_at).days <= int(matrix.param("reopen_window_days"))]
            out["references_resolved_complaint"] = bool(resolved)
    return out
