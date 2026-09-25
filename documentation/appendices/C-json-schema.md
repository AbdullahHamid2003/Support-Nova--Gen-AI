# Appendix C — JSON Schema

This appendix reproduces the two JSON Schema files that define the structured output of the GenAI Complaint Intelligence Pipeline. They are the runtime contract: every model reply is validated against them with `jsonschema` (Draft 2020-12) and then with the Pydantic models from which they are generated (`backend/src/supportnova/genai_pipeline/schemas.py`, exported by `scripts/export_schemas.py`). Chapter 8 documents the fields and the checks that validate them (Tables 8.10 and 8.11).

## C.1 Schema Files

**Table C.1 — AI output schema files**

| File | Title | Top-level fields | Required | Definitions | Used by prompt |
|---|---|---|---|---|---|
| `schemas/ai/complaint_analysis.v1.schema.json` | ComplaintAnalysis | 37 | 37 | Claim, CompensationEligibility, Eligibility, Entity, EscalationNotes, Issue, MissingInfo, PolicyCitation, ResolutionStep | `complaint_analysis` 1.0.0, 1.1.0, 1.2.0 |
| `schemas/ai/customer_communication.v1.schema.json` | CustomerCommunication | 7 | 7 | Claim | `customer_communication` 1.0.0 |

Both schemas set `additionalProperties: false` on every object and list every property as required; optional content is expressed as a nullable type (`anyOf` with `null`). Taxonomy, department, policy and action codes are plain strings in the files, because they are configuration: they are validated against the live Rule Matrix and Knowledge Base by checks SCH-002 to SCH-006 and, for the analysis request, restricted to the live catalogue as enumerations (Section C.4).

## C.2 complaint_analysis.v1

The file below is reproduced verbatim.

