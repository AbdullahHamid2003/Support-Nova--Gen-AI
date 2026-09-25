# Chapter 2 — Requirements Analysis

This chapter analyses the requirements of the SupportNova Software Requirements Specification (SRS, Version 1.0) and states, for each one, how SupportNova implements it and what evidence shows that it works. Every requirement has a stable identifier taken from the requirements inventory (`documentation/traceability/srs-requirements-inventory.md`). **FR-NN** is development step NN of SRS 1.2, **FL-NN** is item NN of the functional-requirement list in SRS 1.6 (FL-01 = item i, FL-75 = item lxxv), and **NFR-N** is a non-functional requirement. P1, P2C and P2V are the Pipeline 1 and Pipeline 2 obligations of SRS 1.2, and ROL and STK are roles and stakeholders. Appendix A traces every identifier, including the dataset, competition-integrity and deliverable requirements, to its module, report chapter and verification.

The SRS writes most functional requirements with "should". Its boxed note in section 1.8, however, states that "it is a must to implement the FUNCTIONAL and NON-FUNCTIONAL requirements given in this SRS", so SupportNova treats all of them as mandatory.

Status labels follow the report convention. **Implemented** means code exists. **Configured** means the requirement is met through data or configuration, such as the Rule Matrix YAML. **Tested** means an automated test or a recorded run demonstrates it. **Planned** means designed but not built. Where the SRS demand is only partly satisfied, or not satisfied, the tables say **Partial** or **Not met** and give the reason. Python module paths are relative to `backend/src/supportnova/`. Tests are cited as `file.py::test_name`; their files are under `tests/backend/` and `tests/e2e/`.

## 2.1 Stakeholders

SRS 1.3 names the audience of the system: project stakeholders, developers, evaluators, customer-service teams, support managers, administrators and complaint-resolution specialists. SRS 1.6 (ii) and 1.7 (3) name the five user roles. The stakeholders and what SupportNova gives each of them are:

- **Customer (ROL-01).** A Lumora customer who submits a complaint, follows its progress and answers clarification questions. SupportNova provides a customer portal with a dashboard, the complaint form and a "My complaints" list. Customers see only their own complaints. The complaint page shows them the status, the updates, the replies that were sent and any requested information, but never the AI output or the internal validation (`api/serializers.py`).
- **Support agent (ROL-02).** Works the complaints of one department; the demo installation has one agent in each of the ten departments. New complaints are assigned automatically to the least-loaded agent of the department the rules chose. The agent workspace orders the queue by priority and shows the AI summary and guidance, the verification result, escalation and SLA warnings and the suggested response. An agent can send only responses that passed validation or were approved by a reviewer.
- **Reviewer (ROL-03).** Works the manual-review queue. The review workspace lists why a case needs review, shows the AI proposal next to the rule decision, and offers eight actions: approve, reject, modify, reclassify, reassign, escalate, regenerate the response, comment. Reviewers can also read analytics, reports, evaluation results and the Adversarial Lab.
- **Support manager (ROL-04).** Monitors complaint volumes, trends, SLA risk, escalations and validation performance on the operations dashboard, the Analytics page and the reports, and can act on reviews.
- **Administrator (ROL-05).** Manages users, the Knowledge Base, the Rule Matrix, the taxonomy, prompt versions and system settings, starts evaluation runs and verifies the audit chain.
- **Complaint-resolution specialist (STK-07).** A member of a specialist team that receives Specialist Team, Compliance Review or Critical Management escalations. In SupportNova this person holds the agent role in a specialist department: Product Safety (DEPT-SAF), Account Security (DEPT-SEC), Compliance & Privacy (DEPT-CMP) or Management Escalations (DEPT-MGT). Each escalation rule names the departments that must receive the case. The SRS defines five roles, so specialists have no separate role.
- **System evaluator (STK-03).** Checks the system with unseen complaints, revised policies, live modifications and deliberate defects (SRS 1.8). SupportNova provides demo accounts for every role, evaluator instructions (README section 3), an Evaluation page that accepts hidden datasets as JSON, JSONL or CSV, the Adversarial Lab, the Rule Matrix simulator and audit-chain verification.
- **Developers and project stakeholders (STK-01, STK-02).** Need code that can be understood, changed and tested. The backend is organised in 14 packages, named after the SRS folder list wherever the SRS names one (for example `complaint_processing`, `genai_pipeline`, `python_validation`, `hallucination_checks`). Rules, prompts and schemas are data, and 206 backend and 12 frontend tests pass.

## 2.2 User Roles and Permissions

Role-based access control is defined in `security/rbac.py`. The dictionary `ROLE_PERMISSIONS` gives each of the five roles a list of permission strings, 27 distinct permissions in total. Every protected endpoint of the REST API (95 routes under `/api/v1`) declares the permission it needs through the dependency `require()` in `api/deps.py`, so access is checked on the server for every request. The frontend reads the same permissions to decide which navigation entries and pages to show (`frontend/src/components/app/layout.tsx`, `frontend/src/App.tsx`), but hiding a page is a convenience, not the control. A customer is further restricted to their own complaints: `services/complaints.py::ensure_can_view` returns "not found" for any other complaint, and the complaint list filters by the customer's ID. Browser sessions use an HttpOnly access cookie. Every state-changing request must echo a CSRF token, and API clients may use a bearer token instead. Denied requests are written to the audit log.

**Table 2.1 — User roles**

| Role (code) | Purpose (`security/rbac.py`) | Permissions | Main screens |
|---|---|---|---|
| Customer (`customer`) | Submits complaints, tracks status, answers clarification requests | 3 | Customer portal, Submit complaint, My complaints |
| Support Agent (`agent`) | Works assigned complaints, sends validated responses, escalates | 10 | Agent workspace, Submit complaint, Complaints, Review queue (read), Knowledge base, Rule Matrix (read) |
| Reviewer (`reviewer`) | Works the manual review queue: approve, reject, modify, reclassify, regenerate | 14 | Quality overview, Complaints, Review queue and workspace, Knowledge base, Rule Matrix, Analytics, Reports, Evaluation, Adversarial Lab, Audit log (per complaint) |
| Support Manager (`manager`) | Monitors trends, SLA, escalations and validation performance | 12 | Operations overview, Complaints, Review queue and workspace, Knowledge base, Rule Matrix, Analytics, Reports, Evaluation, Audit log (per complaint), Administration (read) |
| Administrator (`admin`) | Manages users, knowledge base, rules, prompts and configuration | 24 | All screens, including Prompts & AI, evaluation runs, the full audit log with chain verification and export, Administration |

Table 2.2 lists every permission and the roles that hold it.

**Table 2.2 — Permission matrix**

| Permission | Customer | Agent | Reviewer | Manager | Admin |
|---|---|---|---|---|---|
| complaint:create | Yes | Yes | — | — | Yes |
| complaint:read_own | Yes | — | — | — | — |
| complaint:clarify_own | Yes | — | — | — | — |
| complaint:read_all | — | Yes | Yes | Yes | Yes |
| complaint:update | — | Yes | Yes | Yes | Yes |
| complaint:respond | — | Yes | Yes | — | Yes |
| complaint:reprocess | — | Yes | Yes | — | Yes |
| escalation:create | — | Yes | Yes | Yes | Yes |
| review:read | — | Yes | Yes | Yes | Yes |
| review:act | — | — | Yes | Yes | Yes |
| knowledge:read | — | Yes | Yes | Yes | Yes |
| knowledge:manage | — | — | — | — | Yes |
| rules:read | — | Yes | Yes | Yes | Yes |
| rules:manage | — | — | — | — | Yes |
| taxonomy:manage | — | — | — | — | Yes |
| prompts:manage | — | — | — | — | Yes |
| analytics:read_own | — | Yes | — | — | — |
| analytics:read | — | — | Yes | Yes | Yes |
| reports:export | — | — | Yes | Yes | Yes |
| evaluation:read | — | — | Yes | Yes | Yes |
| evaluation:run | — | — | — | — | Yes |
| lab:use | — | — | Yes | — | Yes |
| audit:read_complaint | — | — | Yes | Yes | Yes |
| audit:read | — | — | — | — | Yes |
| users:read | — | — | — | Yes | Yes |
| users:manage | — | — | — | — | Yes |
| settings:manage | — | — | — | — | Yes |

