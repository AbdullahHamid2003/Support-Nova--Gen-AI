# Appendix D — Sample GenAI Structured Output

This appendix reproduces the structured output that the GenAI Complaint Intelligence Pipeline stored for one complaint of the demo dataset, CMP-00616, together with the complaint it answers and the prompt versions that produced it. All names, references and events are fictional data of Lumora Home Technologies. The JSON is taken from the `analyses` record of the demo database; because PostgreSQL JSON storage does not keep key order, the keys are shown in schema order, and the only abridgement is the evidence quote of `primary_issue`, marked with "…". Chapter 7 (Section 7.10) explains how the Python Ground-Truth Validation Pipeline treated this output.

## D.1 The Complaint

**Table D.1 — Complaint CMP-00616**

| Field | Value |
|---|---|
| Complaint reference | CMP-00616 (dataset case) |
| Title | Front door found unlocked |
| Channel | email |
| Customer type | individual |
| Product or service | Lumora Keystone Smart Lock |
| Order reference | not provided |
| Requested resolution | other |
| Requested tone | professional |
| Complaint date | 2026-09-21 21:28 (UTC+05:00) |

Description as submitted:

```text
Dear Lumora Support,

Good morning. When I came downstairs today I found the door was unlocked, and the Lumora Keystone Smart Lock log shows it unlocked remotely at 4:40am. I live alone and I am rather shaken. I would be grateful if someone could look into this urgently.

Warm regards,
Thea Rahman
Birchmont
```

## D.2 Run Metadata

**Table D.2 — GenAI calls that produced the output**

| Item | Analysis stage | Communication stage |
|---|---|---|
| Prompt | `complaint_analysis` 1.2.0 | `customer_communication` 1.0.0 |
| Prompt SHA-256 | `428c297c112322b4…` | `908eec6961cdbcba…` |
| Provider and model | openai, gpt-4.1-mini (served gpt-4.1-mini-2025-04-14) | openai, gpt-4.1-mini (served gpt-4.1-mini-2025-04-14) |
| Attempts | 1, valid | 1, valid |
| Latency | 20,024 ms | 5,899 ms |
| Input and output tokens | 9,690 and 1,919 | 1,801 and 414 |
| Rendered system and user prompt | 24,141 and 6,919 characters | 2,549 and 4,332 characters |
| Finish reason | stop | stop |

The complete analysis took 26,035 ms from the start of processing to the stored result (20:11:58 to 20:12:24 on 2026-09-24, UTC+05:00).

## D.3 complaint_analysis.v1 Output

