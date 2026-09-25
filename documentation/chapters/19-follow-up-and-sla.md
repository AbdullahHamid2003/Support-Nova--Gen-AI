# Chapter 19 — Follow-up and SLA

This chapter covers four SRS steps. Step 40 asks for follow-up communication of six named kinds, Step 41 for a record of when a complaint needs follow-up, Step 55 for configurable response and resolution targets, and Step 56 for flagging complaints that approach their deadlines (functional requirements xxxvii, xxxviii, lix and lx). In SupportNova the follow-up and the service level are both derived from the validated decision of the Python Ground-Truth Validation Pipeline, not from the AI proposal. They are stored as records with due times, and a background monitor keeps the SLA state current. This chapter describes the rules, the records, the monitor and the measured state of the demo database.

## 19.1 Follow-up types and rules

The six follow-up types of SRS Step 40 are configured in `rules/complaint_rules/followup_rules.yaml` (`follow_up_types`): request for additional information, resolution confirmation, refund-status update, replacement-status update, escalation acknowledgement and closure confirmation. The same list constrains the `follow_up_type` field of the analysis schema, so the model can only propose one of these types. Each of the 116 resolution rules states whether a follow-up is required and, if so, its type and due time. For example, RES-PRD-DOA-02 (damaged on arrival, reported within 7 days with evidence) requires a replacement-status update within 72 hours. Four global follow-up rules decide which follow-up applies. They are listed in Table 19.1.

**Table 19.1 — Follow-up rules**

| Rule | Applies when | Type | Due | Implemented in |
|---|---|---|---|---|
| FUP-001 | Blocking information is missing | Request for additional information | 24 h | `DecisionEngine.decide`, first precedence |
| FUP-002 | Any escalation is required | Escalation acknowledgement | SLA first-response target | `DecisionEngine.decide`, second precedence |
| FUP-004 | The selected resolution rule requires a follow-up | From the rule | From the rule | `DecisionEngine.decide`, third precedence |
| FUP-003 | The complaint is moved to Resolved | Closure confirmation | 48 h | `transition()` in `services/complaints.py` |

The decision engine in `backend/src/supportnova/rule_engine/decision.py` applies the precedence of Table 19.1 in code. It reads the type and due time of FUP-001 and FUP-002 from the Rule Matrix, so an administrator can change them as data. The FUP-002 due time `sla_first_response` resolves to the first-response target of the complaint's priority: one hour for P0, four for P1, 24 for P2 and 48 for P3. The `when` conditions of the four rows document this precedence but are not evaluated by the condition engine. The closure confirmation of FUP-003 is created with fixed values (48 hours, source FUP-003) in the Resolved transition. The values match the YAML row, but adding a new global follow-up rule would require a code change. The follow-up types and due times are therefore **Configured**, while the precedence itself is **Implemented** in code.

## 19.2 Follow-up records and the follow-up message

At the end of the pipeline, `services/pipeline.py` writes a `follow_ups` row whenever the validated decision requires a follow-up with a due time. The row holds the type, a message, the due time (analysis completion plus the due hours), the status `scheduled` and the source rule, which is FUP-001, FUP-002 or the ID of the resolution rule. The message is the `follow_up_message` written by the customer-communication call (Chapter 16), checked by RSP-007 for promises, prohibited statements and unsupported timelines. If the call returned no message, a default text "<type> for <complaint reference>." is stored. Staff see the follow-ups with their due times and source rules in the Escalation & SLA tab of the case. Customers see only the type, due date and status of scheduled or sent follow-ups, not the internal message.

The AI's own proposal (`follow_up_required`, `follow_up_type`) never creates a record. It is only compared with the rules. FUP-001 fails when the rules require a follow-up the AI omits and warns when the AI adds one the rules do not need; FUP-002 warns when the type differs. On the 780 analysed complaints, FUP-001 passed 742 times, warned 32 times and failed 6 times. FUP-002 warned on 422 of the 741 cases where both sides required a follow-up. The follow-up type is the model's weakest field: on the unseen holdout set it matched the expected type in 44.1 % of cases, against 75.7 % for the Python decision (`reports/genai_python_comparison/summary.md`). Because the record always follows the rules, this weakness lowers the verification score but does not change the follow-up that is scheduled.

