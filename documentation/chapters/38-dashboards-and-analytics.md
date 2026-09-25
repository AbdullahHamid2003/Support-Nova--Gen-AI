# Chapter 38 — Dashboard and Analytics

SupportNova gives each role a dashboard that matches its work (SRS Steps 61 to 63) and gives managers, reviewers and administrators an analytics workspace with distributions, trends, validation quality, SLA and policy usage (Steps 64 and 65). Every number is computed from the application database at request time by `backend/src/supportnova/services/analytics.py`, whose header states the rule: "nothing is hard-coded or fabricated". Dashboards cover operational complaints only, those with the source `web`, `api` or `dataset`. Adversarial Lab and evaluation complaints are excluded so that attack tests and benchmark runs do not distort the operational picture. The figures in this chapter were read from the demo database on 25 September 2026 (622 operational complaints) and agree with the screenshots taken the same day.

One limitation of the demo data affects some figures and is stated before them. The 617 dataset complaints carry their original dates, from 4 May to 21 September 2026, but were all processed by the real pipeline on 24 September. To give the resolution-time, SLA and department views a history, the demo time-lapse (`SEED_SIMULATE_LIFECYCLE`, `simulate_lifecycle` in `services/seed.py`) moved older complaints through a plausible lifecycle, labelled "Demo Data Seeder (simulated history)" in the timeline and the audit log: 432 resolved, 322 closed and 300 reviews approved. Figures that depend on these events (resolution times, "Human Verified" counts, and SLA "Met" or "Breached" states of resolved cases) describe the simulated history, not the work of real agents. Classification, routing, priority, sentiment, escalation, validation and AI-versus-rules figures come from the real pipeline runs with gpt-4.1-mini.

## 38.1 Data sources and access

**Table 38.1 — Dashboard and analytics endpoints**

| Endpoint (`/api/v1…`) | Permission | Content |
|---|---|---|
| `GET /dashboard` | any signed-in user | A role-specific dashboard: customer, agent, or operations view for reviewers, managers and administrators |
| `GET /analytics/overview` | `analytics:read` | Headline KPIs and distributions over 13 dimensions |
| `GET /analytics/distribution/{dimension}` | `analytics:read` | One distribution: category, subcategory, department, priority, urgency, sentiment, channel, status, verification, escalation, customer type, product or SLA state |
| `GET /analytics/trends` | `analytics:read` | Volume per day or week over 7 to 730 days, split by any dimension, with escalations and negative sentiment per bucket |
| `GET /analytics/alerts` | `analytics:read` | Trend alerts for a window of 3 to 90 days (default 14) |
| `GET /analytics/validation` | `analytics:read` | Check outcomes, decisions, field agreement, review reasons and dimension scores, using the latest validation of each complaint |
| `GET /analytics/sla`, `/departments`, `/policy-usage`, `/resolution-times` | `analytics:read` | SLA states per priority, department performance, most-used policy sections, resolution times per priority |

The `analytics:read` permission belongs to reviewers, managers and administrators (`security/rbac.py`). The operations dashboard adds the validation statistics and the review queue for reviewers, managers and administrators, SLA, department performance and trend alerts for managers and administrators, and a system summary for administrators only.

## 38.2 Customer dashboard

The customer dashboard (Step 61) lists the customer's own complaints with the complaint ID, status, submission date, department, latest update and resolution status. The latest update is chosen from customer-facing events only (`status.changed`, `complaint.submitted`, `response.sent`, `complaint.clarified`) and rendered in customer-safe wording by `api/serializers.py`, so internal notes, scores and rule IDs never appear. The resolution status is derived from the complaint status: "Resolved", "Waiting for your reply" (Awaiting Customer) or "In progress".

![Figure 38.1 — Customer dashboard of the fictional customer Wesley Jovanovic](../screenshots/03-customer-dashboard.png)
*Figure 38.1 — Customer dashboard of the fictional customer Wesley Jovanovic*