```json
{
  "schema_version": "1.0",
  "complaint_id": "CMP-00616",
  "summary": "Customer reports an unexplained remote unlock event on their Lumora Keystone Smart Lock, causing safety and security concerns.",
  "key_facts": [
    "Customer found front door unlocked unexpectedly.",
    "Smart lock log shows remote unlock at 4:40am.",
    "Customer lives alone and feels shaken.",
    "No order reference provided.",
    "Lumora Keystone Smart Lock is covered by 24-month warranty."
  ],
  "primary_issue": {
    "label": "Unexplained Smart Lock Unlock Event",
    "category": "ACC",
    "subcategory": "ACC-UNA",
    "evidence_quote": "Unexplained lock or unlock events are critical security incidents. …"
  },
  "secondary_issues": [],
  "issue_category": "ACC",
  "subcategory": "ACC-UNA",
  "sentiment": "Negative",
  "emotion_indicators": [
    "Anxiety",
    "Urgency",
    "Frustration"
  ],
  "urgency": "Critical",
  "urgency_rationale": "Unexplained remote unlock of smart lock poses immediate risk to personal safety and home security.",
  "impact": "High",
  "priority": "P0",
  "entities": [
    {
      "type": "product",
      "value": "Lumora Keystone Smart Lock"
    },
    {
      "type": "location",
      "value": "Birchmont"
    },
    {
      "type": "person",
      "value": "Thea Rahman"
    }
  ],
  "department": "DEPT-SEC",
  "supporting_departments": [
    "DEPT-MGT"
  ],
  "policy_references": [
    {
      "policy_id": "SEC-POL-09",
      "section": "5.1",
      "evidence_id": "E1",
      "applicability": "Applicable",
      "reason": "Defines unexplained lock events as critical security incidents requiring investigation."
    },
    {
      "policy_id": "SEC-POL-09",
      "section": "5.2",
      "evidence_id": "E3",
      "applicability": "Applicable",
      "reason": "Requires advising customer to use physical key and disable remote access during investigation."
    },
    {
      "policy_id": "ESC-SOP-12",
      "section": "4.2",
      "evidence_id": "E4",
      "applicability": "Applicable",
      "reason": "Mandates critical management escalation for unexplained smart-lock unlock events."
    },
    {
      "policy_id": "SEC-POL-09",
      "section": "5",
      "evidence_id": "E8",
      "applicability": "Applicable",
      "reason": "Smart locks protect physical security and incidents involving them require highest urgency."
    }
  ],
  "policy_id": "SEC-POL-09",
  "policy_section": "5.1",
  "resolution_steps": [
    {
      "action_code": "VERIFY_IDENTITY",
      "description": "Verify customer identity to ensure secure handling of the account.",
      "policy_ref": "SEC-POL-09:5.1"
    },
    {
      "action_code": "VERIFY_ACCOUNT",
      "description": "Verify the customer's account details and access permissions for the smart lock.",
      "policy_ref": "SEC-POL-09:5.1"
    },
    {
      "action_code": "REVIEW_ACCOUNT_ACTIVITY",
      "description": "Review the smart lock event logs and recent account changes to identify the cause of the unlock event.",
      "policy_ref": "SEC-POL-09:5.1"
    },
    {
      "action_code": "ADVISE_STOP_USING",
      "description": "Advise the customer to use the physical key and disable remote access until the investigation is complete.",
      "policy_ref": "SEC-POL-09:5.2"
    },
    {
      "action_code": "LOCK_ACCOUNT",
      "description": "Lock the account to prevent further unauthorized access during investigation.",
      "policy_ref": "SEC-POL-09:5.1"
    },
    {
      "action_code": "ESCALATE_CRITICAL_MANAGEMENT",
      "description": "Escalate the case to Critical Management due to the high risk of security breach.",
      "policy_ref": "ESC-SOP-12:4.2"
    },
    {
      "action_code": "SCHEDULE_FOLLOW_UP",
      "description": "Schedule a follow-up with the customer to update on investigation progress and resolution.",
      "policy_ref": null
    }
  ],
  "refund_eligibility": {
    "status": "not_applicable",
    "reason": "No refund requested or applicable for security incident.",
    "policy_ref": null
  },
  "replacement_eligibility": {
    "status": "not_applicable",
    "reason": "No product defect or warranty claim indicated.",
    "policy_ref": null
  },
  "compensation_eligibility": {
    "status": "not_applicable",
    "type": "none",
    "amount_usd": null,
    "reason": "No compensation requested or applicable for this security incident.",
    "policy_ref": null
  },
  "escalation_required": true,
  "escalation_level": "Critical Management Escalation",
  "escalation_reason": "Unexplained smart-lock unlock event poses immediate safety and security risk.",
  "escalation_notes": {
    "summary": "Customer's Lumora Keystone Smart Lock was remotely unlocked without explanation, causing safety concerns.",
    "key_facts": [
      "Remote unlock event at 4:40am recorded in lock log.",
      "Customer lives alone and was shaken by the incident.",
      "No order reference provided, but product is a Lumora Keystone Smart Lock.",
      "Security policy mandates critical escalation for unexplained unlock events.",
      "Interim advice includes advising physical key use and disabling remote access."
    ],
    "reason": "The incident represents a critical security breach requiring immediate management attention and containment.",
    "actions_taken": [
      "Verified complaint details and identified primary issue as unexplained account access.",
      "Outlined resolution steps including verification, containment, and escalation.",
      "Prepared to advise customer on interim safety measures.",
      "Escalated to Critical Management as per policy ESC-SOP-12 section 4.2."
    ],
    "relevant_policy": [
      "SEC-POL-09:5.1",
      "SEC-POL-09:5.2",
      "ESC-SOP-12:4.2",
      "SEC-POL-09:5"
    ],
    "required_next_action": "Account Security team to conduct detailed investigation and coordinate with management."
  },
  "response_type": "Apology and Resolution Update",
  "follow_up_required": true,
  "follow_up_type": "Resolution confirmation",
  "missing_information": [
    {
      "field": "order reference",
      "reason": "Order reference is needed to verify product warranty and purchase details."
    }
  ],
  "clarification_questions": [
    "Please provide the order reference or purchase details for the Lumora Keystone Smart Lock.",
    "Have you noticed any other unusual activity on your account or devices recently?"
  ],
  "agent_guidance": [
    "Verify the customer's identity and account before proceeding.",
    "Explain the critical nature of the security incident and the steps being taken.",
    "Advise the customer to use the physical key and disable remote access immediately.",
    "Escalate the case to Critical Management without delay."
  ],
  "claims": [
    {
      "statement": "The front door was found unlocked unexpectedly.",
      "source_type": "complaint",
      "source_ref": "complaint"
    },
    {
      "statement": "The smart lock log shows a remote unlock event at 4:40am.",
      "source_type": "complaint",
      "source_ref": "complaint"
    },
    {
      "statement": "Unexplained lock or unlock events are critical security incidents requiring investigation.",
      "source_type": "policy",
      "source_ref": "E1"
    },
    {
      "statement": "Interim advice includes advising the customer to use the physical key and disable remote access.",
      "source_type": "policy",
      "source_ref": "E3"
    },
    {
      "statement": "Unexplained smart-lock unlock events require escalation to Critical Management.",
      "source_type": "policy",
      "source_ref": "E4"
    }
  ],
  "manipulation_detected": false,
  "manipulation_notes": null
}
```

