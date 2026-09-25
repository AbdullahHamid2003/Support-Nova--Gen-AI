"""Writers for JSON, JSONL and flattened CSV outputs (lists joined with ';')."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .records import RECORD_KEYS


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _action(item: Any) -> str:
    if isinstance(item, dict):
        return "|".join(item.get("any_of", []))
    return str(item)


def flatten(record: dict[str, Any]) -> dict[str, str]:
    """One CSV row per record. Nested blocks become prefixed columns; lists are ';'-joined."""
    row: dict[str, str] = {}
    for key in RECORD_KEYS:
        if key in ("declared", "expected"):
            continue
        value = record.get(key)
        if key == "attachments":
            row[key] = ";".join(f"{a['file_name']}|{a['content_type']}" for a in value or [])
        elif key == "tags":
            row[key] = ";".join(value or [])
        else:
            row[key] = _scalar(value)
    declared = record["declared"]
    row["declared_signals"] = ";".join(declared["signals"])
    for fkey, fvalue in declared["complaint_facts"].items():
        row[f"fact_{fkey}"] = _scalar(fvalue)
    for hkey, hvalue in declared["history"].items():
        row[f"history_{hkey}"] = _scalar(hvalue)
    for ekey, evalue in record["expected"].items():
        column = f"expected_{ekey}"
        if ekey == "secondary_issues":
            row[column] = ";".join(f"{s['subcategory']}:{s['label']}" for s in evalue)
        elif ekey == "entities":
            row[column] = ";".join(f"{e['type']}={e['value']}" for e in evalue)
        elif ekey == "required_actions":
            row[column] = ";".join(_action(a) for a in evalue)
        elif isinstance(evalue, list):
            row[column] = ";".join(_scalar(v) for v in evalue)
        else:
            row[column] = _scalar(evalue)
    return row


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [flatten(r) for r in records]
    columns: list[str] = []
    for row in rows:
        for column in row:
            if column not in columns:
                columns.append(column)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
