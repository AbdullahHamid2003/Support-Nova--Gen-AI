"""Hybrid, precedence-aware, rule-guided retrieval (SRS Step 25, RAG).

1. BM25 (lexical) and vector (semantic) search over ACTIVE, effective, non-quarantined chunks.
2. Rule-guided expansion: sections cited by the Rule Matrix for the top candidate
   subcategories (from the deterministic classifier) are added, so every policy the rules
   rely on can be cited with a valid source reference.
3. Reciprocal-rank fusion, document-type precedence tie-break, per-document diversity cap.
4. Outdated versions of retrieved sections are returned separately as context (never evidence),
   and precedence-resolved conflicts touching the evidence are attached.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

import numpy as np

from supportnova.rule_engine.models import RuleMatrix

from .embeddings import get_embedder
from .store import KnowledgeSnapshot

RRF_K = 60


@dataclass
class EvidenceItem:
    evidence_id: str
    chunk_uid: str
    doc_id: str
    title: str
    doc_type: str
    version: str
    status: str
    effective_date: str | None
    section_id: str
    heading: str
    page_start: int | None
    page_end: int | None
    text: str
    score: float
    methods: list[str]
    precedence_rank: int

    @property
    def ref(self) -> str:
        return f"{self.doc_id}:{self.section_id}"


@dataclass
class RetrievalResult:
    query: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    outdated: list[dict[str, Any]] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    rule_guided_sections: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    def by_id(self) -> dict[str, EvidenceItem]:
        return {e.evidence_id: e for e in self.evidence}


def _section_matches(ref_section: str, section_id: str) -> bool:
    return section_id == ref_section or section_id.startswith(ref_section + ".")


def rule_sections(matrix: RuleMatrix, subcategories: list[str]) -> list[str]:
    """Policy sections cited by the Rule Matrix for the candidate subcategories, most-cited first
    (the section every rule variant relies on outranks one cited by a single edge-case rule)."""
    refs: list[str] = []
    for sub in subcategories:
        counts: dict[str, int] = {}
        order: list[str] = []
        for rule in matrix.rules_for(sub):
            for ref in rule.policy_refs:
                if ref not in counts:
                    order.append(ref)
                counts[ref] = counts.get(ref, 0) + 1
        rt = matrix.routing.get(sub)
        for ref in (rt.policy_refs if rt else ()):
            if not ref.startswith("RTE-RUL-14:3") and ref not in counts:
                order.append(ref)
                counts[ref] = 1
        for ref in sorted(order, key=lambda r: (-counts[r], order.index(r))):
            if ref not in refs:
                refs.append(ref)
    return refs


def retrieve(snapshot: KnowledgeSnapshot, matrix: RuleMatrix, *, query: str, candidate_subcategories: list[str],
             extra_refs: list[str] | None = None, as_of: date | None = None, top_k: int = 10,
             per_doc_cap: int = 4) -> RetrievalResult:
    started = time.perf_counter()
    as_of = as_of or date.today()
    rank_cfg = matrix.precedence.get("doc_type_rank") or {}
    eligible = [c for c in snapshot.chunks if c.primary_eligible(as_of)]
    result = RetrievalResult(query=query[:400])
    if not eligible:
        result.stats = {"eligible_chunks": 0, "latency_ms": 0}
        return result

    fused: dict[int, float] = {}
    methods: dict[int, list[str]] = {}

    def add_ranked(indices: list[int], label: str, weight: float = 1.0) -> None:
        for rank, idx in enumerate(indices):
            fused[idx] = fused.get(idx, 0.0) + weight / (RRF_K + rank + 1)
            methods.setdefault(idx, [])
            if label not in methods[idx]:
                methods[idx].append(label)

    eligible_idx = [c.idx for c in eligible]
    bm25_all = snapshot.bm25.scores(query)
    bm25_sorted = sorted((i for i in eligible_idx if bm25_all[i] > 0), key=lambda i: -bm25_all[i])[:30]
    add_ranked(bm25_sorted, "lexical")
    if snapshot.vectors is not None:
        qv = get_embedder().embed([query])[0]
        sims = snapshot.vectors[eligible_idx] @ qv
        order = np.argsort(-sims)[:30]
        add_ranked([eligible_idx[int(o)] for o in order if sims[int(o)] > 0.05], "semantic")
    guided_refs = rule_sections(matrix, candidate_subcategories[:3]) + list(extra_refs or [])
    result.rule_guided_sections = guided_refs
    guided: list[int] = []
    for ref in guided_refs:
        doc_id, _, section = ref.partition(":")
        for c in eligible:
            if c.doc_id == doc_id and _section_matches(section, c.section_id) and c.idx not in guided:
                guided.append(c.idx)
    add_ranked(guided, "rule-guided", weight=1.4)

    def sort_key(idx: int) -> tuple[float, int]:
        entry = snapshot.chunks[idx]
        return (-fused[idx], int(rank_cfg.get(entry.doc_type, 9)))

    per_doc: dict[str, int] = {}
    chosen: list[int] = []
    for idx in sorted(fused, key=sort_key):
        entry = snapshot.chunks[idx]
        if per_doc.get(entry.doc_id, 0) >= per_doc_cap:
            continue
        per_doc[entry.doc_id] = per_doc.get(entry.doc_id, 0) + 1
        chosen.append(idx)
        if len(chosen) >= top_k:
            break
    for n, idx in enumerate(chosen, start=1):
        c = snapshot.chunks[idx]
        result.evidence.append(EvidenceItem(
            f"E{n}", c.chunk_uid, c.doc_id, c.title, c.doc_type, c.version, "Active",
            c.effective_date.isoformat() if c.effective_date else None, c.section_id, c.heading, c.page_start,
            c.page_end, c.text, round(fused[idx] * 1000, 3), methods.get(idx, []), int(rank_cfg.get(c.doc_type, 9))))

    # outdated versions of the retrieved sections (context only, never evidence)
    seen: set[tuple[str, str, str]] = set()
    for ev in result.evidence:
        for v in snapshot.versions.get(ev.doc_id, []):
            if v.version == ev.version or ev.section_id not in v.sections:
                continue
            key = (ev.doc_id, v.version, ev.section_id)
            if key in seen:
                continue
            seen.add(key)
            result.outdated.append({"doc_id": ev.doc_id, "version": v.version, "status": v.effective_status(as_of),
                                    "section_id": ev.section_id, "heading": v.sections[ev.section_id],
                                    "text": (v.section_text.get(ev.section_id) or "")[:600],
                                    "active_version": ev.version,
                                    "note": "Outdated - not used as the primary basis for decisions (CHP-POL-01 s10.4)."})
    evidence_uids = {e.chunk_uid for e in result.evidence}
    for conflict in snapshot.conflicts:
        if {s["chunk_uid"] for s in conflict["statements"]} & evidence_uids:
            result.conflicts.append(conflict)
    result.stats = {"eligible_chunks": len(eligible), "lexical_hits": len(bm25_sorted), "rule_guided": len(guided),
                    "embedder": snapshot.embedder_name, "latency_ms": round((time.perf_counter() - started) * 1000, 1)}
    return result
