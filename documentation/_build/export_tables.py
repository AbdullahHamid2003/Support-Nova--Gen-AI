"""Export the report's reference tables as CSV files into documentation/tables/ (read-only on the repository).

    backend/.venv/Scripts/python.exe documentation/_build/export_tables.py

Every table is read from the repository itself: rules/, config/, knowledge_base/manifest.yaml, schemas/, data/,
reports/, the API router source, the SQLAlchemy models, the RBAC module and the pytest collection. Nothing is
typed in by hand.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

DOC = Path(__file__).resolve().parents[1]
ROOT = DOC.parent
OUT = DOC / "tables"


def y(path: str):  # noqa: ANN201
    return yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))


def j(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(j(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def write(name: str, header: list[str], rows: list[list[object]], title: str, index: list[tuple[str, str, int]]) -> None:
    OUT.mkdir(exist_ok=True)
    with (OUT / name).open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows([[j(c) for c in r] for r in rows])
    index.append((name, title, len(rows)))


def main() -> None:
    index: list[tuple[str, str, int]] = []

    tax = y("config/taxonomy.yaml")["categories"]
    write("taxonomy.csv", ["category_code", "category_name", "subcategory_code", "subcategory_name", "description"],
          [[c["code"], c["name"], s["code"], s["name"], s.get("description", "")] for c in tax for s in c["subcategories"]],
          "Complaint taxonomy (config/taxonomy.yaml)", index)
    write("departments.csv", ["code", "name", "description"],
          [[d["code"], d["name"], d.get("description", "")] for d in y("config/departments.yaml")["departments"]],
          "Departments (config/departments.yaml)", index)
    acts = y("config/actions.yaml")
    act_rows = []
    for key in ("actions", "prohibited_actions"):
        items = acts.get(key) or []
        for a in items:
            if isinstance(a, dict):
                act_rows.append([key, a.get("code"), a.get("name") or a.get("label"), a.get("group", ""), a.get("description", "")])
    if act_rows:
        write("action-catalog.csv", ["list", "code", "name", "group", "description"], act_rows, "Action catalog (config/actions.yaml)", index)

    vp = y("rules/validation_policy.yaml")
    write("validation-checks.csv", ["code", "dimension", "severity", "name"],
          [[k, v["dimension"], v["severity"], v["name"]] for k, v in vp["checks"].items()],
          "Python validation checks (rules/validation_policy.yaml)", index)
    write("review-triggers.csv", ["rule_id", "code", "name", "enabled", "categories", "signals", "policy_refs"],
          [[r["rule_id"], r["code"], r["name"], r.get("enabled"), r.get("categories"), r.get("signals"), r.get("policy_refs")]
           for r in y("rules/complaint_rules/review_rules.yaml")["review_rules"]],
          "Manual-review triggers (rules/complaint_rules/review_rules.yaml)", index)

    res = y("rules/complaint_rules/resolution_rules.yaml")["resolution_rules"]
    write("resolution-rules.csv",
          ["rule_id", "subcategory", "name", "precedence", "when", "urgency", "impact", "required_actions", "recommended_actions",
           "prohibited_actions", "refund", "replacement", "compensation", "escalation", "follow_up_type", "follow_up_due_hours",
           "timelines", "policy_refs"],
          [[r["rule_id"], r["subcategory"], r["name"], r.get("precedence"), r.get("when") or "always", r.get("urgency"), r.get("impact"),
            [a if isinstance(a, str) else "any_of(" + ", ".join(a["any_of"]) + ")" for a in r.get("required_actions", [])],
            r.get("recommended_actions"), r.get("prohibited_actions"), (r.get("eligibility") or {}).get("refund"),
            (r.get("eligibility") or {}).get("replacement"), (r.get("eligibility") or {}).get("compensation"), r.get("escalation"),
            (r.get("follow_up") or {}).get("type"), (r.get("follow_up") or {}).get("due_hours"), r.get("timelines"), r.get("policy_refs")]
           for r in res],
          "Resolution rules (rules/complaint_rules/resolution_rules.yaml)", index)
    esc = y("rules/escalation_rules/escalation_rules.yaml")
    write("escalation-rules.csv", ["rule_id", "name", "trigger", "when", "level", "departments", "policy_refs", "reason"],
          [[r["rule_id"], r["name"], r.get("trigger"), r.get("when"), r.get("level"), r.get("departments"), r.get("policy_refs"), r.get("reason")]
           for r in esc["escalation_rules"]],
          "Escalation rules (rules/escalation_rules/escalation_rules.yaml)", index)
    rt = y("rules/routing_rules/routing_rules.yaml")
    write("routing-rules.csv", ["rule_id", "type", "subcategory_or_condition", "primary_department", "supporting_departments", "policy_refs"],
          [[r["rule_id"], "routing", r["subcategory"], r["primary_department"], r.get("supporting_departments"), r.get("policy_refs")]
           for r in rt["routing_rules"]]
          + [[r["rule_id"], "conditional", r.get("when"), "", r.get("add_supporting"), r.get("policy_refs")] for r in rt["conditional_routing"]],
          "Routing and conditional routing rules (rules/routing_rules/routing_rules.yaml)", index)
    pr = y("rules/complaint_rules/priority_rules.yaml")
    write("urgency-floors.csv", ["rule_id", "name", "when", "urgency", "impact", "policy_refs"],
          [[r["rule_id"], r["name"], r.get("when"), r.get("urgency", "(unchanged)"), r.get("impact"), r.get("policy_refs")] for r in pr["urgency_floors"]],
          "Urgency floors (rules/complaint_rules/priority_rules.yaml)", index)
    write("priority-matrix.csv", ["urgency", "impact", "priority"],
          [[u, i, p] for u, row in pr["priority_matrix"].items() if isinstance(row, dict) for i, p in row.items()],
          "Priority matrix (rules/complaint_rules/priority_rules.yaml)", index)
    write("sla-rules.csv", ["rule_id", "priority", "first_response_hours", "resolution_hours", "policy_refs"],
          [[r["rule_id"], r["priority"], r["first_response_hours"], r["resolution_hours"], r.get("policy_refs")]
           for r in y("rules/sla_rules/sla_rules.yaml")["sla_rules"]],
          "SLA rules (rules/sla_rules/sla_rules.yaml)", index)
    write("parameters.csv", ["key", "value", "unit", "source", "description"],
          [[k, v.get("value"), v.get("unit"), v.get("source"), v.get("description")] for k, v in y("rules/parameters.yaml")["parameters"].items()],
          "Rule Matrix parameters (rules/parameters.yaml)", index)
    sig = y("rules/complaint_rules/signals.yaml")
    sig_items = sig.get("signals", sig) if isinstance(sig, dict) else sig
    sig_rows = []
    if isinstance(sig_items, dict):
        for k, v in sig_items.items():
            if isinstance(v, dict):
                sig_rows.append([k, v.get("name") or v.get("label", ""), len(v.get("terms") or []), len(v.get("patterns") or [])])
    elif isinstance(sig_items, list):
        for v in sig_items:
            if isinstance(v, dict):
                sig_rows.append([v.get("signal") or v.get("code") or v.get("id"), v.get("name") or v.get("label", ""), len(v.get("terms") or []),
                                 v.get("policy_refs")])
    if sig_rows:
        write("signals.csv", ["signal", "name", "term_count", "pattern_count"], sig_rows, "Deterministic signals (rules/complaint_rules/signals.yaml)", index)

    man = y("knowledge_base/manifest.yaml")
    man = man if isinstance(man, list) else man.get("documents", [])
    write("knowledge-base-documents.csv",
          ["doc_id", "title", "doc_type", "version", "status", "effective_date", "format", "owner_department", "supersedes", "bytes", "sha256"],
          [[m["doc_id"], m["title"], m["doc_type"], m["version"], m["status"], m.get("effective_date"), m.get("format"),
            m.get("owner_department"), m.get("supersedes"), m.get("bytes"), m.get("sha256")] for m in man],
          "Knowledge Base documents and versions (knowledge_base/manifest.yaml)", index)

    for schema in sorted((ROOT / "schemas" / "ai").glob("*.schema.json")):
        s = json.loads(schema.read_text(encoding="utf-8"))
        rows = []
        for name, prop in (s.get("properties") or {}).items():
            typ = prop.get("type") or ("enum" if "enum" in prop else "object")
            rows.append([name, j(typ), "yes" if name in s.get("required", []) else "no", len(prop.get("enum", []) or []),
                         (prop.get("description") or "")[:200]])
        write(f"schema-{schema.name.replace('.schema.json', '')}.csv", ["field", "type", "required", "enum_values", "description"], rows,
              f"AI output schema fields ({schema.relative_to(ROOT).as_posix()})", index)

    summ = json.loads((ROOT / "data" / "sample_complaints" / "dataset_summary.json").read_text(encoding="utf-8")) \
        if (ROOT / "data" / "sample_complaints" / "dataset_summary.json").exists() else None
    if summ:
        rows = []
        for split in ("dev", "holdout"):
            part = summ.get(split) or {}
            for dim in ("by_category", "by_subcategory", "by_difficulty_type", "by_channel", "by_customer_type", "by_sentiment", "by_priority",
                        "by_escalation_level", "by_department", "by_requested_tone", "by_requested_resolution"):
                for k, v in (part.get(dim) or {}).items():
                    rows.append([split, dim.removeprefix("by_"), k, v])
        write("dataset-composition.csv", ["split", "dimension", "value", "complaints"], rows,
              "Complaint dataset composition (data/sample_complaints/dataset_summary.json)", index)

    # routes: read from the router source (same rule as the RBAC dependency: require("perm", ...))
    route_rx = re.compile(r'@router\.(get|post|put|delete|patch)\("([^"]+)"[^)]*\)\s*\n(?:async\s+)?def\s+(\w+)\((.*?)\)\s*->', re.S)
    perm_rx = re.compile(r"require(?:_any)?\(([^)]*)\)")
    rows = []
    for f in sorted((ROOT / "backend/src/supportnova/api/v1").glob("*.py")):
        for mth, path, fn, sig in route_rx.findall(f.read_text(encoding="utf-8")):
            perms = ",".join(p.strip().strip("\"'") for grp in perm_rx.findall(sig) for p in grp.split(","))
            rows.append([f.stem, mth.upper(), "/api/v1" + path, fn, perms or ("current_user" if "current_user" in sig else "public")])
    write("api-endpoints.csv", ["router", "method", "path", "handler", "required_permission"], rows, "REST API endpoints (FastAPI, /api/v1)", index)

    # database tables and RBAC: imported from the application (no settings or secrets are read)
    sys.path.insert(0, str(ROOT / "backend" / "src"))
    os.environ["SUPPORTNOVA_ENV_FILE"] = str(ROOT / "tests" / ".env.none")
    from supportnova.database import models  # noqa: F401
    from supportnova.database.base import Base
    from supportnova.security.rbac import ROLE_PERMISSIONS

    rows = []
    for t in Base.metadata.sorted_tables:
        fks = [f"{c.name}->{fk.column.table.name}" for c in t.columns for fk in c.foreign_keys]
        pk = [c.name for c in t.columns if c.primary_key]
        rows.append([t.name, len(t.columns), "; ".join(pk), "; ".join(c.name for c in t.columns), "; ".join(fks),
                     "; ".join(sorted(i.name for i in t.indexes))])
    write("database-tables.csv", ["table", "columns", "primary_key", "column_names", "foreign_keys", "indexes"], rows,
          "Database tables (SQLAlchemy models, Alembic 0001 + 0002)", index)
    roles = list(ROLE_PERMISSIONS)
    perms = sorted({p for ps in ROLE_PERMISSIONS.values() for p in ps})
    write("rbac-permissions.csv", ["permission", *roles], [[p, *["yes" if p in ROLE_PERMISSIONS[r] else "" for r in roles]] for p in perms],
          "Role permissions (backend/src/supportnova/security/rbac.py)", index)

    col = subprocess.run([sys.executable, "-m", "pytest", "tests", "--collect-only", "-q", "-p", "no:cacheprovider", "-o", "addopts="],
                         cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    tests = [ln.split("::", 1) for ln in col.stdout.splitlines() if "::" in ln]
    write("backend-tests.csv", ["file", "test"], tests, "Backend test cases (pytest --collect-only)", index)

    summary = (ROOT / "reports" / "genai_python_comparison" / "summary.md").read_text(encoding="utf-8")
    block = summary.split("## Accuracy against the expected labels, per field", 1)[1].split("##", 1)[0]
    rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in block.splitlines() if ln.startswith("| ") and "---" not in ln]
    write("holdout-field-accuracy.csv", ["field", "python_accuracy", "genai_accuracy", "genai_python_agreement", "n"], rows[1:],
          "Holdout evaluation run #1: accuracy per field (reports/genai_python_comparison/summary.md)", index)

    lines = ["# Report tables (CSV)", "",
             "Generated by `documentation/_build/export_tables.py` from the repository sources named in each row. "
             "Open the CSV files in Excel or any spreadsheet tool; the report chapters cite the same data.", "",
             "| File | Content | Rows |", "|---|---|---|"]
    lines += [f"| [{n}]({n}) | {t} | {c} |" for n, t, c in index]
    (OUT / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for n, t, c in index:
        print(f"{c:5d}  {n:40s} {t}")


if __name__ == "__main__":
    main()
