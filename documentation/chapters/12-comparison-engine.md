# Chapter 12 — GenAI vs Python Comparison Engine

The Comparison Engine places the proposal of the GenAI Complaint Intelligence Pipeline (Pipeline 1) and the decision of the Python Ground-Truth Validation Pipeline (Pipeline 2) side by side, field by field. It serves two purposes. For every complaint it shows an agent or reviewer where the two pipelines agree, where they differ and on which rule the difference rests, which answers the SRS requirements for classification, routing, urgency and escalation comparison (SRS 1.6 xlvi to xlix). Across a set of unseen complaints with known labels it measures both pipelines against the expected outcome, which produces the GenAI and Python comparison report of SRS Deliverable 8. The first part is implemented by `build_comparison()` in `backend/src/supportnova/python_validation/engine.py`, the second by `backend/src/supportnova/services/evaluation.py`. In the user interface the comparison appears as the "AI vs rules" tab.

## 12.1 Principle

The comparison is descriptive; the checks of Chapter 11 are normative. Both are computed from the same two inputs, the parsed GenAI answer and the rules decision, during Phase A. The comparison rows state what each pipeline says about a field and whether the values match; the checks judge the difference with a severity and feed the verification score and the review triggers. Where the two pipelines differ, the system acts on the rules value, as the "AI vs rules" tab states in its heading: "Where they differ, the rules value is used." The comparison therefore never decides a case by itself, but it makes every decision explainable at the level of individual fields.

## 12.2 Comparison Rows

`build_comparison()` produces 18 rows for every complaint that has a usable GenAI answer. Each row holds the field name, the GenAI value, the Python value, a match result and an explanation that names the basis of the Python value. Table 12.1 lists the fields.

**Table 12.1 — Fields compared for every complaint**

| Field | GenAI value | Python (rules) value | Comparison | Basis shown |
|---|---|---|---|---|
| category | `issue_category` | Category of the rule classifier's own subcategory | value | Rule classification or confidence note |
| subcategory | `subcategory` | Rule classifier's own subcategory | value | Rule classification or confidence note |
| department | `department` | Primary department of the rules decision | value | Routing rule identifiers |
| supporting_departments | `supporting_departments` | Supporting departments of the rules decision | set | — |
| sentiment | `sentiment` | Lexicon sentiment | value | "Keyword-based estimate, for information only" |
| urgency | `urgency` | Urgency of the rules decision | value | Resolution rule and urgency floors that set it |
| impact | `impact` | Impact of the rules decision | value | — |
| priority | `priority` | Priority from the priority matrix | value | "Priority matrix (SLA-RUL-15 s4)" |
| entities | Order, transaction and complaint references in the GenAI entities | References extracted by Python | set | — |
| policy_references | Cited `policy_id:section` | Policy references of the rules decision | set | — |
| resolution | Action codes of the GenAI steps | Required action codes of the selected rule | set | Selected resolution rule |
| refund_eligibility | Refund status | Validated refund eligibility | value | — |
| replacement_eligibility | Replacement status | Validated replacement eligibility | value | — |
| compensation_eligibility | Compensation status | Validated compensation eligibility | value | — |
| escalation_required | `escalation_required` | Escalation required by the rules | value | Fired escalation rules |
| escalation_level | `escalation_level` | Highest fired escalation level | value | — |
| follow_up_required | `follow_up_required` | Follow-up required by the rules | value | — |
| follow_up_type | `follow_up_type` | Follow-up type of the rules | value | — |

A single value matches only when it is identical. A list is compared as a set: equal sets `match`, overlapping sets are `partial`, disjoint sets are a `mismatch`, and two empty lists `match`. The agreement of a complaint is the share of the 18 rows whose result is `match`, so partial rows count as disagreement. The classification rows always show the rule classifier's own result, even when the rules were not confident enough to use it as the reference and the GenAI subcategory decided provisionally (Chapter 11, Section 11.4.1); the explanation then reads "Rule confidence: low. The AI category is used until a reviewer confirms it." The comparison is stored with the validation result in `validation_results.comparison`, together with the agreement, the rules' classification confidence, the reference subcategory and the selected rule. Figure 12.1 shows the flow.