```json
{
  "$defs": {
    "Claim": {
      "additionalProperties": false,
      "properties": {
        "statement": {
          "title": "Statement",
          "type": "string"
        },
        "source_type": {
          "enum": [
            "complaint",
            "policy",
            "rule",
            "metadata",
            "validated_decision"
          ],
          "title": "Source Type",
          "type": "string"
        },
        "source_ref": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Source Ref"
        }
      },
      "required": [
        "statement",
        "source_type",
        "source_ref"
      ],
      "title": "Claim",
      "type": "object"
    },
    "CompensationEligibility": {
      "additionalProperties": false,
      "properties": {
        "status": {
          "enum": [
            "eligible",
            "not_eligible",
            "requires_verification",
            "not_applicable"
          ],
          "title": "Status",
          "type": "string"
        },
        "type": {
          "anyOf": [
            {
              "enum": [
                "store_credit",
                "shipping_fee_refund",
                "subscription_credit",
                "expedited_shipping",
                "none"
              ],
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Type"
        },
        "amount_usd": {
          "anyOf": [
            {
              "type": "number"
            },
            {
              "type": "null"
            }
          ],
          "title": "Amount Usd"
        },
        "reason": {
          "title": "Reason",
          "type": "string"
        },
        "policy_ref": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Policy Ref"
        }
      },
      "required": [
        "status",
        "type",
        "amount_usd",
        "reason",
        "policy_ref"
      ],
      "title": "CompensationEligibility",
      "type": "object"
    },
    "Eligibility": {
      "additionalProperties": false,
      "properties": {
        "status": {
          "enum": [
            "eligible",
            "not_eligible",
            "requires_verification",
            "not_applicable"
          ],
          "title": "Status",
          "type": "string"
        },
        "reason": {
          "title": "Reason",
          "type": "string"
        },
        "policy_ref": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Policy Ref"
        }
      },
      "required": [
        "status",
        "reason",
        "policy_ref"
      ],
      "title": "Eligibility",
      "type": "object"
    },
    "Entity": {
      "additionalProperties": false,
      "properties": {
        "type": {
          "enum": [
            "product",
            "service",
            "order_id",
            "transaction_id",
            "date",
            "amount",
            "location",
            "department",
            "complaint_reference",
            "person",
            "other"
          ],
          "title": "Type",
          "type": "string"
        },
        "value": {
          "title": "Value",
          "type": "string"
        }
      },
      "required": [
        "type",
        "value"
      ],
      "title": "Entity",
      "type": "object"
    },
    "EscalationNotes": {
      "additionalProperties": false,
      "properties": {
        "summary": {
          "title": "Summary",
          "type": "string"
        },
        "key_facts": {
          "items": {
            "type": "string"
          },
          "title": "Key Facts",
          "type": "array"
        },
        "reason": {
          "title": "Reason",
          "type": "string"
        },
        "actions_taken": {
          "items": {
            "type": "string"
          },
          "title": "Actions Taken",
          "type": "array"
        },
        "relevant_policy": {
          "items": {
            "type": "string"
          },
          "title": "Relevant Policy",
          "type": "array"
        },
        "required_next_action": {
          "title": "Required Next Action",
          "type": "string"
        }
      },
      "required": [
        "summary",
        "key_facts",
        "reason",
        "actions_taken",
        "relevant_policy",
        "required_next_action"
      ],
      "title": "EscalationNotes",
      "type": "object"
    },
    "Issue": {
      "additionalProperties": false,
      "properties": {
        "label": {
          "title": "Label",
          "type": "string"
        },
        "category": {
          "title": "Category",
          "type": "string"
        },
        "subcategory": {
          "title": "Subcategory",
          "type": "string"
        },
        "evidence_quote": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Evidence Quote"
        }
      },
      "required": [
        "label",
        "category",
        "subcategory",
        "evidence_quote"
      ],
      "title": "Issue",
      "type": "object"
    },
    "MissingInfo": {
      "additionalProperties": false,
      "properties": {
        "field": {
          "title": "Field",
          "type": "string"
        },
        "reason": {
          "title": "Reason",
          "type": "string"
        }
      },
      "required": [
        "field",
        "reason"
      ],
      "title": "MissingInfo",
      "type": "object"
    },
    "PolicyCitation": {
      "additionalProperties": false,
      "properties": {
        "policy_id": {
          "title": "Policy Id",
          "type": "string"
        },
        "section": {
          "title": "Section",
          "type": "string"
        },
        "evidence_id": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Evidence Id"
        },
        "applicability": {
          "enum": [
            "Applicable",
            "Conditionally Applicable",
            "Not Applicable",
            "Outdated"
          ],
          "title": "Applicability",
          "type": "string"
        },
        "reason": {
          "title": "Reason",
          "type": "string"
        }
      },
      "required": [
        "policy_id",
        "section",
        "evidence_id",
        "applicability",
        "reason"
      ],
      "title": "PolicyCitation",
      "type": "object"
    },
    "ResolutionStep": {
      "additionalProperties": false,
      "properties": {
        "action_code": {
          "title": "Action Code",
          "type": "string"
        },
        "description": {
          "title": "Description",
          "type": "string"
        },
        "policy_ref": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Policy Ref"
        }
      },
      "required": [
        "action_code",
        "description",
        "policy_ref"
      ],
      "title": "ResolutionStep",
      "type": "object"
    }
  },
  "additionalProperties": false,
  "description": "Pipeline 1, stage 1. Field names follow the SRS sample output where one exists\n(issue_category, subcategory, sentiment, urgency, priority, department, policy_id,\npolicy_section, resolution_steps, escalation_required, response_type, follow_up_required).",
  "properties": {
    "schema_version": {
      "const": "1.0",
      "title": "Schema Version",
      "type": "string"
    },
    "complaint_id": {
      "title": "Complaint Id",
      "type": "string"
    },
    "summary": {
      "title": "Summary",
      "type": "string"
    },
    "key_facts": {
      "items": {
        "type": "string"
      },
      "title": "Key Facts",
      "type": "array"
    },
    "primary_issue": {
      "$ref": "#/$defs/Issue"
    },
    "secondary_issues": {
      "items": {
        "$ref": "#/$defs/Issue"
      },
      "title": "Secondary Issues",
      "type": "array"
    },
    "issue_category": {
      "title": "Issue Category",
      "type": "string"
    },
    "subcategory": {
      "title": "Subcategory",
      "type": "string"
    },
    "sentiment": {
      "enum": [
        "Positive",
        "Neutral",
        "Negative",
        "Strongly Negative"
      ],
      "title": "Sentiment",
      "type": "string"
    },
    "emotion_indicators": {
      "items": {
        "enum": [
          "Frustration",
          "Anger",
          "Disappointment",
          "Confusion",
          "Urgency",
          "Anxiety",
          "Satisfaction"
        ],
        "type": "string"
      },
      "title": "Emotion Indicators",
      "type": "array"
    },
    "urgency": {
      "enum": [
        "Low",
        "Medium",
        "High",
        "Critical"
      ],
      "title": "Urgency",
      "type": "string"
    },
    "urgency_rationale": {
      "title": "Urgency Rationale",
      "type": "string"
    },
    "impact": {
      "enum": [
        "Low",
        "Medium",
        "High"
      ],
      "title": "Impact",
      "type": "string"
    },
    "priority": {
      "enum": [
        "P0",
        "P1",
        "P2",
        "P3"
      ],
      "title": "Priority",
      "type": "string"
    },
    "entities": {
      "items": {
        "$ref": "#/$defs/Entity"
      },
      "title": "Entities",
      "type": "array"
    },
    "department": {
      "title": "Department",
      "type": "string"
    },
    "supporting_departments": {
      "items": {
        "type": "string"
      },
      "title": "Supporting Departments",
      "type": "array"
    },
    "policy_references": {
      "items": {
        "$ref": "#/$defs/PolicyCitation"
      },
      "title": "Policy References",
      "type": "array"
    },
    "policy_id": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Policy Id"
    },
    "policy_section": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Policy Section"
    },
    "resolution_steps": {
      "items": {
        "$ref": "#/$defs/ResolutionStep"
      },
      "title": "Resolution Steps",
      "type": "array"
    },
    "refund_eligibility": {
      "$ref": "#/$defs/Eligibility"
    },
    "replacement_eligibility": {
      "$ref": "#/$defs/Eligibility"
    },
    "compensation_eligibility": {
      "$ref": "#/$defs/CompensationEligibility"
    },
    "escalation_required": {
      "title": "Escalation Required",
      "type": "boolean"
    },
    "escalation_level": {
      "enum": [
        "No Escalation",
        "Supervisor Review",
        "Department Manager",
        "Specialist Team",
        "Compliance Review",
        "Critical Management Escalation"
      ],
      "title": "Escalation Level",
      "type": "string"
    },
    "escalation_reason": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Escalation Reason"
    },
    "escalation_notes": {
      "anyOf": [
        {
          "$ref": "#/$defs/EscalationNotes"
        },
        {
          "type": "null"
        }
      ]
    },
    "response_type": {
      "title": "Response Type",
      "type": "string"
    },
    "follow_up_required": {
      "title": "Follow Up Required",
      "type": "boolean"
    },
    "follow_up_type": {
      "anyOf": [
        {
          "enum": [
            "Request for additional information",
            "Resolution confirmation",
            "Refund-status update",
            "Replacement-status update",
            "Escalation acknowledgement",
            "Closure confirmation"
          ],
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Follow Up Type"
    },
    "missing_information": {
      "items": {
        "$ref": "#/$defs/MissingInfo"
      },
      "title": "Missing Information",
      "type": "array"
    },
    "clarification_questions": {
      "items": {
        "type": "string"
      },
      "title": "Clarification Questions",
      "type": "array"
    },
    "agent_guidance": {
      "items": {
        "type": "string"
      },
      "title": "Agent Guidance",
      "type": "array"
    },
    "claims": {
      "items": {
        "$ref": "#/$defs/Claim"
      },
      "title": "Claims",
      "type": "array"
    },
    "manipulation_detected": {
      "title": "Manipulation Detected",
      "type": "boolean"
    },
    "manipulation_notes": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Manipulation Notes"
    }
  },
  "required": [
    "schema_version",
    "complaint_id",
    "summary",
    "key_facts",
    "primary_issue",
    "secondary_issues",
    "issue_category",
    "subcategory",
    "sentiment",
    "emotion_indicators",
    "urgency",
    "urgency_rationale",
    "impact",
    "priority",
    "entities",
    "department",
    "supporting_departments",
    "policy_references",
    "policy_id",
    "policy_section",
    "resolution_steps",
    "refund_eligibility",
    "replacement_eligibility",
    "compensation_eligibility",
    "escalation_required",
    "escalation_level",
    "escalation_reason",
    "escalation_notes",
    "response_type",
    "follow_up_required",
    "follow_up_type",
    "missing_information",
    "clarification_questions",
    "agent_guidance",
    "claims",
    "manipulation_detected",
    "manipulation_notes"
  ],
  "title": "ComplaintAnalysis",
  "type": "object",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://supportnova.example/schemas/ai/complaint_analysis.v1.schema.json"
}
```

