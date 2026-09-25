"""Knowledge-base ingestion and version control (SRS Steps 3-7, 1.8(4) Hidden Policy Update).

upload -> file validation -> duplicate check -> parsing -> metadata validation -> storage ->
sections -> chunking -> injection screening (quarantine) -> embeddings -> policy facts ->
version control (Active/Previous/Superseded/Draft) -> revision impact analysis -> audit.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from supportnova.audit import service as audit
from supportnova.core.config import get_settings
from supportnova.core.errors import Conflict, NotFound, ValidationFailed
from supportnova.core.paths import storage_dir
from supportnova.core.timeutil import utcnow
from supportnova.database.models import (
    Analysis,
    Complaint,
    Document,
    DocumentChunk,
    DocumentSection,
    DocumentVersion,
    PolicyReference,
    User,
)
from supportnova.document_processing.chunking import chunk_sections
from supportnova.document_processing.facts import diff_versions, extract_facts, facts_to_json
from supportnova.document_processing.parsers import parse_document
from supportnova.document_processing.validation import validate_metadata, version_key
from supportnova.knowledge_base.embeddings import get_embedder, to_bytes
from supportnova.knowledge_base.store import knowledge_service
from supportnova.security import injection
from supportnova.security.files import DOCUMENT_TYPES, validate_upload
from supportnova.services.rules import rule_service


def _store_file(doc_id: str, version: str, file_name: str, data: bytes) -> str:
    folder = storage_dir() / "documents" / doc_id / version
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / file_name
    path.write_bytes(data)
    return str(path.relative_to(storage_dir()))


def ingest_document(db: Session, *, data: bytes, file_name: str, metadata: dict[str, Any] | None = None,
                    actor: User | None = None, today: date | None = None) -> DocumentVersion:
    settings = get_settings()
    vf = validate_upload(file_name, data, allowed=DOCUMENT_TYPES, max_bytes=settings.max_upload_mb * 1024 * 1024)
    if db.execute(select(DocumentVersion.id).where(DocumentVersion.sha256 == vf.sha256)).first():
        raise Conflict("This exact document has already been uploaded (duplicate file).", details={"sha256": vf.sha256})
    parsed = parse_document(data, vf.extension)
    merged: dict[str, Any] = {**parsed.detected_metadata, **{k: v for k, v in (metadata or {}).items() if v not in (None, "")}}
    merged.setdefault("title", parsed.title)
    meta = validate_metadata(merged, today=today)
    if not parsed.sections or not any(s.text for s in parsed.sections):
        raise ValidationFailed("The document has no readable content.")

    document = db.execute(select(Document).where(Document.doc_id == meta.doc_id)).scalar_one_or_none()
    if document is None:
        document = Document(doc_id=meta.doc_id, title=meta.title, doc_type=meta.doc_type,
                            owner_department=meta.owner_department, topics=meta.topics)
        db.add(document)
        db.flush()
    else:
        if document.doc_type != meta.doc_type:
            raise ValidationFailed(f"{meta.doc_id} is registered as '{document.doc_type}', not '{meta.doc_type}'.")
        if db.execute(select(DocumentVersion.id).where(DocumentVersion.document_id == document.id,
                                                       DocumentVersion.version == meta.version)).first():
            raise Conflict(f"{meta.doc_id} version {meta.version} already exists.")
        document.title = meta.title
        if meta.topics:
            document.topics = meta.topics

    existing = db.execute(select(DocumentVersion).where(DocumentVersion.document_id == document.id)).scalars().all()
    if meta.status == "Active":
        newer_active = [v for v in existing if v.status == "Active" and version_key(v.version) > version_key(meta.version)]
        if newer_active:
            raise ValidationFailed(f"A newer Active version ({newer_active[0].version}) exists; upload this version as "
                                   "Previous or Superseded instead.")

    storage_path = _store_file(meta.doc_id, meta.version, vf.file_name, data)
    precedence = rule_service.matrix(db).precedence
    facts = extract_facts(parsed.sections, precedence.get("fact_keys"))
    version = DocumentVersion(
        document_id=document.id, version=meta.version, status=meta.status, effective_date=meta.effective_date,
        expiry_date=meta.expiry_date, file_name=vf.file_name, file_format=vf.extension, mime_type=vf.content_type,
        size_bytes=vf.size_bytes, sha256=vf.sha256, storage_path=storage_path, page_count=parsed.page_count,
        parse_status="parsed", section_count=len(parsed.sections), supersedes=meta.supersedes,
        facts=facts_to_json(facts), uploaded_by_id=actor.id if actor else None, status_changed_at=utcnow(),
        extra={"warnings": meta.warnings, "detected_metadata": parsed.detected_metadata, "title": parsed.title},
    )
    db.add(version)
    db.flush()
    for order, s in enumerate(parsed.sections):
        db.add(DocumentSection(version_id=version.id, section_id=s.section_id, heading=s.heading[:300], level=s.level,
                               page_start=s.page_start, page_end=s.page_end, text=s.text, order_index=order))
    chunks = chunk_sections(meta.doc_id, meta.version, parsed.sections)
    embedder = get_embedder()
    vectors: np.ndarray | list[np.ndarray] = embedder.embed([f"{c.heading}\n{c.text}" for c in chunks]) if chunks else []
    findings: list[dict[str, Any]] = []
    for c, vec in zip(chunks, vectors, strict=False):
        report = injection.scan(c.text)
        quarantined = report.is_suspicious
        if report.findings:
            findings.append({"chunk_uid": c.chunk_uid, "section_id": c.section_id, **report.to_dict()})
        db.add(DocumentChunk(chunk_uid=c.chunk_uid, version_id=version.id, section_id=c.section_id, heading=c.heading[:300],
                             page_start=c.page_start, page_end=c.page_end, text=c.text, token_count=c.token_count,
                             embedding=to_bytes(vec), embedding_model=embedder.name, is_quarantined=quarantined,
                             quarantine_reason=("Instruction-like content detected: " + ", ".join(sorted({f.type for f in report.findings})))
                             if quarantined else None, order_index=c.order_index))
    version.chunk_count = len(chunks)
    version.security_findings = findings
    db.flush()  # sessions do not autoflush: the impact analysis below must see the new sections

    impact = None
    demoted: list[str] = []
    if meta.status == "Active":
        for v in sorted(existing, key=lambda v: version_key(v.version), reverse=True):
            if v.status == "Active":
                previous_active = v
                v.status = "Previous"
                v.status_changed_at = utcnow()
                demoted.append(f"{v.version}: Active -> Previous")
                impact = impact_analysis(db, document, previous_active, version)
            elif v.status == "Previous":
                v.status = "Superseded"
                v.status_changed_at = utcnow()
                demoted.append(f"{v.version}: Previous -> Superseded")
    if impact:
        version.extra = {**(version.extra or {}), "impact": impact}
    db.flush()
    knowledge_service.bump_revision(db)
    knowledge_service.invalidate()
    audit.record(db, action="document.uploaded", entity_type="document", entity_id=f"{meta.doc_id}@{meta.version}",
                 actor=actor, summary=f"Uploaded {meta.doc_id} v{meta.version} ({meta.status}) - {len(parsed.sections)} sections, "
                                      f"{len(chunks)} chunks" + (f"; {len(findings)} chunk(s) flagged" if findings else ""),
                 details={"file": vf.file_name, "sha256": vf.sha256, "status": meta.status, "demoted": demoted,
                          "quarantined_chunks": sum(1 for f in findings if f.get("is_suspicious")), "warnings": meta.warnings})
    return version


def change_status(db: Session, *, doc_id: str, version: str, status: str, actor: User | None) -> DocumentVersion:
    if status not in ("Active", "Previous", "Superseded", "Draft"):
        raise ValidationFailed("Invalid status.")
    document = db.execute(select(Document).where(Document.doc_id == doc_id)).scalar_one_or_none()
    if not document:
        raise NotFound(f"Document {doc_id} not found.")
    target = next((v for v in document.versions if v.version == version), None)
    if not target:
        raise NotFound(f"{doc_id} version {version} not found.")
    old = target.status
    impact = None
    if status == "Active":
        for v in document.versions:
            if v is not target and v.status == "Active":
                v.status = "Previous"
                v.status_changed_at = utcnow()
                impact = impact_analysis(db, document, v, target)
    target.status = status
    target.status_changed_at = utcnow()
    if impact:
        target.extra = {**(target.extra or {}), "impact": impact}
    db.flush()
    knowledge_service.bump_revision(db)
    knowledge_service.invalidate()
    audit.record(db, action="document.status_changed", entity_type="document", entity_id=f"{doc_id}@{version}", actor=actor,
                 summary=f"{doc_id} v{version}: {old} -> {status}", details={"old": old, "new": status})
    return target


def impact_analysis(db: Session, document: Document, old: DocumentVersion, new: DocumentVersion) -> dict[str, Any]:
    """Which complaints, rules, escalation rules and responses are affected by a policy revision."""
    old_sections = [{"section_id": s.section_id, "heading": s.heading, "text": s.text} for s in old.sections]
    new_sections = [{"section_id": s.section_id, "heading": s.heading, "text": s.text} for s in
                    db.execute(select(DocumentSection).where(DocumentSection.version_id == new.id)).scalars()]
    changes = diff_versions(old_sections, new_sections, list(old.facts or []), list(new.facts or []))
    changed_ids = {c["section_id"] for c in changes}
    doc_id = document.doc_id

    def touches(ref: str) -> bool:
        d, _, sec = ref.partition(":")
        return d == doc_id and any(sec == cid or cid.startswith(sec + ".") or sec.startswith(cid + ".") for cid in changed_ids)

    matrix = rule_service.matrix(db)
    rules = [r.rule_id for r in matrix.resolution_rules if any(touches(ref) for ref in r.policy_refs)]
    escalation_rules = [e.rule_id for e in matrix.escalation_rules if any(touches(ref) for ref in e.policy_refs)]
    parameters = []
    for key, p in matrix.parameters.items():
        if p.source and touches(p.source):
            sec = p.source.split(":", 1)[1]
            suggestion = None
            for c in changes:
                if c["section_id"] == sec:
                    for vc in c.get("value_changes", []):
                        if float(vc["old"]) == float(p.value):
                            suggestion = vc["new"]
            parameters.append({"key": key, "current_value": p.value, "source": p.source, "suggested_value": suggestion,
                               "out_of_sync": suggestion is not None})
    rows = db.execute(
        select(Complaint.complaint_ref, Complaint.status, PolicyReference.section_id)
        .join(Analysis, Analysis.complaint_id == Complaint.id)
        .join(PolicyReference, PolicyReference.analysis_id == Analysis.id)
        .where(PolicyReference.doc_id == doc_id, PolicyReference.version == old.version, Complaint.status != "Closed",
               Complaint.source.in_(("web", "api", "dataset")))
        .distinct().limit(5000)
    ).all()
    cited: dict[str, dict[str, Any]] = {}
    for ref, st, sec in rows:
        entry = cited.setdefault(ref, {"status": st, "sections": set()})
        if sec:
            entry["sections"].add(sec)
    complaints = []
    for ref, entry in cited.items():
        hit = sorted(s for s in entry["sections"] if touches(f"{doc_id}:{s}")) if changed_ids else sorted(entry["sections"])
        if hit:
            complaints.append({"complaint_ref": ref, "status": entry["status"], "sections": hit,
                               "response_requires_revision": entry["status"] != "Resolved"})
    return {
        "doc_id": doc_id, "old_version": old.version, "new_version": new.version, "analysed_at": utcnow().isoformat(),
        "previous_policy_obsolete": True, "changed_sections": changes, "affected_resolution_rules": rules,
        "affected_escalation_rules": escalation_rules, "escalation_rules_changed": bool(escalation_rules),
        "affected_parameters": parameters, "affected_complaints": complaints,
        "responses_requiring_revision": sum(1 for c in complaints if c["response_requires_revision"]),
    }


def list_documents(db: Session) -> list[Document]:
    return list(db.execute(select(Document).options(selectinload(Document.versions)).order_by(Document.doc_id)).scalars())


def bootstrap_knowledge_base(db: Session, manifest_path: Path, *, actor: User | None = None) -> dict[str, Any]:
    """Ingest the repository knowledge base through the same pipeline as admin uploads.
    Versions are ingested oldest-first so version control produces the documented statuses."""
    import yaml

    entries = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or []
    base = manifest_path.parent
    entries.sort(key=lambda e: (e["doc_id"], version_key(str(e["version"]))))
    done, skipped = 0, 0
    for e in entries:
        path = base / e["file"] if (base / e["file"]).exists() else base / "sample_documents" / Path(e["file"]).name
        data = path.read_bytes()
        from hashlib import sha256
        if db.execute(select(DocumentVersion.id).where(DocumentVersion.sha256 == sha256(data).hexdigest())).first():
            skipped += 1
            continue
        meta = {k: e.get(k) for k in ("doc_id", "title", "doc_type", "version", "status", "effective_date", "expiry_date",
                                     "owner_department", "topics", "supersedes")}
        meta["version"] = str(meta["version"])
        ingest_document(db, data=data, file_name=path.name, metadata=meta, actor=actor)
        done += 1
    # restore the manifest statuses exactly (e.g. Superseded vs Previous chosen by the author)
    for e in entries:
        v = db.execute(select(DocumentVersion).join(Document).where(Document.doc_id == e["doc_id"],
                                                                     DocumentVersion.version == str(e["version"]))).scalar_one_or_none()
        if v and v.status != e["status"]:
            v.status = e["status"]
    db.flush()
    knowledge_service.bump_revision(db)
    knowledge_service.invalidate()
    return {"ingested": done, "skipped": skipped}