![Figure 12.1 — Comparison Engine for one complaint](diagrams/pipelines/fig-12-01-comparison-flow.svg)
*Figure 12.1 — Comparison Engine for one complaint*

The pipeline also stores a compact agreement flag on every complaint, `ai_python_agreement`, which is true only when the GenAI answer agrees with the rules on the category, the primary department and the escalation requirement. This flag feeds the "AI matches rules" indicator of the Analytics page and the count of complaints that "differ on a key field" (`backend/src/supportnova/services/analytics.py`). **Implemented.**

## 12.3 From Comparison to Verification Decision

Each compared field is judged by one or more checks of Chapter 11, and it is these checks, not the rows, that decide the case. Table 12.2 shows the correspondence.

**Table 12.2 — Compared fields, the checks that judge them and their effect**

| Compared field | Checks | Effect when the pipelines disagree |
|---|---|---|
| category, subcategory | CLS-001 (major), CLS-002 (minor), SCH-002 | CLS-001 fail sends the case to review (REV-001); a provisional classification always does (REV-005) |
| department | RTE-001 (critical), SCH-003 | Critical failure, review (REV-002) |
| supporting_departments | RTE-002 (major) | Lower score |
| sentiment | CLS-004 (info, weight 0) | None |
| urgency, impact | PRI-001 (critical when the rules require High or Critical), PRI-003 | Critical failure when the AI is too low (REV-002) |
| priority | PRI-002 (major), PRI-004 (minor) | Lower score |
| entities | CLS-005 (minor), HAL-002 (major) | HAL-002 fail sends the case to review (REV-012) |
| policy_references | SCH-004, POL-001 to POL-005, HAL-004 | POL-002 is critical (REV-002); POL-001 or POL-003 failure means missing policy support (REV-004) |
| resolution | RES-001 to RES-004 | A missing critical action or a prohibited action is critical (REV-002) |
| refund, replacement, compensation eligibility | ELG-001 to ELG-003 | An unsupported "eligible" or an excess amount is critical (REV-002) |
| escalation_required | ESC-001 (critical), ESC-003 (minor) | Missed escalation is critical (REV-002); an unnecessary one is unclear (REV-006) |
| escalation_level | ESC-002 (major, critical for Compliance Review and Critical Management Escalation) | Escalation unclear (REV-006), critical failure for the top levels |
| follow_up_required, follow_up_type | FUP-001, FUP-002 (minor) | Lower score |

The rows are not a subset of the checks and not every difference is an error. A partial match on `resolution`, for example, is normal when the GenAI answer adds investigative steps that the rule does not require; RES-001 then passes as long as every required action is present, and the extra steps are kept if they belong to the verification or information groups (Chapter 15). A mismatch on sentiment is informational only. Conversely, a check can fail when the rows match: RES-001 fails when a required action is missing even if all other fields agree, as in the case CMP-00616 (Chapter 11, Section 11.5.5).

## 12.4 Comparison Against Expected Labels

SRS Deliverable 8 requires a comparison of at least 100 unseen complaint cases showing the expected category, the GenAI and Python category, department, urgency and escalation, the policy reference, the match result, the verification status and an explanation of each disagreement. SupportNova produces this comparison with evaluation runs, started from the Evaluation page or through `POST /api/v1/evaluation/runs` with the `evaluation:run` permission, which only administrators hold.