The matrix is tested on the server side. `test_security_api.py::test_role_permission_matrix_enforced_server_side` calls eleven protected endpoints as every role and expects access only for the permitted roles. `::test_unauthenticated_requests_are_rejected` covers nine endpoints without a session. `::test_customer_sees_only_own_complaints` checks the isolation between customers, and `::test_denied_access_is_audited` checks the audit entry for a refused request.

## 2.3 Functional Requirements

The SRS states its functional requirements in three places: the 68 development steps of section 1.2, the 75-item list of section 1.6, and the obligations for the two pipelines in section 1.2. Tables 2.3 to 2.20 group them by area. A development step and a 1.6 item that state the same requirement share one row. Tables 2.8 and 2.10 map the Pipeline 1 functions and the Pipeline 2 verification items of SRS 1.2 to the schema fields and checks that carry them.

### 2.3.1 Authentication and access

**Table 2.3 — Authentication and access requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-01 | Secure access for authorised users | `security/auth.py`: bcrypt password hashes (12 rounds), HS256 JWT in an HttpOnly cookie, CSRF double-submit token; `api/v1/auth.py`: account locked for 5 minutes after 5 failed logins; `api/middleware.py`: login rate limit of 20 per minute and security headers | Tested: `test_security_api.py::test_account_lockout_after_failed_logins`, `::test_cookie_session_requires_csrf_header`, `::test_security_headers`, `::test_spoofed_forwarded_for_does_not_bypass_login_rate_limit`; `test_perception_security.py::test_password_hashing_and_tokens` |
| FL-02, ROL-01 to ROL-05 | Permissions differ for customers, agents, reviewers, managers and administrators | `security/rbac.py` (5 roles, 27 permissions, Tables 2.1 and 2.2); `require()` in `api/deps.py` on every protected route; customer isolation in `services/complaints.py::ensure_can_view` | Tested: `test_security_api.py::test_role_permission_matrix_enforced_server_side` (11 cases), `::test_unauthenticated_requests_are_rejected` (9 cases), `::test_customer_sees_only_own_complaints`, `::test_denied_access_is_audited` |

### 2.3.2 Complaint management

**Table 2.4 — Complaint management requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-03, FR-09, SOL-02 | Submission of title, description, product/service, order reference, customer type, previous complaint reference, preferred contact channel and supporting information; SRS 1.2 adds transaction reference, channel, date, supporting documents and requested resolution | Complaint form `frontend/src/pages/SubmitComplaint.tsx`; `POST /api/v1/complaints` (`api/v1/complaints.py`); `services/complaints.py::create_complaint`; up to 5 attachments (PDF, PNG, JPEG, TXT, 5 MB each); the date is the submission time; complaint history is attached automatically | Tested: `test_full_chain.py::test_complete_complaint_chain`; screenshot `04-customer-submit-complaint.png` |
| FL-04, FR-10 | Detect empty and extremely short complaints, duplicates, invalid reference IDs, missing mandatory fields and unsupported attachments | `services/complaints.py::validate_submission`: title 5 to 180 characters; description 20 to 8,000 characters and at least 4 words; customer type and channel required; reference formats LMR-######, TXN-########, CMP-#####; a previous complaint must exist and belong to the customer. An exact resubmission within 24 hours is refused with HTTP 409. `security/files.py::validate_upload` checks type by content and extension, size and executables | Tested: `test_boundaries.py` (29 cases, e.g. `::test_description_length_edges`, `::test_order_reference_format`, `::test_malformed_body_is_a_field_error_not_a_crash`); `test_difficult_cases.py::test_exact_duplicate_rejected_and_near_duplicate_linked`; `test_perception_security.py::test_upload_validation_rejects_executables_and_mismatches` |
| FL-05, FR-11 | Whitespace and character normalisation, input sanitisation, metadata extraction, duplicate detection | `security/sanitization.py::normalize_text` (NFKC, invisible and control characters removed, HTML stripped, whitespace collapsed) and `text_hash`; `complaint_processing/perception.py` and `fact_builder.py` extract references, amounts, dates, products and risk signals; the original text is stored unchanged | Tested: `test_perception_security.py::test_normalisation_and_duplicate_hash`, `::test_entities_extracted` |
| FL-56, FR-52 | Detect exact duplicates, near-duplicates and repeated submissions | `services/history.py::analyse_history`: canonical text hash for exact duplicates; cosine similarity of at least 0.86 (`NEAR_DUPLICATE_THRESHOLD`) marks a near-duplicate, which is linked to the original and closed without opening a second case | Tested: `test_difficult_cases.py::test_exact_duplicate_rejected_and_near_duplicate_linked`; holdout run: 2 of 2 duplicates linked |
| FL-57, FR-53 | Keep previous complaints of the same simulated customer | `services/history.py` looks back 90 days (`repeat_window_days`, ESC-SOP-12 §4.5); each complaint keeps a timeline in `complaint_history` (`GET /complaints/{ref}/timeline`) | Tested: `test_difficult_cases.py::test_repeated_complaint_detected` |
| FL-58, FR-54 | Identify repeated unresolved complaints, which may receive higher escalation | A repeat is an earlier complaint of the customer with the cited reference, the same order, the same subcategory, or the same category and a similarity of at least 0.30; ESC-017 (2 unresolved earlier complaints), ESC-018 (3 or more) and ESC-019 (reopened) raise the escalation | Tested: `test_difficult_cases.py::test_repeated_complaint_detected`; holdout run: 4 of 4 repeats detected |
| FL-65, FR-60 | Track the lifecycle: New, Analyzed, Assigned, In Progress, Awaiting Customer, Escalated, Resolved, Closed, Reopened | `services/complaints.py`: `LIFECYCLE` holds the nine SRS statuses plus Processing, and `TRANSITIONS` lists the allowed moves; customers may reopen within 14 days of resolution (CHP-POL-01 §8.2) | Tested: `test_full_chain.py::test_complete_complaint_chain` (Escalated, In Progress, Resolved) |
| FL-71, FR-66 | Search by complaint ID, customer reference, category, department, priority, sentiment, status, date and escalation status | `GET /api/v1/complaints`: `q` (complaint ID, title, order, customer), `customer_ref`, `category`, `department`, `priority`, `sentiment`, `status`, `date_from` and `date_to`, `escalated`, plus urgency, verification, SLA state, channel, repeat, duplicate and injection; filter bar in `frontend/src/pages/Complaints.tsx` | Implemented; only the paging limits are tested (`test_boundaries.py::test_list_pagination_limits`); screenshot `07-complaint-list.png` |

### 2.3.3 Knowledge Base

