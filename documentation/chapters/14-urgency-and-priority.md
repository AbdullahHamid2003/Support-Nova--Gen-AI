# Chapter 14 — Urgency and Priority

A complaint written in capital letters with three exclamation marks is not necessarily urgent, and a polite note that ends "no rush at all" may describe a fire hazard. The SRS makes this distinction a core requirement: urgency "must not be based solely on emotional wording" (Step 19), priority rules "must be configurable" (Step 20), the application must handle the tricky priority cases of Step 21, and the "sentiment-urgency trap" of SRS 1.8 (6) must show that urgency is not determined only by sentiment. SupportNova separates sentiment, urgency, impact, priority and business risk into different values, computes urgency and priority only from the Complaint Resolution Rule Matrix, and checks the GenAI proposal against them with checks PRI-001 to PRI-004.

## 14.1 Sentiment, Urgency, Priority and Business Risk

Table 14.1 defines the concepts as SupportNova implements them.

**Table 14.1 — Separate concepts in the urgency and priority model**

| Concept | Values | Determined by | Effect |
|---|---|---|---|
| Sentiment | Positive, Neutral, Negative, Strongly Negative | GenAI answer; Python lexicon estimate from `signals.yaml` | Informational only; check CLS-004 has weight 0 |
| Emotion indicators | For example Frustration, Anger, Confusion | GenAI answer | Informational only (SRS Step 18) |
| Business risk | 35 signals and facts such as amounts and repeat history | Python perception, order ledger, complaint history | Urgency floors, escalation rules, conditional routing |
| Urgency | Low, Medium, High, Critical | Selected resolution rule, raised by urgency floors | Priority; check PRI-001 |
| Impact | Low, Medium, High | Selected resolution rule, raised by urgency floors | Priority |
| Priority | P3 Low, P2 Medium, P1 High, P0 Critical | Priority matrix: urgency × impact | SLA targets and queue order; check PRI-002 |
| Customer type | Individual, Care+ member, Business, VIP | Complaint and customer record | Entitlements only; never urgency or priority by status (URG-101) |

Sentiment reaches the system twice, as the GenAI value and as the Python lexicon estimate, and neither can raise urgency or priority. No urgency floor and no resolution rule condition refers to sentiment or emotion, and the VIP customer type appears in no rule condition at all. Customer type enters the rules only as an entitlement fact: Care+ membership decides the 45-day refund window, the restocking-fee exemption and the Care+ claim rules (six resolution rules test `customer.is_care_plus`), and a business account with an order of USD 2,500 or more requires a Department Manager review through escalation rule ESC-022. These conditions change which rule applies because the customer is entitled to something different, not because of the customer's status.

## 14.2 Base Urgency and Impact from the Resolution Rule

Every resolution rule fixes an urgency and an impact for the situation it describes, and the priority follows from them. Across the 116 resolution rules the urgency is Critical for 17 rules, High for 19, Medium for 58 and Low for 22, which gives P0 for 17 rules, P1 for 4, P2 for 59 and P3 for 36. The default rules of the subcategories express the ordinary urgency of an issue: an app problem (RES-TEC-APP-01) is Low with Low impact and therefore P3, a delayed delivery (RES-DEL-DLY-01) is High with Medium impact and P2, and an overheating product (RES-SAF-OVH-01) or a privacy incident (RES-PRV-BRC-01) is Critical with High impact and P0. More specific rules adjust the base: a Cloud Vault outage of more than 24 hours (RES-SVC-OUT-02) is High with High impact, P1, while a short outage (RES-SVC-OUT-03) is Medium, P2.

## 14.3 Urgency Floors from Risk Signals and Facts

After the resolution rule, the decision engine applies the 15 urgency floors of `rules/complaint_rules/priority_rules.yaml` to every complaint, whatever its subcategory. A floor whose condition is true raises urgency and impact to its own values if they are higher and never lowers them, and the trace records each floor that changed the outcome. Table 14.2 lists the floors.

**Table 14.2 — Urgency floors**