In Figure 38.1 the fictional customer has five complaints: four in progress and one resolved. For example, CMP-00618, "Power bank got hot", shows the status Escalated, the department Product Safety and the update "Your complaint has been passed to a s…", while no escalation level, verification score or rule appears.

## 38.3 Agent dashboard

The agent dashboard (Step 62) shows the agent's open assigned complaints ordered by priority and age (at most 60). Each card shows the category and subcategory, priority, urgency, sentiment, verification status and score, escalation warning, SLA state, an injection flag where applicable, the validated summary with up to three validated guidance lines, and the suggested response with its status.

![Figure 38.2 — Agent dashboard: assigned complaints with validated guidance and the suggested response](../screenshots/06-agent-dashboard.png)
*Figure 38.2 — Agent dashboard: assigned complaints with validated guidance and the suggested response*

For the agent in Figure 38.2 the dashboard counts 21 open assigned complaints (P1 1, P2 19, P3 1), 17 at risk or breached against their SLA, 3 escalation warnings and 16 awaiting review. The first card, CMP-00358, "Late order LMR-847527", is P1 and Escalated, in Manual Review with a score of 74, carries a Department Manager escalation, a breached SLA and an injection flag. Its guidance names the applicable rule (RES-DEL-DLY-01), the mandatory escalation with its rules (ESC-020, ESC-029, ESC-030) and a prohibited behaviour ("Do not: Promising a delivery date not confirmed by the carrier"). Its suggested response is marked "requires review", so the agent cannot send it until a reviewer approves.

## 38.4 Manager and administrator dashboard

The operations dashboard (Step 63) combines the headline figures with the distributions, trend alerts, review reasons and department performance (Figure 38.3). Table 38.2 lists its KPIs.

![Figure 38.3 — Manager dashboard: KPIs, volume by category, priority levels, distributions, trend alerts, review reasons and department performance](../screenshots/14-manager-dashboard.png)
*Figure 38.3 — Manager dashboard: KPIs, volume by category, priority levels, distributions, trend alerts, review reasons and department performance*

**Table 38.2 — Operations dashboard KPIs (25 September 2026)**

| KPI | Value | Computation (`services/analytics.py`) |
|---|---|---|
| Total complaints | 622 (168 open, 454 resolved or closed) | Operational complaints |
| Verified | 78% (171 automatically, 301 by reviewers) | Verified plus Human Verified over the 604 analysed complaints; 300 of the 301 reviewer approvals are simulated history |
| Manual review | 150 pending | Pending or in-review reviews, including 18 Lab and 5 web reviews; 132 belong to operational complaints |
| Escalated | 203 | Complaints with `escalation_required` |
| SLA at risk · breached | 5 · 156 | Open complaints by SLA state at capture; the monitor re-evaluates every 60 s (a query later that day found 6 at risk and 156 breached) |
| AI and rules agree | 77% (137 complaints differ) | Share of analysed complaints where the AI's category, department and escalation requirement all equal the rules (467 of 604) |
| Repeat complaints | 22 | `is_repeat` |
| Duplicates linked | 18 | `is_duplicate` |
| Injection attempts blocked | 32 | `injection_detected` |
| Average processing time | 23.09 s | Mean `total_latency_ms` of the analyses |
| Average resolution | 96.4 h | Mean time from creation to resolution over 436 resolved complaints (simulated lifecycle) |

## 38.5 Category, priority and sentiment distributions

The distributions group the denormalised complaint columns with SQL. "Unclassified", "Not routed" and "Not set" are the 18 linked duplicates, which are closed without an analysis.

**Table 38.3 — Category distribution**

| Category | Complaints | Share |
|---|---|---|
| Billing | 82 | 13.2% |
| Delivery | 73 | 11.7% |
| Refund | 71 | 11.4% |
| Product Defect | 65 | 10.5% |
| Technical Support | 54 | 8.7% |
| Safety | 49 | 7.9% |
| Account | 46 | 7.4% |
| Privacy | 45 | 7.2% |
| Service Quality | 44 | 7.1% |
| Warranty | 43 | 6.9% |
| Staff Behavior | 32 | 5.1% |
| Unclassified (linked duplicates) | 18 | 2.9% |