**Table 2.5 — Knowledge Base requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FR-01 | Own fictional organisation; no real confidential data | `config/organization.yaml` (Lumora Home Technologies, consumer electronics and smart-home e-commerce, with a fictional-data disclaimer); `config/products.yaml` (15 products and services); `config/departments.yaml` (10); `config/taxonomy.yaml` (11 categories, 35 subcategories) | Configured |
| FR-02 | Knowledge base with complaint, refund, replacement, cancellation, billing, delivery, warranty and privacy policies, escalation procedure, complaint SOP, routing rules, service-level rules and FAQs | 24 documents in 29 versions (`knowledge_base/manifest.yaml`): CHP-POL-01, REF-POL-02, RPL-POL-03, CAN-POL-06, BIL-POL-05, DEL-POL-04, WAR-POL-07, PRV-POL-08, ESC-SOP-12, CHP-SOP-13, RTE-RUL-14, SLA-RUL-15, FAQ-GEN-16 and FAQ-BIL-17, plus 10 further documents such as SAF-POL-10, CPN-POL-11 and TPL-COM-18 | Configured; `test_documents_exports.py::test_knowledge_base_meets_srs_minimums` checks at least 20 documents, both mandatory formats and the presence of Active and older versions |
| FL-06, FR-03, SOL-03 | Administrators upload PDF and DOCX (TXT, Markdown and CSV optional) | Upload dialog on the Knowledge base page (`frontend/src/components/knowledge/UploadDocumentDialog.tsx`); `POST /api/v1/documents` (permission `knowledge:manage`); `document_processing/parsers.py::parse_document` for pdf, docx, md, txt and csv | Tested: `test_documents_exports.py::test_parse_sections_from_real_documents[pdf]`, `[docx]`; `test_full_chain.py::test_document_upload_and_policy_versioning_journey` (Markdown) |
| FL-07, FR-04 | Validate file type, file size, empty files, duplicates, document ID, version, effective and expiry dates and document category | `security/files.py::validate_upload` (magic bytes, 15 MB limit, empty files, executables, DOCX macro and archive-size guards); `document_processing/validation.py::validate_metadata` (ID pattern, numeric version, valid dates with expiry after effective date, category, status); `services/documents.py::ingest_document` (sha256 duplicate check, existing version, newer Active version) | Tested: `test_documents_exports.py::test_metadata_validation_and_version_order`, `::test_corrupted_document_is_rejected_cleanly`; `test_boundaries.py::test_upload_size_edge`; `test_security_api.py::test_executable_upload_rejected` |
| FL-08, FR-05 | Extract content keeping document ID, title, section, heading, page number, version and effective date | `document_processing/parsers.py`: PyMuPDF with font-based heading detection and page spans, python-docx heading styles, Markdown markers, numbered-heading fallback for unseen documents; stored in `document_sections` and `document_versions` | Tested: `test_documents_exports.py::test_parse_sections_from_real_documents[pdf]`, `[docx]`, `::test_pdf_keeps_repeated_body_text_and_reads_tables_by_row` |
| FL-09, FR-06, SOL-04 | Traceable chunks keeping chunk ID, document ID, section, heading, page reference and version | `document_processing/chunking.py` (`chunk_uid` = `<DOC_ID>@<version>#<section>-c<n>`); `document_chunks` with page start and end and the embedding; 484 chunks in the demo database | Tested indirectly: `test_full_chain.py::test_document_upload_and_policy_versioning_journey` (search results carry document ID and version) |
| FL-10, FR-07 | Distinguish Active, Previous, Superseded and Draft; outdated policy never the primary basis | A new Active version demotes the old one to Previous and older ones to Superseded (`services/documents.py`); only Active, effective, non-quarantined chunks can be evidence (`knowledge_base/store.py`); precedence rules PRC-001 to PRC-005; check POL-002 (critical) | Tested: `test_defects_and_live_changes.py::test_revised_policy_upload_versioning_and_impact`; `test_full_chain.py::test_complete_complaint_chain` (all evidence Active) |
| FL-22, FR-25 | Retrieve relevant approved sections with source traceability | `knowledge_base/retriever.py`: BM25 and vector search, rule-guided expansion with the sections the Rule Matrix cites, reciprocal-rank fusion; every evidence item carries document ID, version, status, section, heading and chunk ID; outdated versions appear only as context | Tested: `test_full_chain.py::test_complete_complaint_chain`; `test_defects_and_live_changes.py::test_revised_policy_upload_versioning_and_impact` (only version 2.1 returned) |

### 2.3.4 Rule management

**Table 2.6 — Rule management requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-11, FR-08, SOL-05 | Structured Rule Matrix of approved complaint-handling logic, not generated at runtime by the GenAI model | YAML baseline in `rules/` (276 rule rows and 14 configuration rows, with a ruleset hash) loaded by `rule_engine/loader.py`; live, editable copy in the `rules` table (`services/rules.py`); every rule cites policy sections; the AI receives the code catalogues it must choose from, never the rules themselves | Tested: `test_rule_engine.py::test_rule_matrix_integrity`, `::test_rule_matrix_meets_srs_minimums`; exported as `reports/rule_matrix/complaint_resolution_rule_matrix.csv` |
| FR-14 | Predefined, configurable categories | Categories and subcategories are database rows seeded from `config/taxonomy.yaml`; `POST /api/v1/taxonomy/categories` and `/taxonomy/subcategories` (permission `taxonomy:manage`) add them at runtime, and a new subcategory receives routing, resolution and classification rules | Tested: `test_defects_and_live_changes.py::test_new_category_without_code_changes` |
| FR-20 | Configurable priority rules | The priority matrix (urgency by impact) and 15 urgency floors in `rules/complaint_rules/priority_rules.yaml`, editable as the configuration row `priority_config` and the rule type `urgency_floor` | Tested: `test_rule_engine.py::test_priority_matrix` (8 cases) |
| CI-14 | Live modification of categories, routing rules, priority logic, departments, escalation thresholds and SLAs (SRS 1.8 (14)) | `PUT /rules/{rule_type}/{rule_id}`, `POST /rules/validate` (preview without saving), `POST /rules/simulate`, `PUT /rule-parameters/{key}`, `POST /taxonomy/departments`, `POST /rules/reset-to-baseline`; each edit is checked for integrity before it is saved, then versioned and audited | Tested: `test_defects_and_live_changes.py::test_rule_edit_preview_validates_without_saving`, `::test_changing_a_rule_parameter_changes_the_decision`, `::test_disabling_an_escalation_rule_changes_validation` |

### 2.3.5 GenAI Complaint Intelligence Pipeline

