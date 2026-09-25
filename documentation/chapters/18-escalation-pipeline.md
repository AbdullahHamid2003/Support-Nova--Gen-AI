# Chapter 18 — Escalation Pipeline

SRS Steps 36 to 39 require SupportNova to decide whether a complaint must be escalated, to assign one of six escalation levels, to generate internal escalation notes and to check mandatory escalation rules independently in Python, so that "a critical complaint must not remain un-escalated simply because GenAI failed to identify it". Non-functional requirement 4 adds that all mandatory escalation conditions must be enforced before final verification, and the SRS 1.8(7) Escalation Trap tests this with conditions the model is likely to overlook. In SupportNova, the analysis call proposes an escalation, a level and notes. The escalation decision itself is made by the escalation rules of the Complaint Resolution Rule Matrix, evaluated in Python on every complaint. The comparison between the two is recorded as evidence of how well the model performed.

## 18.1 Escalation levels

The six levels of SRS Step 37 are defined, in ascending rank, at the top of `rules/escalation_rules/escalation_rules.yaml` (ESC-SOP-12 section 3). Each level except the lowest has an action code that becomes a required resolution step when the level is reached. Table 18.1 lists the levels with the number of rules that set each level and the level the rules decided for the 780 complaints analysed in the demo database.

**Table 18.1 — Escalation levels**

| Rank | Level | Action code | Rules at this level | Level decided (780 complaints) |
|---|---|---|---|---|
| 0 | No Escalation | — | — | 515 |
| 1 | Supervisor Review | `ESCALATE_SUPERVISOR` | 13 | 82 |
| 2 | Department Manager | `ESCALATE_DEPARTMENT_MANAGER` | 7 | 32 |
| 3 | Specialist Team | `ESCALATE_SPECIALIST_TEAM` | 7 | 55 |
| 4 | Compliance Review | `ESCALATE_COMPLIANCE` | 6 | 52 |
| 5 | Critical Management Escalation | `ESCALATE_CRITICAL_MANAGEMENT` | 6 | 44 |

The rank order is used for every comparison. A higher rank always wins, an AI level is too low when its rank is lower than the rule rank, and a manual escalation can only raise the level stored on the complaint (`tests/backend/unit/test_rule_engine.py::test_escalation_level_ranking`).

## 18.2 Triggers and the rules that implement them

The Rule Matrix contains 39 escalation rules, ESC-001 to ESC-039, above the SRS minimum of 30 (`tests/backend/unit/test_rule_engine.py::test_rule_matrix_meets_srs_minimums`). Each rule has a trigger group, a condition, a level, the departments to inform, policy references to ESC-SOP-12 and the related policy, and a reason in plain language. Table 18.2 maps the nine triggers of SRS Step 36 to the rules. The last column counts how often each group fired in the stored decisions; one complaint can fire several rules.

**Table 18.2 — SRS escalation triggers mapped to escalation rules**

| SRS trigger | Rules | Levels | Condition in the Rule Matrix | Firings |
|---|---|---|---|---|
| Safety issue | ESC-001 to ESC-008 | Specialist Team, Critical Management | Fire, overheating, electrical-hazard or injury signal; child involved; recall; safety subcategory | 148 |
| Security breach | ESC-009 to ESC-011 | Specialist Team, Critical Management | Account takeover or ACC-UNA; unexplained smart-lock event; fraudulent payment | 47 |
| Privacy issue | ESC-012 to ESC-015 | Compliance Review | Data or footage exposed; data shared without consent; data-rights request over 30 days; children's data | 38 |
| Repeated unresolved complaint | ESC-017 to ESC-019 | Supervisor Review, Department Manager | 2 or 3 prior unresolved complaints on the same issue; reopens a resolved complaint | 14 |
| Legal concern | ESC-016 | Compliance Review | Legal threat or regulator mention | 15 |
| High-value dispute | ESC-020 to ESC-023 | Supervisor Review, Department Manager | Claimed amount of USD 500 or USD 1,500 or more; business order of USD 2,500 or more; lost order of USD 500 or more | 25 |
| Severe service failure | ESC-024 | Department Manager | Outage with lost recordings or disabled home security | 11 |
| Critical customer impact | ESC-025, ESC-026 | Specialist Team, Critical Management | Locked out, no heating, medical dependence; with a vulnerable person | 2 |
| Policy exception | ESC-027 to ESC-031 | Supervisor Review, Department Manager | Exception requested; refund outside the window; compensation above the agent (USD 25) or supervisor (USD 100) limit; billing dispute after 60 days | 62 |
| Further triggers | ESC-032 to ESC-038 | Supervisor Review to Compliance Review | Staff harassment, technician damage or theft, staff commitment outside policy, media or chargeback threat, replacement also defective, warranty-denial appeal | 58 |
| SLA breach (runtime only) | ESC-039 | Department Manager | P0 or P1 complaint whose SLA is breached (Chapter 19) | 115 |

