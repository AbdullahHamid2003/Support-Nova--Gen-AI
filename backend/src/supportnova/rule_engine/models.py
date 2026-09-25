"""Typed, immutable representation of the Complaint Resolution Rule Matrix.

The matrix is loaded from the version-controlled YAML files (rules/, config/) or
from the database (runtime-editable copy); both produce the same *bundle* dict,
which is turned into a :class:`RuleMatrix` here. Python evaluates these rules
deterministically - the GenAI model never creates or approves them.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

URGENCY_LEVELS: tuple[str, ...] = ("Low", "Medium", "High", "Critical")
IMPACT_LEVELS: tuple[str, ...] = ("Low", "Medium", "High")
PRIORITY_ORDER: tuple[str, ...] = ("P3", "P2", "P1", "P0")  # ascending severity
SENTIMENTS: tuple[str, ...] = ("Positive", "Neutral", "Negative", "Strongly Negative")


@dataclass(frozen=True)
class Parameter:
    key: str
    value: Any
    unit: str
    source: str
    description: str = ""


@dataclass(frozen=True)
class Subcategory:
    code: str
    name: str
    category: str
    description: str = ""
    is_active: bool = True


@dataclass(frozen=True)
class Category:
    code: str
    name: str
    description: str = ""
    is_active: bool = True


@dataclass(frozen=True)
class Department:
    code: str
    name: str
    description: str = ""
    is_active: bool = True


@dataclass(frozen=True)
class Action:
    code: str
    name: str
    group: str
    description: str = ""


@dataclass(frozen=True)
class ProhibitedAction:
    code: str
    name: str
    severity: str
    policy_refs: tuple[str, ...]
    patterns: tuple[re.Pattern[str], ...]


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    line: str
    type: str
    price: float
    warranty_months: int | None
    hazard_class: str | None
    aliases: tuple[str, ...]


@dataclass(frozen=True)
class ResolutionRule:
    rule_id: str
    name: str
    subcategory: str
    precedence: int
    when: dict[str, Any]
    urgency: str
    impact: str
    required_actions: tuple[Any, ...]
    recommended_actions: tuple[str, ...]
    prohibited_actions: tuple[str, ...]
    eligibility: dict[str, Any]
    escalation: str
    follow_up: dict[str, Any]
    timelines: tuple[str, ...]
    policy_refs: tuple[str, ...]
    department: str | None = None
    supporting_departments: tuple[str, ...] = ()
    is_active: bool = True


@dataclass(frozen=True)
class EscalationLevel:
    rank: int
    name: str
    action_code: str | None


@dataclass(frozen=True)
class EscalationRule:
    rule_id: str
    name: str
    trigger: str
    when: dict[str, Any]
    level: str
    departments: tuple[str, ...]
    policy_refs: tuple[str, ...]
    reason: str
    runtime_only: bool = False
    is_active: bool = True


@dataclass(frozen=True)
class RoutingRule:
    rule_id: str
    subcategory: str
    primary_department: str
    supporting_departments: tuple[str, ...]
    policy_refs: tuple[str, ...]


@dataclass(frozen=True)
class ConditionalRouting:
    rule_id: str
    name: str
    when: dict[str, Any]
    add_supporting: tuple[str, ...]
    policy_refs: tuple[str, ...]


@dataclass(frozen=True)
class UrgencyFloor:
    rule_id: str
    name: str
    when: dict[str, Any]
    urgency: str | None
    impact: str | None
    policy_refs: tuple[str, ...]


@dataclass(frozen=True)
class MissingInfoRule:
    rule_id: str
    field: str
    label: str
    when: dict[str, Any]
    blocking: bool
    question: str
    keywords: tuple[str, ...]
    policy_refs: tuple[str, ...]


@dataclass(frozen=True)
class SlaRule:
    rule_id: str
    priority: str
    first_response_hours: float
    resolution_hours: float
    policy_refs: tuple[str, ...]


@dataclass(frozen=True)
class CategoryRule:
    rule_id: str
    subcategory: str
    terms: dict[str, float]
    negative: dict[str, float]
    signal_boosts: dict[str, float]
    product_boosts: dict[str, float]


@dataclass(frozen=True)
class SignalDefinition:
    name: str
    label: str
    terms: tuple[str, ...]
    patterns: tuple[re.Pattern[str], ...]


@dataclass
class RuleMatrix:
    """In-memory, validated rule matrix used by both Python pipelines' deterministic parts."""

    parameters: dict[str, Parameter]
    categories: dict[str, Category]
    subcategories: dict[str, Subcategory]
    departments: dict[str, Department]
    products: dict[str, Product]
    actions: dict[str, Action]
    prohibited_actions: dict[str, ProhibitedAction]
    resolution_rules: list[ResolutionRule]
    escalation_levels: list[EscalationLevel]
    escalation_rules: list[EscalationRule]
    escalation_notes_fields: tuple[str, ...]
    routing: dict[str, RoutingRule]
    conditional_routing: list[ConditionalRouting]
    routing_precedence: tuple[str, ...]
    priority_matrix: dict[str, dict[str, str]]
    urgency_floors: list[UrgencyFloor]
    missing_info_rules: list[MissingInfoRule]
    never_block_categories: tuple[str, ...]
    never_block_subcategories: tuple[str, ...]
    follow_up_types: tuple[str, ...]
    followup_rules: list[dict[str, Any]]
    sla_rules: dict[str, SlaRule]
    category_rules: dict[str, CategoryRule]
    category_settings: dict[str, float]
    signals: dict[str, SignalDefinition]
    negation_cues: tuple[str, ...]
    negation_window: int
    sentiment_config: dict[str, Any]
    response_rules: dict[str, Any]
    review_rules: list[dict[str, Any]]
    precedence: dict[str, Any]
    validation_policy: dict[str, Any]
    organization: dict[str, Any]
    raw_bundle: dict[str, Any] = field(repr=False, default_factory=dict)
    ruleset_hash: str = ""

    # ---- derived lookups ---------------------------------------------------
    def __post_init__(self) -> None:
        self._by_subcategory: dict[str, list[ResolutionRule]] = {}
        for rule in self.resolution_rules:
            if rule.is_active:
                self._by_subcategory.setdefault(rule.subcategory, []).append(rule)
        for rules in self._by_subcategory.values():
            rules.sort(key=lambda r: (-r.precedence, r.rule_id))
        self._level_by_name = {lvl.name: lvl for lvl in self.escalation_levels}
        if not self.ruleset_hash:
            canonical = json.dumps(self.raw_bundle, sort_keys=True, default=str)
            self.ruleset_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def rules_for(self, subcategory: str) -> list[ResolutionRule]:
        return self._by_subcategory.get(subcategory, [])

    def param(self, key: str) -> Any:
        if key not in self.parameters:
            raise KeyError(f"Unknown rule parameter '{key}'")
        return self.parameters[key].value

    def level(self, name: str) -> EscalationLevel:
        if name not in self._level_by_name:
            raise KeyError(f"Unknown escalation level '{name}'")
        return self._level_by_name[name]

    def level_rank(self, name: str | None) -> int:
        if not name:
            return 0
        lvl = self._level_by_name.get(name)
        return lvl.rank if lvl else 0

    def level_by_rank(self, rank: int) -> EscalationLevel:
        for lvl in self.escalation_levels:
            if lvl.rank == rank:
                return lvl
        return self.escalation_levels[0]

    def category_of(self, subcategory: str | None) -> str | None:
        if not subcategory:
            return None
        sub = self.subcategories.get(subcategory)
        return sub.category if sub else None

    def compute_priority(self, urgency: str, impact: str) -> str:
        return self.priority_matrix.get(urgency, {}).get(impact, "P2")

    def validation_check(self, code: str) -> dict[str, Any]:
        return dict(self.validation_policy.get("checks", {}).get(code, {}))