An evaluation run imports every case of a dataset as a sandboxed complaint with the source `evaluation` and the reference `R<run>-<case>`, processes it through the production pipeline and then scores it (`services/evaluation.py`). The expected labels of the dataset are read only by the evaluator after processing; the pipeline never sees them. `score_case()` compares 15 fields, 12 as single values and 3 as sets (supporting departments, policy references, missing information), and records three results per field: `ai_ok` (GenAI against the label), `python_ok` (Python against the label) and `ai_vs_python` (the two pipelines against each other). The Python values are taken from the validated decision, except that the category and subcategory are the rule classifier's own result when the GenAI subcategory was used provisionally, so that the Python column never inherits a GenAI label. The six key fields are category, subcategory, department, urgency, priority and escalation level. For each disagreement on a key field or on the escalation requirement or refund and compensation eligibility, `_explain()` writes which pipeline matches the label, for example "the rules match the expected label" or "the AI matches the expected label (gap in the rules)". The results are stored in the table `evaluation_results`, and `compute_metrics()` aggregates them into per-field accuracies, key-field accuracy, the rate at which GenAI errors are caught, prompt-injection and manual-review recall, duplicate and repeat detection, results by difficulty type and latency. A GenAI error counts as *caught* when the case has at least one wrong GenAI key field and either Python matches the label on every such field or the case went to manual review. Figure 12.2 shows the flow.

![Figure 12.2 — Comparison of both pipelines against the expected labels](diagrams/pipelines/fig-12-02-evaluation-comparison.svg)
*Figure 12.2 — Comparison of both pipelines against the expected labels*

The recorded evaluation run #1 processed the 154 holdout cases of the dataset, which were never used to tune the rules or the prompts, with `openai/gpt-4.1-mini`, prompts `complaint_analysis` 1.2.0 and `customer_communication` 1.0.0 and ruleset `be81124c2a1df0d5`, in 858 seconds (`reports/genai_python_comparison/summary.md`). Two of the 154 cases were linked as duplicates of earlier cases and were therefore not validated; the field results below cover the other 152. **Tested (recorded run).** The integration test `tests/backend/integration/test_defects_and_live_changes.py::test_evaluation_run_on_unseen_holdout` runs 12 holdout cases through the same code, and `test_hidden_dataset_upload_with_minimal_columns` shows that a hidden dataset with only an identifier, a title and a description can be evaluated without labels. **Tested.**

## 12.5 Sample Comparison from Stored Results

Table 12.3 reproduces eight cases of evaluation run #1 from the stored rows of `evaluation_results`, with the columns required by Deliverable 8. The cases were chosen to show agreement, each type of disagreement and both directions of error. Categories are shown as subcategory codes, whose first three letters are the category; the policy reference is the first reference of the rules decision. Each case can be opened in the application under its reference, for example R1-EVL-00075.

