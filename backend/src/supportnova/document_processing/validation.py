"""Knowledge-base document metadata validation (SRS Step 4: document ID, version, effective
date, expiry date, category, status; duplicates are checked by the ingestion service)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from supportnova.core.errors import ValidationFailed
from supportnova.core.timeutil import to_date

DOC_ID = re.compile(r"^[A-Z]{2,5}-[A-Z]{2,5}-\d{2,3}$")
VERSION = re.compile(r"^\d{1,3}(\.\d{1,3}){0,2}$")
DOC_TYPES = ("policy", "rules", "sop", "guideline", "faq", "template")
STATUSES = ("Active", "Previous", "Superseded", "Draft")


@dataclass
class DocumentMetadata:
    doc_id: str
    title: str
    doc_type: str
    version: str
    status: str
    effective_date: date | None
    expiry_date: date | None
    owner_department: str | None = None
    topics: list[str] = field(default_factory=list)
    supersedes: str | None = None
    warnings: list[str] = field(default_factory=list)


def infer_doc_type(doc_id: str) -> str | None:
    middle = doc_id.split("-")[1] if doc_id.count("-") >= 2 else ""
    return {"POL": "policy", "RUL": "rules", "SOP": "sop", "GDL": "guideline", "FAQ": "faq", "TPL": "template",
            "COM": "template"}.get(middle)


def validate_metadata(raw: dict[str, Any], *, today: date | None = None) -> DocumentMetadata:
    today = today or date.today()
    errors: list[dict[str, str]] = []
    warnings: list[str] = []
    doc_id = str(raw.get("doc_id") or "").strip().upper()
    if not doc_id:
        errors.append({"field": "doc_id", "message": "Document ID is required (e.g. REF-POL-02)."})
    elif not DOC_ID.match(doc_id):
        errors.append({"field": "doc_id", "message": "Document ID must look like ABC-POL-12."})
    title = str(raw.get("title") or "").strip()
    if not title:
        errors.append({"field": "title", "message": "Title is required."})
    doc_type = str(raw.get("doc_type") or (infer_doc_type(doc_id) if doc_id else "") or "").strip().lower()
    if doc_type not in DOC_TYPES:
        errors.append({"field": "doc_type", "message": f"Document category must be one of: {', '.join(DOC_TYPES)}."})
    version = str(raw.get("version") or "").strip().lstrip("vV")
    if not VERSION.match(version):
        errors.append({"field": "version", "message": "Version must be numeric, e.g. 2.0 or 3.1."})
    status = str(raw.get("status") or "").strip().capitalize()
    if status not in STATUSES:
        errors.append({"field": "status", "message": f"Status must be one of: {', '.join(STATUSES)}."})
    try:
        effective = to_date(raw.get("effective_date"))
    except ValueError:
        effective = None
        errors.append({"field": "effective_date", "message": "Effective date must be a valid date (YYYY-MM-DD)."})
    if effective is None and not any(e["field"] == "effective_date" for e in errors):
        errors.append({"field": "effective_date", "message": "Effective date is required."})
    try:
        expiry = to_date(raw.get("expiry_date")) if raw.get("expiry_date") not in (None, "", "none", "None") else None
    except ValueError:
        expiry = None
        errors.append({"field": "expiry_date", "message": "Expiry date must be a valid date (YYYY-MM-DD)."})
    if effective and expiry and expiry < effective:
        errors.append({"field": "expiry_date", "message": "Expiry date cannot be before the effective date."})
    if status == "Active" and effective and effective > today:
        warnings.append("Effective date is in the future: the document will not be used as primary evidence until then.")
    if status == "Active" and expiry and expiry < today:
        warnings.append("The expiry date has passed: the document will be treated as Outdated.")
    if errors:
        raise ValidationFailed("Document metadata is invalid.", details=errors)
    topics = raw.get("topics") or []
    if isinstance(topics, str):
        topics = [t.strip() for t in topics.split(",") if t.strip()]
    return DocumentMetadata(doc_id=doc_id, title=title, doc_type=doc_type, version=version, status=status,
                            effective_date=effective, expiry_date=expiry,
                            owner_department=(raw.get("owner_department") or None), topics=list(topics),
                            supersedes=(str(raw["supersedes"]) if raw.get("supersedes") else None), warnings=warnings)


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in version.split(".") if p.isdigit())