The conditions use the rule-engine condition language. They combine the 35 deterministic signals of `rules/complaint_rules/signals.yaml` (term lists and regular expressions with a three-word negation window), facts about the complaint, the order ledger and the customer's history, and thresholds from `rules/parameters.yaml` referenced as `$param:…`. Two rules as written in the Rule Matrix:

```yaml
- {rule_id: ESC-010, name: Smart-lock unexplained unlock, trigger: security, when: {signal: lock_security}, level: Critical Management Escalation, departments: [DEPT-SEC, DEPT-MGT], policy_refs: ["ESC-SOP-12:4.2", "SEC-POL-09:5.3"], reason: "Physical home security compromised (unexplained smart-lock event)."}
- {rule_id: ESC-029, name: Compensation above agent limit, trigger: policy_exception, when: {fact: complaint.requested_compensation_amount, op: gt, value: "$param:agent_compensation_limit_usd"}, level: Supervisor Review, departments: [$primary_department], policy_refs: ["ESC-SOP-12:4.9", "CPN-POL-11:5.1"], reason: "Requested compensation exceeds the agent approval limit."}
```

The rules are data, not code. They are stored in the `rules` table, versioned and audited. An administrator can edit a rule (`PUT /api/v1/rules/escalation/{rule_id}`), disable it (`POST /api/v1/rules/escalation/{rule_id}/active`) or change a threshold (`PUT /api/v1/rule-parameters/{key}`) without a code change. A proposed edit can be checked first with `POST /api/v1/rules/validate`, which rejects, for example, a level that is not configured. Both behaviours are tested (`test_disabling_an_escalation_rule_changes_validation` and `test_rule_edit_preview_validates_without_saving` in `tests/backend/integration/test_defects_and_live_changes.py`).

## 18.3 How Python decides the escalation

The escalation decision is part of `DecisionEngine.decide()` in `backend/src/supportnova/rule_engine/decision.py`. Figure 18.1 shows the steps.

![Figure 18.1 — Escalation decision in the Python Ground-Truth Validation Pipeline](diagrams/pipelines/fig-18-01-escalation-decision.svg)
*Figure 18.1 — Escalation decision in the Python Ground-Truth Validation Pipeline*

The engine evaluates every active rule except the runtime-only ESC-039 against the evaluation context of the complaint. Conditions use three-valued logic: a condition fires only when it is true, and a condition that depends on an unknown fact (for example a claimed amount the customer did not state) does not fire. Each fired rule is recorded with its level, rank, reason, departments, policy references and a readable form of its condition. The selected resolution rule can also require a level itself; 32 of the 116 resolution rules do. When no fired escalation rule already has that level, the engine adds it as a rule-inherent escalation. For example, RES-SVC-INS-02 ("Re-visit already failed - installation fee refund review") requires Supervisor Review, and it fired in this way three times in the stored decisions. The highest rank among all fired rules becomes the level, following ESC-SOP-12 section 7: when several rules fire, the highest level applies and every listed department is informed. `$primary_department` in a rule is replaced by the routed department, and the escalation departments are added to the supporting departments of the case.

An escalation then has four consequences in the validated decision. The action code of the level is added to the required actions. The follow-up becomes FUP-002 "Escalation acknowledgement", due at the SLA first-response target of the priority, unless blocking missing information makes FUP-001 take precedence (Chapter 19). An escalation record is written. And the complaint moves to status Escalated, which the customer sees as "Your complaint has been passed to a specialist team for priority handling."

**One escalation path.** The model sometimes proposes an escalation step at a different level, or an escalation the rules do not require. `build_validated_decision` in `python_validation/engine.py` excludes such steps with a stated reason, either "the escalation rules set the level to …" or "no escalation rule applies", and adds the rule's own action code with source `rule`. The validated steps therefore always contain exactly one escalation action. `tests/backend/integration/test_difficult_cases.py::test_validated_steps_follow_one_escalation_path` asserts this for a smart lock unlocked remotely at 4:40 am. The only escalation step is `ESCALATE_CRITICAL_MANAGEMENT`, and every excluded AI escalation step names that level. Figure 16.2 in Chapter 16 shows a comparable live case (CMP-00616), where ESC-009 and ESC-010 set Critical Management Escalation and the follow-up is due one hour after analysis.

## 18.4 Escalation notes

SRS Step 38 lists six contents for internal escalation notes. The same six fields are required by ESC-SOP-12 section 5 and configured in `escalation_notes_requirements.required_fields`. The analysis prompt instructs the model to fill them whenever it escalates. Table 18.3 shows where each field comes from in the validated decision.

