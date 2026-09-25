"""Safe, declarative condition language for the Rule Matrix (no eval, no code in data).

Three-valued logic: every condition evaluates to ``True``, ``False`` or ``None``
(unknown - a required fact is missing, e.g. no order reference was supplied).
Unknown results let the engine say "requires verification" instead of guessing.

Grammar (JSON/YAML mapping)::

    {}                                         -> True
    {all: [c1, c2]} / {any: [..]} / {not: c}   -> combinators
    {signal: name} / {any_signal: [..]} / {all_signals: [..]}
    {subcategory_in: [..]} / {category_in: [..]}
    {text_matches: "<regex>"}
    {escalation_level_at_least: "<level name>"}
    {secondary_issues: true}
    {fact: "order.business_days_late", op: gt, value: 3 | "$param:key" | [..]}
      op in: eq ne in not_in gt gte lt lte exists not_exists contains between
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from .models import RuleMatrix

Tri = bool | None
_MISSING = object()


class ConditionError(ValueError):
    """Raised for malformed conditions (surfaced by rule validation, never at random)."""


@dataclass
class EvalContext:
    """Everything a condition may look at. Built by the fact builder (text-derived facts)
    or by the dataset reference labeler (declared scenario facts)."""

    matrix: RuleMatrix
    facts: dict[str, Any] = field(default_factory=dict)
    signals: set[str] = field(default_factory=set)
    text: str | None = ""
    subcategory: str | None = None
    secondary_subcategories: list[str] = field(default_factory=list)
    escalation_rank: int = 0
    unknown_facts: set[str] = field(default_factory=set)

    @property
    def category(self) -> str | None:
        return self.matrix.category_of(self.subcategory)

    def has_signal(self, name: str) -> bool:
        return name in self.signals

    def get_fact(self, path: str) -> Any:
        node: Any = self.facts
        for part in path.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return _MISSING
        return node

    def resolve(self, value: Any) -> Any:
        if isinstance(value, str) and value.startswith("$param:"):
            return self.matrix.param(value.split(":", 1)[1])
        if isinstance(value, list):
            return [self.resolve(v) for v in value]
        return value


@lru_cache(maxsize=512)
def _regex(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE | re.DOTALL)


def _tri_all(values: Iterable[Tri]) -> Tri:
    seen_unknown = False
    for v in values:
        if v is False:
            return False
        if v is None:
            seen_unknown = True
    return None if seen_unknown else True


def _tri_any(values: Iterable[Tri]) -> Tri:
    seen_unknown = False
    for v in values:
        if v is True:
            return True
        if v is None:
            seen_unknown = True
    return None if seen_unknown else False


def _compare(op: str, actual: Any, expected: Any) -> bool:
    if op == "eq":
        return bool(actual == expected)
    if op == "ne":
        return bool(actual != expected)
    if op == "in":
        return actual in (expected or [])
    if op == "not_in":
        return actual not in (expected or [])
    if op == "contains":
        return expected in actual if isinstance(actual, (list, tuple, set, str)) else False
    if op == "between":
        lo, hi = expected
        return bool(lo <= actual <= hi)
    try:
        if op == "gt":
            return bool(actual > expected)
        if op == "gte":
            return bool(actual >= expected)
        if op == "lt":
            return bool(actual < expected)
        if op == "lte":
            return bool(actual <= expected)
    except TypeError:
        return False
    raise ConditionError(f"Unknown operator '{op}'")


def evaluate(cond: dict[str, Any] | None, ctx: EvalContext) -> Tri:
    """Evaluate a condition against a context using three-valued logic."""
    if not cond:
        return True
    if not isinstance(cond, dict):
        raise ConditionError(f"Condition must be a mapping, got {type(cond).__name__}")

    if "all" in cond:
        return _tri_all(evaluate(c, ctx) for c in cond["all"])
    if "any" in cond:
        return _tri_any(evaluate(c, ctx) for c in cond["any"])
    if "not" in cond:
        inner = evaluate(cond["not"], ctx)
        return None if inner is None else not inner
    if "signal" in cond:
        return ctx.has_signal(str(cond["signal"]))
    if "any_signal" in cond:
        return any(ctx.has_signal(s) for s in cond["any_signal"])
    if "all_signals" in cond:
        return all(ctx.has_signal(s) for s in cond["all_signals"])
    if "subcategory_in" in cond:
        return None if ctx.subcategory is None else ctx.subcategory in cond["subcategory_in"]
    if "category_in" in cond:
        return None if ctx.category is None else ctx.category in cond["category_in"]
    if "text_matches" in cond:
        return None if ctx.text is None else bool(_regex(str(cond["text_matches"])).search(ctx.text))
    if "escalation_level_at_least" in cond:
        return ctx.escalation_rank >= ctx.matrix.level_rank(str(cond["escalation_level_at_least"]))
    if "secondary_issues" in cond:
        return bool(ctx.secondary_subcategories) == bool(cond["secondary_issues"])
    if "fact" in cond:
        path = str(cond["fact"])
        op = str(cond.get("op", "eq"))
        actual = ctx.get_fact(path)
        if op == "exists":
            return actual is not _MISSING and actual is not None
        if op == "not_exists":
            return actual is _MISSING or actual is None
        if actual is _MISSING or actual is None:
            ctx.unknown_facts.add(path)
            return None
        return _compare(op, actual, ctx.resolve(cond.get("value")))
    raise ConditionError(f"Unrecognised condition keys: {sorted(cond)}")


def referenced_facts(cond: Any) -> set[str]:
    """All fact paths used by a condition (for rule integrity checks and UI explanations)."""
    found: set[str] = set()
    if isinstance(cond, dict):
        if "fact" in cond:
            found.add(str(cond["fact"]))
        for key in ("all", "any"):
            for sub in cond.get(key, []) or []:
                found |= referenced_facts(sub)
        if "not" in cond:
            found |= referenced_facts(cond["not"])
    return found


def referenced_signals(cond: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(cond, dict):
        if "signal" in cond:
            found.add(str(cond["signal"]))
        for key in ("any_signal", "all_signals"):
            found |= {str(s) for s in cond.get(key, []) or []}
        for key in ("all", "any"):
            for sub in cond.get(key, []) or []:
                found |= referenced_signals(sub)
        if "not" in cond:
            found |= referenced_signals(cond["not"])
    return found


def describe(cond: Any) -> str:
    """Human-readable rendering of a condition, shown in the UI and reports."""
    if not cond:
        return "always"
    if "all" in cond:
        return " AND ".join(f"({describe(c)})" for c in cond["all"])
    if "any" in cond:
        return " OR ".join(f"({describe(c)})" for c in cond["any"])
    if "not" in cond:
        return f"NOT ({describe(cond['not'])})"
    if "signal" in cond:
        return f"signal:{cond['signal']}"
    if "any_signal" in cond:
        return "any signal of " + ", ".join(cond["any_signal"])
    if "all_signals" in cond:
        return "all signals " + ", ".join(cond["all_signals"])
    if "subcategory_in" in cond:
        return "subcategory in " + ", ".join(cond["subcategory_in"])
    if "category_in" in cond:
        return "category in " + ", ".join(cond["category_in"])
    if "text_matches" in cond:
        return f"text matches /{cond['text_matches']}/"
    if "escalation_level_at_least" in cond:
        return f"escalation >= {cond['escalation_level_at_least']}"
    if "secondary_issues" in cond:
        return "has secondary issues" if cond["secondary_issues"] else "no secondary issues"
    if "fact" in cond:
        op = cond.get("op", "eq")
        symbols = {"eq": "=", "ne": "!=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
        return f"{cond['fact']} {symbols.get(op, op)} {cond.get('value', '')}".strip()
    return str(cond)