## C.3 customer_communication.v1

The file below is reproduced verbatim.

```json
{
  "$defs": {
    "Claim": {
      "additionalProperties": false,
      "properties": {
        "statement": {
          "title": "Statement",
          "type": "string"
        },
        "source_type": {
          "enum": [
            "complaint",
            "policy",
            "rule",
            "metadata",
            "validated_decision"
          ],
          "title": "Source Type",
          "type": "string"
        },
        "source_ref": {
          "anyOf": [
            {
              "type": "string"
            },
            {
              "type": "null"
            }
          ],
          "title": "Source Ref"
        }
      },
      "required": [
        "statement",
        "source_type",
        "source_ref"
      ],
      "title": "Claim",
      "type": "object"
    }
  },
  "additionalProperties": false,
  "description": "Pipeline 1, stage 2 - written from the Python-validated decision only.",
  "properties": {
    "schema_version": {
      "const": "1.0",
      "title": "Schema Version",
      "type": "string"
    },
    "complaint_id": {
      "title": "Complaint Id",
      "type": "string"
    },
    "tone": {
      "enum": [
        "professional",
        "empathetic",
        "concise",
        "formal"
      ],
      "title": "Tone",
      "type": "string"
    },
    "subject": {
      "title": "Subject",
      "type": "string"
    },
    "customer_response": {
      "title": "Customer Response",
      "type": "string"
    },
    "follow_up_message": {
      "anyOf": [
        {
          "type": "string"
        },
        {
          "type": "null"
        }
      ],
      "title": "Follow Up Message"
    },
    "claims": {
      "items": {
        "$ref": "#/$defs/Claim"
      },
      "title": "Claims",
      "type": "array"
    }
  },
  "required": [
    "schema_version",
    "complaint_id",
    "tone",
    "subject",
    "customer_response",
    "follow_up_message",
    "claims"
  ],
  "title": "CustomerCommunication",
  "type": "object",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://supportnova.example/schemas/ai/customer_communication.v1.schema.json"
}
```

