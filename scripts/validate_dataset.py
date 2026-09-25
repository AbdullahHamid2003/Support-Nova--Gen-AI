#!/usr/bin/env python
"""Validate the SupportNova complaint dataset (dev + holdout). Exits non-zero on any FAIL.

Checks
------
* files present, CSV row counts equal the JSONL row counts
* JSON Schema (schemas/dataset/complaint_record.schema.json, draft 2020-12) for every record
* SRS minimum counts and the required difficulty mix (dev and holdout), resolution-rule coverage
* ID format, contiguity and chronological order; complaint dates inside each split's window
* referential integrity: customers, orders, transactions, order ownership (except tagged mismatches),
  previous-complaint references / duplicate links point to EARLIER complaints (except tagged invalid ones)
* codes exist in the YAML configuration: categories, subcategories, departments, actions, escalation
  levels, resolution / escalation rule IDs, follow-up types, missing-information fields, policy documents
* every declared signal exists in signals.yaml and is lexically present in the complaint text
* label reproducibility: label_declared(declared facts) reproduces every expected rule-derived field
* holdout disjointness (no shared scenario_id) and max token-set Jaccard(holdout, dev) < 0.8
* text uniqueness (only tagged exact duplicates may repeat, and must equal their source)
* entities appear verbatim in the text; derived flags (manual review, prompt injection) are consistent
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

# scripts/ (for the ``dataset`` package) and backend/src (for ``supportnova``) - import order independent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

import yaml
from jsonschema import Draft202012Validator

from dataset.common import (
    DEV_END,
    DEV_START,
    HOLDOUT_END,
    HOLDOUT_START,
    KB_SPEC_PATH,
    ORDER_REF_PATTERN,
    REPO_ROOT,
    SCHEMA_PATH,
)
from dataset.lexicon import SignalDetector
from dataset.outputs import read_jsonl
from dataset.records import (
    build_ledger_indexes,
    declared_input,
    is_valid_order_ref,
    jsonable,
    label_projection,
    manual_review_expected,
    text_of,
)
from dataset.summary import mix_checks
from dataset.textutil import jaccard, tokens
from supportnova.rule_engine.loader import load_matrix
from supportnova.rule_engine.reference import label_declared

MAX_EXAMPLES = 5
JACCARD_LIMIT = 0.8


class Report:
    """Collects PASS / WARN / FAIL rows and prints them as a table."""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str]] = []

    def add(self, name: str, ok: bool, detail: str = "", warn_only: bool = False) -> None:
        status = "PASS" if ok else ("WARN" if warn_only else "FAIL")
        self.rows.append((name, status, detail))

    def problems(self, name: str, problems: list[str], ok_detail: str = "", warn_only: bool = False) -> None:
        if problems:
            shown = "; ".join(problems[:MAX_EXAMPLES]) + (f" (+{len(problems) - MAX_EXAMPLES} more)"
                                                          if len(problems) > MAX_EXAMPLES else "")
            self.add(name, False, f"{len(problems)} problem(s): {shown}", warn_only)
        else:
            self.add(name, True, ok_detail)

    @property
    def failed(self) -> bool:
        return any(status == "FAIL" for _, status, _ in self.rows)

    def print(self) -> None:
        width = max(len(n) for n, _, _ in self.rows) + 2
        print(f"{'check'.ljust(width)}status  details")
        print("-" * (width + 60))
        for name, status, detail in self.rows:
            print(f"{name.ljust(width)}{status:6}  {detail}")
        counts = Counter(s for _, s, _ in self.rows)
        print("-" * (width + 60))
        print(f"PASS={counts['PASS']}  WARN={counts['WARN']}  FAIL={counts['FAIL']}  ->  "
              f"{'VALIDATION FAILED' if self.failed else 'VALIDATION PASSED'}")


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _csv_rows(path: Path) -> int:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def _day(value: str) -> date:
    return date.fromisoformat(value[:10])


# ---------------------------------------------------------------------------
def check_files(report: Report, paths: dict[str, Path]) -> bool:
    missing = [k for k, p in paths.items() if not p.exists()]
    report.problems("files.present", [f"missing {k}: {paths[k]}" for k in missing],
                    f"{len(paths)} dataset files found")
    return not missing


def check_schema(report: Report, dev: list[dict[str, Any]], holdout: list[dict[str, Any]]) -> None:
    schema = _load_json(SCHEMA_PATH)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    problems = []
    for record in dev + holdout:
        for err in validator.iter_errors(record):
            path = "/".join(str(p) for p in err.absolute_path)
            problems.append(f"{record.get('complaint_id')}: {path}: {err.message[:90]}")
    report.problems("schema.records", problems, f"{len(dev) + len(holdout)} records valid against {SCHEMA_PATH.name}")


def check_ids_and_dates(report: Report, records: list[dict[str, Any]], prefix: str, start: date, end: date,
                        split: str) -> None:
    problems = []
    ids = [r["complaint_id"] for r in records]
    expected_ids = [f"{prefix}-{n:05d}" for n in range(1, len(records) + 1)]
    if sorted(ids) != expected_ids:
        problems.append(f"IDs are not contiguous {prefix}-00001..{prefix}-{len(records):05d}")
    ordered = sorted(records, key=lambda r: r["complaint_id"])
    dates = [r["complaint_date"] for r in ordered]
    if dates != sorted(dates):
        problems.append("IDs are not in chronological order of complaint_date")
    for r in records:
        if not (start <= _day(r["complaint_date"]) <= end):
            problems.append(f"{r['complaint_id']} date {r['complaint_date']} outside {start}..{end}")
        if r["split"] != split:
            problems.append(f"{r['complaint_id']} split={r['split']} (expected {split})")
    report.problems(f"ids_dates.{split}", problems, f"{prefix}-00001..{prefix}-{len(records):05d}, {start}..{end}")


def check_references(report: Report, dev: list[dict[str, Any]], holdout: list[dict[str, Any]],
                     customers: list[dict[str, Any]], orders: list[dict[str, Any]], matrix: Any) -> None:
    by_cust = {c["customer_ref"]: c for c in customers}
    by_ref, by_txn = build_ledger_indexes(orders)
    all_records = dev + holdout
    by_id = {r["complaint_id"]: r for r in all_records}
    problems: list[str] = []
    for r in all_records:
        cid = r["complaint_id"]
        cust = by_cust.get(r["customer_ref"])
        if cust is None:
            problems.append(f"{cid}: unknown customer {r['customer_ref']}")
        elif cust["full_name"] != r["customer_name"] or cust["customer_type"] != r["customer_type"]:
            problems.append(f"{cid}: customer name/type differ from customers.json")
        ref = r["order_reference"]
        tags = set(r["tags"])
        if ref is not None:
            if not is_valid_order_ref(ref):
                if "malformed_order_reference" not in tags:
                    problems.append(f"{cid}: malformed order reference {ref!r} not tagged")
            elif ref not in by_ref:
                if "invalid_order_reference" not in tags:
                    problems.append(f"{cid}: order {ref} not in ledger and not tagged invalid_order_reference")
            elif by_ref[ref]["customer_ref"] != r["customer_ref"] and "order_ownership_mismatch" not in tags:
                problems.append(f"{cid}: order {ref} belongs to {by_ref[ref]['customer_ref']}")
        txn = r["transaction_reference"]
        if txn is not None:
            if txn not in by_txn:
                problems.append(f"{cid}: transaction {txn} not in ledger")
            elif is_valid_order_ref(ref) and ref in by_ref and by_txn[txn]["order_ref"] != ref:
                problems.append(f"{cid}: transaction {txn} does not belong to order {ref}")
        sku = r["product_sku"]
        if sku is not None and sku not in matrix.products:
            problems.append(f"{cid}: unknown product_sku {sku}")
        prev = r["previous_complaint_reference"]
        if prev is not None:
            target = by_id.get(prev)
            if target is None or (r["split"] == "dev" and target["split"] != "dev"):
                if "invalid_complaint_reference" not in tags:
                    problems.append(f"{cid}: previous_complaint_reference {prev} does not exist")
            elif target["complaint_date"] >= r["complaint_date"]:
                problems.append(f"{cid}: previous_complaint_reference {prev} is not earlier")
            elif target["customer_ref"] != r["customer_ref"]:
                problems.append(f"{cid}: previous complaint {prev} belongs to another customer")
        exp = r["expected"]
        for key in ("is_duplicate_of", "is_near_duplicate_of", "is_repeat_of"):
            link = exp[key]
            if link is None:
                continue
            target = by_id.get(link)
            if target is None:
                problems.append(f"{cid}: {key} {link} does not exist")
            elif target["complaint_date"] >= r["complaint_date"] or target["customer_ref"] != r["customer_ref"]:
                problems.append(f"{cid}: {key} {link} is not an earlier complaint of the same customer")
            elif key == "is_duplicate_of" and (target["title"], target["description"], target["supporting_information"]) != (
                    r["title"], r["description"], r["supporting_information"]):
                problems.append(f"{cid}: exact duplicate text differs from {link}")
        if sum(1 for k in ("is_duplicate_of", "is_near_duplicate_of", "is_repeat_of") if exp[k]) > 1:
            problems.append(f"{cid}: more than one duplicate/repeat link")
    report.problems("references.complaints", problems, "customers, orders, transactions, links and history references resolve")

    # ledger integrity
    ledger_problems: list[str] = []
    order_re = re.compile(ORDER_REF_PATTERN)
    seen_txn: set[str] = set()
    for o in orders:
        if not order_re.match(o["order_ref"]):
            ledger_problems.append(f"bad order_ref {o['order_ref']}")
        if o["customer_ref"] not in by_cust:
            ledger_problems.append(f"{o['order_ref']}: unknown customer {o['customer_ref']}")
        for item in o["items"]:
            product = matrix.products.get(item["sku"])
            if product is None:
                ledger_problems.append(f"{o['order_ref']}: unknown sku {item['sku']}")
            elif abs(float(product.price) - float(item["unit_price"])) > 0.001 and item["sku"] not in ("SVC-CLOUD", "SVC-CARE"):
                ledger_problems.append(f"{o['order_ref']}: unit price {item['unit_price']} != catalog {product.price}")
        for t in o["transactions"]:
            if t["txn_ref"] in seen_txn:
                ledger_problems.append(f"duplicate txn {t['txn_ref']}")
            seen_txn.add(t["txn_ref"])
        if o["status"] not in ("processing", "dispatched", "in_transit", "delivered", "lost", "cancelled", "returned"):
            ledger_problems.append(f"{o['order_ref']}: invalid status {o['status']}")
    report.problems("references.ledger", ledger_problems,
                    f"{len(orders)} orders: refs, owners, catalog prices, unique transactions")


def check_codes(report: Report, records: list[dict[str, Any]], matrix: Any) -> None:
    rules = {r.rule_id: r for r in matrix.resolution_rules}
    esc_ids = {e.rule_id for e in matrix.escalation_rules}
    levels = {lv.name for lv in matrix.escalation_levels}
    mi_fields = {m.field for m in matrix.missing_info_rules}
    follow_types = set(matrix.follow_up_types)
    with KB_SPEC_PATH.open("r", encoding="utf-8") as handle:
        kb = yaml.safe_load(handle)
    kb_sections = {d["doc_id"]: {str(s["id"]) for s in d.get("sections", [])} for d in kb["documents"]}
    problems: list[str] = []
    warn_sections: set[str] = set()
    for r in records:
        cid = r["complaint_id"]
        e = r["expected"]
        if e["category"] not in matrix.categories:
            problems.append(f"{cid}: unknown category {e['category']}")
        if e["subcategory"] not in matrix.subcategories or matrix.category_of(e["subcategory"]) != e["category"]:
            problems.append(f"{cid}: subcategory {e['subcategory']} not in category {e['category']}")
        for sec in e["secondary_issues"]:
            if sec["subcategory"] not in matrix.subcategories or matrix.category_of(sec["subcategory"]) != sec["category"]:
                problems.append(f"{cid}: bad secondary issue {sec}")
        for dept in [e["department"], *e["supporting_departments"]]:
            if dept not in matrix.departments:
                problems.append(f"{cid}: unknown department {dept}")
        for item in e["required_actions"]:
            codes = item["any_of"] if isinstance(item, dict) else [item]
            problems.extend(f"{cid}: unknown action {c}" for c in codes if c not in matrix.actions)
        rule = rules.get(e["resolution_rule"])
        if rule is None or rule.subcategory != e["subcategory"]:
            problems.append(f"{cid}: resolution rule {e['resolution_rule']} invalid for {e['subcategory']}")
        if e["escalation_level"] not in levels:
            problems.append(f"{cid}: unknown escalation level {e['escalation_level']}")
        for rid in e["escalation_rules"]:
            if rid not in esc_ids and rid not in rules:
                problems.append(f"{cid}: unknown escalation rule {rid}")
        if e["follow_up_type"] is not None and e["follow_up_type"] not in follow_types:
            problems.append(f"{cid}: unknown follow-up type {e['follow_up_type']}")
        problems.extend(f"{cid}: unknown missing-info field {m}" for m in e["missing_information"] if m not in mi_fields)
        for ref in e["policy_references"]:
            doc, _, section = ref.partition(":")
            if doc not in kb_sections:
                problems.append(f"{cid}: unknown policy document {doc}")
            elif section not in kb_sections[doc]:
                warn_sections.add(ref)
    report.problems("codes.configuration", problems,
                    "categories, departments, actions, levels, rule IDs, follow-up types, MIS fields, policy documents")
    report.add("codes.policy_sections", not warn_sections,
               "all cited sections exist in knowledge_base/kb_spec.yaml" if not warn_sections else
               f"{len(warn_sections)} cited section(s) not listed in kb_spec.yaml: {sorted(warn_sections)[:6]}",
               warn_only=True)


def check_signals(report: Report, records: list[dict[str, Any]], detector: SignalDetector) -> None:
    unknown: list[str] = []
    missing: list[str] = []
    negated: list[str] = []
    for r in records:
        text = text_of(r)
        for sig in r["declared"]["signals"]:
            if sig not in detector.names:
                unknown.append(f"{r['complaint_id']}: {sig}")
            elif not detector.found_any(text, sig):
                missing.append(f"{r['complaint_id']}: {sig}")
            elif not detector.found(text, sig):
                negated.append(f"{r['complaint_id']}: {sig}")
    report.problems("signals.exist", unknown, "every declared signal is defined in signals.yaml")
    report.problems("signals.coherence", missing, "every declared signal is expressed in the complaint text")
    report.problems("signals.negation_window", negated, "no declared signal appears only inside a negation window",
                    warn_only=True)


def check_reproducibility(report: Report, records: list[dict[str, Any]], orders: list[dict[str, Any]],
                          matrix: Any) -> None:
    by_ref, by_txn = build_ledger_indexes(orders)
    problems: list[str] = []
    for r in records:
        label = label_projection(label_declared(matrix, declared_input(r, by_ref, by_txn)))
        exp = jsonable(r["expected"])
        diffs = [k for k, v in label.items() if exp.get(k) != v]
        secondary = [s["subcategory"] for s in exp["secondary_issues"]]
        if diffs:
            problems.append(f"{r['complaint_id']}: {', '.join(diffs)}")
        elif matrix.category_of(exp["subcategory"]) != exp["category"] or len(set(secondary)) != len(secondary):
            problems.append(f"{r['complaint_id']}: classification inconsistent")
    report.problems("labels.reproducible", problems,
                    f"label_declared reproduces all rule-derived expected fields for {len(records)} records")


def check_holdout(report: Report, dev: list[dict[str, Any]], holdout: list[dict[str, Any]]) -> None:
    shared = sorted({r["scenario_id"] for r in dev} & {r["scenario_id"] for r in holdout})
    report.problems("holdout.scenario_disjoint", [f"shared scenario_id {s}" for s in shared],
                    f"{len({r['scenario_id'] for r in holdout})} holdout scenarios, none used in dev")
    dev_tokens = [(r["complaint_id"], tokens(text_of(r))) for r in dev]
    best = (0.0, "", "")
    for h in holdout:
        ht = tokens(text_of(h))
        for cid, dt in dev_tokens:
            score = jaccard(ht, dt)
            if score > best[0]:
                best = (score, h["complaint_id"], cid)
    report.add("holdout.max_jaccard", best[0] < JACCARD_LIMIT,
               f"max token-set Jaccard(holdout, dev) = {best[0]:.3f} ({best[1]} vs {best[2]}), limit < {JACCARD_LIMIT}")


def check_uniqueness(report: Report, records: list[dict[str, Any]]) -> None:
    seen: dict[tuple[str, str], str] = {}
    problems = []
    for r in sorted(records, key=lambda r: (r["split"] != "dev", r["complaint_id"])):
        key = (r["title"], r["description"])
        if key in seen and not r["expected"]["is_duplicate_of"]:
            problems.append(f"{r['complaint_id']} repeats the text of {seen[key]}")
        seen.setdefault(key, r["complaint_id"])
    dups = sum(1 for r in records if r["expected"]["is_duplicate_of"])
    report.problems("texts.unique", problems, f"all texts unique except {dups} deliberate exact duplicates")


def check_consistency(report: Report, records: list[dict[str, Any]]) -> None:
    problems = []
    order_re = re.compile(ORDER_REF_PATTERN)
    for r in records:
        cid = r["complaint_id"]
        text = text_of(r)
        e = r["expected"]
        f = r["declared"]["complaint_facts"]
        for ent in e["entities"]:
            if ent["value"] not in text:
                problems.append(f"{cid}: entity {ent['value']!r} not in text")
        if f["channel"] != r["channel"] or f["requested_resolution"] != r["requested_resolution"]:
            problems.append(f"{cid}: complaint_facts channel/requested_resolution differ from the record")
        if f["has_order_reference"] != bool(r["order_reference"] and order_re.match(r["order_reference"])):
            problems.append(f"{cid}: has_order_reference inconsistent with order_reference")
        if f["has_transaction_reference"] != bool(r["transaction_reference"]):
            problems.append(f"{cid}: has_transaction_reference inconsistent")
        images = any(a["content_type"].startswith("image/") for a in r["attachments"])
        if f["has_photo_evidence"] != images:
            problems.append(f"{cid}: has_photo_evidence inconsistent with attachments")
        if f["word_count"] != len(r["description"].split()):
            problems.append(f"{cid}: word_count mismatch")
        if e["prompt_injection"] != ("prompt_injection" in r["tags"]):
            problems.append(f"{cid}: prompt_injection flag and tag disagree")
        manual = manual_review_expected(prompt_injection=e["prompt_injection"], tags=r["tags"], category=e["category"],
                                        signals=r["declared"]["signals"],
                                        blocking_missing=e["blocking_missing_information"])
        if manual != e["manual_review_expected"]:
            problems.append(f"{cid}: manual_review_expected inconsistent")
        if bool(e["secondary_issues"]) != ("multi_issue" in r["tags"]):
            problems.append(f"{cid}: multi_issue tag inconsistent")
    report.problems("records.consistency", problems,
                    "entities verbatim in text, facts match record fields, derived flags consistent")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", default="data", help="dataset root (default: data, relative to the repo root)")
    args = parser.parse_args(argv)
    root = Path(args.data_dir)
    if not root.is_absolute():
        root = REPO_ROOT / root
    paths = {
        "customers": root / "sample_complaints" / "customers.json",
        "orders": root / "sample_complaints" / "orders.json",
        "dev_jsonl": root / "sample_complaints" / "complaints.jsonl",
        "dev_csv": root / "sample_complaints" / "complaints.csv",
        "holdout_jsonl": root / "hidden_test_ready" / "holdout_complaints.jsonl",
        "holdout_csv": root / "hidden_test_ready" / "holdout_complaints.csv",
        "summary": root / "sample_complaints" / "dataset_summary.json",
    }
    report = Report()
    if not check_files(report, paths):
        report.print()
        return 1
    customers = _load_json(paths["customers"])
    orders = _load_json(paths["orders"])
    dev = read_jsonl(paths["dev_jsonl"])
    holdout = read_jsonl(paths["holdout_jsonl"])
    matrix = load_matrix()
    detector = SignalDetector()

    csv_problems = []
    if _csv_rows(paths["dev_csv"]) != len(dev):
        csv_problems.append("complaints.csv row count differs from complaints.jsonl")
    if _csv_rows(paths["holdout_csv"]) != len(holdout):
        csv_problems.append("holdout_complaints.csv row count differs from holdout_complaints.jsonl")
    report.problems("files.csv_rows", csv_problems, f"CSV rows match JSONL ({len(dev)} dev, {len(holdout)} holdout)")

    check_schema(report, dev, holdout)
    rule_ids = {r.rule_id for r in matrix.resolution_rules}
    for check in mix_checks(dev, holdout, rule_ids):
        report.add(f"counts.{check.name}", check.passed, f"{check.actual} (required {check.requirement})")
    check_ids_and_dates(report, dev, "CMP", DEV_START, DEV_END, "dev")
    check_ids_and_dates(report, holdout, "EVL", HOLDOUT_START, HOLDOUT_END, "holdout")
    check_references(report, dev, holdout, customers, orders, matrix)
    check_codes(report, dev + holdout, matrix)
    check_signals(report, dev + holdout, detector)
    check_reproducibility(report, dev + holdout, orders, matrix)
    check_holdout(report, dev, holdout)
    check_uniqueness(report, dev + holdout)
    check_consistency(report, dev + holdout)

    types = Counter(c["customer_type"] for c in customers)
    share = {k: round(v / len(customers), 2) for k, v in types.items()}
    report.add("customers.distribution", abs(share.get("individual", 0) - 0.6) <= 0.05,
               f"{len(customers)} customers {dict(sorted(share.items()))} (target 60/20/10/10)")
    report.print()
    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
