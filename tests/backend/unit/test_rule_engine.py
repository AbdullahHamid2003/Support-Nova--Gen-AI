"""Rule Matrix: condition semantics, priority matrix, escalation levels, integrity and the reference labeler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from supportnova.rule_engine.conditions import EvalContext, evaluate
from supportnova.rule_engine.decision import DecisionEngine
from supportnova.rule_engine.integrity import summarize, validate_matrix
from supportnova.rule_engine.reference import build_declared_context, label_declared

ROOT = Path(__file__).resolve().parents[3]


def ctx(matrix, facts: dict | None = None, signals: set[str] | None = None) -> EvalContext:  # type: ignore[no-untyped-def]
    return EvalContext(matrix=matrix, facts=facts or {}, signals=signals or set())


def test_rule_matrix_integrity(matrix) -> None:  # type: ignore[no-untyped-def]
    summary = summarize(validate_matrix(matrix))
    assert summary["valid"], summary["issues"][:5]
    assert summary["errors"] == 0


def test_rule_matrix_meets_srs_minimums(matrix) -> None:  # type: ignore[no-untyped-def]
    assert len(matrix.categories) >= 10
    assert len(matrix.subcategories) >= 20
    assert len(matrix.departments) >= 8
    assert len(matrix.resolution_rules) >= 100
    assert len(matrix.escalation_rules) >= 30


def test_three_valued_conditions(matrix) -> None:  # type: ignore[no-untyped-def]
    cond = {"fact": "order.days_since_delivery", "op": "lte", "value": 30}
    assert evaluate(cond, ctx(matrix, {"order": {"days_since_delivery": 10}})) is True
    assert evaluate(cond, ctx(matrix, {"order": {"days_since_delivery": 45}})) is False
    # unknown fact -> None ("requires verification"), never a guess
    assert evaluate(cond, ctx(matrix, {"order": {}})) is None
    assert evaluate({"all": [cond, {"signal": "overheating"}]}, ctx(matrix, {"order": {"days_since_delivery": 10}}, {"overheating"})) is True
    assert evaluate({"any": [{"signal": "fire_event"}, cond]}, ctx(matrix, {"order": {}}, set())) is None
    assert evaluate({"not": {"signal": "fire_event"}}, ctx(matrix)) is True
    # parameters are referenced, not hard-coded
    param_cond = {"fact": "order.days_since_delivery", "op": "lte", "value": "$param:refund_window_days"}
    assert evaluate(param_cond, ctx(matrix, {"order": {"days_since_delivery": 25}})) is True


@pytest.mark.parametrize(("urgency", "impact", "priority"), [
    ("Critical", "High", "P0"), ("Critical", "Medium", "P0"), ("Critical", "Low", "P1"),
    ("High", "High", "P1"), ("High", "Medium", "P2"), ("Medium", "High", "P2"), ("Medium", "Low", "P3"), ("Low", "Low", "P3"),
])
def test_priority_matrix(matrix, urgency: str, impact: str, priority: str) -> None:  # type: ignore[no-untyped-def]
    assert matrix.compute_priority(urgency, impact) == priority


def test_escalation_level_ranking(matrix) -> None:  # type: ignore[no-untyped-def]
    levels = [lv.name for lv in matrix.escalation_levels]
    assert levels[0] == "No Escalation"
    assert matrix.level_rank("Critical Management Escalation") > matrix.level_rank("Supervisor Review")


def test_safety_signal_forces_critical_escalation(matrix) -> None:  # type: ignore[no-untyped-def]
    declared = {"primary_subcategory": "SAF-OVH", "signals": ["overheating", "child_involved"], "complaint_facts": {}, "history": {}}
    label = label_declared(matrix, declared)
    assert label["urgency"] == "Critical"
    assert label["priority"] == "P0"
    assert label["escalation_required"] is True
    assert matrix.level_rank(label["escalation_level"]) >= matrix.level_rank("Specialist Team")


def test_emotional_language_does_not_raise_priority(matrix) -> None:  # type: ignore[no-untyped-def]
    declared = {"primary_subcategory": "TEC-APP", "signals": [], "complaint_facts": {"customer_type": "vip"}, "history": {}}
    label = label_declared(matrix, declared)
    assert label["urgency"] in ("Low", "Medium")
    assert label["priority"] in ("P2", "P3")


def test_reference_labels_reproduce_dataset(matrix) -> None:  # type: ignore[no-untyped-def]
    """The dataset's expected labels are exactly what the Rule Matrix derives from the declared facts."""
    path = ROOT / "data" / "sample_complaints" / "complaints.jsonl"
    if not path.exists():
        pytest.skip("dataset not generated")
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from dataset.records import (  # type: ignore[import-not-found]
        build_ledger_indexes,
        declared_input,
        label_projection,
    )
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()[:150]]
    by_ref, by_txn = build_ledger_indexes(json.loads((ROOT / "data" / "sample_complaints" / "orders.json").read_text(encoding="utf-8")))
    for rec in records:
        declared = declared_input(rec, by_ref, by_txn)
        got = label_projection(label_declared(matrix, declared))
        exp = {k: rec["expected"].get(k) for k in got}
        assert got == exp, rec["complaint_id"]


def test_decision_engine_trace_is_explainable(matrix) -> None:  # type: ignore[no-untyped-def]
    declared = {"primary_subcategory": "DEL-DLY", "signals": [], "complaint_facts": {}, "history": {}}
    decision = DecisionEngine(matrix).decide(build_declared_context(matrix, declared), "DEL-DLY", [])
    assert decision.department
    assert decision.selected_rule_id and decision.selected_rule_id.startswith("RES-DEL-DLY")
    assert decision.trace, "every decision carries a trace for the UI"