**Table 2.7 — GenAI Complaint Intelligence Pipeline requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-12, SOL-08, SOL-09 | Integrate an approved GenAI API; send complaint information, customer context and approved knowledge | `genai_pipeline/providers/` (`http_providers.py` for OpenAI and Gemini, `anthropic_provider.py` for Anthropic), chosen by `AI_PROVIDER` and `AI_MODEL`; `genai_pipeline/context.py` builds the evidence, policy conflicts, verified facts and the nonce-tagged complaint block | Tested: `test_genai_providers.py` (31 tests, e.g. `::test_openai_request_uses_strict_json_schema`, `::test_factory_selects_the_configured_provider`); recorded: 780 completed analyses with openai / gpt-4.1-mini |
| FL-43, SOL-11 | Predefined structured JSON; free text not the only output | `schemas/ai/complaint_analysis.v1.schema.json`, 37 required fields, which keep the names of the SRS sample output (issue_category, subcategory, sentiment, urgency, priority, department, policy_id, policy_section, resolution_steps, escalation_required, response_type, follow_up_required), and `customer_communication.v1` (7 fields); strict structured output with live code enums (`genai_pipeline/schemas.py::constrain_codes`) | Tested: `test_genai_providers.py::test_structured_output_schema_uses_only_supported_keywords` (4 cases); `reports/genai_pipeline_evidence/sample_request_and_structured_response.json` |
| FL-13, FR-12 | Identify the primary issue | Fields `primary_issue` (label, category, subcategory, evidence quote), `summary` and `key_facts`; the 11 categories are the SRS examples | Tested: category assertions in `test_difficult_cases.py`; holdout: AI category accuracy 89.5% |
| FL-14, FR-13 | Distinguish primary and secondary issues | Field `secondary_issues`; Python keeps its own secondary list (CLS-003) and applies risk-first precedence (SAF, ACC-UNA, PRV, legal, BIL, PRD, DEL, WAR, then the rest) | Tested: `test_difficult_cases.py::test_multi_issue_multi_department` |
| FL-15, FR-14, FR-15 | Category and subcategory classification | `issue_category` and `subcategory`, restricted to the 11 categories and 35 subcategories (e.g. BIL-DUP, BIL-INC, BIL-RFM, BIL-SUB); checks SCH-002, CLS-001, CLS-002 | Tested: `test_perception_security.py::test_classification_categories` (5 cases); holdout: subcategory accuracy AI 77.6%, Python 68.4% |
| FL-16, FR-16 | Extract product, service, order ID, transaction ID, date, amount, location, department and complaint reference | Entity types in `genai_pipeline/schemas.py` (the nine SRS types plus person and other); Python extracts references and amounts itself (`complaint_processing/perception.py`); checks CLS-005 and HAL-002 | Tested: `test_perception_security.py::test_entities_extracted`; `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[hallucinated_entity-HAL-002]` |
| FL-17, FR-17 | Sentiment: Positive, Neutral, Negative, Strongly Negative | `sentiment` enumeration; a Python lexicon estimate is used for comparison only (CLS-004, severity info) | Tested: `test_perception_security.py::test_sentiment_is_informational` |
| FR-18 | Emotion and tone indicators that do not replace priority rules | `emotion_indicators` (Frustration, Anger, Disappointment, Confusion, Urgency, plus Anxiety and Satisfaction); never an input to urgency; check PRI-003 | Tested: `test_rule_engine.py::test_emotional_language_does_not_raise_priority` |
| FL-18, FL-19, FR-19, FR-20 | Determine urgency (Low to Critical) and priority (P0 to P3), not solely from emotional wording | The AI proposes `urgency`, `impact`, `priority` and `urgency_rationale`; Python sets them from the resolution rule, the urgency floors and the priority matrix; checks PRI-001 (critical) to PRI-004 | Tested: `test_difficult_cases.py::test_calm_critical_safety_complaint`, `::test_angry_low_priority_complaint`; holdout: urgency accuracy Python 84.2%, AI 68.4% |
| FL-24, FR-27 | Generate resolution steps grounded in approved rules | `resolution_steps`, each with an `action_code` from the 66-action catalogue and a policy reference; SCH-006 rejects unknown actions | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FL-29, FR-32 | Professional response that acknowledges, empathises, summarises, explains the next step, avoids unsupported promises, quotes only supported timelines and uses professional language | Second call with prompt `customer_communication` 1.0.0, which is given the validated decision instead of the raw AI analysis, together with the allowed timelines, the clarification questions, the follow-up, the cited evidence and the complaint in its untrusted block; RSP-001 checks acknowledgement, empathy, summary and next step | Tested: `test_full_chain.py::test_complete_complaint_chain` (response drafted and validated) |
| FL-30, FR-33 | Configurable tone: Professional, Empathetic, Concise, Formal | Tone chosen on submission (`requested_tone`) or when a reviewer regenerates the response; RSP-005 checks it | Implemented; no dedicated test |
| FL-41, FR-44 | Concise structured summary for agents | `summary` and `key_facts`; the validated summary removes spans flagged as injected instructions; HAL-003 | Tested: `test_perception_security.py::test_validated_summary_never_relays_flagged_instructions` |
| FL-42, FR-45 | Internal agent guidance | `agent_guidance`; the validated decision carries checked guidance, shown on the agent dashboard | Tested: `test_full_chain.py::test_complete_complaint_chain` (validated guidance present) |
| FR-47 | Detect invalid output, retry in a controlled way, log the failure, never retry forever, send unresolved failures to manual review | `genai_pipeline/runner.py::run_stage`: at most 1 + `AI_MAX_RETRIES` (2) attempts; validation errors are sent back to the model; back-off for rate limits and connection errors; every attempt stored in `ai_runs`; with no usable answer SCH-001 fails and REV-009 opens a review | Tested: `test_genai_providers.py::test_invalid_json_is_retried_with_the_validation_errors_then_accepted`, `::test_retries_are_bounded_and_the_failure_is_reported`, `::test_transient_errors_are_retried_but_authentication_errors_are_not`; `test_ai_not_configured.py::test_no_api_key_means_no_ai_output_and_manual_review`; `reports/genai_pipeline_evidence/invalid_response_and_retry.json` |
| FL-52, FR-48 | Prompts centrally stored and versioned | `prompts/<key>/<version>.yaml` (complaint_analysis 1.0.0, 1.1.0, 1.2.0; customer_communication 1.0.0), seeded into `prompts` and `prompt_versions` with sha256 fingerprints; administrators create and activate versions on the Prompts & AI page; the only instruction text in Python is the fixed validation-feedback sentence added on a controlled retry (`genai_pipeline/runner.py`, `providers/base.py`) | Implemented; recorded in `reports/genai_pipeline_evidence/prompt_templates_and_versions.json` |
| FL-53, FR-49 | Each analysis stores prompt version, provider, model, timestamp and policy version | `analyses`: `prompt_versions` (key, version, sha256), `provider`, `model`, `created_at`, `completed_at`, `policy_versions`, `ruleset_hash`, `stage_timings`; one row per attempt in `ai_runs` | Implemented; recorded for all 780 analyses and shown on the complaint's AI runs tab and the Prompts & AI page (screenshot `19-prompts-and-ai.png`) |

Table 2.8 shows where each Pipeline 1 function required by SRS 1.2 (SOL-10) appears in the structured output. Every field is present in every answer, because the schema marks all fields as required and optional values are nullable.

**Table 2.8 — Pipeline 1 functions and the output fields that carry them**

| ID | Function (SRS 1.2) | Field in complaint_analysis.v1 or customer_communication.v1 |
|---|---|---|
| P1-01 | Analyse the complaint | summary, key_facts, claims |
| P1-02 | Primary issue | primary_issue |
| P1-03 | Category | issue_category |
| P1-04 | Subcategory | subcategory, secondary_issues |
| P1-05 | Sentiment | sentiment, emotion_indicators |
| P1-06 | Urgency | urgency, urgency_rationale, impact |
| P1-07 | Priority | priority |
| P1-08 | Entities | entities |
| P1-09 | Responsible department | department, supporting_departments |
| P1-10 | Relevant policies | policy_references (policy_id, section, evidence_id, applicability, reason), policy_id, policy_section |
| P1-11 | Resolution steps | resolution_steps, refund_eligibility, replacement_eligibility, compensation_eligibility |
| P1-12 | Escalation requirement | escalation_required, escalation_level, escalation_reason |
| P1-13 | Escalation notes | escalation_notes (summary, key_facts, reason, actions_taken, relevant_policy, required_next_action) |
| P1-14 | Professional response | customer_communication: subject, customer_response, tone |
| P1-15 | Follow-up communication | follow_up_required, follow_up_type; customer_communication: follow_up_message |
| P1-16 | Agent guidance | agent_guidance |
| P1-17 | Clarification questions | missing_information, clarification_questions |

### 2.3.6 Python Ground-Truth Validation

