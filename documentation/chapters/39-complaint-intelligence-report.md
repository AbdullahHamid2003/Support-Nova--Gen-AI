# Chapter 39 — Complaint Intelligence Report

The SRS asks for reports on complaint analysis, department performance, escalations, SLA status, policy usage, resolution compliance, the GenAI/Python comparison and manual reviews (Step 67), exportable as CSV, PDF and an Excel-compatible format (Step 68). Three deliverables are reports in their own right: the GenAI and Python comparison on at least 100 unseen cases (Deliverable 8), the Complaint Intelligence Report (Deliverable 9) and the security and adversarial testing report (Deliverable 10). SupportNova implements all of them as ten server-side report builders that render one format-neutral model into CSV, Excel, PDF and JSON. It adds four further exports: a complete case report per complaint, the filtered complaint list, the audit log and the Rule Matrix. This chapter describes how reports are built and exported, what each one contains, the Complaint Intelligence Report in detail, the evidence files in `reports/`, and one defect found while this chapter was being written.

## 39.1 Reporting architecture

Reports are generated on the server from live data; nothing is typed in by hand. `backend/src/supportnova/reporting/builders.py` contains one builder per report. Each builder queries the database and returns a `Report`: a title, a subtitle, metadata (the scope and the AI model), and sections that contain paragraphs, metrics, bullets and tables. `backend/src/supportnova/reporting/exports.py` renders that single model to every format, so the CSV, the Excel workbook and the PDF of a report always carry the same numbers. `GET /api/v1/reports` returns the catalogue and the supported formats, and `GET /api/v1/reports/{key}?format=…` builds and renders one report (`api/v1/insights.py`). Both require the permission `reports:export`, which reviewers, managers and administrators hold. The JSON format feeds the in-page preview. Every file format is sent as an attachment named `supportnova-{key}.{ext}`, and each such download is written to the audit log as `report.exported`, with the scope used. In the browser, `download()` in `frontend/src/lib/api.ts` fetches the file with the session cookie and saves it under the server's file name (Figure 39.1).

![Figure 39.1 — How a report is generated and exported](diagrams/data-flow/fig-39-01-report-generation.svg)
*Figure 39.1 — How a report is generated and exported*

## 39.2 Report catalogue

**Table 39.1 — Reports implemented in `reporting/builders.py`**

| Key | Report | SRS item | Contents |
|---|---|---|---|
| `complaint-analysis` | Complaint analysis | Step 67 | 12 KPIs; distributions by category, subcategory, product, urgency, priority, sentiment, channel and status; register of the latest 500 complaints |
| `department-performance` | Department performance | Step 67 | Per department: primary and supporting volume, open, resolved, escalated, SLA breaches and breach rate, manual reviews, average resolution time and score; agent workload |
| `escalations` | Escalations | Step 67 | Totals, open and resolved, escalations enforced by the rules where the AI missed them, SLA-triggered; breakdown by level, rule and source; register |
| `sla-status` | SLA status | Step 67 | On track, at risk, breached and met; first-response compliance; targets and states per priority; open complaints at risk or breached, by due time |
| `policy-usage` | Policy usage | Step 67 | Documents and versions, quarantined sections, outdated sections used only as background; the most used sections (cited by AI, required by rules, retrieved); all document versions |
| `resolution-compliance` | Resolution compliance | Step 67 | Pass rate over 15 compliance checks (RES-001 to RES-004, ELG-001 to ELG-003, RSP-002, RSP-003, RSP-004, RSP-006, MIS-001, MIS-002, ESC-001, ESC-002); unsupported promises, prohibited actions and eligibility corrections caught; each failure |
| `genai-python-comparison` | AI vs rules comparison | Step 67, Deliverable 8 | The 14 columns the SRS lists (complaint, expected, AI and rules category, department, urgency and escalation, policy reference, match, verification, explanation of the disagreement), field agreement, summary; for operational complaints or for an evaluation run (`run_id`) |
| `manual-reviews` | Manual reviews | Step 67 | Pending, in review and completed reviews, average turnaround, reasons with their REV rule, outcomes, reviewer actions, register |
| `complaint-intelligence` | Complaint intelligence (shown as "Complaint insights" on the Reports page) | Deliverable 9 | See Section 39.4 |
| `security` | Security and adversarial testing | Deliverable 10 | Manipulation attempts, Adversarial Lab results with the checks that caught each defect, deliberate-defect outcomes, quarantined sections, failed logins and denied access, controls |

## 39.3 Scope and filters

