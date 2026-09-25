"""In-memory knowledge snapshot: chunk index (BM25 + vectors), document/version registry and
precedence-resolved conflicts. Rebuilt automatically whenever the knowledge base changes
(``kb_revision`` counter), so uploads and status changes take effect without restarts."""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from supportnova.core.logging import get_logger
from supportnova.database.models import Document, DocumentChunk, DocumentVersion, SystemSetting
from supportnova.document_processing.validation import version_key
from supportnova.rule_engine.models import RuleMatrix

from .bm25 import BM25
from .embeddings import from_bytes, get_embedder

log = get_logger(__name__)
KB_REVISION_KEY = "kb_revision"


@dataclass
class ChunkEntry:
    idx: int
    chunk_id: int
    chunk_uid: str
    doc_id: str
    title: str
    doc_type: str
    owner: str | None
    topics: list[str]
    version: str
    status: str
    effective_date: date | None
    expiry_date: date | None
    section_id: str
    heading: str
    page_start: int | None
    page_end: int | None
    text: str
    quarantined: bool
    quarantine_reason: str | None

    def primary_eligible(self, as_of: date) -> bool:
        return (self.status == "Active" and not self.quarantined
                and (self.effective_date is None or self.effective_date <= as_of)
                and (self.expiry_date is None or self.expiry_date >= as_of))


@dataclass
class VersionInfo:
    version_id: int
    doc_id: str
    title: str
    doc_type: str
    version: str
    status: str
    effective_date: date | None
    expiry_date: date | None
    sections: dict[str, str]
    section_text: dict[str, str] = field(default_factory=dict)

    def effective_status(self, as_of: date) -> str:
        """Active only when approved AND within its effective window; otherwise the stored status or Outdated."""
        if self.status != "Active":
            return self.status
        if self.effective_date and self.effective_date > as_of:
            return "Pending"
        if self.expiry_date and self.expiry_date < as_of:
            return "Expired"
        return "Active"


@dataclass
class KnowledgeSnapshot:
    revision: int
    chunks: list[ChunkEntry]
    versions: dict[str, list[VersionInfo]]
    bm25: BM25
    vectors: np.ndarray | None
    embedder_name: str
    conflicts: list[dict[str, Any]]

    # ---- registry helpers --------------------------------------------------
    def active_version(self, doc_id: str, as_of: date) -> VersionInfo | None:
        candidates = [v for v in self.versions.get(doc_id, []) if v.effective_status(as_of) == "Active"]
        return max(candidates, key=lambda v: version_key(v.version)) if candidates else None

    def find_version(self, doc_id: str, version: str | None) -> VersionInfo | None:
        for v in self.versions.get(doc_id, []):
            if version and v.version == version.lstrip("vV"):
                return v
        return None

    def resolve_ref(self, ref: str, as_of: date, version: str | None = None) -> dict[str, Any]:
        """Resolve 'DOC-ID:section' (optionally a specific version) against the registry."""
        doc_id, _, section = (ref or "").partition(":")
        doc_id, section = doc_id.strip().upper(), section.strip().lstrip("sS§ ").rstrip(".")
        info: dict[str, Any] = {"ref": ref, "doc_id": doc_id, "section": section, "doc_exists": doc_id in self.versions,
                                "section_exists": False, "active_version": None, "cited_version": version,
                                "cited_version_status": None, "heading": None}
        active = self.active_version(doc_id, as_of)
        if active:
            info["active_version"] = active.version
            info["title"] = active.title
            info["doc_type"] = active.doc_type
        target = self.find_version(doc_id, version) if version else active
        if version and target:
            info["cited_version_status"] = target.effective_status(as_of)
        if target is None and self.versions.get(doc_id):
            target = max(self.versions[doc_id], key=lambda v: version_key(v.version))
        if target and section:
            if section in target.sections:
                info["section_exists"] = True
                info["heading"] = target.sections[section]
            elif any(s.startswith(section + ".") for s in target.sections):
                info["section_exists"] = True
                info["heading"] = target.sections.get(section)
        elif target and not section:
            info["section_exists"] = True
        return info

    def active_section_keys(self, as_of: date) -> set[str]:
        keys: set[str] = set()
        for doc_id in self.versions:
            av = self.active_version(doc_id, as_of)
            if av:
                keys |= {f"{doc_id}:{sid}" for sid in av.sections}
        return keys


def _doc_rank(matrix: RuleMatrix, doc_type: str) -> int:
    return int((matrix.precedence.get("doc_type_rank") or {}).get(doc_type, 9))


