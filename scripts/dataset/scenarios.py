"""Scenario bank loader.

A scenario file (``scenarios/*.yaml``) holds ``scenarios:`` (independent complaints) and/or
``chains:`` (related complaints from one customer about one issue: repeats, exact and
near duplicates, reopened complaints). Each entry is validated structurally here so that
authoring mistakes fail fast with a clear message.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .common import (
    CHANNELS,
    CUSTOMER_TYPES,
    DIFFICULTY_TYPES,
    EMOTIONS,
    LINK_KINDS,
    REQUESTED_RESOLUTIONS,
    SCENARIO_DIR,
    SEED_STATUSES,
    SENTIMENTS,
    STYLES,
)
from .ledger import PROFILES
from .textutil import clean_quotes

ORDER_MODES = ("normal", "invalid_reference", "unknown_reference", "malformed_reference", "other_customer")
INCLUDE_KEYS = ("order_reference", "photo", "product", "transaction_reference")
NEAR_DUP_EDITS = ("resend_prefix", "update_suffix", "typo", "drop_last_sentence", "swap_greeting",
                  "lowercase_start", "chase_suffix")
VARIANT_KEYS = frozenset({
    "style", "title", "body", "supporting", "count", "signals_add", "signals_remove", "lexical_traps",
    "requested_resolution",
    "include", "params", "emotions", "sentiment", "channels", "customer_types", "tags", "intended_rule",
    "difficulty_type", "products", "expect", "attachments", "product_service", "link", "of", "cite",
    "cite_previous", "gap_days", "seed_status", "edits", "pool", "scenario_id", "note",
})
SCENARIO_KEYS = frozenset({
    "scenario_id", "pool", "subcategory", "secondary", "intended_rule", "difficulty_type", "primary_issue",
    "order_profile", "order_mode", "products", "product2", "customer_types", "channels", "requested_resolution",
    "include", "signals", "lexical_traps", "params", "tags", "emotions_add", "prompt_injection", "expect", "texts",
    "steps", "malformed_ref", "rationale",
})
EXPECT_KEYS = frozenset({
    "priority_in", "escalation_level", "escalation_rules_include", "escalation_rules_exclude",
    "missing_information_include", "refund_eligibility", "replacement_eligibility", "compensation_eligibility",
})


class ScenarioError(ValueError):
    """Raised for malformed scenario-bank entries."""


@dataclass
class Variant:
    """One text variant of a scenario, or one step of a chain."""

    style: str
    title: str
    body: str
    supporting: str = ""
    count: int = 1
    signals_add: list[str] = field(default_factory=list)
    signals_remove: list[str] = field(default_factory=list)
    lexical_traps: list[str] = field(default_factory=list)
    requested_resolution: str | None = None
    include: dict[str, bool] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    emotions: list[str] | None = None
    sentiment: str | None = None
    channels: list[str] | None = None
    customer_types: list[str] | None = None
    tags: list[str] = field(default_factory=list)
    intended_rule: str | None = None
    difficulty_type: str | None = None
    products: list[str] | None = None
    expect: dict[str, Any] = field(default_factory=dict)
    attachments: list[dict[str, str]] | None = None
    product_service: str | None = None
    # chain-only fields
    link: str = "original"
    of: int | None = None
    cite: int | None = None
    cite_previous: bool = False
    gap_days: int = 0
    seed_status: str = "New"
    edits: list[str] = field(default_factory=list)
    pool: str | None = None
    scenario_id: str | None = None


@dataclass
class Scenario:
    """A scenario (independent complaint template) or a chain of related complaints."""

    scenario_id: str
    pool: str
    kind: str
    source_file: str
    subcategory: str
    intended_rule: str | None
    difficulty_type: str
    primary_issue: str
    secondary: list[dict[str, str]]
    order_profile: dict[str, Any] | None
    order_mode: str
    products: list[str]
    product2: list[str]
    customer_types: list[str] | None
    channels: list[str] | None
    requested_resolution: str
    include: dict[str, bool]
    signals: list[str]
    lexical_traps: list[str]
    params: dict[str, Any]
    tags: list[str]
    emotions_add: list[str]
    prompt_injection: bool
    expect: dict[str, Any]
    variants: list[Variant]
    malformed_ref: str | None = None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return clean_quotes(value).strip()
    return value


class ScenarioBank:
    """Load and validate every scenario file."""

    def __init__(self, matrix: Any, signal_names: set[str], directory: Path = SCENARIO_DIR) -> None:
        self.matrix = matrix
        self.signal_names = signal_names
        self.directory = directory
        self.rule_ids = {r.rule_id for r in matrix.resolution_rules}
        self.rule_sub = {r.rule_id: r.subcategory for r in matrix.resolution_rules}
        self.scenarios: list[Scenario] = []
        self._ids: set[str] = set()

    # ---- loading ----------------------------------------------------------------
    def load(self) -> list[Scenario]:
        files = sorted(self.directory.glob("*.yaml"))
        if not files:
            raise ScenarioError(f"No scenario files in {self.directory}")
        for path in files:
            with path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            for raw in data.get("scenarios", []) or []:
                self.scenarios.append(self._parse(raw, path.name, kind="single"))
            for raw in data.get("chains", []) or []:
                self.scenarios.append(self._parse(raw, path.name, kind="chain"))
        return self.scenarios

    # ---- parsing ----------------------------------------------------------------
    def _fail(self, sid: str, message: str) -> None:
        raise ScenarioError(f"[{sid}] {message}")

    def _check_signals(self, sid: str, names: list[str]) -> None:
        unknown = [s for s in names if s not in self.signal_names]
        if unknown:
            self._fail(sid, f"unknown signals {unknown}")

    def _check_rule(self, sid: str, rule_id: str | None, subcategory: str) -> None:
        if rule_id is None:
            return
        if rule_id not in self.rule_ids:
            self._fail(sid, f"unknown resolution rule {rule_id}")
        if self.rule_sub[rule_id] != subcategory:
            self._fail(sid, f"rule {rule_id} belongs to {self.rule_sub[rule_id]}, not {subcategory}")

    def _variant(self, sid: str, raw: dict[str, Any], subcategory: str, chain: bool) -> Variant:
        if not isinstance(raw, dict):
            self._fail(sid, "variant must be a mapping")
        unknown = sorted(set(raw) - VARIANT_KEYS)
        if unknown:
            self._fail(sid, f"unknown variant keys {unknown}")
        if set(raw.get("expect") or {}) - EXPECT_KEYS:
            self._fail(sid, f"unknown expect keys {sorted(set(raw['expect']) - EXPECT_KEYS)}")
        style = raw.get("style")
        if style not in STYLES:
            self._fail(sid, f"invalid style {style!r}")
        for key in ("title", "body"):
            if key not in raw and not (chain and raw.get("link") == "exact_duplicate") and not (
                    chain and raw.get("link") == "near_duplicate"):
                self._fail(sid, f"variant missing {key}")
        variant = Variant(
            style=str(style),
            title=_clean(raw.get("title", "")),
            body=_clean(raw.get("body", "")),
            supporting=_clean(raw.get("supporting", "")),
            count=int(raw.get("count", 1)),
            signals_add=list(_as_list(raw.get("signals_add"))),
            signals_remove=list(_as_list(raw.get("signals_remove"))),
            lexical_traps=list(_as_list(raw.get("lexical_traps"))),
            requested_resolution=raw.get("requested_resolution"),
            include=dict(raw.get("include") or {}),
            params=dict(raw.get("params") or {}),
            emotions=raw.get("emotions"),
            sentiment=raw.get("sentiment"),
            channels=raw.get("channels"),
            customer_types=raw.get("customer_types"),
            tags=list(_as_list(raw.get("tags"))),
            intended_rule=raw.get("intended_rule"),
            difficulty_type=raw.get("difficulty_type"),
            products=raw.get("products"),
            expect=dict(raw.get("expect") or {}),
            attachments=raw.get("attachments"),
            product_service=raw.get("product_service"),
            link=raw.get("link", "original"),
            of=raw.get("of"),
            cite=raw.get("cite"),
            cite_previous=bool(raw.get("cite_previous", False)),
            gap_days=int(raw.get("gap_days", 0)),
            seed_status=raw.get("seed_status", "New"),
            edits=list(_as_list(raw.get("edits"))),
            pool=raw.get("pool"),
            scenario_id=raw.get("scenario_id"),
        )
        self._check_signals(sid, variant.signals_add + variant.signals_remove + variant.lexical_traps)
        self._check_rule(sid, variant.intended_rule, subcategory)
        if variant.requested_resolution and variant.requested_resolution not in REQUESTED_RESOLUTIONS:
            self._fail(sid, f"invalid requested_resolution {variant.requested_resolution}")
        for key in variant.include:
            if key not in INCLUDE_KEYS:
                self._fail(sid, f"invalid include key {key}")
        if variant.emotions is not None and any(e not in EMOTIONS for e in variant.emotions):
            self._fail(sid, f"invalid emotions {variant.emotions}")
        if variant.sentiment is not None and variant.sentiment not in SENTIMENTS:
            self._fail(sid, f"invalid sentiment {variant.sentiment}")
        if variant.channels and any(c not in CHANNELS for c in variant.channels):
            self._fail(sid, f"invalid channels {variant.channels}")
        if variant.customer_types and any(c not in CUSTOMER_TYPES for c in variant.customer_types):
            self._fail(sid, f"invalid customer_types {variant.customer_types}")
        if variant.difficulty_type and variant.difficulty_type not in DIFFICULTY_TYPES:
            self._fail(sid, f"invalid difficulty_type {variant.difficulty_type}")
        if variant.products:
            self._check_products(sid, variant.products)
        if chain:
            if variant.link not in LINK_KINDS:
                self._fail(sid, f"invalid link {variant.link}")
            if variant.seed_status not in SEED_STATUSES:
                self._fail(sid, f"invalid seed_status {variant.seed_status}")
            if any(e not in NEAR_DUP_EDITS for e in variant.edits):
                self._fail(sid, f"invalid near-duplicate edits {variant.edits}")
            if variant.pool and variant.pool not in ("dev", "holdout"):
                self._fail(sid, f"invalid step pool {variant.pool}")
        return variant

    def _check_products(self, sid: str, skus: list[str]) -> None:
        unknown = [s for s in skus if s not in self.matrix.products]
        if unknown:
            self._fail(sid, f"unknown SKUs {unknown}")

    def _parse(self, raw: dict[str, Any], source: str, kind: str) -> Scenario:
        sid = str(raw.get("scenario_id") or "")
        if not sid:
            raise ScenarioError(f"{source}: scenario without scenario_id")
        if sid in self._ids:
            self._fail(sid, "duplicate scenario_id")
        self._ids.add(sid)
        unknown = sorted(set(raw) - SCENARIO_KEYS)
        if unknown:
            self._fail(sid, f"unknown scenario keys {unknown}")
        if set(raw.get("expect") or {}) - EXPECT_KEYS:
            self._fail(sid, f"unknown expect keys {sorted(set(raw['expect']) - EXPECT_KEYS)}")
        pool = raw.get("pool", "dev")
        if pool not in ("dev", "holdout"):
            self._fail(sid, f"invalid pool {pool}")
        sub = raw.get("subcategory")
        if sub not in self.matrix.subcategories:
            self._fail(sid, f"unknown subcategory {sub}")
        secondary = []
        for item in _as_list(raw.get("secondary")):
            if not isinstance(item, dict) or item.get("subcategory") not in self.matrix.subcategories:
                self._fail(sid, f"invalid secondary issue {item}")
            if not item.get("label"):
                self._fail(sid, f"secondary issue without label {item}")
            secondary.append({"subcategory": item["subcategory"], "label": _clean(item["label"])})
        profile = raw.get("order_profile")
        if profile is not None:
            if not isinstance(profile, dict) or profile.get("name") not in PROFILES:
                self._fail(sid, f"unknown order profile {profile}")
            profile = {"name": profile["name"], "params": dict(profile.get("params") or {})}
        mode = raw.get("order_mode", "normal")
        if mode not in ORDER_MODES:
            self._fail(sid, f"invalid order_mode {mode}")
        products = list(_as_list(raw.get("products")))
        product2 = list(_as_list(raw.get("product2")))
        self._check_products(sid, products + product2)
        signals = list(_as_list(raw.get("signals")))
        traps = list(_as_list(raw.get("lexical_traps")))
        self._check_signals(sid, signals + traps)
        include = {"order_reference": profile is not None or mode != "normal", "photo": False, "product": True,
                   "transaction_reference": False}
        for key, value in (raw.get("include") or {}).items():
            if key not in INCLUDE_KEYS:
                self._fail(sid, f"invalid include key {key}")
            include[key] = bool(value)
        requested = raw.get("requested_resolution", "none")
        if requested not in REQUESTED_RESOLUTIONS:
            self._fail(sid, f"invalid requested_resolution {requested}")
        difficulty = raw.get("difficulty_type", "simple")
        if difficulty not in DIFFICULTY_TYPES:
            self._fail(sid, f"invalid difficulty_type {difficulty}")
        ctypes = raw.get("customer_types")
        if ctypes and any(c not in CUSTOMER_TYPES for c in ctypes):
            self._fail(sid, f"invalid customer_types {ctypes}")
        channels = raw.get("channels")
        if channels and any(c not in CHANNELS for c in channels):
            self._fail(sid, f"invalid channels {channels}")
        intended = raw.get("intended_rule")
        sub = str(sub)
        self._check_rule(sid, intended, sub)
        key = "steps" if kind == "chain" else "texts"
        variants_raw = _as_list(raw.get(key))
        if not variants_raw:
            self._fail(sid, f"no {key}")
        variants = [self._variant(sid, v, sub, chain=(kind == "chain")) for v in variants_raw]
        if kind == "single" and intended is None and any(v.intended_rule is None for v in variants):
            self._fail(sid, "intended_rule missing")
        if kind == "chain":
            if any(v.intended_rule is None for v in variants) and intended is None:
                self._fail(sid, "every chain step needs an intended_rule")
            if variants[0].link != "original":
                self._fail(sid, "the first chain step must be the original")
        if not raw.get("primary_issue"):
            self._fail(sid, "primary_issue missing")
        return Scenario(
            scenario_id=sid, pool=pool, kind=kind, source_file=source, subcategory=sub, intended_rule=intended,
            difficulty_type=difficulty, primary_issue=_clean(raw["primary_issue"]), secondary=secondary,
            order_profile=profile, order_mode=mode, products=products, product2=product2,
            customer_types=ctypes, channels=channels, requested_resolution=requested, include=include,
            signals=signals, lexical_traps=traps, params=dict(raw.get("params") or {}),
            tags=list(_as_list(raw.get("tags"))), emotions_add=list(_as_list(raw.get("emotions_add"))),
            prompt_injection=bool(raw.get("prompt_injection", False)), expect=dict(raw.get("expect") or {}),
            variants=variants, malformed_ref=raw.get("malformed_ref"),
        )