**Table 2.9 — Validation requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-44, FR-46 | Validate required fields, data types, category and urgency values, department IDs, policy IDs and escalation status | `genai_pipeline/parsing.py`: JSON extraction, jsonschema (Draft 2020-12) against the committed schema, then the Pydantic model; SCH-001 to SCH-006 in `python_validation/engine.py` (taxonomy, departments, policy IDs and sections in the Knowledge Base, escalation consistency, action codes) | Tested: `test_genai_providers.py::test_schema_violation_is_retried`; `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[hallucinated_policy-SCH-004]` |
| FL-45, SOL-07, SOL-12, SOL-15 | Independent Python validation that never uses GenAI to approve Pipeline 1 and does not accept the AI answer by default | `python_validation/engine.py` (`run_phase_a`, `run_phase_b`, `finalize`) with `rule_engine/decision.py`; no module in `python_validation/`, `rule_engine/` or `hallucination_checks/` imports a GenAI provider; the rules override the AI on every decision field | Tested: `test_rule_engine.py::test_decision_engine_trace_is_explainable`, `::test_reference_labels_reproduce_dataset`; holdout: Python key-field accuracy 82.7% against 79.2% for the AI |
| SOL-13, SOL-14 | Compare with the ten references P2C-01 to P2C-10 and verify the seventeen items P2V-01 to P2V-17 | See Table 2.10 | Implemented |
| FL-46 to FL-49 | Compare GenAI and Python category, department, urgency and escalation | `engine.py::build_comparison` stores one row per field (AI value, rule value, match, explanation) in `validation_results.comparison`; shown as the "AI vs rules" tab (`frontend/src/components/complaint/ComparisonPanel.tsx`) | Tested: `test_full_chain.py::test_complete_complaint_chain`; holdout agreement: category 69.7%, department 84.9%, urgency 66.5%, escalation level 82.9% |
| FL-23, FR-26 | Classify each referenced policy as Applicable, Conditionally Applicable, Not Applicable or Outdated | `engine.py::assess_applicability`; each AI citation carries an `applicability` value that POL-005 compares; results are stored in `policy_references` | Implemented; all four values occur in the demo database; no dedicated test |
| FL-50 | Generated actions reference approved sources | The validated decision cites the policy sections of the selected rule; POL-001 to POL-004, SCH-004, HAL-004 | Tested: `test_perception_security.py::test_fake_policy_ids_versions_sections`; example in `reports/python_validation_evidence/README.md` (POL-003) |
| FL-51 | Verification score from consistency and compliance measures | `engine.py::finalize`: score = 100 × Σ(weight × value) / Σ weight over applicable checks, weights critical 5, major 3, minor 1, info 0, values pass 1, warn 0.5, fail 0; Verified requires no critical failure, score ≥ 80 (`rules/validation_policy.yaml`) and no review trigger | Implemented; exercised by every pipeline test; no unit test of the formula itself |
| FL-31, FR-34 | Flag guaranteed refunds, guaranteed compensation, unsupported delivery deadlines and unauthorised policy exceptions | `hallucination_checks/promises.py` with the prohibited-action patterns in `config/actions.yaml` (PROMISE_REFUND_BEFORE_VERIFICATION, GUARANTEE_COMPENSATION, CASH_COMPENSATION, GRANT_POLICY_EXCEPTION, UNSUPPORTED_DELIVERY_DEADLINE); checks RSP-002, RSP-003, RSP-006 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[unsupported_refund-RSP-002]`, `[prohibited_action-RSP-006]` |
| FL-32, FR-35 | Flag factual claims not traceable to the complaint, policy, knowledge base or rule matrix | `hallucination_checks/grounding.py` (claim grounding that accepts paraphrase); HAL-001 to HAL-004 | Tested: `test_perception_security.py::test_claim_grounding_accepts_paraphrase_but_not_invented_facts`; `test_difficult_cases.py::test_product_name_is_not_a_hazard` |
| FR-21 | Handle the tricky priority cases and keep sentiment separate from urgency | Urgency and priority come only from rules and signals; customer type never changes them (SLA-RUL-15 §5.4); signals for legal threats, repeats and failed replacements | Tested: `test_difficult_cases.py::test_angry_low_priority_complaint` (angry VIP customer), `::test_calm_critical_safety_complaint`, `::test_privacy_exposure`, `::test_escalation_for_legal_threat`, `::test_repeated_complaint_detected`; the development set holds 23 VIP-minor and 5 low-value privacy cases |
| FL-76 | Source-grounded, validated intelligence instead of a GenAI pass-through | The complete chain of Figure 1.1: retrieval, Pipeline 2, validated decision, response checks | Tested: `test_full_chain.py::test_complete_complaint_chain` |

Table 2.10 maps each item that SRS 1.2 requires Pipeline 2 to verify to the checks that verify it and to the reference it is compared with (P2C). Chapter 11 describes the checks.

**Table 2.10 — Pipeline 2 verification items and the checks that perform them**

| ID | Item (SRS 1.2) | Checks | Reference compared with |
|---|---|---|---|
| P2V-01 | Complaint category | SCH-002, CLS-001 | Complaint-category rules (P2C-06) |
| P2V-02 | Complaint subcategory | SCH-002, CLS-002, CLS-003 | Complaint-category rules (P2C-06) |
| P2V-03 | Department assignment | SCH-003, RTE-001, RTE-002 | Department-routing rules (P2C-02) |
| P2V-04 | Urgency | PRI-001, PRI-003 | Urgency thresholds and resolution rules (P2C-03, P2C-08) |
| P2V-05 | Priority | PRI-002, PRI-004 | Priority matrix in the Rule Matrix (P2C-01) |
| P2V-06 | Mandatory escalation | ESC-001, ESC-002, ESC-003, SCH-005 | Escalation rules (P2C-04) |
| P2V-07 | Policy applicability | POL-005 | Approved policy versions (P2C-05) |
| P2V-08 | Policy version | POL-002, POL-006 | Approved policy versions and document metadata (P2C-05, P2C-10) |
| P2V-09 | Resolution eligibility | ELG-001, ELG-002 | Customer eligibility rules (P2C-07) |
| P2V-10 | Required actions | RES-001, RES-003 | Resolution rules (P2C-08) |
| P2V-11 | Prohibited actions | RES-002, RSP-006 | Resolution rules and action catalogue (P2C-08) |
| P2V-12 | Compensation eligibility | ELG-003, RSP-002 | Customer eligibility rules and parameters (P2C-07) |
| P2V-13 | Follow-up requirements | FUP-001, FUP-002, RSP-007 | Follow-up requirements (P2C-09) |
| P2V-14 | Source-document references | SCH-004, POL-001, POL-003, POL-004, HAL-004 | Source-document metadata (P2C-10) |
| P2V-15 | Unsupported generated claims | HAL-001, HAL-002, HAL-003, RSP-003, RSP-004 | Complaint text, retrieved evidence, verified facts |
| P2V-16 | Contradictory instructions | RES-004, POL-006, SEC-001 | Resolution rules, precedence rules |
| P2V-17 | Missing mandatory actions | RES-001 (raised to critical when a safety, security, privacy or escalation action is missing) | Resolution rules (P2C-08) |

### 2.3.7 Routing

**Table 2.11 — Routing requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-20, FR-22 | Recommend a responsible department (Billing, Technical Support, Logistics, Returns, Warranty, Customer Relations, Account Security, Compliance, Safety, Management Escalations) | The ten departments in `config/departments.yaml` match the SRS list (DEPT-BIL, DEPT-TEC, DEPT-LOG, DEPT-RET, DEPT-WAR, DEPT-CRL, DEPT-SEC, DEPT-CMP, DEPT-SAF, DEPT-MGT); AI field `department`; automatic assignment to the least-loaded agent of the department (`services/pipeline.py::_auto_assign`) | Tested: `test_difficult_cases.py::test_normal_delayed_delivery` (DEPT-LOG) |
| FR-23, FL-47 | Python independently verifies the department with the Rule Matrix | 35 routing rules and 6 conditional routing rules in `rules/routing_rules/routing_rules.yaml` with a routing precedence; RTE-001 (critical) | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[wrong_department-RTE-001]`; lab scenario LAB-DEF-02; holdout: Python department accuracy 84.9% |
| FL-21, FR-24 | Primary and supporting departments for multi-department complaints | Routing rules name supporting departments and secondary issues add theirs; AI field `supporting_departments`; RTE-002 | Tested: `test_difficult_cases.py::test_multi_issue_multi_department`; holdout: supporting-department accuracy Python 74.3% |

### 2.3.8 Resolution and eligibility