def detect_conflicts(chunks: list[ChunkEntry], matrix: RuleMatrix, as_of: date) -> list[dict[str, Any]]:
    """Numeric-fact conflicts between ACTIVE documents, resolved by CHP-POL-01 s10 precedence."""
    keys = [(fk["key"], fk.get("topic", ""), re.compile(fk["pattern"], re.I | re.S))
            for fk in (matrix.precedence.get("fact_keys") or [])]
    found: dict[str, list[dict[str, Any]]] = {}
    for c in chunks:
        if not c.primary_eligible(as_of):
            continue
        text = f"{c.heading}. {c.text}"
        for key, _topic, pattern in keys:
            m = pattern.search(text)
            if m:
                value = (m.groupdict().get("value") or m.group(0)).strip().lower()
                found.setdefault(key, []).append({
                    "doc_id": c.doc_id, "title": c.title, "doc_type": c.doc_type, "version": c.version,
                    "section_id": c.section_id, "chunk_uid": c.chunk_uid, "value": value,
                    "snippet": m.group(0)[:220], "precedence_rank": _doc_rank(matrix, c.doc_type),
                    "effective_date": c.effective_date.isoformat() if c.effective_date else None,
                })
    conflicts: list[dict[str, Any]] = []
    for key, items in found.items():
        # one statement per document for the comparison
        per_doc: dict[str, dict[str, Any]] = {}
        for it in items:
            per_doc.setdefault(it["doc_id"], it)
        values = {it["value"] for it in per_doc.values()}
        if len(values) < 2:
            continue
        ordered = sorted(per_doc.values(), key=lambda it: (it["precedence_rank"], -(int((it["effective_date"] or "0000").replace("-", "")[:8] or 0))))
        winner = ordered[0]
        losers = [it for it in ordered[1:] if it["value"] != winner["value"]]
        rule = "PRC-002" if any(it["precedence_rank"] != winner["precedence_rank"] for it in losers) else "PRC-003"
        conflicts.append({
            "fact_key": key, "statements": ordered, "prevailing": winner, "overridden": losers,
            "resolution_rule": rule,
            "explanation": (f"{winner['doc_id']} v{winner['version']} section {winner['section_id']} ({winner['doc_type']}) prevails over "
                            + ", ".join(f"{it['doc_id']} section {it['section_id']} ({it['doc_type']})" for it in losers)
                            + f" under {rule} (CHP-POL-01 s10)."),
        })
    return conflicts


class KnowledgeService:
    """Process-wide cached snapshot, rebuilt when the kb_revision counter changes."""

    def __init__(self) -> None:
        self._snapshot: KnowledgeSnapshot | None = None
        self._lock = threading.Lock()

    @staticmethod
    def current_revision(db: Session) -> int:
        row = db.get(SystemSetting, KB_REVISION_KEY)
        return int((row.value or {}).get("value", 0)) if row else 0

    @staticmethod
    def bump_revision(db: Session) -> int:
        row = db.get(SystemSetting, KB_REVISION_KEY)
        if row is None:
            row = SystemSetting(key=KB_REVISION_KEY, value={"value": 1})
            db.add(row)
            db.flush()
            return 1
        new = int((row.value or {}).get("value", 0)) + 1
        row.value = {"value": new}
        db.flush()
        return new

    def invalidate(self) -> None:
        with self._lock:
            self._snapshot = None

    def snapshot(self, db: Session, matrix: RuleMatrix, as_of: date | None = None) -> KnowledgeSnapshot:
        revision = self.current_revision(db)
        snap = self._snapshot
        if snap is not None and snap.revision == revision:
            return snap
        with self._lock:
            if self._snapshot is not None and self._snapshot.revision == revision:
                return self._snapshot
            self._snapshot = self._build(db, matrix, revision, as_of or date.today())
            return self._snapshot

    def _build(self, db: Session, matrix: RuleMatrix, revision: int, as_of: date) -> KnowledgeSnapshot:
        docs = db.execute(select(Document).options(selectinload(Document.versions).selectinload(DocumentVersion.sections))
                          ).scalars().all()
        versions: dict[str, list[VersionInfo]] = {}
        version_meta: dict[int, tuple[Document, DocumentVersion]] = {}
        for d in docs:
            for v in d.versions:
                if v.parse_status != "parsed":
                    continue
                version_meta[v.id] = (d, v)
                versions.setdefault(d.doc_id, []).append(VersionInfo(
                    v.id, d.doc_id, d.title, d.doc_type, v.version, v.status, v.effective_date, v.expiry_date,
                    {s.section_id: s.heading for s in v.sections}, {s.section_id: s.text for s in v.sections}))
        rows = db.execute(select(DocumentChunk).order_by(DocumentChunk.id)).scalars().all()
        entries: list[ChunkEntry] = []
        vectors: list[np.ndarray] = []
        embedder = get_embedder()
        missing: list[int] = []
        for row in rows:
            meta = version_meta.get(row.version_id)
            if not meta:
                continue
            d, v = meta
            entries.append(ChunkEntry(len(entries), row.id, row.chunk_uid, d.doc_id, d.title, d.doc_type,
                                      d.owner_department, list(d.topics or []), v.version, v.status, v.effective_date,
                                      v.expiry_date, row.section_id, row.heading, row.page_start, row.page_end, row.text,
                                      row.is_quarantined, row.quarantine_reason))
            vec = from_bytes(row.embedding) if row.embedding_model == embedder.name else None
            if vec is None or vec.shape[0] != embedder.dim:
                missing.append(len(entries) - 1)
                vectors.append(np.zeros(embedder.dim, dtype=np.float32))
            else:
                vectors.append(vec)
        if missing:
            texts = [f"{entries[i].heading}\n{entries[i].text}" for i in missing]
            fresh = embedder.embed(texts)
            for j, i in enumerate(missing):
                vectors[i] = fresh[j]
        bm25 = BM25([f"{e.heading} {e.heading} {e.title}\n{e.text}" for e in entries])
        matrix_vectors = np.vstack(vectors) if vectors else None
        conflicts = detect_conflicts(entries, matrix, as_of)
        log.info("knowledge snapshot built", extra={"event": "kb_snapshot"})
        return KnowledgeSnapshot(revision, entries, versions, bm25, matrix_vectors, embedder.name, conflicts)


knowledge_service = KnowledgeService()