Every report accepts the same scope parameters, collected in `ReportParams`: `date_from` and `date_to` (applied to the submission date), `department`, `category`, and for the comparison report `run_id`. By default the scope is all operational complaints (sources `web`, `api` and `dataset`), so Adversarial Lab and evaluation complaints never mix into operational figures. The scope is printed in the header of each report ("Scope: all operational complaints", or for example "2026-06-01 to 2026-06-30, department DEPT-LOG") together with the AI provider and model. The Reports page (Figure 39.2) shows for each report whether it follows the filters. Most do ("Uses filters"). The policy usage report is "Partly filtered": its most-used-sections table covers all operational complaints and only the outdated-section counts follow the filters. The security report covers the "Whole system".

![Figure 39.2 — Reports & exports: scope filters, and preview or CSV, Excel and PDF export for each report](../screenshots/22-reports-and-exports.png)
*Figure 39.2 — Reports & exports: scope filters, and preview or CSV, Excel and PDF export for each report*

## 39.4 The Complaint Intelligence Report

The Complaint Intelligence Report is built by `complaint_intelligence` in `builders.py`. It reuses the summary and three distributions of the complaint analysis report and adds the sections Deliverable 9 lists. The generated copy in `reports/complaint_intelligence/complaint-intelligence.pdf` (3 pages, generated 25 September 2026 at 11:53 UTC, scope all operational complaints, AI model openai gpt-4.1-mini) and its Excel twin `complaint-intelligence.xlsx` contain the values in Table 39.2. The workbook has a Summary sheet holding the metrics and the trend bullets, and one sheet per table: By category, By priority, By sentiment, By department, By escalation level, Repeat complaints, Policy usage, and AI vs rules disagreements.

**Table 39.2 — Deliverable 9 items and their content in the generated report**

| Deliverable 9 item | Report section | Values in the generated report |
|---|---|---|
| Category distribution | Distributions: by category | Billing 82 (13.2%), Delivery 73 (11.7%), Refund 71 (11.4%), Product Defect 65 (10.5%) … Staff Behavior 32 (5.1%), Unclassified 18 (2.9%) |
| Priority distribution | Distributions: by priority | P2 310 (49.8%), P3 178 (28.6%), P0 94 (15.1%), P1 22 (3.5%), not set 18 (2.9%) |
| Sentiment distribution | Distributions: by sentiment | Neutral 304 (48.9%), Negative 177 (28.5%), Strongly Negative 119 (19.1%), Positive 4 (0.6%), not set 18 (2.9%) |
| Department routing | Department routing | Technical Support 102 (16.4%), Returns & Refunds 92 (14.8%), Logistics Support 88 (14.1%) … Account Security 38 (6.1%), not routed 18 (2.9%) |
| Escalations | Escalations and SLA risk | 203 escalated, 34 at Critical Management Escalation; by level: Supervisor Review 59, Compliance Review 41, Specialist Team 41, Critical Management Escalation 34, Department Manager 28 |
| SLA risk | Escalations and SLA risk | 5 open complaints at risk, 156 open complaints breached |
| Repeat complaints | Repeat complaints | 22 repeat complaints from 16 customers; top customers listed (CUST-10114 with 3) |
| Policy usage | Policy usage | Top 15 sections with AI and rule citations, led by REF-POL-02 section 4.3 (62 AI, 36 rules) and ESC-SOP-12 section 4.1 (26, 49) |
| GenAI/Python disagreements | AI vs rules disagreements | Mismatches per field: sentiment 352, follow-up type 350, refund eligibility 257, priority 240, urgency 208 … department 53, entities 34, follow-up required 31, resolution 27 |
| Manual-review cases | Manual-review cases | 132 in Manual Review, 301 Human Verified |
| (added) Summary | Summary | 622 complaints, 168 open, 454 resolved or closed, 472 verified, 22 repeat, 18 duplicates, average resolution 96.4 h, average verification score 87.8, 32 manipulation attempts, 7 channels |
| (added) Emerging trends | Emerging trends | 12 alerts, for example "Product Defect complaints rose from 2 to 12 in the last 14 days" |

Two notes help read the report correctly. The average verification score in the report (87.8) counts the 18 unanalysed duplicates as 0; the dashboard's 90.4 averages analysed complaints only. The Human Verified count includes 300 approvals written by the labelled demo time-lapse (Chapter 38), and the resolution time depends on the same simulated history.

## 39.5 The other reports and their recorded figures