**Table 2.12 — Resolution and eligibility requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-25, FR-28 | Verify that mandatory steps are present; detect prohibited or unsupported actions | 116 resolution rules with required, recommended and prohibited actions; RES-001 (critical when a safety, security, privacy or escalation action is missing), RES-002 (critical), RES-003, RES-004 (contradictions such as PROCESS_REFUND while the refund is not eligible), SCH-006 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[prohibited_action-RSP-006]`; lab scenario LAB-DEF-05 (RES-002 caught) |
| FL-26, FR-29 | Refund eligibility decided by approved rules, not GenAI opinion | Eligibility from the selected resolution rule and the order facts (`complaint_processing/order_facts.py`: refund window 30 days, 45 for Care+ members, defect window 30 days); ELG-001 | Tested: `test_difficult_cases.py::test_unsupported_refund_request`; `test_boundaries.py::test_refund_window_edge` (0, 29, 30, 31 and 365 days); holdout: refund eligibility Python 93.4%, AI 60.5% |
| FL-27, FR-30 | Replacement checked against product condition, purchase period, policy, previous replacement and other conditions | Order facts `within_doa_window`, `within_defect_window`, `within_warranty` and `replacement_limit_reached` (parameter `max_policy_replacements`); signals `misuse_damage`, `replacement_failed`, `photo_evidence`; ELG-002 | Implemented; lab scenario LAB-POL-02 (ELG-002 caught); holdout: replacement eligibility Python 93.4%, AI 85.5%; no dedicated unit test |
| FL-28, FR-31 | Python verifies whether proposed compensation is permitted; unsupported promises flagged | Compensation limits from CPN-POL-11 (`agent_compensation_limit_usd` 25, `supervisor_compensation_limit_usd` 100); ESC-029 and ESC-030 escalate larger claims; ELG-003, RSP-002 | Tested: `test_difficult_cases.py::test_unsupported_compensation_request`; lab scenarios LAB-CMP-01, LAB-CMP-02 |

### 2.3.9 Escalation

**Table 2.13 — Escalation requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-33, FR-36 | Determine whether escalation is required: safety, security breach, privacy, repeated unresolved complaint, legal concern, high-value dispute, severe service failure, critical customer impact, policy exception | 39 rules in `rules/escalation_rules/escalation_rules.yaml`: safety ESC-001 to ESC-008, security ESC-009 to ESC-011, privacy ESC-012 to ESC-015, legal ESC-016, repeats ESC-017 to ESC-019, high value ESC-020 to ESC-023, service failure ESC-024, critical impact ESC-025 and ESC-026, policy exception ESC-027 to ESC-031, staff conduct ESC-032 to ESC-034, public media and chargeback threats ESC-035 and ESC-036, failed replacement ESC-037, warranty appeal ESC-038, SLA breach ESC-039 | Tested: `test_rule_engine.py::test_safety_signal_forces_critical_escalation`; `test_difficult_cases.py::test_escalation_for_legal_threat`, `::test_security_account_takeover`, `::test_privacy_exposure` |
| FL-34, FR-37 | Levels: No Escalation, Supervisor Review, Department Manager, Specialist Team, Compliance Review, Critical Management Escalation | The six SRS levels, ranked 0 to 5 in `escalation_rules.yaml` (ESC-SOP-12 §3); when several rules fire, the highest level applies | Tested: `test_rule_engine.py::test_escalation_level_ranking` |
| FL-35, FR-38 | Internal notes with complaint summary, key facts, reason, actions taken, relevant policy and required next action | Schema object `escalation_notes` with exactly these six fields; SCH-005 requires notes when a case is escalated, ESC-004 requires all six elements; stored in `escalations.notes` | Implemented; example in `reports/python_validation_evidence/README.md` (ESC-004 on CMP-00396); no dedicated test |
| FL-36, FL-49, FR-39 | Python independently enforces mandatory escalation; a critical complaint never stays un-escalated because GenAI missed it | ESC-001 (critical) and ESC-002; `services/pipeline.py` creates the escalation from the rule decision, with source "rule" when the AI missed it, and the timeline records "the AI missed it, the rules require it" | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[missed_escalation-ESC-001]`; lab scenario LAB-DEF-01; demo database: 47 escalations raised by the rules alone |

### 2.3.10 Follow-up, missing information and SLA

**Table 2.14 — Follow-up, missing-information and SLA requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-37, FR-40 | Follow-up communication: request for information, resolution confirmation, refund-status update, replacement-status update, escalation acknowledgement, closure confirmation | The six SRS types in `rules/complaint_rules/followup_rules.yaml`; AI fields `follow_up_type` and `follow_up_message`; FUP-001, FUP-002 and RSP-007 (follow-up message safe to send) | Implemented; demo database: 747 follow-ups of five types; no dedicated test |
| FL-38, FR-41 | Record when a complaint requires follow-up | `follow_ups` rows with type, message, due time from the rule's `due_hours`, status and source rule; a Closure confirmation is scheduled 48 hours after resolution (FUP-003); `POST /complaints/{ref}/follow-ups/{id}/complete` | Implemented; no dedicated test |
| FL-39, FR-42 | Identify complaints missing an order number, transaction date, product, problem description or evidence | Eight rules in `rules/complaint_rules/missing_info_rules.yaml`: MIS-001 order reference, MIS-002 transaction reference, MIS-003 product, MIS-004 photo evidence, MIS-005 problem description, MIS-006 transaction date, MIS-007 unverified order, MIS-008 order ownership; SAF and PRV complaints and ACC-UNA are never blocked for missing information; validation check MIS-001 (missing information identified) | Tested: `test_difficult_cases.py::test_missing_information_triggers_clarification`; lab scenario LAB-DEF-06 |
| FL-40, FR-43 | Focused clarification questions instead of invented facts | Field `clarification_questions`; the validated decision lists the questions the rules require; validation check MIS-002 (questions ask for the missing information); the customer answers through `POST /complaints/{ref}/clarify`, which runs the pipeline again | Tested: `test_full_chain.py::test_customer_clarification_loop` |
| FL-59, FR-55 | Configurable response and resolution targets, tracked | SLA-P0 to SLA-P3 in `rules/sla_rules/sla_rules.yaml` (first response and resolution: 1 and 24 h, 4 and 48 h, 24 and 120 h, 48 and 240 h), editable as rule type `sla`; `services/sla.py::ensure_sla` creates an `sla_records` row for each complaint | Configured; recorded in `reports/operations/sla-status.pdf`; no automated test |
| FL-60, FR-56 | Flag complaints approaching their deadlines | `services/sla.py::evaluate` marks At Risk once 75% of the window has passed (`sla_at_risk_pct`) and Breached after the deadline; `refresh_all` runs every 60 seconds (`services/worker.py`) and escalates P0 and P1 breaches to Department Manager (ESC-039) | Implemented; demo database: 115 ESC-039 breach escalations; no automated test |

### 2.3.11 Security

**Table 2.15 — Security requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-54, FR-50 | Complaints and uploaded documents are untrusted; injected text is never an application instruction | `security/injection.py` screens text with 13 pattern types (instruction override, directives to the system, fake system and authority messages, role hijack, output manipulation, policy-override claims, prompt and data exfiltration, security bypass, tag and code injection, concealment), decodes base64 payloads and flags unknown policy IDs; flagged spans are annotated and the complaint is placed inside a `<complaint_NONCE>` element with a fresh nonce; SEC-001 checks that the AI did not obey; REV-010 sends the case to review; instruction-like document chunks are quarantined | Tested: `test_perception_security.py::test_injection_attacks_detected` (9 attacks), `::test_benign_text_not_flagged` (5 cases), `::test_injection_annotation_marks_untrusted_span`; `test_difficult_cases.py::test_prompt_injection_is_blocked`; holdout: 6 of 6 detected, no false positives |
| FL-55, FR-51 | Test prompt injection, fake administrative instructions, manipulative language, embedded policy claims and attempts to obtain unauthorised compensation | 31 prompt-injection complaints in the development set; 18 scenarios in `config/adversarial_scenarios.yaml` run by the Adversarial Lab (`services/lab.py`), several with fault profiles that corrupt the GenAI output | Tested: `test_defects_and_live_changes.py::test_every_adversarial_scenario_is_caught`; `reports/security_adversarial/summary.md` (18 of 18 met) |
| SEC-01, SEC-05 | Privacy, confidentiality and customer-data protection | `security/pii.py` redacts card numbers, CVV codes, passwords, one-time codes, e-mail addresses and phone numbers before any GenAI call and in AI-run logs; SEC-002 blocks sensitive data in responses; prohibited actions REQUEST_SENSITIVE_CREDENTIALS and DISCLOSE_OTHER_CUSTOMER_DATA; exports neutralise spreadsheet formulas | Tested: `test_perception_security.py::test_pii_redaction`; `test_documents_exports.py::test_csv_neutralises_formula_injection`, `::test_xlsx_never_contains_formulas`; lab scenarios LAB-PII-01, LAB-PII-02 |
| SEC-02, SEC-03 | Access control and secure storage | RBAC (Table 2.3); bcrypt hashes; uploads validated and stored under the git-ignored `storage/` folder with safe file names; append-only audit table; executables, macros and mismatched types rejected | Tested: `test_security_api.py::test_executable_upload_rejected`, `::test_audit_log_is_append_only_in_the_database`; `test_perception_security.py::test_upload_validation_rejects_executables_and_mismatches` |
| SEC-04 | API costs | gpt-4.1-mini by default; bounded retries; input and output tokens stored for every call in `ai_runs`; batch concurrency limited by `BATCH_WORKERS` | Implemented; token counts recorded in the demo database |
| SEC-06, SEC-07 | API keys never committed or uploaded; the key is never exposed | The key is read from the git-ignored `.env.secrets` on the server only; `.gitignore` excludes `.env` and `.env.*`; on Render the key is entered in the dashboard (`sync: false` in `render.yaml`) | Tested: `test_security_api.py::test_ai_key_never_exposed`; `test_genai_providers.py::test_gemini_key_travels_in_a_header_never_the_url` |