**Table 12.3 — GenAI and Python comparison for eight unseen holdout cases (evaluation run #1)**

| Complaint ID | Expected category (label) | GenAI category | Python category | GenAI department | Python department | GenAI urgency | Python urgency | GenAI escalation | Python escalation | Policy reference | Match | Verification status | Explanation |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| EVL-00075 | ACC-LGN | ACC-LGN | ACC-LGN | DEPT-SEC | DEPT-SEC | Medium | Medium | No Escalation | No Escalation | SEC-POL-09:7.1 | Match | Verified (99.6) | Both pipelines agree on every key field; one minor warning (POL-005) |
| EVL-00020 | BIL-SUB | REF-REQ | BIL-SUB | DEPT-RET | DEPT-BIL | Medium | Medium | No Escalation | No Escalation | CAN-POL-06:4.3 | Mismatch | Manual Review (80.3) | The AI read an annual Cloud Vault renewal as a refund request and denied a refund that RES-BIL-SUB-02 grants; rules match the label; RTE-001 critical fail, REV-001, REV-002 |
| EVL-00010 | PRV-BRC | PRV-BRC | PRV-BRC | DEPT-CMP | DEPT-CMP | High | Critical | Compliance Review | Compliance Review | PRV-POL-08:6.1 | Mismatch | Manual Review (83.6) | Camera recordings visible to an ex-partner: RES-PRV-BRC-03 requires Critical; PRI-001 critical fail; privacy case (REV-008) |
| EVL-00056 | SAF-OVH | SAF-OVH | SAF-OVH | DEPT-SAF | DEPT-SAF | Critical | Critical | Specialist Team | Critical Management Escalation | SAF-POL-10:4.4 | Mismatch | Manual Review (85.7) | A smouldering dock raises `fire_event`; ESC-001 requires Critical Management Escalation; ESC-002 critical fail; rules match the label |
| EVL-00061 | SVC-OUT | SVC-OUT | SVC-OUT | DEPT-TEC | DEPT-TEC | Medium | High | No Escalation | Department Manager | CPN-POL-11:5.1 | Mismatch | Manual Review (77.6) | Injected fake policy claiming USD 200 credit: ESC-029 and ESC-030 enforced (ESC-001 and SEC-001 fail); the rules' High comes from the default rule because the outage length was not extracted, while the label says Medium |
| EVL-00030 | PRD-DOA | PRD-DOA | STF-MIS | DEPT-RET | DEPT-CRL | Medium | High | No Escalation | Department Manager | STF-POL-21:6 | Mismatch | Manual Review (70.7) | The rule classifier matched only "took pictures" (low confidence) and the correct AI category failed the evidence gate; six review reasons; the AI matches the label |
| EVL-00082 | WAR-DEN | WAR-DEN | WAR-CLM | DEPT-WAR | DEPT-WAR | Medium | Medium | Supervisor Review | No Escalation | WAR-POL-07:4.2 | Mismatch | Manual Review (94.9) | "Declined" and "appealed" are not in the WAR-DEN vocabulary, so the rules chose WAR-CLM and ESC-038 did not fire; the AI matches the label; REV-006 escalation unclear |
| EVL-00111 | REF-PAR | DEL-WRG | DEL-WRG | DEPT-LOG | DEPT-LOG | Medium | Medium | No Escalation | No Escalation | RPL-POL-03:5.1 | Match | Verified (88.9) | Both read a restocking-fee dispute on a wrong-item return as DEL-WRG, with REF-PAR as a secondary issue; no trigger fired, so the agreeing pipelines were verified although both differ from the label |

The eight cases show how the comparison and the checks work together. In EVL-00020, EVL-00010, EVL-00056 and EVL-00061 the rules corrected the GenAI answer: a wrong category and department, an urgency one level too low for a privacy exposure, an escalation level too low for a fire hazard and a mandatory escalation that the model missed in a complaint containing an injected instruction. Each of these produced a critical failure, and each case went to manual review with the rules' values already applied. In EVL-00030 and EVL-00082 the GenAI answer was right and the rules were wrong, because the customer's words were missing from the rule vocabulary; both cases also went to manual review, so the rules' error was held for a person rather than acted on unreviewed. EVL-00111 is the uncomfortable case: the pipelines agreed, nothing triggered a review and the case was verified, yet both differ from the label. EVL-00075 is the ordinary case of full agreement.

## 12.6 Holdout Evaluation Results

Table 12.4 reproduces the per-field accuracy of evaluation run #1 from `reports/genai_python_comparison/summary.md`, computed over the 152 validated holdout cases.

**Table 12.4 — Accuracy against the expected labels on 152 unseen holdout cases (evaluation run #1)**

| Field | Python (Pipeline 2) | GenAI (Pipeline 1) | GenAI-Python agreement |
|---|---|---|---|
| Category | 75.7 % | 89.5 % | 69.7 % |
| Subcategory | 68.4 % | 77.6 % | 58.6 % |
| Department | 84.9 % | 92.1 % | 84.9 % |
| Supporting departments | 74.3 % | 73.7 % | 61.8 % |
| Urgency | 84.2 % | 68.4 % | 66.5 % |
| Priority | 88.8 % | 62.5 % | 61.2 % |
| Escalation required | 94.7 % | 92.8 % | 91.5 % |
| Escalation level | 94.1 % | 84.9 % | 82.9 % |
| Refund eligibility | 93.4 % | 60.5 % | 62.5 % |
| Replacement eligibility | 93.4 % | 85.5 % | 82.9 % |
| Compensation eligibility | 95.4 % | 79.0 % | 76.3 % |
| Follow-up type | 75.7 % | 44.1 % | 39.5 % |
| Missing information | 77.0 % | 59.2 % | 47.4 % |
| Policy references | 76.3 % | 5.9 % | 5.9 % |
| Resolution rule | 75.0 % | 0.0 % | 0.0 % |

Over the six key fields, the Python key-field accuracy was 82.7 percent, the GenAI key-field accuracy 79.2 percent and the agreement between the pipelines 70.6 percent. The two pipelines are strong in different places. The GenAI model classifies better: it is 13.8 points ahead on category, 9.2 on subcategory and 7.2 on department, because the rule classifier depends on the vocabulary of its category rules. The rules decide better wherever the answer follows from policy once the subcategory and the facts are known: urgency (15.8 points ahead), priority (26.3), escalation level (9.2), refund eligibility (32.9), compensation eligibility (16.4) and follow-up type (31.6). The GenAI figures for the last two rows are not comparable: the GenAI output schema has no field for the resolution rule, so its accuracy is 0 by construction, and a set of policy references matches only when it is identical to the labelled set, which the model's citations of neighbouring or additional sections almost never are; the policy checks POL-001 to POL-004 judge citations more finely (Chapter 11).

This complementarity is the reason for comparing the pipelines rather than replacing one with the other. Table 12.5 shows what happened when they disagreed, computed from the 152 stored rows.

**Table 12.5 — Outcome of GenAI-Python disagreements in evaluation run #1**

| Field | Disagreements | Python right | GenAI right | Neither right | Sent to manual review |
|---|---|---|---|---|---|
| Category | 46 | 11 | 32 | 3 | 46 |
| Subcategory | 63 | 20 | 34 | 9 | 59 |
| Department | 23 | 6 | 17 | 0 | 23 |
| Urgency | 51 | 37 | 13 | 1 | 43 |
| Priority | 59 | 48 | 8 | 3 | 48 |
| Escalation required | 13 | 8 | 5 | 0 | 13 |
| Escalation level | 26 | 19 | 5 | 2 | 26 |
| Refund eligibility | 57 | 52 | 2 | 3 | 50 |
| Compensation eligibility | 36 | 30 | 5 | 1 | 33 |

Every disagreement on the category, the primary department, the escalation requirement or the escalation level went to manual review, whichever pipeline was right. The 8 urgency disagreements that did not lead to review were all cases in which the GenAI urgency was one level higher than the rules' urgency, which PRI-001 only warns about; in each of them the rules matched the label and the case was acted on with the rules' value. At the case level, 93 of the 154 GenAI answers contained at least one key-field error and 92 of them (98.9 percent) were caught. The safety nets of the run were complete for prompt injection (6 of 6 injected cases detected, no false positives), duplicates (2 of 2 linked) and repeats (4 of 4 detected); 48 of the 51 cases for which the labels expect manual review were routed to it (94.1 percent recall), while 130 of the 154 cases went to manual review in total. By difficulty type, the rules had all key fields right in 6 of 9 emotional low-priority cases against 2 for the GenAI model, and in 7 of 8 multi-issue cases against 3.

## 12.7 Presentation in the User Interface

The "AI vs rules" tab of the complaint page (`frontend/src/components/complaint/ComparisonPanel.tsx`) presents the comparison of one case (Figure 12.3). A gauge shows the verification score against the pass mark of 80, with the decision badge and the counts of passed, warned and failed checks. "Score by area" shows the dimension scores as bars, green from 90, amber from 70 and red below. When the case was held, a panel "Why this needs review" lists each review reason with its detail. The table "AI proposal vs rules decision" shows the agreement percentage and, for each of the 18 fields, the AI value, the rules value, the result badge (Match, Partial or Mismatch, with mismatched rows highlighted) and the basis, for example "RTE-016, RTE-104" or "Rule RES-ACC-UNA-03". Below it the rule checks are listed, filtered to "Failures & warnings" or "All 52 checks"; each check expands to the expected value from the rules, the actual value from the AI and the rule and policy references. Figure 12.3 shows CMP-00616, whose comparison rows are reproduced in Appendix F.

![Figure 12.3 — AI vs rules tab of CMP-00616](../screenshots/09-complaint-ai-vs-rules.png)
*Figure 12.3 — AI vs rules tab of CMP-00616*

The Evaluation run page (`frontend/src/pages/EvaluationRun.tsx`) presents Deliverable 8 for a whole run (Figure 12.4): the key-field accuracy of the rules and of the AI, their agreement, the number of AI errors caught, the verified and manual-review rates, accuracy by field with the lead of the rules, the verification outcome, prompt-injection and manual-review statistics, results by difficulty type and a case-by-case comparison with the expected, AI and rules values of category, department, urgency and escalation, the match result, the verification status and the explanation, filterable to cases where AI and rules disagree. The Analytics page has an "AI vs rules" tab that aggregates the latest comparison of every operational complaint: the rules decisions, the score by check area, the reasons why complaints went to review, the field agreement and the outcome of each of the 52 checks (Figure 12.5). This view gives administrators the GenAI/Python mismatches required by SRS Step 63. The Reports page offers the GenAI/Python comparison report for operational complaints as PDF, Excel and CSV (`backend/src/supportnova/reporting/builders.py`).

![Figure 12.4 — Evaluation run #1 on the holdout dataset](../screenshots/24-evaluation-run-holdout.png)
*Figure 12.4 — Evaluation run #1 on the holdout dataset*

![Figure 12.5 — Analytics, AI vs rules tab](../screenshots/21-analytics-ai-vs-rules.png)
*Figure 12.5 — Analytics, AI vs rules tab*

## 12.8 Defect in the Per-Case Export of Evaluation Runs

While this chapter was written, the exported per-case report of evaluation run #1 was found to be defective. The files `reports/genai_python_comparison/genai-python-comparison.csv`, `.xlsx` and `.pdf`, which `summary.md` names as the location of the per-case table, list the 154 cases with their expected categories and verification statuses, but every GenAI and rules value is empty ("None/None"), every case is marked "Match" and the summary states 154 full matches and 0 mismatches. The cause is in `genai_python_comparison()` of `backend/src/supportnova/reporting/builders.py`: for an evaluation run it passes the evaluation comparison, which is keyed by field name, to `_comparison_row()`, which expects the `rows` list of a validation-result comparison and therefore finds no values. The operational report built from validation results is not affected. The correct per-case values are stored in `evaluation_results`, shown on the Evaluation run page (Figure 12.4) and summarised correctly in `summary.md`, and Table 12.3 was built from those stored rows. The defect is not yet fixed; the fix is to build the evaluation rows from the per-field entries (`ai`, `python`, `ai_vs_python`) and to regenerate the three files.

## 12.9 Requirement Coverage

**Table 12.6 — SRS requirements for the GenAI and Python comparison**

| SRS requirement | How SupportNova meets it | Status |
|---|---|---|
| 1.6 (xlvi) Classification comparison | Category and subcategory rows; CLS-001, CLS-002 | Implemented, Tested |
| 1.6 (xlvii) Routing comparison | Department and supporting-department rows; RTE-001, RTE-002 | Implemented, Tested |
| 1.6 (xlviii) Urgency comparison | Urgency, impact and priority rows; PRI-001 to PRI-004 | Implemented, Tested |
| 1.6 (xlix) Escalation comparison | Escalation rows; ESC-001 to ESC-004 | Implemented, Tested |
| Step 57: manual review when GenAI and Python disagree significantly | Critical checks and REV-001, REV-002, REV-005, REV-006 | Implemented, Tested |
| Step 63: GenAI/Python mismatches on the administrator dashboard | Analytics "AI vs rules" tab, `ai_python_agreement` | Implemented |
| Deliverable 8: at least 100 unseen cases compared | Evaluation run #1, 154 holdout cases | Tested (recorded run) |
| Deliverable 8: per-case table with the required columns | Stored in `evaluation_results` and shown on the Evaluation run page; the exported CSV, Excel and PDF files have empty value columns | Partially met (export defect, Section 12.8) |

The next three chapters apply the same ground truth to the three areas where the comparison shows the largest differences: routing (Chapter 13), urgency and priority (Chapter 14), and resolution and eligibility (Chapter 15).