`scripts/export_deliverables.py` regenerates every deliverable file from the live database. Its header states that everything is "generated from live data - nothing is typed in by hand". Table 39.3 lists the headline figures of the operational reports as generated on 25 September 2026.

**Table 39.3 — Headline figures of the generated operational reports**

| File (`reports/operations/`) | Pages | Headline figures |
|---|---|---|
| `complaint-analysis.pdf` / `.xlsx` | 15 | 622 complaints, 203 escalated, 472 verified, 132 in manual review; eight distributions; register of the latest 500 |
| `department-performance.pdf` / `.xlsx` | 1 | Ten department rows including Management Escalations (59 supporting, 0 primary) and the agent workload |
| `escalations.pdf` / `.xlsx` | 12 | 317 escalations on 203 complaints, 89 open, 228 resolved, 35 enforced by the rules where the AI missed them, 115 SLA-triggered; ESC-039 fired 115 times, ESC-007 37 times |
| `sla-status.pdf` / `.xlsx` | 3 | 604 tracked: 7 on track, 5 at risk, 226 breached, 366 met; first response met 336 times |
| `policy-usage.pdf` / `.xlsx` | 3 | 24 documents, 29 versions (23 Active, 5 Superseded or Previous), 4 quarantined sections, 1,145 outdated sections used as background only |
| `resolution-compliance.pdf` / `.xlsx` | 9 | 604 complaints validated, 6,487 compliance checks, pass rate 80.9%; 0 unsupported promises, 38 prohibited actions and 119 eligibility corrections caught |
| `manual-reviews.pdf` / `.xlsx` | 8 | 433 reviews, 132 pending, 301 completed; reasons led by REV-002 (255) and REV-005 (156) |

The resolution compliance report shows the effect of the design. RSP-002 ("No unsupported promises") did not fail once on the 604 operational complaints. The customer response is drafted by the GenAI from the validated decision, not from the model's own analysis, so the unsupported promises occur in the analysis instead: prohibited actions in the proposed steps (RES-002, 37 failures) and eligibility the rules do not grant (ELG-001 to ELG-003, 119 corrections). Pipeline 2 catches those before the response is written.

## 39.6 Case report and other exports

**Table 39.4 — Exports besides the report catalogue**

| Export | Endpoint and permission | Formats and limits | Content |
|---|---|---|---|
| Case report | `GET /api/v1/complaints/{ref}/report.pdf`, `complaint:read_all` | PDF | Complaint and facts, final decision checked against the rules, AI vs rules, validation checks with review reasons, policy evidence, customer response, escalations, manual review, timeline, traceability (Chapter 37) |
| Complaint list | `GET /api/v1/complaints-export`, `reports:export` | CSV and Excel up to 10,000 rows, PDF up to 500 | 20 columns: reference, date, title, customer, customer type, channel, category, subcategory, department, urgency, priority, sentiment, status, verification status and score, escalation level, SLA state, repeat, duplicate and injection flags |
| Audit log | `GET /api/v1/audit/export`, `audit:read` | CSV, Excel or PDF, up to 20,000 rows | Entry, time, actor, role, action, entity, summary, hash |
| Rule Matrix | `GET /api/v1/rules/export`, `rules:read` | CSV, PDF, Excel, YAML | The complete live Rule Matrix |
| Evaluation run | `GET /api/v1/evaluation/runs/{id}/report`, `reports:export` | PDF, Excel, CSV | The comparison report for that run (Section 39.9) |

All downloads except the evaluation-run report write a `report.exported` audit entry; the evaluation-run endpoint (`api/v1/quality.py`) does not record one. The complaint-list export applies the list's search, status, category, subcategory, department, priority, urgency, sentiment, verification, SLA, channel, customer and source filters. It does not pass on the list's date range or its yes/no filters (escalated, needs review, repeat, duplicate, injection), which `export_complaints` in `api/v1/complaints.py` sets to `None`. Passing these filters through is a small correction (**Planned**).

## 39.7 Export safety

Report content includes untrusted text: complaint titles, customer wording and AI output. The renderer defends the export formats against it (`reporting/exports.py`).

**Table 39.5 — Protections in the export formats**