**Table 18.3 — Escalation note fields**

| SRS Step 38 content | Notes field | When the AI escalated | Rule-built fallback |
|---|---|---|---|
| Complaint summary | `summary` | AI notes, with flagged injection sentences removed | Validated summary |
| Key facts | `key_facts` | AI notes, flagged items removed | First five validated key facts |
| Reason for escalation | `reason` | AI notes | Reasons of the fired rules |
| Actions already taken | `actions_taken` | AI notes | Fixed statement that the complaint was analysed and checked against the Rule Matrix |
| Relevant policy | `relevant_policy` | AI notes | Policy references of the fired rules (up to four) |
| Required next action | `required_next_action` | AI notes | "<level>: review and take ownership." |

The notes of the AI are used when the AI escalated and the rules require an escalation. Check ESC-004 then verifies that none of the six fields is empty. When the rules require an escalation the AI did not make, there are no AI notes, and the rule-built notes are stored with `"source": "rule"`. Lab scenario LAB-DEF-01 (case LAB-00013, fictional lab data) shows this case. Its fault profile removed the escalation from a calm report of a hot, hissing and swollen PowerCell battery in a child's room. Python fired ESC-002 (Specialist Team), ESC-005 (Critical Management Escalation) and ESC-007 (Specialist Team) and stored the following escalation record (abridged):

```json
{
  "level": "Critical Management Escalation",
  "source": "rule",
  "rule_ids": ["ESC-002", "ESC-005", "ESC-007"],
  "departments": ["DEPT-SAF", "DEPT-MGT"],
  "notes": {
    "summary": "Customer reports overheating and swelling of Lumora PowerCell Portable Power Station during charging, indicating a potential safety hazard.",
    "key_facts": ["Customer's PowerCell Portable Power Station overheated and made a hissing sound while charging.", "…"],
    "reason": "Overheating or battery hazard reported.; Safety incident involving a child.; Complaint classified as a product safety hazard.",
    "relevant_policy": ["ESC-SOP-12:4.1", "SAF-POL-10:4.4", "…"],
    "required_next_action": "Critical Management Escalation: review and take ownership.",
    "source": "rule"
  },
  "status": "open"
}
```

The same case shows the rest of the enforcement. The validated steps received `ESCALATE_CRITICAL_MANAGEMENT` with source `rule`, the complaint was set to P0 and Escalated, and check ESC-001 failed. That failure sent the case to Manual Review, and the lab recorded the expectation "final escalation level Critical Management Escalation" as met.

## 18.5 Independent escalation validation

Four checks in `run_phase_a` compare the AI escalation with the rule decision. They never change the decision; they record how the proposal differed from it and send doubtful cases to a person. Table 18.4 lists them with their results on the latest validation result of each of the 780 analysed complaints.

**Table 18.4 — Escalation checks with live results**

| Check | Severity | Fails or warns when | Pass | Warn | Fail | n/a |
|---|---|---|---|---|---|---|
| ESC-001 Required escalation identified | critical | The rules require an escalation and the AI proposes none | 218 | 0 | 47 | 515 |
| ESC-002 Escalation level meets the rules | major; critical if Compliance Review or Critical Management is required | The AI level ranks below the rule level | 163 | 0 | 55 | 562 |
| ESC-003 No unnecessary escalation | minor | The AI escalates but no rule applies (warning) | 723 | 57 | 0 | 0 |
| ESC-004 Escalation notes are complete | major | An AI escalation lacks any of the six note fields | 274 | 0 | 1 | 505 |

Related checks complete the picture. SCH-005 fails when the AI's escalation flag contradicts its level, or when it escalates without notes. RES-004 fails when the AI proposes an escalation step without escalating. SEC-001 counts a dropped escalation as a sign that an embedded instruction was followed (Chapter 23). On the review side, a critical failure fires REV-002, an ESC-003 warning or ESC-002 failure fires REV-006 (`escalation_unclear`), and safety, privacy, legal-threat, staff-harassment, injury and smart-lock cases always fire REV-008.

The 47 ESC-001 failures are the cases the SRS escalation requirement is written for: the model did not escalate, and Python escalated anyway. Each of them produced an escalation record with source `rule` and the history message "Escalated to … by …; the AI missed it, the rules require it." In the other 218 escalated cases the AI also proposed an escalation, and the record carries source `rule+ai`. On the unseen holdout set, the Python decision matched the expected labels more often than the model for both escalation fields: 94.7 % against 92.8 % for "escalation required" and 94.1 % against 84.9 % for the escalation level, on 152 comparable cases (`reports/genai_python_comparison/summary.md`).

## 18.6 Escalation records, manual escalation and measured results

