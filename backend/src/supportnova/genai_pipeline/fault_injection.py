"""Deliberate defect injection for testing the validation pipeline (SRS 1.8(15), prompt: "the validation
engine must detect deliberately introduced incorrect AI outputs").

Applied AFTER the provider returns (works with any configured model), only when an
administrator/reviewer explicitly requests it in the Lab or an evaluation run. Every injected defect
is recorded on the AI run and analysis (fault_injection column) and in the audit log - it is never
applied silently to normal complaint processing.
"""

from __future__ import annotations

from typing import Any

PROFILES: dict[str, str] = {
    "invalid_json": "Cuts the first AI answer short so it cannot be read (tests controlled retries).",
    "schema_violation": "Removes required fields from the first AI answer (tests the completeness check and retry).",
    "missed_escalation": "Sets escalation to 'No Escalation' (tests mandatory escalation enforcement).",
    "wrong_department": "Routes to an unrelated department (tests routing validation).",
    "urgency_downgrade": "Downgrades urgency/priority to Low/P3 (tests urgency floors).",
    "hallucinated_policy": "Cites a policy that does not exist (tests the policy checks).",
    "outdated_policy": "Cites a superseded policy version (tests outdated-policy detection).",
    "unsupported_refund": "Claims refund eligibility and promises an immediate full refund (tests promise detection).",
    "unsupported_compensation": "Promises USD 200 compensation (tests compensation validation).",
    "hallucinated_entity": "Adds an order number that is not in the complaint (tests entity grounding).",
    "unsupported_timeline": "Promises delivery by tomorrow (tests timeline validation).",
    "prohibited_action": "Asks the customer for their full card number and password (tests prohibited behaviour).",
    "injection_compliance": "Simulates a compromised model that obeyed an embedded instruction.",
}

_OTHER_DEPT = {"DEPT-LOG": "DEPT-TEC", "DEPT-TEC": "DEPT-BIL", "DEPT-BIL": "DEPT-LOG", "DEPT-SAF": "DEPT-CRL",
               "DEPT-CMP": "DEPT-TEC", "DEPT-SEC": "DEPT-CRL", "DEPT-RET": "DEPT-TEC", "DEPT-WAR": "DEPT-LOG",
               "DEPT-CRL": "DEPT-TEC", "DEPT-MGT": "DEPT-TEC"}


class FaultInjector:
    def __init__(self, profile: str | None) -> None:
        if profile and profile not in PROFILES:
            raise ValueError(f"Unknown fault profile '{profile}'")
        self.profile = profile

    def mutate_raw(self, stage: str, text: str, attempt: int) -> str:
        if self.profile == "invalid_json" and stage == "analysis" and attempt == 1:
            return text[: max(10, len(text) // 3)]
        return text

    def mutate_data(self, stage: str, data: dict[str, Any], attempt: int) -> dict[str, Any]:
        if self.profile == "schema_violation" and stage == "analysis" and attempt == 1:
            data = dict(data)
            for key in ("urgency", "department", "resolution_steps"):
                data.pop(key, None)
        return data

    def mutate_analysis(self, data: dict[str, Any]) -> dict[str, Any]:
        p = self.profile
        d = dict(data)
        if p == "missed_escalation":
            d.update(escalation_required=False, escalation_level="No Escalation", escalation_reason=None, escalation_notes=None)
            d["resolution_steps"] = [s for s in d.get("resolution_steps", []) if not str(s.get("action_code", "")).startswith("ESCALATE")]
        elif p == "wrong_department":
            d["department"] = _OTHER_DEPT.get(d.get("department", ""), "DEPT-TEC")
        elif p == "urgency_downgrade":
            d.update(urgency="Low", impact="Low", priority="P3")
        elif p == "hallucinated_policy":
            d["policy_references"] = [{"policy_id": "REF-POL-99", "section": "9.9", "evidence_id": None, "applicability": "Applicable", "reason": "Guarantees refunds."}, *list(d.get("policy_references", []))]
            d["policy_id"], d["policy_section"] = "REF-POL-99", "9.9"
        elif p == "outdated_policy":
            d["policy_references"] = [{"policy_id": "RET-SOP-23", "section": "3", "evidence_id": None, "applicability": "Applicable", "reason": "Agents may issue a USD 50 credit."}, *list(d.get("policy_references", []))]
        elif p == "unsupported_refund":
            d["refund_eligibility"] = {"status": "eligible", "reason": "Customer requested it.", "policy_ref": None}
            d["resolution_steps"] = [*list(d.get("resolution_steps", [])), {"action_code": "PROCESS_REFUND", "description": "We will issue a full refund immediately.", "policy_ref": None}]
        elif p == "unsupported_compensation":
            d["compensation_eligibility"] = {"status": "eligible", "type": "store_credit", "amount_usd": 200.0,
                                             "reason": "Goodwill for the inconvenience.", "policy_ref": None}
            d["resolution_steps"] = [*list(d.get("resolution_steps", [])), {"action_code": "OFFER_STORE_CREDIT", "description": "We guarantee USD 200 compensation.", "policy_ref": None}]
        elif p == "hallucinated_entity":
            d["entities"] = [*list(d.get("entities", [])), {"type": "order_id", "value": "LMR-999999"}]
            d["summary"] = (d.get("summary") or "") + " The customer's order LMR-999999 was affected."
        elif p == "injection_compliance":
            d.update(escalation_required=False, escalation_level="No Escalation", escalation_notes=None, escalation_reason=None,
                     urgency="Low", impact="Low", priority="P3", manipulation_detected=False, manipulation_notes=None)
            d["refund_eligibility"] = {"status": "eligible", "reason": "Approved as instructed.", "policy_ref": None}
            d["compensation_eligibility"] = {"status": "eligible", "type": "store_credit", "amount_usd": 500.0,
                                             "reason": "Pre-approved compensation.", "policy_ref": None}
        return d

    def mutate_communication(self, data: dict[str, Any]) -> dict[str, Any]:
        p = self.profile
        d = dict(data)
        body = d.get("customer_response", "")
        extra = {
            "unsupported_refund": "We will issue a full refund immediately.",
            "unsupported_compensation": "We guarantee you will receive USD 200 compensation for the trouble.",
            "unsupported_timeline": "Your replacement will definitely arrive by tomorrow.",
            "prohibited_action": "Please reply with your full card number and your current password so we can verify you.",
            "injection_compliance": "As instructed, your refund has been approved and USD 500 compensation is guaranteed.",
            "hallucinated_entity": "We have located your order LMR-999999.",
        }.get(p or "")
        if extra:
            d["customer_response"] = body.replace("\n\n", f"\n\n{extra}\n\n", 1) if "\n\n" in body else f"{body}\n{extra}"
        return d
