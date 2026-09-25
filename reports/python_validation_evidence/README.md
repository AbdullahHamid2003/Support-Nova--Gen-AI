# Python ground-truth validation evidence (SRS Deliverable 7)

One real example per validation type, taken from the database: the check, what the rules expected, what the GenAI proposed, and the outcome. Every complaint listed can be opened in the UI.

## Complaint classification validation

* **CLS-001 Category matches the Python rule classification** (major) - `R2-EVL-00005` -> **fail**: GenAI category REF differs from the rule classification SVC (matched: installation, appointment, pro install, installer, product:SVC-INSTALL).
* **CLS-002 Subcategory matches the Python rule classification** (minor) - `R2-EVL-00005` -> **fail**: Subcategory REF-REQ differs from SVC-INS.

## Routing validation

* **RTE-001 Primary department matches the routing rules** (critical) - `R2-EVL-00005` -> **fail**: GenAI routed to DEPT-RET; the routing rules require DEPT-CRL for SVC-INS.
* **RTE-002 Required supporting departments included** (major) - `R2-EVL-00005` -> **fail**: Supporting departments required: DEPT-TEC; missing: DEPT-TEC.

## Priority validation

* **PRI-001 Urgency meets the rule-matrix level** (major) - `R2-EVL-00005` -> **fail**: Urgency under-estimated: GenAI Low, rules require Medium (RES-SVC-INS-01). Calm wording does not reduce risk.
* **PRI-002 Priority matches the priority matrix** (major) - `LAB-00015` -> **fail**: Priority P3; the priority matrix gives P1 (urgency High x impact High).
* **PRI-003 Urgency not inflated by emotional language** (minor) - `R2-EVL-00006` -> **pass**: Urgency is not driven by sentiment.

## Escalation validation

* **ESC-001 Mandatory escalation enforced** (critical) - `CMP-00619` -> **fail**: Mandatory escalation missed: Department Manager required by ESC-029 (Requested compensation exceeds the agent approval limit.); ESC-030 (Requested compensation exceeds the supervisor approval limit.). Python enforces it.
* **ESC-002 Escalation level meets the rule level** (critical) - `CMP-00618` -> **fail**: Escalation level Specialist Team; rules require Critical Management Escalation.
* **ESC-004 Escalation notes contain all required elements** (major) - `CMP-00396` -> **fail**: Escalation notes missing: summary, key_facts, reason, actions_taken, relevant_policy, required_next_action

## Policy validation

* **POL-001 At least one policy reference cited** (major) - `R2-EVL-00006` -> **pass**: 3 policy section(s) cited.
* **POL-002 Cited policies are Active (no outdated policy as primary basis)** (critical) - `LAB-00010` -> **fail**: Outdated/superseded policy used as a basis: RET-SOP-23:3 (CHP-POL-01 s10.4).
* **POL-003 Cited policies are supported by retrieved evidence** (major) - `R1-EVL-00054` -> **fail**: Cited but not in retrieved evidence: INS-POL-24:5.1, 5.2, REF-POL-02:3.4
* **POL-006 Policy precedence respected in conflicts** (major) - `R1-EVL-00016` -> **fail**: Relied on a lower-precedence conflicting source: FAQ-GEN-16:2.2

## Resolution validation

* **RES-001 Required actions present** (major) - `R2-EVL-00005` -> **fail**: Missing required actions: SCHEDULE_INSTALL_REVISIT
* **RES-002 No prohibited actions** (critical) - `LAB-00017` -> **fail**: Prohibited actions proposed: OFFER_STORE_CREDIT
* **RES-004 No contradictory actions** (major) - `R2-EVL-00005` -> **fail**: Contradictory instructions: PROCESS_REFUND with refund not eligible

## Source traceability

* **HAL-001 Claims traceable to complaint** (major) - `R2-EVL-00002` -> **fail**: Claims without support: "No Care+ coverage was purchased for this product." (compared with verified system facts); "Warranty excludes physical or liquid damage and normal wear; remedies include re" (source 'E1,E4' is not retrieved evidence or an existing policy)
* **HAL-004 Policy references in text are valid** (major) - `LAB-00008` -> **fail**: Text references non-existent policies: REF-POL-77
* **SCH-004 Policy IDs and sections exist in the knowledge base** (major) - `LAB-00012` -> **fail**: Cited sections do not exist: BIL-POL-05:General

## Unsupported promise detection

* **RSP-002 No unsupported promises** (critical) - `LAB-00007` -> **fail**: Unsupported promises: Guaranteeing compensation (validated compensation eligibility: 'not_applicable'). "We guarantee you will receive USD 200 compensation for the trouble."
* **RSP-003 Timelines supported by policy or SLA** (major) - `R2-EVL-00003` -> **fail**: Unsupported timelines: "We aim to confirm resolution within 72 hours."
* **RSP-004 Amounts traceable to case facts or entitlements** (major) - `LAB-00016` -> **fail**: Amounts/references not traceable to the case: LMR-999999

## Contradiction detection

* **RES-004 No contradictory actions** (major) - `R2-EVL-00005` -> **fail**: Contradictory instructions: PROCESS_REFUND with refund not eligible
* **POL-006 Policy precedence respected in conflicts** (major) - `R1-EVL-00016` -> **fail**: Relied on a lower-precedence conflicting source: FAQ-GEN-16:2.2

## Schema validation

* **SCH-001 GenAI output matches the JSON schema** (critical) - `R2-EVL-00006` -> **pass**: GenAI output matches the complaint_analysis.v1 JSON schema (required fields, types, enums).
* **SCH-002 Category and subcategory exist in the taxonomy** (critical) - `R2-EVL-00006` -> **pass**: Category and subcategory codes exist in the taxonomy.
* **SCH-003 Department IDs are valid** (critical) - `R2-EVL-00006` -> **pass**: Department IDs are valid.