| Format | Protection | Test |
|---|---|---|
| CSV | Cells starting with `=`, `+`, `-`, `@`, a tab or a carriage return are prefixed with an apostrophe (formula-injection defence), control characters are removed, and the file starts with a UTF-8 byte-order mark so Excel reads the encoding correctly | `test_documents_exports.py::test_csv_neutralises_formula_injection` |
| Excel | Text that starts with `=` is forced to the string type so it can never become a formula; characters that are illegal in XLSX are removed; numbers stay numeric; the header row is frozen and filterable | `test_documents_exports.py::test_xlsx_never_contains_formulas` |
| PDF | Text is transliterated to the core-font character set (for example curly quotes and "≥"), and anything else is replaced; wide tables switch the page to landscape; every page shows the report title, the generation time and "fictional demo data" | `test_documents_exports.py::test_pdf_report_renders_unicode_safely` |
| JSON | Plain serialisation of the same model | `test_documents_exports.py::test_json_render_roundtrip` |

The CSV rule is visible in the generated files. In `genai-python-comparison.csv` the "-" placeholder of an empty explanation is written as `'-`, because it starts with a minus sign. The Excel and PDF versions of every report end with the statement that Lumora Home Technologies is a fictional organisation and that all customers, orders and policies are synthetic demo data. The end-to-end test downloads a case report PDF, a CSV report and an Excel export for a new complaint. It checks that the PDF starts with `%PDF`, that the CSV contains the new complaint's reference and that the Excel file is a ZIP archive (`test_full_chain.py::test_complete_complaint_chain`).

## 39.8 Generated evidence in `reports/`

**Table 39.6 — Files in `reports/`**

| Folder | Files | Contents |
|---|---|---|
| `complaint_intelligence/` | `complaint-intelligence.pdf`, `.xlsx` | Deliverable 9 (Section 39.4) |
| `genai_python_comparison/` | `genai-python-comparison.pdf`, `.xlsx`, `.csv`, `summary.md` | Deliverable 8 for evaluation run #1 on 154 unseen holdout cases; `summary.md` holds the run's metrics (Chapter 33) |
| `security_adversarial/` | `security.pdf`, `.xlsx`, `summary.md` | Deliverable 10; `summary.md` lists the 18 Lab scenarios with the checks that caught each one (18 of 18 met) |
| `operations/` | 7 reports as `.pdf` and `.xlsx` (14 files) | Step 67 reports (Table 39.3) |
| `rule_matrix/` | `complaint_resolution_rule_matrix.csv`, `.pdf`, `.xlsx`, `.yaml` | Deliverable 5: the Complaint Resolution Rule Matrix |
| `genai_pipeline_evidence/` | `provider_and_generation_config.json`, `prompt_templates_and_versions.json`, `sample_request_and_structured_response.json`, `invalid_response_and_retry.json`, `attempt_statistics.json` | Deliverable 6: provider and generation settings, all prompt versions with fingerprints, a sample request and structured response, three invalid-answer and retry examples, attempt statistics (1,560 valid, 31 invalid) |
| `python_validation_evidence/` | `README.md`, `examples.json` | Deliverable 7: one real check result per validation type, taken from the database |

The folder holds 34 files. They are generated by `scripts/export_deliverables.py`, which calls the report builders and the renderer directly. For that reason the exports left no `report.exported` entries in the audit log.

## 39.9 Defect found in the evaluation-run comparison export

While this chapter was being written, the per-case table of the Deliverable 8 files was found to be empty. In `genai-python-comparison.csv`, `.pdf` and `.xlsx`, all 154 case rows show "None/None" for the AI and rules categories and blank department, urgency and escalation columns. Every row is marked "Match", so the summary reports 154 full matches, 0 mismatches and no field agreement. The cause is a format mismatch. For evaluation runs, `genai_python_comparison` passes `EvaluationResult.comparison` to `_comparison_row`, which reads a list under the key `rows`. Evaluation results, however, store the comparison keyed by field (for example `{"category": {"ai": "TEC", "python": "TEC", "expected": "TEC", …}}`), as written by `services/evaluation.py`. The same builder serves `GET /evaluation/runs/{id}/report`, so the in-app download of a run's report is affected too. The operational comparison (without `run_id`), which reads `ValidationResult.comparison` with its `rows` list, is not affected.

The correct per-case data exists and can be shown. The Evaluation page displays the case-by-case comparison with the expected, AI and rules values and the explanation of every disagreement (Figure 33.2), and `GET /api/v1/evaluation/runs/1/results` returns it. `reports/genai_python_comparison/summary.md`, which is built from the run's stored metrics, carries the correct accuracy and agreement figures. The fix is to let the builder read the field-keyed structure for evaluation results and to extend `test_evaluation_run_on_unseen_holdout` so that it checks the content of the report, not only that the file starts with `%PDF`. Until then, the Deliverable 8 files have to be regenerated after the fix before they can serve as the per-case comparison (**Planned**).