A follow-up is completed by `POST /api/v1/complaints/{ref}/follow-ups/{follow_up_id}/complete` (permission `complaint:update`). The call sets the status `completed` and the completion time and writes a history event and an audit entry. As for responses, delivery is simulated: SupportNova records the follow-up but does not send it through an external channel, and nothing is sent automatically when a follow-up falls due.

**Table 19.2 — Follow-up records in the demo database**

| Type | Records | Source rule |
|---|---|---|
| Escalation acknowledgement | 243 | FUP-002 |
| Resolution confirmation | 238 | Resolution rules |
| Request for additional information | 158 | FUP-001 (150), resolution rules (8) |
| Refund-status update | 79 | Resolution rules |
| Replacement-status update | 29 | Resolution rules |
| Closure confirmation | 0 | FUP-003 |

The demo database holds 747 follow-up records for 747 of the 780 analysed complaints; the other 33 needed none. Of these records, 334 are scheduled and 413 completed. All 413 completions were set by the simulated lifecycle of the demo data; the audit log contains no `follow_up.completed` entry from a user. No closure confirmation exists because the simulated history resolves complaints directly, without the Resolved transition that schedules FUP-003. The end-to-end test resolves its complaint through that transition.

## 19.3 SLA rules

The service-level targets required by SRS Step 55 are the four SLA rules in `rules/sla_rules/sla_rules.yaml`, taken from SLA-RUL-15 version 2.0 and shown in Table 19.3.

**Table 19.3 — SLA rules**

| Rule | Priority | First response | Resolution | Policy |
|---|---|---|---|---|
| SLA-P0 | P0 | 1 h | 24 h | SLA-RUL-15:3.1 |
| SLA-P1 | P1 | 4 h | 48 h | SLA-RUL-15:3.2 |
| SLA-P2 | P2 | 24 h | 120 h | SLA-RUL-15:3.3 |
| SLA-P3 | P3 | 48 h | 240 h | SLA-RUL-15:3.4 |

The at-risk threshold is the parameter `sla_at_risk_pct` in `rules/parameters.yaml`: 75 % of the window, from SLA-RUL-15 section 7.1. The clocks run in calendar hours from submission. The targets are Rule Matrix rows of type `sla` and the threshold is a rule parameter, so both can be changed at runtime (`PUT /api/v1/rules/sla/{rule_id}`, `PUT /api/v1/rule-parameters/sla_at_risk_pct`, permission `rules:manage`). Each change is versioned and audited like any other rule change. The SLA follows the validated priority, which the Rule Matrix derives from the priority matrix (urgency × impact) and the urgency floors. A model that under-rates a complaint therefore cannot give it a longer SLA.

## 19.4 SLA records, due dates and states