| Rule | Condition | Urgency | Impact | Policy |
|---|---|---|---|---|
| URG-001 | signal `fire_event` | Critical | High | SLA-RUL-15:5.1, SAF-POL-10:3 |
| URG-002 | signal `overheating` | Critical | High | SLA-RUL-15:5.1, SAF-POL-10:3 |
| URG-003 | signal `electrical_hazard` | Critical | High | SLA-RUL-15:5.1, SAF-POL-10:3 |
| URG-004 | signal `injury` | Critical | High | SLA-RUL-15:5.1 |
| URG-005 | signal `security_breach` | Critical | High | SLA-RUL-15:5.1, SEC-POL-09:4.3 |
| URG-006 | signal `lock_security` | Critical | High | SLA-RUL-15:5.1, SEC-POL-09:5.1 |
| URG-007 | signal `privacy_breach` | High | High | SLA-RUL-15:5.2, PRV-POL-08:7.1 |
| URG-008 | signal `legal_threat` | High | Medium | SLA-RUL-15:5.2, CMP-GDL-19:3 |
| URG-009 | signal `critical_impact` | High | High | SLA-RUL-15:5.2, ESC-SOP-12:4.8 |
| URG-010 | signals `vulnerable_customer` and `critical_impact` | Critical | High | ESC-SOP-12:4.8, CMP-GDL-19:5.2 |
| URG-011 | at least 2 unresolved prior complaints on the same issue | High | Medium | SLA-RUL-15:5.2, ESC-SOP-12:4.5 |
| URG-012 | amount of at least USD 500 | (unchanged) | High | SLA-RUL-15:6 |
| URG-013 | signal `severe_service_failure` | High | High | SLA-RUL-15:5.2, ESC-SOP-12:4.7 |
| URG-014 | signal `fraud` | High | High | SLA-RUL-15:5.2, ESC-SOP-12:4.2 |
| URG-015 | signal `staff_harassment` | High | Medium | ESC-SOP-12:4.10 |

The thresholds of URG-011 and URG-012 are the parameters `repeat_supervisor_threshold` (2) and `high_value_supervisor_usd` (USD 500), both traced to ESC-SOP-12, so the floors change when the parameters change. Because the floors are evaluated independently of the subcategory, a delivery complaint that mentions smoke is raised to Critical by URG-001 even though its delivery rule is only High, and the same signal also fires escalation rule ESC-001 and conditional routing rule RTE-105, which adds Product Safety. The file records three principles that the validator enforces, quoted here verbatim:

```yaml
principles:
  - {rule_id: URG-100, name: Sentiment neutrality, description: "Sentiment and emotion indicators never raise urgency or priority. An AI urgency above the rule urgency with no risk signal is flagged as 'urgency inflated by emotional language'.", policy_refs: ["CHP-POL-01:5.2", "SLA-RUL-15:5.4"]}
  - {rule_id: URG-101, name: Customer-type neutrality, description: "Customer type (including VIP) never changes urgency or priority.", policy_refs: ["SLA-RUL-15:5.4"]}
  - {rule_id: URG-102, name: Calm critical complaints, description: "Risk signals set urgency floors regardless of calm wording; an AI urgency below the floor is a critical validation failure.", policy_refs: ["CHP-POL-01:5.2", "SLA-RUL-15:5.1"]}
```

Signals are detected in the text by phrases and patterns with negation handling (Chapter 11, Section 11.2). The unit test `tests/backend/unit/test_perception_security.py::test_calm_safety_complaint_detects_risk` asserts that "No rush at all. My PowerCell got very hot and made a hissing sound while charging in my son's room, and the case looks swollen." raises both `overheating` and `child_involved`, and `test_negation_suppresses_signal` asserts that "There was no smoke and no fire" raises no fire signal. **Tested.**

## 14.4 Priority Matrix and Service Levels

The priority is looked up in the priority matrix of the `priority_config` configuration row, which reproduces SLA-RUL-15 section 4 (Table 14.3). Changing the priority logic is an edit of this matrix and needs no code change (SRS Step 20); the integrity validator rejects a matrix with a missing or invalid cell. The unit test `tests/backend/unit/test_rule_engine.py::test_priority_matrix` checks eight cells. **Configured, Tested.**

**Table 14.3 — Priority matrix (urgency × impact, SLA-RUL-15:4)**

| Urgency | High impact | Medium impact | Low impact |
|---|---|---|---|
| Critical | P0 | P0 | P1 |
| High | P1 | P2 | P2 |
| Medium | P2 | P2 | P3 |
| Low | P2 | P3 | P3 |