## D.4 customer_communication.v1 Output

The communication stage received the validated decision, not the analysis above. The reply therefore contains the two actions that the Rule Matrix added (advising the physical key and signing out all sessions) and uses the follow-up type the rules set (Escalation acknowledgement, due within one hour).

```json
{
  "schema_version": "1.0",
  "complaint_id": "CMP-00616",
  "tone": "professional",
  "subject": "Urgent: Unexplained Remote Unlock Event on Lumora Keystone Smart Lock",
  "customer_response": "Dear Ms. Rahman,\n\nThank you for contacting us regarding your complaint CMP-00616. We understand your concern about the unexpected remote unlock event on your Lumora Keystone Smart Lock at 4:40am, which understandably caused you distress. This incident has been escalated to our Account Security specialist team for critical management review.\n\nTo proceed, we need to verify your identity and review the smart lock event logs along with recent account changes to identify the cause of this unlock event. Meanwhile, please use your physical key to secure your door and disable remote access via the Lumora Home App. We have also signed out all active sessions on your account to prevent further unauthorized access.\n\nCould you please provide the order reference or purchase details for your Lumora Keystone Smart Lock? Additionally, have you noticed any other unusual activity on your account or devices recently? Your prompt response will help us expedite the investigation.\n\nWe appreciate your cooperation and are committed to resolving this matter swiftly.\n\nSincerely,\nLumora Customer Care",
  "follow_up_message": "Acknowledgement of escalation has been sent. We will update you within 1 hour.",
  "claims": [
    {
      "statement": "Customer reports an unexplained remote unlock event on their Lumora Keystone Smart Lock, causing safety and security concerns.",
      "source_type": "complaint",
      "source_ref": "CMP-00616"
    },
    {
      "statement": "Unexplained lock or unlock events are critical security incidents and require review of event history and recent account changes.",
      "source_type": "policy",
      "source_ref": "E1"
    },
    {
      "statement": "Advise the customer to use the physical key and disable remote access until the investigation is complete.",
      "source_type": "policy",
      "source_ref": "E3"
    },
    {
      "statement": "The case has been escalated to the Account Security specialist team for critical management review.",
      "source_type": "validated_decision",
      "source_ref": null
    }
  ]
}
```

## D.5 Outcome of Validation

**Table D.3 — Selected fields: AI proposal and validated decision for CMP-00616**

| Field | AI proposal | Validated decision |
|---|---|---|
| Category and subcategory | ACC, ACC-UNA | ACC, ACC-UNA (AI unconfirmed, rule confidence low) |
| Department and supporting | DEPT-SEC; DEPT-MGT | DEPT-SEC; DEPT-MGT |
| Urgency, impact, priority | Critical, High, P0 | Critical, High, P0 (rule RES-ACC-UNA-03) |
| Escalation | Critical Management Escalation | Critical Management Escalation (ESC-009, ESC-010) |
| Resolution actions | 7 steps | 6 steps: 4 AI steps kept, ADVISE_PHYSICAL_KEY and REVOKE_SESSIONS added, 3 AI steps excluded |
| Follow-up type | Resolution confirmation | Escalation acknowledgement, due in 1 hour (FUP-002) |
| Verification | — | Score 94.0, Manual Review (REV-002, REV-005, REV-008) |