### 2.3.12 Manual review

**Table 2.16 — Manual review requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-61, FR-57 | Manual review when GenAI and Python disagree significantly, policy support is missing, the complaint is ambiguous, escalation is unclear, a policy contradiction exists or a sensitive complaint needs review | 14 triggers in `rules/complaint_rules/review_rules.yaml`, evaluated by `engine.py::finalize`. The six SRS conditions are REV-001 (category mismatch), REV-004 (missing policy support), REV-005 (ambiguous), REV-006 (escalation unclear), REV-007 (policy contradiction) and REV-008 (sensitive: SAF and PRV cases and legal-threat, harassment, injury and smart-lock signals). REV-002, REV-003 and REV-009 to REV-014 add critical failures, low score, invalid AI output, injection, unsupported promises, hallucination, unknown category and order mismatch | Tested: `test_difficult_cases.py::test_ambiguous_complaint_goes_to_review`, `::test_privacy_exposure`, `::test_prompt_injection_is_blocked`; holdout: 48 of the 51 cases labelled for review were reviewed (recall 94.1%) |
| FL-62, FR-58 | Approve, reject, modify, reclassify, reassign, escalate, regenerate the response, add comments | `services/reviews.py` (`ACTIONS`); `POST /reviews/{id}/claim` and `/reviews/{id}/actions`; reject, modify, reclassify and reassign require a comment; reclassify runs the pipeline again with the reviewer's subcategory and regenerate with the chosen tone; review workspace `frontend/src/pages/ReviewWorkspace.tsx` | Partial testing: "approve" is covered by `test_full_chain.py::test_complete_complaint_chain`; the other seven actions have no automated test; the demo database records 300 approvals and 1 modification |
| FL-63, FR-59 | Store reviewer overrides; keep the original recommendation and the reviewer decision in the audit trail | `reviews.original_snapshot` (AI output, validated decision, score) and `final_snapshot`; each action in `review_actions` with before and after state, actor and time; audit entries; the original AI output and validation result are never changed | Tested: `test_full_chain.py::test_complete_complaint_chain` (Human Verified after approval); `test_security_api.py::test_audit_log_is_append_only_in_the_database` |

### 2.3.13 Analytics and dashboards

**Table 2.17 — Dashboard, analytics and trend requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-66, FR-61 | Customer view of complaint ID, status, submitted date, department, latest update and resolution status | `CustomerDashboard` in `frontend/src/pages/Dashboard.tsx`: a table with exactly these columns plus summary counts; `GET /api/v1/dashboard` returns only the customer's own complaints | Recorded: screenshot `03-customer-dashboard.png`; no dedicated test |
| FL-67, FR-62 | Agent view of assigned complaints, category, priority, sentiment, GenAI recommendation, validation status, suggested response and escalation warnings | `AgentDashboard`: assigned queue ordered by priority with priority, status, verification badge and score, escalation and SLA badges, injection flag, category and subcategory, urgency, sentiment, AI summary and guidance, and the suggested response with its status | Recorded: screenshot `06-agent-dashboard.png`; no dedicated test |
| FL-68, FR-63 | Administrator view of total complaints, category and department distribution, priority levels, escalations, resolution status, SLA risks, GenAI/Python mismatches and manual-review cases | `OpsDashboard` for administrators, managers and reviewers: totals, verified rate, pending reviews, escalations, SLA at risk and breached, AI-and-rules agreement with the number of field mismatches, weekly category trend, priority donut, category and department distributions, resolution status, trend alerts and open reviews by reason | Tested: `test_full_chain.py::test_complete_complaint_chain` (dashboard total updates); screenshot `14-manager-dashboard.png` |
| FL-69, FR-64 | Analytics for volume, category, product/service, department, urgency, sentiment, escalations, resolution time and repeat complaints | `services/analytics.py`: distributions over 13 dimensions (among them product, urgency, sentiment and escalation level), weekly or monthly trends, resolution times, repeat and duplicate counts, validation results per check, SLA and department views; `GET /api/v1/analytics/*` (permission `analytics:read`) | Recorded: screenshots `20-analytics.png`, `21-analytics-ai-vs-rules.png`; no dedicated test |
| FL-70, FR-65 | Identify rising delivery and billing complaints, recurring product issues, repeated service failures and escalation spikes | `services/analytics.py::trend_alerts`: a category, department or product is "rising" when its last-14-day count is at least 5 and at least 1.5 times the previous 14 days; an escalation spike is at least 4 escalations this week and 1.5 times the weekly average of the four weeks before; a recurring product issue is at least 4 complaints about one product and subcategory in 30 days; repeated service failures are at least 5 outage or repeat complaints in 30 days | Recorded: "Emerging trends" in `reports/complaint_intelligence/complaint-intelligence.pdf`; no automated test |

### 2.3.14 Reporting and export

**Table 2.18 — Reporting and export requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-72, FR-67 | Reports for complaint analysis, department performance, escalations, SLA status, policy usage, resolution compliance, GenAI/Python comparison and manual reviews | `reporting/builders.py` (`REPORTS`): the eight SRS reports plus Complaint intelligence and Security & adversarial testing; Reports page and `GET /api/v1/reports/{key}` (permission `reports:export`) | Tested: `test_full_chain.py::test_complete_complaint_chain` (complaint-analysis CSV); recorded: `reports/operations/` (seven reports), `reports/genai_python_comparison/`, `reports/complaint_intelligence/`, `reports/security_adversarial/`. Partial: the per-case table of the committed evaluation-run comparison export is empty (Section 2.5) |
| FL-73, FR-68 | Export in CSV, PDF and an Excel-compatible format | `reporting/exports.py` renders every report as PDF (fpdf2), XLSX (openpyxl), CSV and JSON; case report `GET /complaints/{ref}/report.pdf`; complaint list export `GET /complaints-export` | Tested: `test_documents_exports.py::test_csv_neutralises_formula_injection`, `::test_xlsx_never_contains_formulas`, `::test_pdf_report_renders_unicode_safely`, `::test_json_render_roundtrip`; `test_full_chain.py::test_complete_complaint_chain` (PDF, CSV, XLSX) |

### 2.3.15 Audit and traceability

**Table 2.19 — Audit and traceability requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-64 | Original and final decisions logged | `audit/service.py`: each record stores sha256(previous hash + canonical record); a PostgreSQL trigger blocks UPDATE, DELETE and TRUNCATE on `audit_logs` (migration `0001_initial_schema`); `GET /api/v1/audit/verify` recomputes the chain; per-complaint timeline in `complaint_history`; review snapshots (Table 2.16) | Tested: `test_security_api.py::test_audit_log_is_append_only_in_the_database`, `::test_denied_access_is_audited`; `test_full_chain.py::test_complete_complaint_chain` (chain valid at the end of the journey) |
| FL-53, FR-49 | Prompt version, provider, model, timestamp and policy versions per analysis | Table 2.7; in addition, the audit entry of every processed complaint repeats provider, model, prompt versions, policy versions, ruleset hash and stage timings | Implemented |
| FL-50 | Policy traceability of generated actions | Every policy reference, whether retrieved, cited by the AI or required by a rule, is stored in `policy_references` with version, section, chunk ID and applicability | Implemented |

### 2.3.16 Error handling and web interface

**Table 2.20 — Error handling and interface requirements**

| ID | Requirement (SRS) | SupportNova implementation | Status and evidence |
|---|---|---|---|
| FL-74 | Handle API, parsing, validation and database errors | `api/errors.py` turns application errors, request validation (422), integrity conflicts (409), an unavailable database (503) and other database errors (500) into structured JSON errors; `services/pipeline.py::process_complaint` catches any pipeline failure, marks the complaint for manual review and opens a review instead of leaving it in Processing; GenAI errors are classified and retried (FR-47); parser errors return readable messages | Tested: `test_boundaries.py::test_malformed_body_is_a_field_error_not_a_crash`, `::test_title_over_the_hard_cap_is_a_field_error_not_a_crash`; `test_documents_exports.py::test_corrupted_document_is_rejected_cleanly`; frontend test "maps error payloads to ApiError with field errors" |
| FL-75 | Intuitive, responsive web interface | React 19 single-page application (`frontend/src`, 18 pages) with role-specific navigation, light and dark themes and layouts for narrow screens | Recorded: 31 screenshots captured with no console errors, including `30-mobile-dashboard.png` and `31-mobile-complaint-detail.png`; 12 frontend tests in `frontend/src/test/core.test.tsx` |