**Table 38.4 — Priority, urgency and sentiment distributions**

| Priority | Complaints | Urgency | Complaints | Sentiment | Complaints |
|---|---|---|---|---|---|
| P0 Critical | 94 (15.1%) | Critical | 94 | Neutral | 304 (48.9%) |
| P1 High | 22 (3.5%) | High | 122 | Negative | 177 (28.5%) |
| P2 Medium | 310 (49.8%) | Medium | 287 | Strongly Negative | 119 (19.1%) |
| P3 Low | 178 (28.6%) | Low | 101 | Positive | 4 (0.6%) |
| Not set | 18 (2.9%) | Not set | 18 | Not set | 18 (2.9%) |

The priority and urgency columns hold the rules' values, and the sentiment column holds the AI's reading. Sentiment is informational in SupportNova and never changes urgency, so a large Negative or Strongly Negative share (47.6%) does not inflate the priority mix: 28.6% of the complaints are P3.

## 38.6 Department routing

**Table 38.5 — Department routing and performance**

| Department | Primary | Share | Supporting | Open | Escalated | SLA breach rate | Average score |
|---|---|---|---|---|---|---|---|
| Technical Support | 102 | 16.4% | 79 | 33 | 15 | 39.2% | 91.1 |
| Returns & Refunds | 92 | 14.8% | 45 | 27 | 18 | 39.1% | 90.3 |
| Logistics Support | 88 | 14.1% | 26 | 21 | 13 | 33.0% | 89.1 |
| Billing Operations | 82 | 13.2% | 51 | 27 | 13 | 40.2% | 90.5 |
| Customer Relations | 65 | 10.5% | 22 | 11 | 28 | 30.8% | 91.0 |
| Product Safety | 49 | 7.9% | 0 | 12 | 49 | 28.6% | 88.7 |
| Compliance & Privacy | 45 | 7.2% | 34 | 14 | 26 | 48.9% | 90.6 |
| Warranty Services | 43 | 6.9% | 10 | 10 | 13 | 34.9% | 91.1 |
| Account Security | 38 | 6.1% | 18 | 13 | 28 | 44.7% | 92.1 |
| Management Escalations | 0 | — | 59 | — | — | — | — |
| Not routed (linked duplicates) | 18 | 2.9% | — | 0 | 0 | 0.0% | — |

The primary department is always the Rule Matrix department. Every Product Safety complaint is escalated (49 of 49), which follows from the safety escalation rules. Management Escalations is never a primary department but supports 59 complaints. The primary, open, escalated, breach-rate and score columns come from the dashboard (Figure 38.3); the supporting counts come from the department performance report in `reports/operations/department-performance.pdf`. The SLA breach rates reflect the synthetic timeline described at the start of this chapter.

## 38.7 Escalations

The dashboard counts escalated complaints, and the escalation report counts escalation records. Both views are useful. A complaint carries its highest escalation level, while every escalation event, including those added later by the SLA monitor, is a separate record in `escalations`.

**Table 38.6 — Escalations by level**

| Level | Complaints (highest level) | Escalation records |
|---|---|---|
| Critical Management Escalation | 34 | 34 |
| Compliance Review | 41 | 41 |
| Specialist Team | 41 | 41 |
| Department Manager | 28 | 139 |
| Supervisor Review | 59 | 62 |
| Total | 203 complaints (32.6%) | 317 records |

Of the 317 records, 167 were required by the rules and also proposed by the AI (source `rule+ai`), 35 were required by the rules although the AI missed them (source `rule`), and 115 were added by the SLA monitor under ESC-039 when a P0 or P1 complaint breached its resolution target (source `sla`). 89 records are open and 228 resolved. The most frequent escalation rules are ESC-039 (115, SLA breach), ESC-007 (37), ESC-009 (27), ESC-002 (20) and ESC-012 (20). The ESC-039 records are a consequence of the past-dated demo complaints: they were already overdue when they were analysed.

