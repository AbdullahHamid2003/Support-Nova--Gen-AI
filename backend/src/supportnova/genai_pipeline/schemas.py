"""Structured-output contracts for Pipeline 1 (SRS Steps 46-47, 1.6 xliii-xliv).

Two stages, two schemas:
* ``complaint_analysis`` v1   - classification, routing, urgency, policy citations, resolution,
                               eligibility, escalation, missing info, guidance, claims.
* ``customer_communication`` v1 - the customer response and follow-up message, generated only
                               from the Python-validated decision.

The committed JSON Schema files in ``schemas/ai/`` are the runtime contract (validated with
jsonschema) and are generated from these Pydantic models (``scripts/export_schemas.py``).
Taxonomy, department, policy and action codes are deliberately plain strings: they are
configuration, validated against the live Rule Matrix/knowledge base, so new categories need
no schema change.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from supportnova.core.paths import SCHEMAS_DIR

Sentiment = Literal["Positive", "Neutral", "Negative", "Strongly Negative"]
Urgency = Literal["Low", "Medium", "High", "Critical"]
Impact = Literal["Low", "Medium", "High"]
Priority = Literal["P0", "P1", "P2", "P3"]
EscalationLevel = Literal["No Escalation", "Supervisor Review", "Department Manager", "Specialist Team",
                          "Compliance Review", "Critical Management Escalation"]
EligibilityStatus = Literal["eligible", "not_eligible", "requires_verification", "not_applicable"]
Applicability = Literal["Applicable", "Conditionally Applicable", "Not Applicable", "Outdated"]
FollowUpType = Literal["Request for additional information", "Resolution confirmation", "Refund-status update",
                       "Replacement-status update", "Escalation acknowledgement", "Closure confirmation"]
EntityType = Literal["product", "service", "order_id", "transaction_id", "date", "amount", "location",
                     "department", "complaint_reference", "person", "other"]
Emotion = Literal["Frustration", "Anger", "Disappointment", "Confusion", "Urgency", "Anxiety", "Satisfaction"]
CompensationType = Literal["store_credit", "shipping_fee_refund", "subscription_credit", "expedited_shipping", "none"]
Tone = Literal["professional", "empathetic", "concise", "formal"]
ClaimSource = Literal["complaint", "policy", "rule", "metadata", "validated_decision"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Issue(_Strict):
    label: str
    category: str
    subcategory: str
    evidence_quote: str | None


class Entity(_Strict):
    type: EntityType
    value: str


class PolicyCitation(_Strict):
    policy_id: str
    section: str
    evidence_id: str | None
    applicability: Applicability
    reason: str


class ResolutionStep(_Strict):
    action_code: str
    description: str
    policy_ref: str | None


class Eligibility(_Strict):
    status: EligibilityStatus
    reason: str
    policy_ref: str | None


class CompensationEligibility(_Strict):
    status: EligibilityStatus
    type: CompensationType | None
    amount_usd: float | None
    reason: str
    policy_ref: str | None


class EscalationNotes(_Strict):
    summary: str
    key_facts: list[str]
    reason: str
    actions_taken: list[str]
    relevant_policy: list[str]
    required_next_action: str


class Claim(_Strict):
    statement: str
    source_type: ClaimSource
    source_ref: str | None


class MissingInfo(_Strict):
    field: str
    reason: str


class ComplaintAnalysis(BaseModel):
    """Pipeline 1, stage 1. Field names follow the SRS sample output where one exists
    (issue_category, subcategory, sentiment, urgency, priority, department, policy_id,
    policy_section, resolution_steps, escalation_required, response_type, follow_up_required)."""

    model_config = ConfigDict(extra="allow")  # fields added to the schema file are kept (live schema changes)

    schema_version: Literal["1.0"]
    complaint_id: str
    summary: str
    key_facts: list[str]
    primary_issue: Issue
    secondary_issues: list[Issue]
    issue_category: str
    subcategory: str
    sentiment: Sentiment
    emotion_indicators: list[Emotion]
    urgency: Urgency
    urgency_rationale: str
    impact: Impact
    priority: Priority
    entities: list[Entity]
    department: str
    supporting_departments: list[str]
    policy_references: list[PolicyCitation]
    policy_id: str | None
    policy_section: str | None
    resolution_steps: list[ResolutionStep]
    refund_eligibility: Eligibility
    replacement_eligibility: Eligibility
    compensation_eligibility: CompensationEligibility
    escalation_required: bool
    escalation_level: EscalationLevel
    escalation_reason: str | None
    escalation_notes: EscalationNotes | None
    response_type: str
    follow_up_required: bool
    follow_up_type: FollowUpType | None
    missing_information: list[MissingInfo]
    clarification_questions: list[str]
    agent_guidance: list[str]
    claims: list[Claim]
    manipulation_detected: bool
    manipulation_notes: str | None


class CustomerCommunication(BaseModel):
    """Pipeline 1, stage 2 - written from the Python-validated decision only."""

    model_config = ConfigDict(extra="allow")

    schema_version: Literal["1.0"]
    complaint_id: str
    tone: Tone
    subject: str
    customer_response: str
    follow_up_message: str | None
    claims: list[Claim]


MODELS: dict[str, type[BaseModel]] = {
    "complaint_analysis.v1": ComplaintAnalysis,
    "customer_communication.v1": CustomerCommunication,
}

_UNSUPPORTED = {"minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
                "minItems", "maxItems", "uniqueItems", "pattern", "default", "title", "examples", "minProperties",
                "maxProperties"}


def schema_path(name: str) -> str:
    return str(SCHEMAS_DIR / "ai" / f"{name}.schema.json")


def generate_schema(name: str) -> dict[str, Any]:
    """JSON Schema generated from the Pydantic model (used by scripts/export_schemas.py)."""
    model = MODELS[name]
    schema = model.model_json_schema(mode="validation")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = f"https://supportnova.example/schemas/ai/{name}.schema.json"
    schema["additionalProperties"] = False
    return schema


@lru_cache(maxsize=8)
def _load_file(name: str, mtime: float) -> dict[str, Any]:
    with open(schema_path(name), encoding="utf-8") as fh:
        return json.load(fh)


def load_schema(name: str) -> dict[str, Any]:
    """The committed schema file is the runtime contract; falls back to the generated schema."""
    import os

    path = schema_path(name)
    if os.path.exists(path):
        return copy.deepcopy(_load_file(name, os.path.getmtime(path)))
    return generate_schema(name)


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            ref = node["$ref"].split("/")[-1]
            merged = {**_inline(copy.deepcopy(defs[ref]), defs), **{k: v for k, v in node.items() if k != "$ref"}}
            return merged
        return {k: _inline(v, defs) for k, v in node.items() if k not in ("$defs", "definitions")}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


# schema field name -> catalog it must come from (see constrain_codes)
FIELD_CATALOG = {"issue_category": "categories", "category": "categories", "subcategory": "subcategories",
                 "department": "departments", "supporting_departments": "departments", "action_code": "actions",
                 "policy_id": "policies", "follow_up_type": "follow_up_types"}


def constrain_codes(schema: dict[str, Any], catalog: dict[str, list[str]]) -> dict[str, Any]:
    """Put the live catalog (taxonomy, departments, action codes, policy IDs) into the structured-output schema
    as enums, so a vendor's strict JSON mode can only return codes that exist - a category code where the
    category belongs, never a subcategory code. Built per request from the live Rule Matrix and knowledge base,
    so a category or policy added at runtime is accepted at once. Nullable fields stay nullable."""
    schema = copy.deepcopy(schema)

    def restrict(node: dict[str, Any], values: list[str]) -> None:
        if node.get("type") == "string":
            node["enum"] = values
        elif node.get("type") == "array" and isinstance(node.get("items"), dict):
            restrict(node["items"], values)
        for branch in node.get("anyOf", []):
            restrict(branch, values)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for name, sub in (node.get("properties") or {}).items():
                values = sorted(set(catalog.get(FIELD_CATALOG.get(name, ""), [])))
                if values and isinstance(sub, dict):
                    restrict(sub, values)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)
    return schema


def provider_schema(name: str, *, inline_refs: bool = False, all_required: bool = True) -> dict[str, Any]:
    """Schema adapted for provider structured-output features: unsupported keywords removed,
    ``additionalProperties: false`` and every property required on every object (optional fields
    are nullable). Full constraints are still enforced client-side (jsonschema + Pydantic)."""
    schema = load_schema(name)
    defs = schema.get("$defs", {})

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: ({name: walk(sub) for name, sub in v.items()} if k in ("properties", "$defs") and isinstance(v, dict)
                       else walk(v))  # field and definition names are data, never keywords to strip
                   for k, v in node.items() if k not in _UNSUPPORTED and k not in ("$schema", "$id")}
            if "const" in out:  # a one-value enum means the same and every vendor's strict mode accepts it
                out["enum"] = [out.pop("const")]
            if out.get("type") == "object" or "properties" in out:
                out["additionalProperties"] = False
                if all_required and "properties" in out:
                    out["required"] = list(out["properties"].keys())
            return out
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    adapted = walk(schema)
    if inline_refs:
        adapted = _inline(adapted, walk(defs))
    return adapted
