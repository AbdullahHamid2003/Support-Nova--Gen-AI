# Chapter 13 — Routing Validation

Routing decides which department of Lumora Home Technologies owns a complaint and which other departments must be involved. The SRS requires the application to recommend a responsible department (Step 22), to identify primary and supporting departments when several are needed (Step 24), and to have Python "independently verify the GenAI department assignment using the Complaint Resolution Rule Matrix" (Step 23). Non-functional requirement 4 adds that critical complaint-routing rules must be correctly enforced before final verification. In SupportNova the GenAI Complaint Intelligence Pipeline (Pipeline 1) proposes a primary department and supporting departments; the Python Ground-Truth Validation Pipeline (Pipeline 2) derives the departments from the routing rules, checks the proposal with checks RTE-001 and RTE-002, and always routes the complaint to the rules' department.

## 13.1 Routing Ground Truth

The routing ground truth is `rules/routing_rules/routing_rules.yaml`, the machine-readable form of section 3 of the Department Routing Rules RTE-RUL-14 v2.0. It contains one routing rule per subcategory, RTE-001 to RTE-035, each naming a primary department, optional supporting departments and the policy sections on which it rests. The integrity validator rejects any matrix in which an active subcategory has no routing rule or a routing rule names an unknown department (Chapter 10, Section 10.7), and the Knowledge Base build requires section 3 of RTE-RUL-14 to reproduce the routing rules row by row, so the routing policy that agents read and the rules that Python applies are the same table. Two entries, quoted verbatim, show the format:

```yaml
  - {rule_id: RTE-016, subcategory: ACC-UNA, primary_department: DEPT-SEC, supporting_departments: [], policy_refs: ["RTE-RUL-14:3", "SEC-POL-09:4.1"]}
  - {rule_id: RTE-027, subcategory: PRV-BRC, primary_department: DEPT-CMP, supporting_departments: [DEPT-SEC], policy_refs: ["RTE-RUL-14:3", "PRV-POL-08:7.1"]}
```

Nine of the ten departments act as a primary department; Management Escalations (DEPT-MGT) is only ever a supporting department, added by escalation rules and conditional routing. Table 13.1 shows the distribution. **Configured.**

**Table 13.1 — Primary departments in the routing rules**

| Department | Subcategories routed to it as primary | Count |
|---|---|---|
| DEPT-TEC Technical Support | PRD-MAL, ACC-UPD, TEC-CON, TEC-APP, TEC-SET, SVC-OUT | 6 |
| DEPT-BIL Billing Operations | BIL-DUP, BIL-INC, BIL-RFM, BIL-SUB, BIL-CAN | 5 |
| DEPT-CRL Customer Relations | SVC-SUP, SVC-INS, STF-RUD, STF-MIS, STF-MIN | 5 |
| DEPT-RET Returns & Refunds | PRD-DOA, REF-REQ, REF-DLY, REF-PAR | 4 |
| DEPT-LOG Logistics Support | PRD-MIS, DEL-DLY, DEL-LST, DEL-WRG | 4 |
| DEPT-WAR Warranty Services | WAR-CLM, WAR-DEN, WAR-CPL | 3 |
| DEPT-CMP Compliance & Privacy | PRV-BRC, PRV-CON, PRV-DSR | 3 |
| DEPT-SAF Product Safety | SAF-OVH, SAF-ELC, SAF-INJ | 3 |
| DEPT-SEC Account Security | ACC-LGN, ACC-UNA | 2 |
| DEPT-MGT Management Escalations | none (supporting only) | 0 |

Nine routing rules also name a fixed supporting department: RTE-001 (damaged on arrival, Logistics), RTE-006 (refund missing, Returns), RTE-011 (wrong item, Returns), RTE-013 (refund delay, Billing), RTE-022 (installation service, Technical Support), RTE-023 (service outage, Billing), RTE-027 (data exposure, Account Security), RTE-032 (injury, Compliance) and RTE-034 (technician misconduct, Management Escalations). The loader supports a department override on a resolution rule, but none of the 116 resolution rules uses one, so the primary department always comes from the routing rule of the subcategory.

## 13.2 Multi-Department Complaints

A complaint may need more departments than its routing rule names. The decision engine in `backend/src/supportnova/rule_engine/decision.py` therefore assembles the supporting departments from five sources, in this order, adding each department once and never repeating the primary department:

1. the supporting departments of the routing rule;
2. the supporting departments of the selected resolution rule (16 resolution rules add one, for example RES-PRD-MAL-02, a malfunction within 30 days, adds Returns & Refunds);
3. the primary department of each secondary issue found by the rule classifier;
4. the conditional routing rules whose conditions are true (Table 13.2);
5. the departments of every fired escalation rule, with `$primary_department` replaced by the primary department.

**Table 13.2 — Conditional routing rules (RTE-RUL-14 section 4)**