## 38.8 Repeat complaints, duplicates and manipulation attempts

The dashboard shows 22 repeat complaints from 16 customers (CUST-10114 has three), 18 duplicates that were linked to the original and closed instead of opening a second case, and 32 complaints with manipulation attempts. All 32 are in Manual Review with a pending review. The Analytics page shows the same figures as shares: repeats are 3.5% of the complaints.

## 38.9 SLA risk

SLA targets come from the Rule Matrix (`rules/sla_rules/sla_rules.yaml`, SLA-RUL-15), and the SLA monitor re-evaluates every open complaint each minute. A complaint is At Risk once the elapsed share of its resolution window reaches the `sla_at_risk_pct` parameter, and Breached after its due time.

**Table 38.7 — SLA state by priority (SLA status report, 25 September 2026, 11:54 UTC)**

| Priority | First response target | Resolution target | On Track | At Risk | Breached | Met |
|---|---|---|---|---|---|---|
| P0 | 1 h | 24 h | 0 | 1 | 34 | 59 |
| P1 | 4 h | 48 h | 0 | 0 | 8 | 14 |
| P2 | 24 h | 120 h | 4 | 1 | 120 | 185 |
| P3 | 48 h | 240 h | 3 | 3 | 64 | 108 |
| Total | | | 7 | 5 | 226 | 366 |

The report tracks 604 SLA records, and 336 of them met the first-response target. The high number of breaches is a property of the demo data: open dataset complaints dated weeks or months before they were processed are past their due time by construction. The mechanism itself (the state transitions, the at-risk threshold and the ESC-039 breach escalation) is what these figures demonstrate, not operational performance.

## 38.10 Policy usage

Policy usage counts, per document section, how often the AI cited it, how often the Rule Matrix required it and how often retrieval returned it (`policy_references`).

**Table 38.8 — Most-used policy sections**

| Document | Section | Cited by AI | Required by rules | Retrieved |
|---|---|---|---|---|
| REF-POL-02 Refund Policy | 4.3 | 62 | 36 | 88 |
| ESC-SOP-12 Escalation Procedure | 4.1 | 26 | 49 | 84 |
| REF-POL-02 Refund Policy | 3.1 | 45 | 28 | 166 |
| SAF-POL-10 Product Safety Policy | 4.4 | 13 | 49 | 17 |
| ESC-SOP-12 Escalation Procedure | 4.2 | 23 | 27 | 93 |
| DEL-POL-04 Delivery and Shipping Policy | 6.1 | 27 | 23 | 118 |
| TEC-GDL-20 Product Support Guidelines | 2 | 29 | 17 | 43 |
| ESC-SOP-12 Escalation Procedure | 4.9 | 6 | 39 | 39 |
| RPL-POL-03 Replacement and Returns Policy | 3.1 | 24 | 19 | 36 |
| BIL-POL-05 Billing and Payments Policy | 4.1 | 21 | 21 | 37 |

The gap between the "Required by rules" and "Cited by AI" columns is itself informative. SAF-POL-10 section 4.4 and ESC-SOP-12 section 4.9 are required far more often than the model cites them, which matches the low AI score for policy references in the holdout evaluation (Chapter 33).

## 38.11 AI vs rules disagreements

The "AI vs rules" tab of the Analytics page (Figure 38.4) summarises the validation of the latest analysis of each complaint. Of 604 checked complaints, the rules verified 171 (28%) and sent 433 (72%) to manual review. Table 38.9 shows the field agreement, and Table 38.10 the checks that fail most often.

![Figure 38.4 — Analytics, "AI vs rules" tab: rules decision, score by check area, review reasons, field agreement and rule checks](../screenshots/21-analytics-ai-vs-rules.png)
*Figure 38.4 — Analytics, "AI vs rules" tab: rules decision, score by check area, review reasons, field agreement and rule checks*

