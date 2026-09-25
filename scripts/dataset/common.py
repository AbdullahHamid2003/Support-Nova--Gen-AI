"""Shared paths, constants and deterministic random helpers for the dataset generator."""

from __future__ import annotations

import hashlib
import random
import sys
from collections.abc import Mapping
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_SRC = REPO_ROOT / "backend" / "src"
SCENARIO_DIR = Path(__file__).resolve().parent / "scenarios"
SCHEMA_PATH = REPO_ROOT / "schemas" / "dataset" / "complaint_record.schema.json"
SIGNALS_PATH = REPO_ROOT / "rules" / "complaint_rules" / "signals.yaml"
KB_SPEC_PATH = REPO_ROOT / "knowledge_base" / "kb_spec.yaml"

DEFAULT_SEED = 20260923

DEV_START = date(2026, 5, 4)
DEV_END = date(2026, 9, 21)
HOLDOUT_START = date(2026, 9, 1)
HOLDOUT_END = date(2026, 9, 21)

STYLES: tuple[str, ...] = ("calm", "polite", "frustrated", "angry")
CHANNELS: tuple[str, ...] = ("web_form", "email", "chat", "phone", "mobile_app", "social_media", "uploaded")
CHANNEL_WEIGHTS: dict[str, float] = {
    "web_form": 30, "email": 25, "chat": 14, "phone": 10, "mobile_app": 10, "social_media": 6, "uploaded": 5,
}
CUSTOMER_TYPES: tuple[str, ...] = ("individual", "care_plus", "business", "vip")
CUSTOMER_TYPE_WEIGHTS: dict[str, float] = {"individual": 60, "care_plus": 20, "business": 10, "vip": 10}
TONES: tuple[str, ...] = ("professional", "empathetic", "concise", "formal")
CONTACT_METHODS: tuple[str, ...] = ("email", "phone", "sms", "chat")
REQUESTED_RESOLUTIONS: tuple[str, ...] = (
    "refund", "replacement", "repair", "compensation", "explanation", "cancellation", "other", "none",
)
SENTIMENTS: tuple[str, ...] = ("Positive", "Neutral", "Negative", "Strongly Negative")
EMOTIONS: tuple[str, ...] = ("Frustration", "Anger", "Disappointment", "Confusion", "Urgency")
ENTITY_TYPES: tuple[str, ...] = (
    "order_id", "transaction_id", "product", "service", "date", "amount", "location", "complaint_reference",
)
SEED_STATUSES: tuple[str, ...] = ("New", "In Progress", "Escalated", "Awaiting Customer", "Resolved", "Closed")
UNRESOLVED_STATUSES = frozenset({"New", "In Progress", "Escalated", "Awaiting Customer"})
RESOLVED_STATUSES = frozenset({"Resolved", "Closed"})
LINK_KINDS: tuple[str, ...] = ("original", "exact_duplicate", "near_duplicate", "repeat")

DIFFICULTY_TYPES: tuple[str, ...] = (
    "simple", "multi_issue", "ambiguous", "contradictory_policy", "prompt_injection", "incomplete",
    "repeat", "near_duplicate", "exact_duplicate", "emotional_low_priority", "calm_critical",
    "policy_exception", "unsupported_refund", "unsupported_compensation", "high_value", "vip_minor",
    "sensitive",
)

ORDER_REF_PATTERN = r"^LMR-\d{6}$"
TXN_REF_PATTERN = r"^TXN-\d{8}$"
COMPLAINT_REF_PATTERN = r"^(CMP|EVL)-\d{5}$"
INVALID_ORDER_REF = "LMR-000000"


def ensure_backend_path() -> None:
    """Make ``supportnova`` (backend/src) importable without installing the package."""
    src = str(BACKEND_SRC)
    if src not in sys.path:
        sys.path.insert(0, src)


def stable_int(*parts: object) -> int:
    """Deterministic 64-bit integer derived from ``parts`` (unlike ``hash()``, not salted per process)."""
    digest = hashlib.sha256("\x1f".join(str(p) for p in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def sub_rng(*parts: object) -> random.Random:
    """A ``random.Random`` seeded from ``parts`` - stable across runs and independent of call order."""
    return random.Random(stable_int(*parts))


def pick_range(rng: random.Random, spec: object) -> int:
    """Pick an integer from ``[lo, hi]`` (inclusive), a list of choices, or return a scalar as-is."""
    if isinstance(spec, (list, tuple)):
        if len(spec) == 2 and all(isinstance(v, int) for v in spec) and spec[0] <= spec[1]:
            return rng.randint(int(spec[0]), int(spec[1]))
        return int(rng.choice(list(spec)))
    return int(spec)  # type: ignore[call-overload]


def pick_amount(rng: random.Random, spec: object) -> float:
    """Pick a money amount: a 2-int list is an inclusive range, any other list is a set of choices."""
    if isinstance(spec, (list, tuple)):
        if len(spec) == 2 and all(isinstance(v, int) for v in spec) and spec[0] <= spec[1]:
            return float(rng.randint(int(spec[0]), int(spec[1])))
        return float(rng.choice(list(spec)))
    return float(spec)  # type: ignore[arg-type]


def weighted_choice(rng: random.Random, weights: Mapping[str, float],
                    allowed: list[str] | tuple[str, ...] | None = None) -> str:
    """Weighted choice restricted to ``allowed`` keys (all keys when ``allowed`` is empty)."""
    keys = [k for k in weights if not allowed or k in allowed]
    if not keys:
        keys = list(allowed or weights)
        return rng.choice(keys)
    total = sum(weights[k] for k in keys)
    point = rng.uniform(0, total)
    upto = 0.0
    for key in keys:
        upto += weights[key]
        if point <= upto:
            return key
    return keys[-1]
