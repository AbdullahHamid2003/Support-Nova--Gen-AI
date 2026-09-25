"""Complaint dataset I/O shared by the seeder and the evaluation runner (hidden-dataset compatibility).

Accepts the dataset record format (docs/dataset.md, schemas/dataset/complaint_record.schema.json) as
a JSON array, JSON Lines or the flattened CSV written by scripts/generate_dataset.py. Only
``title`` and ``description`` are mandatory; every other field is optional, unknown columns are
ignored and ``expected`` labels are used only for scoring - never by the runtime pipeline.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from supportnova.core.errors import ValidationFailed
from supportnova.core.paths import DATA_DIR

BUILTIN = {
    "holdout": DATA_DIR / "hidden_test_ready" / "holdout_complaints.jsonl",
    "dev": DATA_DIR / "sample_complaints" / "complaints.jsonl",
}
HIDDEN_DIR = DATA_DIR / "hidden_test_ready"
LIST_KEYS = {"supporting_departments", "policy_references", "escalation_rules", "missing_information", "emotion_indicators",
             "tags", "required_actions", "secondary_issues", "entities", "signals"}
BOOL_KEYS = {"escalation_required", "follow_up_required", "blocking_missing_information", "prompt_injection", "manual_review_expected"}
NUM_KEYS = {"compensation_amount_usd"}
MAX_RECORDS = 5000


def available() -> list[dict[str, Any]]:
    """Built-in splits plus any dataset file dropped into data/hidden_test_ready/ (e.g. a judges' hidden set)."""
    out = []
    for key, path in BUILTIN.items():
        out.append({"key": key, "path": str(path.relative_to(DATA_DIR.parent)), "exists": path.exists(),
                    "records": _count(path) if path.exists() else 0})
    if HIDDEN_DIR.exists():
        for path in sorted(HIDDEN_DIR.iterdir()):
            if path.is_file() and path.suffix.lower() in (".json", ".jsonl", ".csv") and path != BUILTIN["holdout"] \
                    and path.name != "manifest.yaml" and not path.name.startswith("holdout_complaints."):
                out.append({"key": f"file:{path.name}", "path": str(path.relative_to(DATA_DIR.parent)), "exists": True,
                            "records": _count(path)})
    return out


def _count(path: Path) -> int:
    try:
        return len(read_path(path))
    except Exception:
        return 0


def resolve(key: str) -> Path:
    if key in BUILTIN:
        return BUILTIN[key]
    if key.startswith("file:"):
        name = Path(key[5:]).name  # no traversal: only a bare file name inside hidden_test_ready
        path = HIDDEN_DIR / name
        if path.exists():
            return path
    raise ValidationFailed(f"Unknown dataset '{key}'.")


def read_path(path: Path) -> list[dict[str, Any]]:
    return parse(path.read_bytes(), path.suffix.lower().lstrip("."))


def parse(data: bytes, fmt: str) -> list[dict[str, Any]]:
    text = data.decode("utf-8-sig", errors="replace")
    fmt = fmt.lower()
    if fmt == "csv":
        records = [unflatten(row) for row in csv.DictReader(io.StringIO(text))]
    elif fmt == "jsonl":
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    elif fmt == "json":
        payload = json.loads(text)
        records = (payload.get("complaints") or payload.get("records") or []) if isinstance(payload, dict) else payload
    else:
        raise ValidationFailed(f"Unsupported dataset format '{fmt}' (use json, jsonl or csv).")
    if not isinstance(records, list) or not all(isinstance(r, dict) for r in records):
        raise ValidationFailed("The dataset must be a list of complaint records.")
    if len(records) > MAX_RECORDS:
        raise ValidationFailed(f"Datasets are limited to {MAX_RECORDS} records per run.")
    problems = [i for i, r in enumerate(records) if not str(r.get("description") or "").strip()]
    if problems and len(problems) == len(records):
        raise ValidationFailed("No record has a description - is this a complaint dataset?")
    for i, r in enumerate(records):
        r.setdefault("complaint_id", r.get("id") or f"ROW-{i + 1:05d}")
        if not r.get("title"):
            r["title"] = str(r.get("description") or "")[:80] or "(untitled complaint)"
    return records


def _value(key: str, raw: str) -> Any:
    raw = raw.strip()
    if raw == "":
        return [] if key in LIST_KEYS else None
    if key in BOOL_KEYS:
        return raw.lower() in ("true", "1", "yes")
    if key in NUM_KEYS:
        try:
            return float(raw)
        except ValueError:
            return None
    if key == "secondary_issues":
        return [{"subcategory": part.split(":")[0], "label": part.split(":", 1)[1] if ":" in part else ""} for part in raw.split(";")]
    if key == "entities":
        return [{"type": p.split("=", 1)[0], "value": p.split("=", 1)[1] if "=" in p else ""} for p in raw.split(";")]
    if key == "required_actions":
        return [{"any_of": p.split("|")} if "|" in p else p for p in raw.split(";")]
    if key in LIST_KEYS:
        return [p for p in raw.split(";") if p]
    return raw


def unflatten(row: dict[str, str]) -> dict[str, Any]:
    """Inverse of scripts/dataset/outputs.flatten (tolerant of missing or extra columns)."""
    rec: dict[str, Any] = {"expected": {}, "declared": {"signals": [], "complaint_facts": {}, "history": {}}}
    for col, raw in row.items():
        if col is None:
            continue
        raw = raw or ""
        if col.startswith("expected_"):
            key = col[len("expected_"):]
            rec["expected"][key] = _value(key, raw)
        elif col == "declared_signals":
            rec["declared"]["signals"] = [s for s in raw.split(";") if s]
        elif col.startswith("fact_"):
            rec["declared"]["complaint_facts"][col[5:]] = raw
        elif col.startswith("history_"):
            rec["declared"]["history"][col[8:]] = raw
        elif col == "attachments":
            rec["attachments"] = [{"file_name": p.split("|")[0], "content_type": p.split("|")[1] if "|" in p else "application/octet-stream"}
                                  for p in raw.split(";") if p]
        elif col == "tags":
            rec["tags"] = [t for t in raw.split(";") if t]
        else:
            rec[col] = raw.strip() or None
    if not rec["expected"]:
        rec["expected"] = None
    return rec


def to_submission(rec: dict[str, Any], *, previous_ref: str | None = None) -> dict[str, Any]:
    """Dataset record -> complaint submission (the same fields a customer or agent would provide)."""
    return {
        "title": str(rec.get("title") or "").strip(), "description": str(rec.get("description") or ""),
        "supporting_info": rec.get("supporting_information") or rec.get("supporting_info") or "",
        "customer_type": rec.get("customer_type") or "individual", "channel": rec.get("channel") or "web_form",
        "product_text": rec.get("product_service") or rec.get("product") or "",
        "order_ref": rec.get("order_reference") or rec.get("order_ref") or None,
        "transaction_ref": rec.get("transaction_reference") or rec.get("transaction_ref") or None,
        "previous_complaint_ref": previous_ref if previous_ref is not None else (rec.get("previous_complaint_reference") or None),
        "preferred_contact": rec.get("preferred_contact_method") or rec.get("preferred_contact") or "email",
        "requested_resolution": rec.get("requested_resolution") or "none",
        "requested_tone": rec.get("requested_tone") or "professional",
        "complaint_date": rec.get("complaint_date"),
        "attachment_metadata": rec.get("attachments") or [],
    }