| Rule | Condition | Adds | Policy |
|---|---|---|---|
| RTE-101 | signal `privacy_breach` | DEPT-CMP | RTE-RUL-14:4.2 |
| RTE-102 | signal `legal_threat` | DEPT-CMP | RTE-RUL-14:4.2 |
| RTE-103 | signal `security_breach` | DEPT-SEC | RTE-RUL-14:4.4 |
| RTE-104 | escalation level at least Critical Management Escalation | DEPT-MGT | RTE-RUL-14:4.3 |
| RTE-105 | any of `fire_event`, `overheating`, `electrical_hazard`, `injury` | DEPT-SAF | RTE-RUL-14:4 |
| RTE-106 | secondary issues present | the primary departments of the secondary issues | RTE-RUL-14:4.1 |

RTE-106 is recorded as a routing basis but has no separate effect, because the engine already adds the secondary issues' departments in step 3. Conditional routing never replaces the primary department; it only adds support. Escalation rules contribute in the same way: the injury rule ESC-004, for example, informs Product Safety, Management Escalations and Compliance & Privacy, and the repeat rule ESC-018 informs the primary department and Management Escalations.

Secondary issues come from the rule classifier (Chapter 11, Section 11.2). A candidate is kept as a secondary issue when its score is at least 4.0, when it reaches 35 percent of the primary score or is strong on its own (5.0), and when it belongs to a different category than the primary issue and the secondary issues already kept; at most three are kept. The integration test `tests/backend/integration/test_difficult_cases.py::test_multi_issue_multi_department` submits a complaint about a PowerCell that arrived more than a week late, overheated with a burning smell on first charge and was charged twice, and asserts that the category is SAF by risk-first precedence, that the other issues are kept as secondary issues and that supporting departments are assigned. **Tested.** The case CMP-00616 of Chapter 11 shows the escalation path: DEPT-SEC is the primary department from RTE-016, and DEPT-MGT is supporting because RES-ACC-UNA-03 lists it, because RTE-104 fires at Critical Management Escalation and because escalation rule ESC-010 informs it; the comparison row for the department accordingly names "RTE-016, RTE-104" as its basis.

## 13.3 Which Issue Decides the Primary Department

When a complaint contains several issues, the primary issue, and with it the primary department, is decided by the routing precedence of RTE-RUL-14 section 5, configured in the `routing_precedence` row as `order: [SAF, ACC-UNA, PRV, LEGAL, BIL, PRD, DEL, WAR]`. Safety, account compromise and privacy always win when the classifier finds them with a score of at least 4.0; among the lower groups, billing outranks product, product outranks delivery and delivery outranks warranty, and every other category, including refunds, ranks below them. The comment in the rule file explains the intention that root causes outrank the refund consequences they cause. Applied to the example of SRS Step 13, "Product arrived damaged and refund has not been processed.", the rule classifier scores REF-DLY at 4.5 and PRD-DOA at 4.0, applies the precedence ("PRD-DOA outranks REF-DLY by risk precedence (RTE-RUL-14:5)") and returns PRD-DOA as the primary issue with REF-DLY as the secondary issue, the split the SRS describes. The complaint is then routed to Returns & Refunds, with Logistics Support supporting through RTE-001. Because the winning score of 4.0 gives the classifier only low confidence, such a short complaint also goes to manual review (REV-005). **Implemented.**

As noted in Chapter 10, the `LEGAL` entry of the precedence order is not matched by the classifier, whose candidates carry only category and subcategory codes. A legal threat therefore does not change the primary department; it adds Compliance & Privacy through RTE-102, escalates to Compliance Review through ESC-016 and raises urgency through URG-008.

## 13.4 Routing Checks

Phase A of Pipeline 2 applies two routing checks after SCH-003 has confirmed that every department code in the GenAI answer exists. Figure 13.1 shows the decision.

![Figure 13.1 — Routing decision and routing checks](diagrams/pipelines/fig-13-01-routing-decision.svg)
*Figure 13.1 — Routing decision and routing checks*

**RTE-001 Primary department matches the routing rules** (critical) compares the GenAI primary department with the primary department of the rules decision. When they agree the check passes with the message naming the routing rule, for example "Primary department DEPT-SEC matches routing rule RTE-016." When they differ it fails, stating the rules' department and the subcategory, and cites RTE-RUL-14:3. Because the check is critical, a failure always triggers REV-002 and the case goes to manual review whatever the score.

**RTE-002 Required supporting departments included** (major) compares the supporting departments required by the rules with the departments named by the GenAI answer, counting the GenAI primary department as covered. The check passes when all required departments are named, warns when only some are and fails when none is, citing RTE-RUL-14:4; it does not apply when the rules require no supporting department.

The routing decision is enforced, not only checked. The persistence step of `backend/src/supportnova/services/pipeline.py` sets the complaint's department to the rules' primary department in every case, the escalation record lists the departments of the fired escalation rules, and a submitted complaint is then assigned automatically to the active agent of that department with the fewest open complaints (lab and evaluation runs skip the assignment). A GenAI routing error can therefore delay a case in review but can never send it to the wrong queue, which is how SupportNova meets non-functional requirement 4 for routing. **Implemented, Tested.**

## 13.5 Routing When the Classification Is Uncertain