## 2.4 Non-Functional Requirements

SRS 1.7 states five non-functional requirements (NFR-1 to NFR-5). Five further quality attributes follow from other sections of the SRS: reliability, security, traceability, maintainability and responsiveness (NFR-6 to NFR-10). Table 2.21 gives the design response and the measured result for each. Latency figures come from the 599 non-duplicate development complaints imported into the demo database and processed by gpt-4.1-mini with four complaints in parallel. Accuracy figures come from evaluation run 1 on the 154 unseen holdout complaints (`reports/genai_python_comparison/summary.md`).

**Table 2.21 — Non-functional requirements**

| ID | Requirement (SRS) | SupportNova design | Measured result | Status |
|---|---|---|---|---|
| NFR-1 | Initial recommendation analysed, validated and generated within 20 s | Two model calls on the critical path; pre-processing, retrieval and validation take milliseconds; background workers (`BACKGROUND_WORKERS` = 2); live pipeline tracker | Full pipeline p50 21.7 s, p95 33.9 s, 32.4% within 20 s; holdout run p50 21.2 s, p95 33.8 s; stages up to the validated decision p50 16.2 s, p95 25.2 s, 80.8% within 20 s | Tested (measured); **not met** at the median for the saved result |
| NFR-2 | 10,000 complaints, 100 categories/subcategories, 1,000 documents without redesign | PostgreSQL with 17 indexes on `complaints`; paged lists (at most 200 rows); taxonomy, rules and documents stored as data; stateless API with thread-pool workers | Demo database: 800 complaints, 46 taxonomy entries (11 + 35), 24 documents with 484 chunks; no load test | Implemented as a design; **not load-tested** |
| NFR-3 | Intuitive, user-friendly interface for all five roles | Role-specific dashboards and navigation; plain labels (the rule check, "AI vs rules"); pipeline tracker; field-level validation messages | 31 screenshots with no console errors; 12 frontend tests; no user study | Implemented; not formally evaluated |
| NFR-4 | Mandatory escalations and critical routing enforced before final verification; valid source references | RTE-001 and ESC-001 are critical checks that block Verified; the rules' department and escalation always apply; policy references checked (SCH-004, POL-001 to POL-004, HAL-004); the validated decision cites the rule's policy sections | Holdout, Python against the expected labels: escalation required 94.7%, escalation level 94.1%, department 84.9%, policy references 76.3%; every injected miss in the fault-profile tests is caught | Tested; **partly met**: enforcement is only as complete as Python's detection of the triggering facts |
| NFR-5 | At least 99% uptime during evaluation, excluding GenAI outages | Health endpoint `/api/health` used by the Docker and Render health checks; Docker image; Render blueprint `render.yaml` | No public deployment; uptime not measured | **Planned** |
| NFR-6 | Reliability (derived from SRS 1.1, Step 47, 1.6 (lxxiv)) | Bounded retries with error classes; no output without a key (`not_configured`), never a fabricated answer; pipeline failures go to manual review; database errors return structured responses | All 780 analyses completed; 31 failed attempts (26 connection, 4 timeout, 1 invalid output) recovered by retries; 206 of 206 backend tests pass | Tested |
| NFR-7 | Security (derived from SRS 1.1, 1.5) | Tables 2.3 and 2.15; Chapters 24 and 34 | 30 API security tests pass; 18 of 18 adversarial scenarios met | Tested |
| NFR-8 | Traceability (derived from SRS 1.1, Steps 25, 49, 59) | Prompt versions and sha256, provider, model, policy versions and ruleset hash per analysis; raw AI responses per attempt; check results with rule and policy references; hash-chained audit log | Every analysis in the demo database carries these fields | Tested |
| NFR-9 | Maintainability and configurability (derived from SRS 1.7 (2), 1.8 (5), (14)) | Rule Matrix, taxonomy, prompts, schemas and thresholds are data; 14 backend packages; ruff, mypy, eslint and tsc | New categories, parameter changes and disabled rules take effect without code changes (Table 2.6) | Tested |
| NFR-10 | Responsiveness (derived from SRS 1.6 (lxxv)) | Responsive layouts, dark mode | Screenshots `30-mobile-dashboard.png`, `31-mobile-complaint-detail.png` | Implemented; recorded |

NFR-1 deserves a closer look, because the 20-second target is missed by a small margin and for a specific reason. Table 2.22 breaks the measured time down by stage, using the timings stored with each analysis (`analyses.stage_timings`).

**Table 2.22 — Measured pipeline latency by stage (599 development complaints, gpt-4.1-mini)**

| Stage | Median | 95th percentile |
|---|---|---|
| Pre-processing (normalisation, screening, perception, history) | 20 ms | 29 ms |
| Retrieval | 3 ms | 5 ms |
| GenAI analysis call (including retries) | 16.2 s | 25.2 s |
| Python validation, Phase A | 2 ms | 4 ms |
| GenAI customer-response call | 5.2 s | 9.8 s |
| Python response validation, Phase B | 2 ms | 5 ms |
| Full pipeline, result saved | 21.7 s | 33.9 s |

The deterministic Python stages together take about 30 ms at the median. Almost the whole time is spent in the two model calls. The validated decision, which is the "initial complaint recommendation" of NFR-1, is complete after the analysis call and Phase A: a median of 16.2 seconds, with 80.8% of complaints within 20 seconds. SupportNova, however, saves the decision together with the customer-response draft at the end of the run, so the user sees the result after 21.7 seconds at the median, and only 32.4% of complaints complete within 20 seconds. Saving the validated decision before the response call, or streaming the response, would close most of the gap. Neither has been implemented or measured; Chapter 35 treats performance in detail.

## 2.5 Coverage Summary and Open Items

Every development step (FR-01 to FR-68) and every item of the SRS 1.6 list (FL-01 to FL-76) is implemented or configured. For most of them an automated test or a recorded run provides the evidence. Four groups of requirements are weaker than the tables above might suggest:

- **Requirements that rely on recorded runs rather than automated tests:** policy applicability (FR-26), replacement eligibility (FR-30), response tone (FR-33), escalation notes (FR-38), follow-up communication and scheduling (FR-40, FR-41), SLA tracking and risk (FR-55, FR-56), the dashboards and analytics (FR-61 to FR-65), the search filters (FR-66) and the verification-score formula (FL-51). They work in the demo database, the reports and the screenshots, but no test would catch a regression.
- **Reviewer actions (FR-58):** all eight actions are implemented, but only "approve" is covered by an automated test.
- **The GenAI/Python comparison export (FR-67, SRS 1.10 (8)):** `reports/genai_python_comparison/summary.md` is complete and correct. The per-case table in `genai-python-comparison.csv`, `.xlsx` and `.pdf`, however, shows "None/None" in the category columns, empty department, urgency, escalation and policy columns, and "Match" on all 154 rows. The per-case values are stored in `evaluation_results` for run 1, but `reporting/builders.py::_comparison_row` reads a `rows` list that only operational validation results contain. Until this is fixed and the report regenerated, the per-case columns required by the SRS are missing from the committed file.
- **Non-functional targets:** NFR-1 is not met at the median, NFR-2 and NFR-5 have not been measured, and NFR-4 depends on the accuracy of Python's own fact detection.

The requirements outside the functional and non-functional sections are traced in Appendix A: dataset minimums, hidden-evaluation readiness, competition integrity, interfaces and deliverables. The open items there are the commit history across five days (CI-16), the verifying-team record in `AI_USAGE.md` (CI-19), the public deployment URL, the demonstration video, the technical blog and the team contribution record (DEL-15 to DEL-19). Chapter 43 discusses these limitations and Chapter 44 the planned improvements.
