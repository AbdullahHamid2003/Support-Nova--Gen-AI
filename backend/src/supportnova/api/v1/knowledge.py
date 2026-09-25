"""Knowledge-base endpoints: upload (PDF/DOCX/TXT/MD/CSV), versions & status, sections/chunks,
revision impact, retrieval playground and precedence-resolved conflicts (SRS Steps 3-7, 25-26)."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from supportnova.api.deps import db_session, require
from supportnova.api.serializers import iso
from supportnova.core.errors import NotFound
from supportnova.core.paths import storage_dir
from supportnova.database.models import Document, DocumentChunk, DocumentVersion, User
from supportnova.document_processing.parsers import parse_document
from supportnova.knowledge_base.retriever import retrieve
from supportnova.knowledge_base.store import knowledge_service
from supportnova.security.files import DOCUMENT_TYPES, validate_upload
from supportnova.services import documents as svc
from supportnova.services.rules import rule_service

router = APIRouter(tags=["knowledge"])


def _version_json(v: DocumentVersion, as_of: date) -> dict[str, Any]:
    effective_ok = v.effective_date is None or v.effective_date <= as_of
    expired = v.expiry_date is not None and v.expiry_date < as_of
    return {"id": v.id, "version": v.version, "status": v.status, "effective_date": iso(v.effective_date) if v.effective_date else None,
            "expiry_date": v.expiry_date.isoformat() if v.expiry_date else None, "file_name": v.file_name, "file_format": v.file_format,
            "size_bytes": v.size_bytes, "sha256": v.sha256, "page_count": v.page_count, "section_count": v.section_count,
            "chunk_count": v.chunk_count, "parse_status": v.parse_status, "uploaded_at": iso(v.uploaded_at),
            "supersedes": v.supersedes, "security_findings": v.security_findings, "warnings": (v.extra or {}).get("warnings", []),
            "impact": (v.extra or {}).get("impact"),
            "primary_eligible": v.status == "Active" and effective_ok and not expired,
            "effective_state": "Active" if (v.status == "Active" and effective_ok and not expired) else
            ("Pending" if v.status == "Active" and not effective_ok else "Expired" if v.status == "Active" and expired else v.status)}


@router.get("/documents")
def list_documents(user: User = Depends(require("knowledge:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    today = date.today()
    docs = svc.list_documents(db)
    items = []
    for d in docs:
        versions = sorted(d.versions, key=lambda v: [int(p) for p in v.version.split(".") if p.isdigit()])
        active = next((v for v in reversed(versions) if v.status == "Active"), None)
        items.append({"doc_id": d.doc_id, "title": d.title, "doc_type": d.doc_type, "owner_department": d.owner_department,
                      "topics": d.topics, "active_version": active.version if active else None,
                      "active_format": active.file_format if active else None, "version_count": len(versions),
                      "statuses": sorted({v.status for v in versions}),
                      "quarantined_chunks": sum(len([f for f in (v.security_findings or []) if f.get("is_suspicious")]) for v in versions),
                      "versions": [_version_json(v, today) for v in versions]})
    return {"items": items, "total": len(items)}


@router.post("/documents/preview")
async def preview_document(file: UploadFile = File(...), user: User = Depends(require("knowledge:manage"))) -> dict[str, Any]:
    """Parse without saving: detected metadata and section outline (pre-fills the upload form)."""
    from supportnova.core.config import get_settings
    data = await file.read()
    vf = validate_upload(file.filename or "document", data, allowed=DOCUMENT_TYPES, max_bytes=get_settings().max_upload_mb * 1024 * 1024)
    parsed = parse_document(data, vf.extension)
    return {"file_name": vf.file_name, "format": vf.extension, "size_bytes": vf.size_bytes, "title": parsed.title,
            "page_count": parsed.page_count, "detected_metadata": parsed.detected_metadata,
            "sections": [{"section_id": s.section_id, "heading": s.heading, "level": s.level, "page_start": s.page_start,
                          "chars": len(s.text)} for s in parsed.sections[:200]]}


@router.post("/documents", status_code=201)
async def upload_document(file: UploadFile = File(...), doc_id: str = Form(""), title: str = Form(""), doc_type: str = Form(""),
                          version: str = Form(""), status: str = Form(""), effective_date: str = Form(""),
                          expiry_date: str = Form(""), owner_department: str = Form(""), topics: str = Form(""),
                          user: User = Depends(require("knowledge:manage")), db: Session = Depends(db_session)) -> dict[str, Any]:
    data = await file.read()
    meta = {"doc_id": doc_id, "title": title, "doc_type": doc_type, "version": version, "status": status,
            "effective_date": effective_date, "expiry_date": expiry_date or None, "owner_department": owner_department or None,
            "topics": [t.strip() for t in topics.split(",") if t.strip()]}
    v = svc.ingest_document(db, data=data, file_name=file.filename or "document", metadata=meta, actor=user)
    db.commit()
    return {"doc_id": v.document.doc_id, **_version_json(v, date.today())}


@router.get("/documents/{doc_id}")
def get_document(doc_id: str, user: User = Depends(require("knowledge:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    d = db.execute(select(Document).options(selectinload(Document.versions)).where(Document.doc_id == doc_id.upper())).scalar_one_or_none()
    if d is None:
        raise NotFound(f"Document {doc_id} not found.")
    today = date.today()
    return {"doc_id": d.doc_id, "title": d.title, "doc_type": d.doc_type, "owner_department": d.owner_department, "topics": d.topics,
            "versions": [_version_json(v, today) for v in d.versions]}


@router.get("/documents/{doc_id}/versions/{version}")
def get_version(doc_id: str, version: str, user: User = Depends(require("knowledge:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    v = db.execute(select(DocumentVersion).join(Document).where(Document.doc_id == doc_id.upper(), DocumentVersion.version == version)
                   .options(selectinload(DocumentVersion.sections), selectinload(DocumentVersion.chunks))).scalar_one_or_none()
    if v is None:
        raise NotFound(f"{doc_id} version {version} not found.")
    return {**_version_json(v, date.today()), "doc_id": doc_id.upper(), "title": v.document.title, "facts": v.facts,
            "sections": [{"section_id": s.section_id, "heading": s.heading, "level": s.level, "page_start": s.page_start,
                          "page_end": s.page_end, "text": s.text} for s in v.sections],
            "chunks": [{"chunk_uid": c.chunk_uid, "section_id": c.section_id, "heading": c.heading, "page_start": c.page_start,
                        "token_count": c.token_count, "is_quarantined": c.is_quarantined, "quarantine_reason": c.quarantine_reason,
                        "embedding_model": c.embedding_model, "text": c.text} for c in v.chunks]}


class StatusIn(BaseModel):
    status: str


@router.post("/documents/{doc_id}/versions/{version}/status")
def set_version_status(doc_id: str, version: str, body: StatusIn, user: User = Depends(require("knowledge:manage")),
                       db: Session = Depends(db_session)) -> dict[str, Any]:
    v = svc.change_status(db, doc_id=doc_id.upper(), version=version, status=body.status, actor=user)
    db.commit()
    return _version_json(v, date.today())


@router.get("/documents/{doc_id}/versions/{version}/download")
def download_version(doc_id: str, version: str, user: User = Depends(require("knowledge:read")), db: Session = Depends(db_session)) -> Response:
    v = db.execute(select(DocumentVersion).join(Document).where(Document.doc_id == doc_id.upper(), DocumentVersion.version == version)
                   ).scalar_one_or_none()
    if v is None:
        raise NotFound("Document version not found.")
    path = (storage_dir() / v.storage_path).resolve()
    if storage_dir().resolve() not in path.parents or not path.exists():
        raise NotFound("Stored file not available.")
    return Response(path.read_bytes(), media_type=v.mime_type, headers={"Content-Disposition": f'attachment; filename="{v.file_name}"'})


@router.get("/documents/{doc_id}/impact")
def document_impact(doc_id: str, user: User = Depends(require("knowledge:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    d = db.execute(select(Document).options(selectinload(Document.versions)).where(Document.doc_id == doc_id.upper())).scalar_one_or_none()
    if d is None:
        raise NotFound(f"Document {doc_id} not found.")
    impacts = [{"version": v.version, **(v.extra or {}).get("impact", {})} for v in d.versions if (v.extra or {}).get("impact")]
    return {"doc_id": d.doc_id, "impacts": impacts}


@router.get("/knowledge/search")
def search(q: str, subcategory: str | None = None, top_k: int = 8, user: User = Depends(require("knowledge:read")),
           db: Session = Depends(db_session)) -> dict[str, Any]:
    """Retrieval playground: shows exactly what evidence the pipeline would retrieve."""
    matrix = rule_service.matrix(db)
    snapshot = knowledge_service.snapshot(db, matrix)
    from supportnova.complaint_processing.perception import classify, detect_signals
    candidates = [subcategory] if subcategory else [c.subcategory for c in classify(matrix, q, "", set(detect_signals(matrix, q)), []).candidates[:3]]
    result = retrieve(snapshot, matrix, query=q, candidate_subcategories=[c for c in candidates if c], top_k=min(max(top_k, 1), 20))
    return {**result.to_dict(), "candidate_subcategories": candidates}


@router.get("/knowledge/conflicts")
def conflicts(user: User = Depends(require("knowledge:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    matrix = rule_service.matrix(db)
    snapshot = knowledge_service.snapshot(db, matrix)
    return {"items": snapshot.conflicts, "precedence": matrix.precedence.get("precedence_rules", []),
            "doc_type_rank": matrix.precedence.get("doc_type_rank", {})}


@router.get("/knowledge/stats")
def stats(user: User = Depends(require("knowledge:read")), db: Session = Depends(db_session)) -> dict[str, Any]:
    by_status = dict(db.execute(select(DocumentVersion.status, func.count()).group_by(DocumentVersion.status)).tuples().all())
    by_format = dict(db.execute(select(DocumentVersion.file_format, func.count()).group_by(DocumentVersion.file_format))
                     .tuples().all())
    return {"documents": db.scalar(select(func.count()).select_from(Document)), "versions": sum(by_status.values()),
            "by_status": by_status, "by_format": by_format,
            "chunks": db.scalar(select(func.count()).select_from(DocumentChunk)),
            "quarantined_chunks": db.scalar(select(func.count()).select_from(DocumentChunk).where(DocumentChunk.is_quarantined)),
            "revision": knowledge_service.current_revision(db)}