The priority selects the service-level targets of `rules/sla_rules/sla_rules.yaml` (Table 14.4), which the SLA monitor tracks from submission in calendar hours; a complaint is flagged At Risk when 75 percent of a window has elapsed (`sla_at_risk_pct`), and a breach on P0 or P1 triggers escalation rule ESC-039 (Chapter 19).

**Table 14.4 — Service-level targets by priority**

| Rule | Priority | First response | Resolution | Policy |
|---|---|---|---|---|
| SLA-P0 | P0 | 1 hour | 24 hours | SLA-RUL-15:3.1 |
| SLA-P1 | P1 | 4 hours | 48 hours | SLA-RUL-15:3.2 |
| SLA-P2 | P2 | 24 hours | 120 hours | SLA-RUL-15:3.3 |
| SLA-P3 | P3 | 48 hours | 240 hours | SLA-RUL-15:3.4 |

## 14.5 Urgency and Priority Checks

Figure 14.1 shows how the rules' urgency and priority are formed and how the GenAI proposal is checked against them.

![Figure 14.1 — Urgency and priority decision and checks](diagrams/pipelines/fig-14-01-urgency-decision.svg)
*Figure 14.1 — Urgency and priority decision and checks*

**PRI-001 Urgency matches the rules** (critical) compares the GenAI urgency with the rules' urgency. An equal value passes and names the rules that set it. A lower GenAI urgency fails, with critical severity when the rules require High or Critical and major severity otherwise, and the message adds "Calm wording does not reduce risk." A higher GenAI urgency warns. **PRI-002 Priority matches the priority matrix** (major) fails when the GenAI priority is less severe than the matrix value and warns when it is more severe. **PRI-003 Urgency not inflated by emotional language** (minor) warns when the GenAI urgency is above the rules' urgency while the lexicon sentiment is Negative or Strongly Negative and no risk signal is present, citing URG-100. **PRI-004 AI priority fits its urgency and impact** (minor) warns when the GenAI priority does not follow from the GenAI's own urgency and impact. The rules' urgency and priority are the values stored on the complaint and used for the SLA, whatever the checks find.

The checks catch errors in both directions. In the 780 validation results of the demonstration database, PRI-001 passed 511 times, warned 172 times because the GenAI urgency was higher than the rules, and failed 97 times because it was lower; PRI-002 passed 470 times, warned 258 times and failed 52 times; PRI-003 warned 25 times. On the 152 validated holdout cases the rules' urgency matched the label in 84.2 percent of cases against 68.4 percent for the GenAI model, and the rules' priority in 88.8 percent against 62.5 percent. Of the 51 urgency disagreements, the rules matched the label in 37, the GenAI model in 13 and neither in 1; 43 of these cases went to manual review, and the other 8 were cases in which the GenAI urgency was one level too high, which PRI-001 only warns about, and in which the rules were right (Chapter 12).

## 14.6 Difficult Cases

SRS Step 21 lists six tricky priority cases. Table 14.5 shows the Rule Matrix mechanism that handles each of them, the automated tests that cover it and the recorded evidence.

**Table 14.5 — The tricky priority cases of SRS Step 21**

