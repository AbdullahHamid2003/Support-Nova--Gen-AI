"""Dataset summary and SRS-minimum / required-mix checks (shared by generator and validator)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from typing import Any

from .common import CHANNELS, SENTIMENTS, TONES


@dataclass
class Check:
    """One count requirement."""

    name: str
    requirement: str
    actual: Any
    passed: bool
    source: str = "mix"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _count(records: Iterable[dict[str, Any]], key: Callable[[dict[str, Any]], Any]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for record in records:
        value = key(record)
        if isinstance(value, (list, tuple, set)):
            for item in value:
                counter[str(item)] += 1
        elif value is not None:
            counter[str(value)] += 1
    return dict(sorted(counter.items()))


def _tag(records: list[dict[str, Any]], tag: str) -> int:
    return sum(1 for r in records if tag in r["tags"])


def _link_count(records: list[dict[str, Any]]) -> dict[str, int]:
    exp = [r["expected"] for r in records]
    return {
        "exact_duplicate": sum(1 for e in exp if e["is_duplicate_of"]),
        "near_duplicate": sum(1 for e in exp if e["is_near_duplicate_of"]),
        "repeat": sum(1 for e in exp if e["is_repeat_of"]),
    }


def _esc(records: list[dict[str, Any]], rule_id: str) -> int:
    return sum(1 for r in records if rule_id in r["expected"]["escalation_rules"])


def _signal(records: list[dict[str, Any]], name: str) -> int:
    return sum(1 for r in records if name in r["declared"]["signals"])


def facts(records: list[dict[str, Any]]) -> dict[str, int]:
    """Named counts used by the checks and printed in the summary."""
    links = _link_count(records)
    return {
        "complaints": len(records),
        "categories": len({r["expected"]["category"] for r in records}),
        "subcategories": len({r["expected"]["subcategory"] for r in records}),
        "min_per_subcategory": min(Counter(r["expected"]["subcategory"] for r in records).values(), default=0),
        "departments_primary": len({r["expected"]["department"] for r in records}),
        "departments_any": len({d for r in records for d in [r["expected"]["department"],
                                                             *r["expected"]["supporting_departments"]]}),
        "multi_issue": sum(1 for r in records if r["expected"]["secondary_issues"]),
        "three_plus_issues": sum(1 for r in records if len(r["expected"]["secondary_issues"]) >= 2),
        "ambiguous": _tag(records, "ambiguous"),
        "ambiguous_or_multi_issue": sum(1 for r in records if "ambiguous" in r["tags"] or r["expected"]["secondary_issues"]),
        "contradictory_policy": _tag(records, "contradictory_policy"),
        "prompt_injection": sum(1 for r in records if r["expected"]["prompt_injection"]),
        "repeated_or_near_duplicate": sum(links.values()),
        "exact_duplicate": links["exact_duplicate"],
        "near_duplicate": links["near_duplicate"],
        "repeat": links["repeat"],
        "with_previous_complaint_reference": sum(1 for r in records if r["previous_complaint_reference"]),
        "esc017_repeat_2": _esc(records, "ESC-017"),
        "esc018_repeat_3": _esc(records, "ESC-018"),
        "esc019_reopened": _esc(records, "ESC-019"),
        "incomplete": _tag(records, "incomplete"),
        "invalid_order_reference": _tag(records, "invalid_order_reference"),
        "malformed_order_reference": _tag(records, "malformed_order_reference"),
        "emotional_low_priority": _tag(records, "emotional_low_priority"),
        "calm_critical": _tag(records, "calm_critical"),
        "vip_minor": _tag(records, "vip_minor"),
        "low_value_privacy": _tag(records, "low_value_privacy"),
        "legal_threat": _signal(records, "legal_threat"),
        "security": _tag(records, "security"),
        "privacy": _tag(records, "privacy"),
        "safety": _tag(records, "safety"),
        "unsupported_refund": _tag(records, "unsupported_refund"),
        "unsupported_compensation": _tag(records, "unsupported_compensation"),
        "high_value": _tag(records, "high_value"),
        "simple": sum(1 for r in records if r["difficulty_type"] == "simple"),
        "policy_exception_request": _signal(records, "policy_exception_request"),
        "channels_used": len({r["channel"] for r in records}),
        "tones_used": len({r["requested_tone"] for r in records}),
        "sentiments_used": len({r["expected"]["sentiment"] for r in records}),
        "priorities_used": len({r["expected"]["priority"] for r in records}),
    }


DEV_MINIMUMS: tuple[tuple[str, int, str], ...] = (
    ("complaints", 540, "SRS: 500 unique complaints (target 540)"),
    ("categories", 11, "SRS: >= 10 categories (all 11 used)"),
    ("subcategories", 35, "SRS: >= 20 subcategories (all 35 used)"),
    ("min_per_subcategory", 6, "each subcategory >= 6 complaints"),
    ("departments_primary", 8, "SRS: >= 8 departments referenced"),
    ("ambiguous_or_multi_issue", 25, "SRS: >= 25 ambiguous or multi-issue"),
    ("multi_issue", 30, "multi-issue >= 30"),
    ("three_plus_issues", 6, "three or more issues >= 6"),
    ("ambiguous", 15, "ambiguous >= 15"),
    ("contradictory_policy", 22, "SRS: >= 20 contradictory/difficult policy (target 22)"),
    ("prompt_injection", 22, "SRS: >= 20 prompt-injection/adversarial (target 22)"),
    ("repeated_or_near_duplicate", 30, "SRS: >= 25 repeated/near-duplicate (target 30)"),
    ("exact_duplicate", 8, "exact resubmissions >= 8"),
    ("near_duplicate", 10, "near-duplicates >= 10"),
    ("repeat", 12, "repeat complaints (different wording) >= 12"),
    ("with_previous_complaint_reference", 8, "complaints citing a previous complaint >= 8"),
    ("esc017_repeat_2", 2, "ESC-017 (2 prior unresolved) fires >= 2"),
    ("esc018_repeat_3", 1, "ESC-018 (3+ prior unresolved) fires >= 1"),
    ("esc019_reopened", 2, "ESC-019 (reopened resolved complaint) fires >= 2"),
    ("incomplete", 25, "incomplete >= 25"),
    ("invalid_order_reference", 1, "invalid/unknown order references >= 1"),
    ("malformed_order_reference", 1, "malformed order references >= 1"),
    ("emotional_low_priority", 15, "angry language about minor issues (P3) >= 15"),
    ("calm_critical", 15, "calmly written critical complaints (P0/P1) >= 15"),
    ("vip_minor", 6, "VIP customers with minor issues (P3) >= 6"),
    ("low_value_privacy", 4, "low-value privacy breaches >= 4"),
    ("legal_threat", 10, "legal threats >= 10"),
    ("security", 15, "security complaints >= 15"),
    ("privacy", 25, "privacy complaints >= 25"),
    ("safety", 25, "safety complaints >= 25"),
    ("unsupported_refund", 12, "unsupported refund requests >= 12"),
    ("unsupported_compensation", 12, "unsupported compensation requests >= 12"),
    ("high_value", 8, "high-value orders >= 8"),
    ("simple", 100, "plenty of simple complaints (>= 100)"),
    ("channels_used", len(CHANNELS), "all channels used"),
    ("tones_used", len(TONES), "all requested tones used"),
    ("sentiments_used", len(SENTIMENTS), "all sentiment values used"),
    ("priorities_used", 4, "all priorities P0-P3 used"),
)

HOLDOUT_MINIMUMS: tuple[tuple[str, int, str], ...] = (
    ("complaints", 120, "holdout >= 120 unseen complaints (SRS comparison needs >= 100)"),
    ("categories", 11, "holdout covers all 11 categories"),
    ("subcategories", 30, "holdout covers >= 30 subcategories"),
    ("multi_issue", 6, "holdout multi-issue >= 6"),
    ("three_plus_issues", 2, "holdout three or more issues >= 2"),
    ("ambiguous", 3, "holdout ambiguous >= 3"),
    ("contradictory_policy", 5, "holdout contradictory policy >= 5"),
    ("prompt_injection", 5, "holdout prompt injection >= 5"),
    ("repeated_or_near_duplicate", 5, "holdout repeated/near-duplicate >= 5"),
    ("incomplete", 5, "holdout incomplete >= 5"),
    ("emotional_low_priority", 3, "holdout angry low-priority >= 3"),
    ("calm_critical", 3, "holdout calm critical >= 3"),
    ("vip_minor", 1, "holdout VIP minor >= 1"),
    ("legal_threat", 2, "holdout legal threats >= 2"),
    ("security", 3, "holdout security >= 3"),
    ("privacy", 5, "holdout privacy >= 5"),
    ("safety", 5, "holdout safety >= 5"),
    ("unsupported_refund", 2, "holdout unsupported refund >= 2"),
    ("unsupported_compensation", 2, "holdout unsupported compensation >= 2"),
    ("high_value", 1, "holdout high value >= 1"),
    ("channels_used", 5, "holdout uses >= 5 channels"),
)


def mix_checks(dev: list[dict[str, Any]], holdout: list[dict[str, Any]], rule_ids: set[str]) -> list[Check]:
    """All count requirements for both sets plus resolution-rule coverage."""
    checks: list[Check] = []
    dev_facts, hold_facts = facts(dev), facts(holdout)
    for key, minimum, label in DEV_MINIMUMS:
        checks.append(Check(f"dev.{key}", f">= {minimum} ({label})", dev_facts[key], dev_facts[key] >= minimum, "dev"))
    for key, minimum, label in HOLDOUT_MINIMUMS:
        checks.append(Check(f"holdout.{key}", f">= {minimum} ({label})", hold_facts[key], hold_facts[key] >= minimum,
                            "holdout"))
    covered = {r["expected"]["resolution_rule"] for r in dev + holdout}
    missing = sorted(rule_ids - covered)
    checks.append(Check("all.resolution_rules_covered", f"== {len(rule_ids)} (every resolution rule at least once)",
                        len(rule_ids & covered), not missing, "all"))
    return checks


def summarize(dev: list[dict[str, Any]], holdout: list[dict[str, Any]], rule_ids: set[str],
              extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """The content of ``dataset_summary.json``."""
    def block(records: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "counts": facts(records),
            "by_category": _count(records, lambda r: r["expected"]["category"]),
            "by_subcategory": _count(records, lambda r: r["expected"]["subcategory"]),
            "by_difficulty_type": _count(records, lambda r: r["difficulty_type"]),
            "by_channel": _count(records, lambda r: r["channel"]),
            "by_customer_type": _count(records, lambda r: r["customer_type"]),
            "by_sentiment": _count(records, lambda r: r["expected"]["sentiment"]),
            "by_priority": _count(records, lambda r: r["expected"]["priority"]),
            "by_escalation_level": _count(records, lambda r: r["expected"]["escalation_level"]),
            "by_department": _count(records, lambda r: r["expected"]["department"]),
            "by_requested_tone": _count(records, lambda r: r["requested_tone"]),
            "by_requested_resolution": _count(records, lambda r: r["requested_resolution"]),
            "by_resolution_rule": _count(records, lambda r: r["expected"]["resolution_rule"]),
            "by_escalation_rule": _count(records, lambda r: r["expected"]["escalation_rules"]),
            "by_tag": _count(records, lambda r: r["tags"]),
        }
    checks = mix_checks(dev, holdout, rule_ids)
    covered = {r["expected"]["resolution_rule"] for r in dev + holdout}
    summary: dict[str, Any] = {
        "splits": {"dev": len(dev), "holdout": len(holdout)},
        "dev": block(dev),
        "holdout": block(holdout),
        "resolution_rule_coverage": {
            "total_rules": len(rule_ids), "covered": len(rule_ids & covered),
            "dev_only": sorted({r["expected"]["resolution_rule"] for r in dev} - {r["expected"]["resolution_rule"] for r in holdout}),
            "uncovered": sorted(rule_ids - covered),
        },
        "srs_minimum_checks": [c.as_dict() for c in checks],
        "all_checks_passed": all(c.passed for c in checks),
    }
    if extra:
        summary.update(extra)
    return summary