The rules' department is only as good as the reference subcategory from which it is derived. When the rule classifier is confident, the department follows from its own classification. When it is not, the department follows from the provisional reference of Chapter 11, Section 11.4.1: the GenAI subcategory if it passes the evidence gate, otherwise the rules' best candidate. In both provisional cases trigger REV-005 sends the complaint to manual review, where a reviewer can reclassify it; the pipeline then runs again with the reviewer's subcategory as the reference and derives the department from its routing rule. The holdout case EVL-00030 shows why this matters: the rule classifier's low-confidence candidate STF-MIS would have routed a damaged-on-arrival hub to Customer Relations instead of Returns & Refunds, and the case was held for review with six reasons instead of being acted on.

## 13.6 Measured Routing Accuracy

Table 13.3 shows the routing accuracy of both pipelines on the 152 validated holdout cases of evaluation run #1 (`reports/genai_python_comparison/summary.md`).

**Table 13.3 — Routing accuracy on unseen holdout cases (evaluation run #1)**

| Field | Python (Pipeline 2) | GenAI (Pipeline 1) | GenAI-Python agreement |
|---|---|---|---|
| Primary department | 84.9 % | 92.1 % | 84.9 % |
| Supporting departments (exact set) | 74.3 % | 73.7 % | 61.8 % |

The GenAI model was more accurate on the primary department than the rules, because every rules routing error follows from a classification error, and the rule classifier is the weaker classifier (Chapter 12). The design turns this into a safe outcome. The pipelines disagreed on the primary department in 23 of the 152 cases; the GenAI department matched the label in 17 of them and the rules' department in 6, and all 23 went to manual review through the critical failure of RTE-001. In 6 further cases both pipelines agreed on a department that differs from the label. The GenAI prompt contributes to its own routing accuracy: from prompt version 1.2.0 on, sections 3 to 5 of RTE-RUL-14 are supplied as fixed reference data, after the first live runs showed that retrieval surfaced the routing policy for only 6 percent of complaints and that routing was the most frequent critical mismatch (`prompts/complaint_analysis/1.2.0.yaml`, Chapter 22).

Across all 780 validation results in the demonstration database, RTE-001 passed 699 times and failed 81 times, and RTE-002 passed 146 times, warned 67 times, failed 122 times and did not apply 445 times. Typical recorded failures are the holdout case EVL-00020, where the GenAI answer routed an annual Cloud Vault renewal to Returns & Refunds instead of Billing Operations, and the lab run LAB-00014, where the fault profile `wrong_department` changed the real model's answer for a charge on a cancelled Care+ plan to Logistics Support and RTE-001 failed with the stored message "GenAI routed to DEPT-LOG; the routing rules require DEPT-BIL for BIL-CAN."

**Table 13.4 — Tests of routing validation**

| Test | What it asserts | Status |
|---|---|---|
| `tests/backend/integration/test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[wrong_department-RTE-001]` | A corrupted GenAI department fails RTE-001 and the case goes to Manual Review | Tested |
| `tests/backend/integration/test_difficult_cases.py::test_normal_delayed_delivery` | A late thermostat delivery is classified DEL-DLY and routed to DEPT-LOG | Tested |
| `tests/backend/integration/test_difficult_cases.py::test_multi_issue_multi_department` | Risk-first primary issue, secondary issues kept, supporting departments assigned | Tested |
| `tests/backend/integration/test_difficult_cases.py::test_security_account_takeover` | An account takeover with a remote unlock involves DEPT-SEC as primary or supporting department | Tested |
| `tests/backend/unit/test_perception_security.py::test_risk_precedence_beats_higher_scoring_issue` | A higher-scoring delivery issue loses to a safety issue | Tested |
| `tests/backend/integration/test_defects_and_live_changes.py::test_new_category_without_code_changes` | A subcategory created at runtime is routed by its new routing rule | Tested |
| `tests/backend/unit/test_rule_engine.py::test_rule_matrix_integrity` | Every active subcategory has a routing rule and every department exists | Tested |

## 13.7 Requirement Coverage

**Table 13.5 — SRS routing requirements**

| SRS requirement | How SupportNova meets it | Status |
|---|---|---|
| Step 22: recommend a responsible department | GenAI `department` field; rules' department from RTE-001 to RTE-035 | Implemented, Tested |
| Step 23: Python independently verifies the GenAI department using the Rule Matrix | RTE-001 against the routing rule of the reference subcategory | Implemented, Tested |
| Step 24: primary and supporting departments | Five sources of supporting departments, RTE-002 | Implemented, Tested |
| 1.6 (xx, xxi): department and multi-department routing | Same mechanisms, shown in the comparison rows | Implemented, Tested |
| 1.6 (xlvii): routing comparison | Department and supporting-department comparison rows (Chapter 12) | Implemented |
| NFR 4: critical routing rules enforced before final verification | RTE-001 is critical; the complaint is always routed to the rules' department | Implemented, Tested |
| 1.8 (14): add a routing rule, add a department | Rule edit and taxonomy endpoints (Chapter 10) | Implemented, Tested |