## C.4 Schema Sent to the Provider

The schema sent with a request is an adapted copy produced by `provider_schema`: unsupported keywords such as `title`, `minLength` and `default` are removed, `$schema` and `$id` are dropped, the one-value `const` becomes an `enum`, and every object has `additionalProperties: false` with all properties required. For the analysis stage, `constrain_codes` then adds the live catalogue as enumerations to the fields `issue_category`, `category`, `subcategory`, `department`, `supporting_departments`, `action_code`, `policy_id` and `follow_up_type`. The fragment below was produced by these two functions with the demo catalogue of 11 categories, 10 departments and 6 follow-up types (the subcategory, action and policy enumerations are applied in the same way and are omitted here for length); nullable fields such as `follow_up_type` and `escalation_notes` stay nullable.

```json
{
  "schema_version": {"type": "string", "enum": ["1.0"]},
  "issue_category": {"type": "string", "enum": ["ACC", "BIL", "DEL", "PRD", "PRV", "REF", "SAF", "STF", "SVC", "TEC", "WAR"]},
  "department": {"type": "string", "enum": ["DEPT-BIL", "DEPT-CMP", "DEPT-CRL", "DEPT-LOG", "DEPT-MGT", "DEPT-RET", "DEPT-SAF", "DEPT-SEC", "DEPT-TEC", "DEPT-WAR"]},
  "follow_up_type": {"anyOf": [{"enum": ["Closure confirmation", "Escalation acknowledgement", "Refund-status update", "Replacement-status update", "Request for additional information", "Resolution confirmation"], "type": "string"}, {"type": "null"}]},
  "escalation_notes": {"anyOf": [{"$ref": "#/$defs/EscalationNotes"}, {"type": "null"}]}
}
```