**Table 38.9 — Field agreement between the AI and the rules (latest analysis of 604 complaints)**

| Field | Agree | Disagree | Agreement |
|---|---|---|---|
| Follow-up required | 573 | 31 | 94.9% |
| Entities | 552 (18 partial) | 34 | 91.4% |
| Department | 551 | 53 | 91.2% |
| Escalation required | 521 | 83 | 86.3% |
| Category | 503 | 101 | 83.3% |
| Replacement eligibility | 501 | 103 | 83.0% |
| Compensation eligibility | 477 | 127 | 79.0% |
| Escalation level | 469 | 135 | 77.6% |
| Subcategory | 465 | 139 | 77.0% |
| Impact | 428 | 176 | 70.9% |
| Urgency | 396 | 208 | 65.6% |
| Supporting departments | 376 (54 partial) | 174 | 62.3% |
| Priority | 364 | 240 | 60.3% |
| Refund eligibility | 347 | 257 | 57.5% |
| Follow-up type | 254 | 350 | 42.0% |
| Sentiment | 252 | 352 | 41.7% |
| Policy references | 42 (451 partial) | 111 | 7.0% |
| Resolution steps | 2 (575 partial) | 27 | 0.3% |

**Table 38.10 — Most frequently failing checks (latest analysis per complaint)**

| Check | Name | Fail | Fail rate (of applicable) |
|---|---|---|---|
| RES-001 | Required actions present | 289 | 47.8% |
| RTE-002 | Required supporting departments included | 90 | 34.1% |
| CLS-004 | Sentiment matches the rule check | 79 | 13.1% |
| PRI-001 | Urgency matches the rules | 73 | 12.1% |
| CLS-002 | Subcategory matches the rules | 62 | 10.3% |
| CLS-001 | Category matches the rules | 62 | 10.3% |
| RSP-007 | Follow-up message is safe to send | 61 | 10.6% |
| MIS-002 | Questions ask for the missing information | 59 | 55.1% |
| RSP-001 | Response includes the required parts | 56 | 9.3% |
| MIS-001 | Missing information identified | 56 | 52.3% |
| RTE-001 | Primary department matches the routing rules | 53 | 8.8% |
| ELG-001 | Refund eligibility matches the rules | 45 | 7.5% |
| ESC-002 | Escalation level meets the rules | 43 | 25.7% |

The average score per check area, from lowest to highest, is follow-up 78.3, resolution 78.9, priority 81.4, classification 81.7, eligibility 82.6, routing 86.1, escalation 91.8, grounding 93.7, policy 95.5, communication 96.9, security 98.6 and AI answer (schema) 99.5. Three patterns stand out. First, the model most often leaves out a required action (RES-001), which is why resolution steps rarely match exactly: 575 are partial matches, and the validated decision adds the missing rule actions. Second, the model under-rates urgency and priority more often than it misroutes: 91.2% department agreement against 60.3% priority agreement. Third, sentiment disagreement is high but harmless, because the rules' sentiment is a keyword estimate used for information only (CLS-004 has severity "info" and never changes urgency).

## 38.12 Manual-review cases

The review reasons explain why cases need a person. Across the latest analyses of the 604 complaints, 840 reasons were recorded (a case can have several): a critical check failed (REV-002) 255, unclear complaint (REV-005) 156, sensitive case (REV-008) 114, escalation level unclear (REV-006) 91, AI and rules disagree on the category (REV-001) 62, unsupported claims (REV-012) 50, attempt to manipulate the AI (REV-010) 32, verification score too low (REV-003) 31, unsupported promises (REV-011) 26, conflicting policy information (REV-007) 9, no policy supports the decision (REV-004) 7 and order not found for this customer (REV-014) 7. For the 132 reviews of operational complaints that are still pending, the dashboard chart ranks the same reasons: a critical check failed 76, unclear complaint 49, attempt to manipulate the AI 32, sensitive case 30, escalation level unclear 28, category disagreement 20, score too low 16 and unsupported claims 14.