| Case | Mechanism in the Rule Matrix | Automated tests | Recorded evidence |
|---|---|---|---|
| Terribly angry complaint with low business risk | No floor fires without a risk signal; sentiment is not an input; PRI-003 flags inflated AI urgency (URG-100) | `test_difficult_cases.py::test_angry_low_priority_complaint`, `test_rule_engine.py::test_emotional_language_does_not_raise_priority`, `test_perception_security.py::test_sentiment_is_informational` | Holdout, 9 emotional low-priority cases: rules all key fields right in 6, GenAI in 2; EVL-00027 rude staff complaint, Low and P3 in both pipelines, Verified 95.9 |
| Calmly written complaint involving a safety issue | Signals `overheating`, `electrical_hazard`, `fire_event` set Critical and High (URG-001 to URG-003) and fire ESC-001 to ESC-003; a lower AI urgency is a critical failure (URG-102) | `test_difficult_cases.py::test_calm_critical_safety_complaint`, `test_difficult_cases.py::test_electrical_safety`, `test_perception_security.py::test_calm_safety_complaint_detects_risk`, `test_rule_engine.py::test_safety_signal_forces_critical_escalation` | Rule simulator, "no rush at all" smart plug with sparks, P0 (Figure 10.4); lab run LAB-00015 with fault profile `urgency_downgrade`, PRI-001 fail |
| VIP customer with a minor issue | Customer type appears in no urgency floor and no rule condition (URG-101) | `test_difficult_cases.py::test_angry_low_priority_complaint` (VIP customer), `test_rule_engine.py::test_emotional_language_does_not_raise_priority` (VIP customer) | Holdout VIP case EVL-00116: Low urgency in both pipelines |
| Low-value transaction involving a privacy breach | Privacy rules RES-PRV-BRC-01 to -03 are Critical and High, P0; URG-007 raises any `privacy_breach` to High and High; no condition depends on the amount; ESC-012 Compliance Review; RTE-101 adds Compliance; REV-008 requires a person | `test_difficult_cases.py::test_privacy_exposure` | Holdout EVL-00010: AI High, rules Critical, PRI-001 critical fail |
| Complaint containing legal-threat language | URG-008 raises to High and Medium; ESC-016 Compliance Review; RTE-102 adds Compliance; REV-008 requires a person | `test_difficult_cases.py::test_escalation_for_legal_threat`, `test_defects_and_live_changes.py::test_disabling_an_escalation_rule_changes_validation` | Dataset: 12 development cases tagged `legal_threat` |
| Repeated complaint after failed resolution | History facts; URG-011 raises to High at 2 unresolved prior complaints; ESC-017 (2 prior, Supervisor Review), ESC-018 (3 or more, Department Manager), ESC-019 (reopened resolved complaint, Supervisor Review) | `test_difficult_cases.py::test_repeated_complaint_detected` | Holdout: 4 of 4 repeats detected; lab run LAB-00017, ESC-017 enforced after the AI missed it |

The automated tests in `tests/backend/integration/test_difficult_cases.py` submit each complaint through the public API and run the real Python validation, with GenAI calls answered by the offline test double (Chapter 11, Section 11.7). `test_angry_low_priority_complaint` submits "This is absolutely RIDICULOUS!!! The dark mode in the Lumora app looks awful and I am FURIOUS. Fix it NOW, I am a VIP customer!!!" from a VIP customer and asserts that the priority is P2 or P3, the urgency Low or Medium and the sentiment Negative or Strongly Negative, the assertion message stating that emotion and VIP status never raise priority (SLA-RUL-15 5.4). `test_calm_critical_safety_complaint` submits the calm PowerCell complaint quoted in Section 14.3 and asserts Critical urgency, P0, a required escalation at Critical Management Escalation or Specialist Team level, category SAF and the safety flag. `test_privacy_exposure` asserts category PRV, a required escalation and Manual Review, "privacy cases always need a human (REV-008)". **Tested.**

The dataset contains these cases in quantity: among the 617 development complaints, 38 are tagged as emotional low-priority complaints, 70 as calm but critical, 23 as VIP complaints with a minor issue, 5 as low-value privacy complaints and 12 as legal threats, and 5, 1 and 3 complaints exercise ESC-017, ESC-018 and ESC-019 respectively (`data/dataset_summary.json`).

## 14.7 Requirement Coverage

**Table 14.6 — SRS requirements for urgency and priority**

| SRS requirement | How SupportNova meets it | Status |
|---|---|---|
| Step 17: sentiment classification | GenAI sentiment and lexicon estimate, four values | Implemented |
| Step 18: emotion indicators do not replace objective priority rules | Indicators are informational; no rule uses them | Implemented |
| Step 19: urgency Low to Critical, not based solely on emotional wording | Resolution rule urgency, 15 urgency floors, URG-100, PRI-001, PRI-003 | Implemented, Tested |
| Step 20: priority P0 to P3, configurable | Priority matrix in the `priority_config` row | Configured, Tested |
| Step 21: tricky priority cases | Table 14.5 | Implemented, Tested |
| 1.6 (xviii, xix, xlviii): urgency, priority and urgency comparison | Rules decision, PRI checks, urgency and priority comparison rows | Implemented, Tested |
| 1.8 (6): sentiment-urgency trap | `test_angry_low_priority_complaint`, `test_calm_critical_safety_complaint` | Tested |
| 1.8 (14): change priority logic, modify an SLA | Edit of the priority matrix or of the SLA rules (Chapter 10) | Configured |