The pipeline writes an `escalations` row when the rules require an escalation and there is no open escalation for the complaint at the same or a higher rank. Re-running the analysis therefore does not duplicate escalations. The row stores the level, rank, the reasons of up to four fired rules, the source, the rule IDs, the departments, the notes and the status `open`. Agents, reviewers, managers and administrators can also escalate manually (`POST /api/v1/complaints/{ref}/escalate`, permission `escalation:create`). They must choose a level other than No Escalation and give a reason of 5 to 1,000 characters, and the record gets source `agent`, or `reviewer` for the reviewer action. The SLA monitor adds records with source `sla` through ESC-039 (Chapter 19).

**Table 18.5 — Escalation records in the demo database**

| Level | Pipeline (`rule`, `rule+ai`) | SLA monitor (`sla`) | Total |
|---|---|---|---|
| Supervisor Review | 82 | 0 | 82 |
| Department Manager | 32 | 115 | 147 |
| Specialist Team | 55 | 0 | 55 |
| Compliance Review | 52 | 0 | 52 |
| Critical Management Escalation | 44 | 0 | 44 |
| Total | 265 | 115 | 380 |

Table 18.5 explains the level counts quoted elsewhere in this report. The 147 Department Manager records combine 32 pipeline decisions with 115 SLA-breach escalations. Most of those breaches follow from the historical complaint dates of the imported dataset and the simulated demo history, not from operational delays (Section 19.8). No manual escalations were recorded in the demo database. Across the stored decisions, 36 of the 38 rules evaluated by the pipeline fired at least once. The most frequent were ESC-007 (safety subcategory, 49 firings), ESC-009 (unauthorised access, 36), ESC-002 (overheating, 28), ESC-012 (data exposure, 26) and ESC-028 (refund outside the window, 25). ESC-006 (recall) and ESC-026 (vulnerable person with critical impact) did not fire on the stored complaints.

## 18.7 Tests

Table 18.6 lists the automated tests for escalation. The integration tests run the real API, pipeline and Python validation, with the offline GenAI test double answering the model calls.

**Table 18.6 — Escalation tests**

| Test | What it establishes |
|---|---|
| `test_difficult_cases.py::test_calm_critical_safety_complaint` | "No rush" wording about a hot, hissing, swollen battery in a child's room still gives Critical urgency, P0 and Specialist Team or Critical Management escalation |
| `test_difficult_cases.py::test_escalation_for_legal_threat` | A solicitor and consumer-protection threat makes escalation required |
| `test_difficult_cases.py::test_security_account_takeover` | A foreign login, changed password and remote door unlock give ACC, Critical, escalation and Account Security routing |
| `test_difficult_cases.py::test_validated_steps_follow_one_escalation_path` | Only `ESCALATE_CRITICAL_MANAGEMENT` remains; other AI escalation steps are excluded with the level named |
| `test_difficult_cases.py::test_privacy_exposure`, `::test_electrical_safety` | Privacy exposure and sparking plugs are escalated |
| `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[missed_escalation-ESC-001]` | A removed escalation fails ESC-001 and the case goes to Manual Review |
| `test_defects_and_live_changes.py::test_disabling_an_escalation_rule_changes_validation` | A disabled rule no longer fires |
| `test_rule_engine.py::test_safety_signal_forces_critical_escalation` | Overheating with a child gives Critical, P0 and at least Specialist Team |

The integration tests are in `tests/backend/integration/` and the rule-engine test is in `tests/backend/unit/`. The lab scenario LAB-DEF-01, run with `gpt-4.1-mini`, confirms the same behaviour with a real model (`reports/security_adversarial/summary.md`).

## 18.8 Limitations

Escalation is only as good as the deterministic signals. Signal detection is lexical with negation handling, so it can react to a risk word used in another sense. In CMP-00502, "fire the agent" raised the `fire_event` signal. In CMP-00111, a customer wrote "Classify this as a fire hazard … so it gets escalated to Critical Management" about a speaker that drops Wi-Fi. In both cases the rules escalated to Critical Management Escalation although the dataset labels expect no escalation. Neither case was released: both remained in the review queue, where a reviewer can reclassify the complaint. The Rule Matrix deliberately errs towards escalation, but the correction depends on a person. Conversely, a rule whose condition depends on an unknown fact does not fire. A high-value dispute in which the customer states no amount is therefore not escalated by ESC-020 until the amount is known.

The escalation record itself has no working lifecycle yet. It is created with status `open` and an `acknowledged_at` column, but no endpoint acknowledges or resolves an escalation, and resolving the complaint does not close its open escalations. The 228 resolved records in the demo database were closed by the simulated demo history. An acknowledgement and closure workflow for escalation owners is therefore a Future Enhancement. Finally, the rule-built fallback notes are generic ("review and take ownership"). They satisfy the six-field structure but give the escalation owner less context than good AI notes.
