#!/usr/bin/env python
"""Generate the SupportNova complaint dataset for the fictional Lumora Home Technologies.

Outputs (relative to ``--out-dir``, default ``data``)::

    sample_complaints/customers.json          simulated customers
    sample_complaints/orders.json             simulated order ledger (all referenced + background orders)
    sample_complaints/complaints.jsonl|csv    DEV set    (CMP-00001.., chronological)
    hidden_test_ready/holdout_complaints.jsonl|csv   HOLDOUT set (EVL-00001.., unseen templates)
    sample_complaints/dataset_summary.json    counts, SRS-minimum checks, coherence report

Deterministic: the same ``--seed`` always produces byte-identical files.
Exit code 1 when an intended resolution rule, a scenario expectation or a declared
signal (coherence) check fails, unless ``--allow-failures`` is given.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# scripts/ (for the ``dataset`` package) and backend/src (for ``supportnova``) - import order independent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from dataset.builder import DatasetBuilder
from dataset.common import DEFAULT_SEED, REPO_ROOT
from dataset.outputs import write_csv, write_json, write_jsonl
from dataset.summary import summarize


def _print_checks(summary: dict) -> None:
    print(f"{'check':45} {'actual':>8}  status  requirement")
    for check in summary["srs_minimum_checks"]:
        status = "PASS" if check["passed"] else "FAIL"
        print(f"{check['name']:45} {check['actual']!s:>8}  {status:6}  {check['requirement']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"random seed (default {DEFAULT_SEED})")
    parser.add_argument("--out-dir", default="data", help="output directory (default: data, relative to the repo root)")
    parser.add_argument("--allow-failures", action="store_true", help="write outputs and exit 0 despite check failures")
    parser.add_argument("--quiet", action="store_true", help="only print failures and the final status")
    args = parser.parse_args(argv)

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir

    builder = DatasetBuilder(args.seed)
    dev, holdout = builder.build()
    rule_ids = {r.rule_id for r in builder.matrix.resolution_rules}

    declared_missing = [c for c in builder.coherence if c["declared_not_found"]]
    negated_only = [c for c in builder.coherence if c["declared_negated_only"]]
    undeclared = [c for c in builder.coherence if c["undeclared_lexical_hits"]]
    traps = [c for c in builder.coherence if c["deliberate_lexical_traps"]]
    extra = {
        "seed": args.seed,
        "generation": builder.stats(),
        "coherence": {
            "method": "declared signals are searched in title+description+supporting text with the terms/patterns "
                      "of rules/complaint_rules/signals.yaml; negation window as configured",
            "declared_signal_not_found": len(declared_missing),
            "declared_signal_only_in_negation_window": len(negated_only),
            "undeclared_lexical_hits": len(undeclared),
            "deliberate_lexical_traps": len(traps),
            "details": builder.coherence,
        },
        "intended_rule_or_expectation_failures": builder.failures,
        "render_errors": builder.render_errors,
    }
    summary = summarize(dev, holdout, rule_ids, extra)

    sample = out_dir / "sample_complaints"
    hidden = out_dir / "hidden_test_ready"
    write_json(sample / "customers.json", builder.customers)
    write_json(sample / "orders.json", builder.ledger())
    write_jsonl(sample / "complaints.jsonl", dev)
    write_csv(sample / "complaints.csv", dev)
    write_jsonl(hidden / "holdout_complaints.jsonl", holdout)
    write_csv(hidden / "holdout_complaints.csv", holdout)
    write_json(sample / "dataset_summary.json", summary)

    if not args.quiet:
        print(f"seed={args.seed}  scenarios={len(builder.scenarios)}  dev={len(dev)}  holdout={len(holdout)}  "
              f"orders={len(builder.orders)}  customers={len(builder.customers)}")
        _print_checks(summary)
        print(f"coherence: declared-not-found={len(declared_missing)}  declared-negated-only={len(negated_only)}  "
              f"undeclared-lexical-hits={len(undeclared)}  deliberate-traps={len(traps)}")
    problems = builder.failures + builder.render_errors
    for line in problems:
        print("FAILURE", line)
    for item in declared_missing:
        print("COHERENCE", item["complaint_id"], item["scenario_id"], "declared but not found:",
              item["declared_not_found"])
    failed = bool(problems or declared_missing or not summary["all_checks_passed"])
    print("GENERATION", "FAILED" if failed else "OK", f"-> {out_dir}")
    return 1 if failed and not args.allow_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