## 38.13 Trends and trend alerts

The trend endpoint buckets complaints per day or per week and splits them by a chosen dimension. It returns the six leading values of that dimension together with the escalations and negative-sentiment complaints per bucket. The Analytics page defaults to 120 days per week and the dashboard chart to 150 days. In the window shown in Figure 38.5 there are 521 complaints over 18 weeks, 172 of them escalated (33.0%) and 249 with negative sentiment (47.8%); the busiest week, starting 29 June 2026, had 42 complaints.

![Figure 38.5 — Analytics, "Volume & trends" tab: weekly volume by category, trend alerts, escalation levels and screening figures](../screenshots/20-analytics.png)
*Figure 38.5 — Analytics, "Volume & trends" tab: weekly volume by category, trend alerts, escalation levels and screening figures*

Trend alerts implement Step 65 with explicit, deterministic rules in `trend_alerts`. The thresholds in Table 38.11 are code constants, and the window length is a request parameter.

**Table 38.11 — Trend-alert rules**

| Alert | Rule | Severity |
|---|---|---|
| Rising category, department or product | At least 5 complaints in the current window and at least 1.5 times the previous window of the same length | High at 2.5 times or more, otherwise medium |
| Escalation spike | At least 4 escalated complaints in the last 7 days and at least 1.5 times the weekly average of the 28 days before | High |
| Recurring product issue | At least 4 complaints about the same product and subcategory within 30 days (categories PRD, SAF, WAR, TEC) | High for safety subcategories, otherwise medium |
| Repeated service failures | At least 5 service-outage (SVC-OUT) or repeat complaints within 30 days | Medium |

The complaint intelligence report generated on 25 September 2026 at 11:53 UTC lists the 12 alerts that were active: 2 high and 10 medium, as the Analytics page shows. The two high alerts were Product Defect complaints rising from 2 to 12 in 14 days, and Lumora Aura Smart Thermostat complaints rising from 2 to 5. The medium alerts were Technical Support (6 to 12), Returns & Refunds (6 to 9), Account (4 to 6), Privacy (3 to 5), Compliance & Privacy (3 to 5), Account Security (3 to 5) and Lumora Glide Robot Vacuum (3 to 5) rising; 7 service-outage or repeat complaints in 30 days; and 4 Product Malfunction complaints each for the Lumora Halo Smart Speaker and the Lumora Glide Robot Vacuum. Because the windows are measured back from the moment of the request, the list changes as time passes.

## 38.14 Coverage of the SRS dashboard and analytics steps

**Table 38.12 — SRS Steps 61 to 65 and where they are implemented**

| SRS step | Required content | Where | Status |
|---|---|---|---|
| 61 Customer dashboard | Complaint ID, status, submitted date, department, latest update, resolution status | `CustomerDashboard` in `pages/Dashboard.tsx`; `analytics.dashboard` | Implemented |
| 62 Agent dashboard | Assigned complaints, category, priority, sentiment, GenAI recommendation, validation status, suggested response, escalation warnings | `AgentDashboard` | Implemented |
| 63 Administrator dashboard | Total, category and department distributions, priority levels, escalations, resolution status, SLA risks, GenAI/Python mismatches, manual-review cases | `OpsDashboard` | Implemented |
| 64 Complaint analytics | Volume, category, product or service, department, urgency, sentiment, escalations, resolution time, repeat complaints | Analytics tabs; `/analytics/*` | Implemented |
| 65 Trend detection | Rising delivery and billing complaints, recurring product issues, repeated service failures, escalation spikes | `trend_alerts`; dashboard and Analytics alert panels | Implemented |

The dashboards are exercised by the end-to-end test, which checks that the dashboard total increases by one after a submission (`test_full_chain.py::test_complete_complaint_chain`). The status badges they use are covered by the frontend tests. There are no dedicated automated tests for the individual aggregates or for the alert thresholds; the figures above were checked against the database while this chapter was written. Tests for the aggregates and alert rules are **Planned**.