`ensure_sla()` in `services/sla.py` runs at the end of the pipeline and keeps one `sla_records` row per complaint. The row stores the priority, the SLA rule, the start (the complaint's submission time) and the first-response and resolution due times. If a later re-analysis changes the priority, both due times are recomputed from the original start. The first response is recorded when the first draft is sent (Chapter 16), and the resolution when the complaint is moved to Resolved. The function `_state()` evaluates each clock with the rules of Table 19.4.

**Table 19.4 — SLA state evaluation for one clock**

| Situation | State |
|---|---|
| Recorded at or before the due time | Met |
| Recorded after the due time, or not recorded and the due time has passed | Breached |
| Not recorded, and at least 75 % of the window has elapsed | At Risk |
| Otherwise | On Track |

The first-response and resolution clocks are evaluated separately (`response_state`, `resolution_state`). The resolution state is copied to the complaint as `sla_state`, which the complaint list, filters and dashboards use. The first time a record becomes At Risk or Breached, the time is stored in `at_risk_flagged_at` or `breached_at`. Figure 19.1 shows the resulting lifecycle.

![Figure 19.1 — SLA state lifecycle](diagrams/uml/fig-19-01-sla-lifecycle.svg)
*Figure 19.1 — SLA state lifecycle*

## 19.5 SLA monitor and SLA-based escalation

The SLA monitor is a background thread (`sla-monitor`) that the application starts at launch (`services/worker.py`, started from the lifespan handler in `main.py`). It wakes every `SLA_MONITOR_INTERVAL_SECONDS` seconds (default 60, minimum 10) and calls `refresh_all()`. The function re-evaluates the SLA record of every open operational complaint: sources web, API and dataset, in any status from New to Reopened other than Resolved and Closed. When the resolution state changes to At Risk or Breached, it writes the history event `sla.at_risk` or `sla.breached` with the actor "SLA monitor".

The monitor also enforces the one SLA-based escalation rule, ESC-039. When the resolution clock of a P0 or P1 complaint is Breached and the record has not been escalated yet, the monitor creates an escalation at Department Manager level with source `sla`. It informs the routed department and Management Escalations, sets `breach_escalated` so that this happens only once, raises the complaint's escalation level if the new level is higher, and writes the audit entry `complaint.sla_breach_escalated`. An At Risk state is flagged and visible, but it does not escalate. A breach of a P2 or P3 complaint is recorded but not escalated, because ESC-039 is limited to P0 and P1 (ESC-SOP-12 section 4.11). Evaluation and lab complaints are excluded from the monitor so that test runs do not raise operational escalations; their SLA records are evaluated once at the end of their pipeline run.

The SLA state is visible in several places. The Escalation & SLA tab shows the state badge and progress bars for both clocks with their due times, and the case header shows how long a breached complaint is overdue (Figure 16.2 shows "Breached, overdue by 2d 19h"). The complaint list can be filtered by SLA state. The agent dashboard counts At Risk and Breached cases in the agent's own queue, and the manager and administrator dashboards show SLA states by priority, also available from `GET /api/v1/analytics/sla`. The SLA status report is exported to `reports/operations/sla-status.pdf` and `.xlsx`.

## 19.6 Repeat unresolved complaints and the SLA

Repeat complaints affect the SLA through the priority. When a customer has two or more unresolved earlier complaints on the same issue, the urgency floor URG-011 raises the urgency to High with Medium impact, which the priority matrix maps to P2. ESC-017 adds Supervisor Review, and ESC-018 adds Department Manager at three unresolved complaints. A complaint that reopens a resolved one fires ESC-019. Because the SLA record takes the validated priority, a repeat complaint also receives the shorter targets of that priority. Chapter 20 describes how repeats are detected.

## 19.7 Measured state and its interpretation

Table 19.5 shows the SLA state of the 780 records in the demo database. The records are split by priority into 123 P0, 29 P1, 393 P2 and 235 P3.

**Table 19.5 — SLA states in the demo database**

| State | Resolution clock | First-response clock |
|---|---|---|
| Met | 366 | 333 |
| Breached | 358 | 425 |
| At Risk | 18 | 3 |
| On Track | 38 | 19 |
| Total | 780 | 780 |

These figures show that the mechanism works on realistic data, but they are not a measurement of operational SLA performance. The imported dataset complaints carry their historical complaint dates (4 May to 21 September 2026) as submission times. Their first responses and resolutions were placed on the timeline by the simulated demo history, and the evaluation cases keep the dates of their dataset records. Many clocks were therefore already past their due time when the complaint was first analysed. This is also why the monitor recorded few transitions (4 `sla.at_risk` and 1 `sla.breached` events): most records reached their state when `ensure_sla()` first evaluated them. The monitor did create the 115 ESC-039 escalations of Chapter 18 for breached P0 and P1 complaints. Of the 168 operational complaints still open, 6 were On Track, 6 At Risk and 156 Breached.

## 19.8 Tests and limitations

No automated test targets the SLA state function, the SLA monitor, ESC-039 or follow-up scheduling directly. The end-to-end test `tests/e2e/test_full_chain.py::test_complete_complaint_chain` moves a complaint to Resolved, which records the resolution time and schedules the FUP-003 follow-up, but it does not assert either value. The follow-up comparison checks FUP-001 and FUP-002 run in every pipeline test. The SLA and follow-up logic is therefore **Implemented**, with evidence from the stored records and the SLA report, but not **Tested** by a dedicated test.

The implementation also has known limitations:

- The SLA clock does not pause while the complaint is Awaiting Customer, and it counts calendar hours, not business hours.
- Changing an SLA target applies to new SLA records and to records whose priority changes. Existing due times are not recomputed.
- Reopening a resolved complaint does not restart its SLA; the record keeps the state of the first resolution.
- Only a P0 or P1 breach escalates. An At Risk state or a P2 or P3 breach is flagged but not escalated.
- Follow-ups are not monitored for lateness and are not sent automatically when due.
- The global follow-up rules are applied in a fixed precedence in code rather than through the condition engine.
- A follow-up message that repeats its own due time fails RSP-007 (Chapter 16).
- The monitor runs inside the application process, which suits the single-instance deployment described in Chapter 43.
