# Appendix A — SRS Requirement Traceability Matrix

This appendix traces every requirement of the SupportNova Software Requirements Specification (SRS, Version 1.0) to the part of SupportNova that implements it, the chapter of this report that describes it and the evidence that verifies it. The identifiers and the full requirement texts are defined in the requirements inventory (`documentation/traceability/srs-requirements-inventory.md`). Chapter 2 discusses the functional and non-functional requirements in detail.

## A.1 How to Read the Matrix

Each table has five columns. **Requirement ID** is the inventory identifier. **Requirement** is a condensed form of the SRS text. **Implementation module** names the file, package, configuration or data that meets the requirement. Python paths are relative to `backend/src/supportnova/`; paths that begin with `rules/`, `config/`, `prompts/`, `schemas/`, `knowledge_base/`, `data/`, `frontend/`, `scripts/` or `reports/` are relative to the repository root. **Report section** gives chapter numbers ("Ch 7, 11") or appendix letters ("App C") from the report plan. **Verification / test** gives the status and the evidence.

The status labels are: **Implemented** (code exists), **Configured** (met through data or configuration), **Tested** (an automated test or a recorded run demonstrates it), **Recorded** (evidence from a recorded run, report file or screenshot, without an automated test), **Planned** (designed, not built), **Partial** (only partly met) and **Not met**. Automated tests are cited as `file.py::test_name` (files under `tests/backend/` and `tests/e2e/`). The recorded evidence comes from these sources:

- the **holdout run**: evaluation run 1, 154 unseen complaints, OpenAI gpt-4.1-mini, `reports/genai_python_comparison/summary.md`;
- the **lab**: 18 adversarial scenarios, `reports/security_adversarial/summary.md`;
- **validation evidence**: `reports/python_validation_evidence/README.md`;
- the **demo database**: 617 imported development complaints processed live, as summarised in `documentation/_work/facts.md`.

## A.2 Project Context, Constraints and Proposed Solution

**Table A.1 — Context (CTX), constraints (CON) and proposed-solution obligations (SOL)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| CTX-01 | Project name SupportNova | Product name in `README.md`, UI header and report exports | Ch 1, 3 | Documented |
| CTX-02 | Theme ResponseX Intelligence | Brand "SupportNova - ResponseX Intelligence" (`reporting/exports.py`) | Ch 1 | Documented |
| CTX-03 | Category Generative AI PowerPlay | Project classification | Ch 1 | Documented |
| CTX-04 | Complaints arrive in volume through many channels and concern many issue types | 7 channels (`config/organization.yaml`), 11 categories and 35 subcategories (`config/taxonomy.yaml`) | Ch 1, 3 | Configured |
| CTX-05 | Manual handling is slow and inconsistent | Whole system; Table 1.1 | Ch 1 | Documented |
| CTX-06 | Automatic identification of issue, category, urgency, sentiment, entities, department, escalation; GenAI responses, steps, notes, follow-ups, guidance | `genai_pipeline/` (Pipeline 1) | Ch 1, 8 | Tested: see FL-12 to FL-43 |
| CTX-07 | Independent Python Ground-Truth Validation Pipeline | `python_validation/`, `rule_engine/`, `hallucination_checks/` | Ch 1, 11 | Tested: see FL-45 |
| CTX-08 | Secure, reliable, traceable application that prevents unsupported GenAI responses | Whole system | Ch 1, 24, 37 | Tested: see NFR-6 to NFR-8 |
| CTX-09 | Purpose and audience of the SRS | Stakeholder analysis | Ch 1, 2 | Documented |
| CTX-10 | Scope: identify issue, category, urgency, sentiment, priority, department; generate responses, steps, notes, follow-ups | Pipelines 1 and 2 | Ch 1 | Tested: holdout run |
| CTX-11 | Scope: independent validation of classification, routing, policy applicability, urgency, escalation, resolution, traceability and unsupported content | Pipeline 2 (52 checks) | Ch 1, 11 | Tested: see SOL-12 to SOL-15 |
| CTX-12 | Scope aims: less manual triage, consistent routing, faster resolution, critical cases found, grounded communication | Whole system | Ch 1 | Tested, except NFR-1 (not met) |
| CTX-13 | Out of scope: live CRM, payment gateways, banking, call-centre platforms, production Zendesk | Simulated order ledger `data/sample_complaints/orders.json`; responses sent inside the application (`customer_responses.sent_via`) | Ch 1 | Not integrated, as the SRS allows |
| CON-01 | Results depend on the quality of complaints and policies | Complaint and document validation, missing-information rules, conflict detection | Ch 1, 5, 19 | Tested: see FR-04, FR-10, FR-42 |
| CON-02 | Results depend on model behaviour, prompts, context limits, API availability, rules and validation | Strict schema, versioned prompts, bounded retries, `not_configured` state | Ch 1, 8, 21 | Tested: `test_genai_providers.py` (31 tests); `test_ai_not_configured.py::test_no_api_key_means_no_ai_output_and_manual_review` |
| CON-03 | Wording varies; AI and rules may disagree | Field-level comparison (`python_validation/engine.py::build_comparison`) | Ch 1, 12 | Tested: holdout run, key-field agreement 70.6% |
| CON-04 | Generated content verified before final approval | Pipeline 2; only responses with status ready or approved can be sent (`api/v1/complaints.py::send_response`) | Ch 1, 11, 16 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| CON-05 | Privacy, security, confidentiality, API cost, data protection, access control, secure storage | See SEC-01 to SEC-05 | Ch 1, 24 | See Table A.22 |
| SOL-01 | Web-based application in Python with GenAI APIs | FastAPI backend (`backend/src/supportnova`), React frontend (`frontend/src`), provider adapters | Ch 3, 4 | Tested: 206 backend and 12 frontend tests pass |
| SOL-02 | Web submission with the complaint fields | See Table A.2 | Ch 7, 27 | See FR-09 |
| SOL-03 | Administrators upload the 14 kinds of approved documents | `POST /api/v1/documents`; all 14 kinds present: CHP-POL-01, REF-POL-02, RPL-POL-03, WAR-POL-07, BIL-POL-05, DEL-POL-04, SLA-RUL-15, ESC-SOP-12, CHP-SOP-13, TEC-GDL-20, RTE-RUL-14, FAQ-GEN-16 and FAQ-BIL-17, CMP-GDL-19, TPL-COM-18 | Ch 5; App J | Configured; `test_documents_exports.py::test_knowledge_base_meets_srs_minimums` |
| SOL-04 | Validate PDF and DOCX; traceable sections and chunks with document ID, section ID, version, effective date, source | `document_processing/`, `services/documents.py`; tables `document_versions`, `document_sections`, `document_chunks` | Ch 5 | Tested: see FR-04 to FR-06 |
| SOL-05 | Rule Matrix built from the approved documents | `rules/*.yaml` (276 rule rows); every rule has `policy_refs` | Ch 10; App B | Tested: `test_rule_engine.py::test_rule_matrix_integrity` |
| SOL-06 | Structured complaint-intelligence result | See Table A.3 | Ch 8; App D | See FL-43 |
| SOL-07 | Two separate Python pipelines | `genai_pipeline/`; `python_validation/` with `rule_engine/` | Ch 4, 8, 11 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| SOL-08 | Pipeline 1 uses an approved GenAI API | OpenAI (default gpt-4.1-mini), Anthropic and Gemini adapters in `genai_pipeline/providers/` | Ch 8 | Tested: `test_genai_providers.py::test_factory_selects_the_configured_provider`; 780 live analyses |
| SOL-09 | Send complaint, customer context and approved knowledge to the model | `genai_pipeline/context.py` (evidence, conflicts, verified facts, complaint block) | Ch 8, 9 | Recorded: `reports/genai_pipeline_evidence/sample_request_and_structured_response.json` |
| SOL-10 | Pipeline 1 performs P1-01 to P1-17 | See Table A.4 | Ch 8 | See Table A.4 |
| SOL-11 | Predefined structured JSON; free text not the only output | `schemas/ai/complaint_analysis.v1.schema.json`, `customer_communication.v1.schema.json`, `genai_pipeline/schemas.py` | Ch 8; App C | Tested: see FL-43 |
| SOL-12 | Pipeline 2 independent; never uses GenAI to approve Pipeline 1 | `python_validation/engine.py`; no provider import in `python_validation/`, `rule_engine/`, `hallucination_checks/` | Ch 11 | Tested: `test_ai_not_configured.py::test_no_api_key_means_no_ai_output_and_manual_review` (the rules still decide without a model) |
| SOL-13 | Pipeline 2 compares with P2C-01 to P2C-10 | See Table A.5 | Ch 11, 12 | See Table A.5 |
| SOL-14 | Pipeline 2 verifies P2V-01 to P2V-17 | See Table A.6 | Ch 11 | See Table A.6 |
| SOL-15 | Pipeline 2 does not simply accept the GenAI output | The rules override every decision field; critical failures block Verified (`engine.py::finalize`) | Ch 11, 12 | Tested: `test_defects_and_live_changes.py::test_every_adversarial_scenario_is_caught`; holdout run: 92 of 93 AI key-field errors caught |
| SOL-16 | Reference application only for concepts; original solution | Original implementation in this repository | Ch 3 | Documented |

## A.3 Complaint Fields and Structured Result

**Table A.2 — Complaint input fields (CF)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| CF-01 | Complaint title | Form field "Title"; `complaints.title` (5 to 180 characters) | Ch 7 | Tested: `test_boundaries.py::test_title_length_edges` |
| CF-02 | Complaint description | "Description"; `complaints.description` and `description_normalized` | Ch 7 | Tested: `test_boundaries.py::test_description_length_edges` |
| CF-03 | Customer type | "Customer type"; `complaints.customer_type` (individual, care_plus, business, vip) | Ch 7 | Tested: `test_boundaries.py::test_customer_precheck_uses_the_profile_customer_type` |
| CF-04 | Product or service | "Product or service"; `complaints.product_text`, detected `product_sku` | Ch 7 | Tested: `test_perception_security.py::test_entities_extracted` |
| CF-05 | Order reference | "Order reference"; `complaints.order_ref` (LMR-######, looked up in the order ledger) | Ch 7 | Tested: `test_boundaries.py::test_order_reference_format` |
| CF-06 | Transaction reference | "Transaction reference"; `complaints.transaction_ref` (TXN-########) | Ch 7 | Implemented (format check in `services/complaints.py::validate_submission`) |
| CF-07 | Complaint channel | "Channel"; `complaints.channel` (7 channels) | Ch 7 | Implemented; all 7 channels occur in the dataset |
| CF-08 | Date | `complaints.complaint_date` (submission time or supplied date) | Ch 7 | Implemented |
| CF-09 | Supporting documents | "Attachments"; `complaint_attachments` (up to 5 files; PDF, PNG, JPEG, TXT; 5 MB each) | Ch 7 | Tested: `test_perception_security.py::test_upload_validation_rejects_executables_and_mismatches` |
| CF-10 | Previous complaint history | `services/history.py::analyse_history` (90-day window) | Ch 20 | Tested: `test_difficult_cases.py::test_repeated_complaint_detected` |
| CF-11 | Requested resolution | "What would you like us to do?"; `complaints.requested_resolution` (8 codes) | Ch 7 | Implemented |
| CF-12 | Previous complaint reference | "Previous complaint"; `complaints.previous_complaint_ref` (must exist and belong to the customer) | Ch 7, 20 | Implemented (`validate_submission`) |
| CF-13 | Preferred contact channel | "Preferred contact"; `complaints.preferred_contact` (email, phone, sms, chat) | Ch 7 | Implemented |
| CF-14 | Supporting information | "Supporting information"; `complaints.supporting_info` | Ch 7 | Implemented |

**Table A.3 — Structured complaint-intelligence result (OUT)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| OUT-01 | Main complaint issue | `primary_issue`, `summary`; CLS-001 | Ch 8; App D | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| OUT-02 | Complaint category | `issue_category`; SCH-002, CLS-001 | Ch 8, 11 | Tested: `test_perception_security.py::test_classification_categories` |
| OUT-03 | Subcategory | `subcategory`; CLS-002 | Ch 8, 11 | Tested: holdout run (AI 77.6%, Python 68.4%) |
| OUT-04 | Sentiment | `sentiment`; CLS-004 | Ch 8, 14 | Tested: `test_perception_security.py::test_sentiment_is_informational` |
| OUT-05 | Urgency | `urgency`, `urgency_rationale`; PRI-001 | Ch 14 | Tested: `test_difficult_cases.py::test_calm_critical_safety_complaint` |
| OUT-06 | Priority | `priority`; PRI-002 | Ch 14 | Tested: `test_rule_engine.py::test_priority_matrix` |
| OUT-07 | Product or service | `entities` (product, service); Python `product_sku` | Ch 7, 8 | Tested: `test_perception_security.py::test_entities_extracted` |
| OUT-08 | Relevant entities | `entities`; CLS-005, HAL-002 | Ch 8, 17 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[hallucinated_entity-HAL-002]` |
| OUT-09 | Required department | `department`, `supporting_departments`; RTE-001, RTE-002 | Ch 13 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[wrong_department-RTE-001]` |
| OUT-10 | Resolution recommendation | `resolution_steps`, eligibility fields; RES-001 to RES-004, ELG-001 to ELG-003 | Ch 15 | Tested: `test_difficult_cases.py::test_unsupported_refund_request` |
| OUT-11 | Escalation requirement | `escalation_required`, `escalation_level`; ESC-001, ESC-002 | Ch 18 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[missed_escalation-ESC-001]` |
| OUT-12 | Escalation reason | `escalation_reason`, `escalation_notes`; ESC-004 | Ch 18 | Implemented; example in validation evidence (ESC-004 on CMP-00396) |
| OUT-13 | Professional customer response | `customer_communication.customer_response`; RSP-001 to RSP-006 | Ch 16 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| OUT-14 | Follow-up communication | `follow_up_message`, `follow_up_type`; FUP-001, FUP-002, RSP-007 | Ch 16, 19 | Implemented; no dedicated test |
| OUT-15 | Supporting policy references | `policy_references`, `policy_id`, `policy_section`; SCH-004, POL-001 to POL-006 | Ch 9; App D | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[hallucinated_policy-SCH-004]` |

## A.4 Pipeline Obligations

**Table A.4 — Pipeline 1 functions (P1)**

All functions are carried by prompt `complaint_analysis` 1.2.0 (P1-14 and P1-15 also by `customer_communication` 1.0.0) and by required fields of the output schemas. Every answer is validated against the schema (SCH-001).

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| P1-01 | Analyse the complaint | `summary`, `key_facts`, `claims`; HAL-001, HAL-003 | Ch 8, 17 | Tested: `test_perception_security.py::test_claim_grounding_accepts_paraphrase_but_not_invented_facts` |
| P1-02 | Identify the primary issue | `primary_issue` | Ch 8 | Tested: `test_difficult_cases.py::test_multi_issue_multi_department` |
| P1-03 | Identify the category | `issue_category` (live enum) | Ch 8 | Tested: holdout run (AI 89.5%) |
| P1-04 | Identify the subcategory | `subcategory`, `secondary_issues` | Ch 8 | Tested: holdout run (AI 77.6%) |
| P1-05 | Detect sentiment | `sentiment`, `emotion_indicators` | Ch 8, 14 | Tested: `test_perception_security.py::test_sentiment_is_informational` |
| P1-06 | Determine urgency | `urgency`, `urgency_rationale`, `impact` | Ch 14 | Tested: `test_difficult_cases.py::test_calm_critical_safety_complaint` |
| P1-07 | Determine priority | `priority` | Ch 14 | Tested: holdout run (AI 62.5%, Python 88.8%) |
| P1-08 | Extract entities | `entities` | Ch 8 | Tested: `test_perception_security.py::test_entities_extracted` |
| P1-09 | Recommend the department | `department`, `supporting_departments` | Ch 13 | Tested: holdout run (AI 92.1%) |
| P1-10 | Identify relevant policies | `policy_references` with applicability | Ch 9 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[hallucinated_policy-SCH-004]` |
| P1-11 | Generate resolution steps | `resolution_steps`, eligibility fields | Ch 15 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[prohibited_action-RSP-006]` |
| P1-12 | Determine whether escalation is required | `escalation_required`, `escalation_level`, `escalation_reason` | Ch 18 | Tested: holdout run (escalation required AI 92.8%) |
| P1-13 | Generate escalation notes | `escalation_notes` (six elements) | Ch 18 | Implemented; ESC-004 example in validation evidence |
| P1-14 | Generate a professional response | `customer_communication`: `subject`, `customer_response`, `tone` | Ch 16 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| P1-15 | Generate follow-up communication | `follow_up_required`, `follow_up_type`, `follow_up_message` | Ch 16, 19 | Implemented; no dedicated test |
| P1-16 | Generate agent guidance | `agent_guidance` | Ch 8, 27 | Tested: `test_full_chain.py::test_complete_complaint_chain` (validated guidance) |
| P1-17 | Generate clarification questions | `missing_information`, `clarification_questions` | Ch 16, 19 | Tested: `test_difficult_cases.py::test_missing_information_triggers_clarification` |

**Table A.5 — Pipeline 2 comparison references (P2C)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| P2C-01 | Complaint Resolution Rule Matrix | `rule_engine/loader.py`, `rule_engine/decision.py` (`DecisionEngine`) | Ch 10, 11 | Tested: `test_rule_engine.py::test_decision_engine_trace_is_explainable` |
| P2C-02 | Department-routing rules | `rules/routing_rules/routing_rules.yaml` (35 + 6 conditional) | Ch 13 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[wrong_department-RTE-001]` |
| P2C-03 | Urgency thresholds | 15 urgency floors (`rules/complaint_rules/priority_rules.yaml`) and resolution-rule urgency | Ch 14 | Tested: `test_difficult_cases.py::test_calm_critical_safety_complaint` |
| P2C-04 | Escalation rules | `rules/escalation_rules/escalation_rules.yaml` (39) | Ch 18 | Tested: `test_rule_engine.py::test_safety_signal_forces_critical_escalation` |
| P2C-05 | Approved policy versions | Knowledge snapshot of Active, effective versions (`knowledge_base/store.py`) | Ch 5, 9 | Tested: `test_defects_and_live_changes.py::test_revised_policy_upload_versioning_and_impact` |
| P2C-06 | Complaint-category rules | `rules/complaint_rules/category_rules.yaml` (35), `complaint_processing/perception.py` | Ch 11 | Tested: `test_perception_security.py::test_classification_categories` |
| P2C-07 | Customer eligibility rules | Resolution-rule eligibility, 59 parameters, order facts (`complaint_processing/order_facts.py`) | Ch 15 | Tested: `test_boundaries.py::test_refund_window_edge`; `test_defects_and_live_changes.py::test_changing_a_rule_parameter_changes_the_decision` |
| P2C-08 | Resolution rules | `rules/complaint_rules/resolution_rules.yaml` (116) | Ch 15 | Tested: `test_rule_engine.py::test_reference_labels_reproduce_dataset` |
| P2C-09 | Follow-up requirements | `rules/complaint_rules/followup_rules.yaml` | Ch 19 | Tested: `test_rule_engine.py::test_reference_labels_reproduce_dataset` (follow-up labels reproduced) |
| P2C-10 | Source-document metadata | Version status, effective and expiry dates, section IDs (`knowledge_base/store.py::resolve_ref`) | Ch 5, 9 | Tested: `test_perception_security.py::test_fake_policy_ids_versions_sections` |

**Table A.6 — Pipeline 2 verification items (P2V)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| P2V-01 | Complaint category | SCH-002, CLS-001 (`python_validation/engine.py`) | Ch 11, 12 | Tested: `test_perception_security.py::test_unsupported_genai_category_is_never_the_provisional_reference` |
| P2V-02 | Complaint subcategory | SCH-002, CLS-002, CLS-003 | Ch 11 | Recorded: validation evidence (CLS-002 on R2-EVL-00005) |
| P2V-03 | Department assignment | SCH-003, RTE-001, RTE-002 | Ch 13 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[wrong_department-RTE-001]` |
| P2V-04 | Urgency | PRI-001, PRI-003 | Ch 14 | Tested: `test_difficult_cases.py::test_calm_critical_safety_complaint`, `::test_angry_low_priority_complaint` |
| P2V-05 | Priority | PRI-002, PRI-004 | Ch 14 | Tested: `test_rule_engine.py::test_priority_matrix`; lab LAB-DEF-03 |
| P2V-06 | Mandatory escalation | ESC-001, ESC-002, ESC-003, SCH-005 | Ch 18 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[missed_escalation-ESC-001]` |
| P2V-07 | Policy applicability | POL-005 (`engine.py::assess_applicability`) | Ch 9, 11 | Implemented; all four values in the demo database; no dedicated test |
| P2V-08 | Policy version | POL-002, POL-006 | Ch 9 | Recorded: lab LAB-POL-03 (POL-002 on an outdated RET-SOP-23 citation) |
| P2V-09 | Resolution eligibility | ELG-001, ELG-002 | Ch 15 | Tested: `test_difficult_cases.py::test_unsupported_refund_request`; lab LAB-POL-02 |
| P2V-10 | Required actions | RES-001, RES-003 | Ch 15 | Recorded: lab LAB-DEF-01, LAB-DEF-05 |
| P2V-11 | Prohibited actions | RES-002, RSP-006 | Ch 15, 17 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[prohibited_action-RSP-006]` |
| P2V-12 | Compensation eligibility | ELG-003, RSP-002 | Ch 15 | Tested: `test_difficult_cases.py::test_unsupported_compensation_request`; lab LAB-CMP-02 |
| P2V-13 | Follow-up requirements | FUP-001, FUP-002, RSP-007 | Ch 19 | Implemented; no dedicated test |
| P2V-14 | Source-document references | SCH-004, POL-001, POL-003, POL-004, HAL-004 | Ch 9, 17 | Tested: `test_perception_security.py::test_fake_policy_ids_versions_sections`; lab LAB-POL-01 (HAL-004) |
| P2V-15 | Unsupported generated claims | HAL-001, HAL-002, HAL-003, RSP-003, RSP-004 | Ch 17 | Tested: `test_perception_security.py::test_claim_grounding_accepts_paraphrase_but_not_invented_facts`; lab LAB-DEF-04 |
| P2V-16 | Contradictory instructions | RES-004, POL-006, SEC-001 | Ch 9, 15, 23 | Tested: `test_difficult_cases.py::test_contradictory_policy_resolved_by_precedence`; lab LAB-INJ-01 (RES-004) |
| P2V-17 | Missing mandatory actions | RES-001, critical when a safety, security, privacy or escalation action is missing | Ch 15 | Recorded: lab LAB-DEF-01 (ESC-001 and RES-001 caught) |

## A.5 Development Steps (SRS 1.2, Steps 1-68)

**Table A.7 — Development-step requirements (FR)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| FR-01 | Own fictional organisation; no real confidential data | `config/organization.yaml`, `config/products.yaml`, `config/departments.yaml`, `config/taxonomy.yaml` | Ch 3, 6, 42 | Configured (Lumora Home Technologies, fictional-data disclaimer) |
| FR-02 | Knowledge base with the 13 required document kinds | `knowledge_base/manifest.yaml`, `knowledge_base/sample_documents/` (24 documents, 29 versions) | Ch 5; App J | Configured; `test_documents_exports.py::test_knowledge_base_meets_srs_minimums` |
| FR-03 | PDF and DOCX mandatory; TXT, Markdown, CSV optional | `document_processing/parsers.py::parse_document`; `security/files.py` `DOCUMENT_TYPES` | Ch 5 | Tested: `test_documents_exports.py::test_parse_sections_from_real_documents[pdf]`, `[docx]`; `test_full_chain.py::test_document_upload_and_policy_versioning_journey` |
| FR-04 | Validate type, size, empty, duplicate, document ID, version, effective and expiry dates, category | `security/files.py::validate_upload`, `document_processing/validation.py::validate_metadata`, `services/documents.py::ingest_document` | Ch 5 | Tested: `test_documents_exports.py::test_metadata_validation_and_version_order`, `::test_corrupted_document_is_rejected_cleanly`; `test_boundaries.py::test_upload_size_edge` |
| FR-05 | Parse keeping document ID, title, section, heading, page, version, effective date | `document_processing/parsers.py`; `document_sections` | Ch 5 | Tested: `test_documents_exports.py::test_parse_sections_from_real_documents`, `::test_pdf_keeps_repeated_body_text_and_reads_tables_by_row` |
| FR-06 | Chunks keep chunk ID, document ID, section, heading, page reference, version | `document_processing/chunking.py`; `document_chunks` (484 chunks) | Ch 5; App J | Tested indirectly: `test_full_chain.py::test_document_upload_and_policy_versioning_journey` |
| FR-07 | Active, Previous, Superseded, Draft; outdated not the primary basis | `services/documents.py` (demotion), `knowledge_base/store.py`, `rules/precedence/precedence_rules.yaml`; POL-002 | Ch 5, 9 | Tested: `test_defects_and_live_changes.py::test_revised_policy_upload_versioning_and_impact` |
| FR-08 | Structured Rule Matrix, not generated at runtime by GenAI | `rules/*.yaml`, `rule_engine/loader.py`, `services/rules.py` | Ch 10; App B | Tested: `test_rule_engine.py::test_rule_matrix_integrity` |
| FR-09 | Complaint entry fields | `frontend/src/pages/SubmitComplaint.tsx`, `api/v1/complaints.py`, `services/complaints.py::create_complaint` | Ch 7, 27 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FR-10 | Detect empty, short, duplicate, invalid references, missing fields, unsupported attachments | `services/complaints.py::validate_submission`, `security/files.py` | Ch 7 | Tested: `test_boundaries.py` (29 cases); `test_difficult_cases.py::test_exact_duplicate_rejected_and_near_duplicate_linked` |
| FR-11 | Normalisation, sanitisation, metadata extraction, duplicate detection | `security/sanitization.py`, `complaint_processing/`, `services/history.py` | Ch 7 | Tested: `test_perception_security.py::test_normalisation_and_duplicate_hash` |
| FR-12 | GenAI identifies the primary issue (11 example categories) | `primary_issue`; `config/taxonomy.yaml` | Ch 8 | Tested: holdout run (AI category 89.5%) |
| FR-13 | Primary and secondary issues | `secondary_issues`; CLS-003; risk-first precedence | Ch 8, 11 | Tested: `test_difficult_cases.py::test_multi_issue_multi_department` |
| FR-14 | Predefined, configurable categories | `categories` table; `POST /taxonomy/categories` | Ch 10 | Tested: `test_defects_and_live_changes.py::test_new_category_without_code_changes` |
| FR-15 | Subcategories (e.g. Billing: duplicate, incorrect, refund missing, subscription renewal) | 35 subcategories incl. BIL-DUP, BIL-INC, BIL-RFM, BIL-SUB | Ch 8, 10 | Tested: `test_perception_security.py::test_classification_categories` |
| FR-16 | Entities: product, service, order ID, transaction ID, date, amount, location, department, complaint reference | `genai_pipeline/schemas.py` `EntityType`; `complaint_processing/perception.py` | Ch 7, 8 | Tested: `test_perception_security.py::test_entities_extracted` |
| FR-17 | Sentiment with four values | `sentiment`; lexicon estimate; CLS-004 | Ch 8, 14 | Tested: `test_perception_security.py::test_sentiment_is_informational` |
| FR-18 | Emotion indicators do not replace priority rules | `emotion_indicators`; PRI-003 | Ch 14 | Tested: `test_rule_engine.py::test_emotional_language_does_not_raise_priority` |
| FR-19 | Urgency Low to Critical, not only from emotion | Urgency floors, resolution-rule urgency; PRI-001, PRI-003 | Ch 14 | Tested: `test_difficult_cases.py::test_calm_critical_safety_complaint`, `::test_angry_low_priority_complaint` |
| FR-20 | Priority P0 to P3; configurable rules | Priority matrix (`priority_config`); PRI-002 | Ch 14 | Tested: `test_rule_engine.py::test_priority_matrix` |
| FR-21 | Tricky priority cases; sentiment separate from urgency | Signals and rules; customer type ignored for urgency (SLA-RUL-15 §5.4) | Ch 14, 18, 20 | Tested: `test_difficult_cases.py::test_angry_low_priority_complaint`, `::test_calm_critical_safety_complaint`, `::test_privacy_exposure`, `::test_escalation_for_legal_threat`, `::test_repeated_complaint_detected` |
| FR-22 | Recommend a department (10 SRS departments) | `config/departments.yaml`; `department`; `services/pipeline.py::_auto_assign` | Ch 13 | Tested: `test_difficult_cases.py::test_normal_delayed_delivery` |
| FR-23 | Python verifies the department with the Rule Matrix | `rules/routing_rules/routing_rules.yaml`; RTE-001 | Ch 13 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[wrong_department-RTE-001]` |
| FR-24 | Primary and supporting departments | Routing rules; `supporting_departments`; RTE-002 | Ch 13 | Tested: `test_difficult_cases.py::test_multi_issue_multi_department` |
| FR-25 | Retrieve approved sections with source traceability | `knowledge_base/retriever.py` | Ch 9 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FR-26 | Applicable, Conditionally Applicable, Not Applicable, Outdated | `engine.py::assess_applicability`; POL-005; `policy_references` | Ch 9, 11 | Implemented; recorded in the demo database; no dedicated test |
| FR-27 | GenAI resolution steps grounded in rules | `resolution_steps` from the 66-action catalogue; SCH-006 | Ch 8, 15 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FR-28 | Python verifies mandatory steps; detects prohibited or unsupported actions | RES-001 to RES-004 | Ch 15 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[prohibited_action-RSP-006]` |
| FR-29 | Refund eligibility from approved rules | Resolution rules, `refund_window_days` and related parameters; ELG-001 | Ch 15 | Tested: `test_difficult_cases.py::test_unsupported_refund_request`; `test_boundaries.py::test_refund_window_edge` |
| FR-30 | Replacement checked against condition, purchase period, policy, previous replacement | `complaint_processing/order_facts.py`; ELG-002 | Ch 15 | Recorded: lab LAB-POL-02; holdout run (Python 93.4%); no dedicated test |
| FR-31 | Compensation permitted? Unsupported promises flagged | CPN-POL-11 limits; ESC-029, ESC-030; ELG-003, RSP-002 | Ch 15, 17 | Tested: `test_difficult_cases.py::test_unsupported_compensation_request` |
| FR-32 | Professional response with the seven qualities | `prompts/customer_communication/1.0.0.yaml`; RSP-001 to RSP-007 | Ch 16 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FR-33 | Configurable tone | `requested_tone`; RSP-005 | Ch 16 | Implemented; no dedicated test |
| FR-34 | Flag guaranteed refunds, compensation, delivery deadlines, policy exceptions | `hallucination_checks/promises.py`; `config/actions.yaml`; RSP-002, RSP-003, RSP-006 | Ch 17 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[unsupported_refund-RSP-002]` |
| FR-35 | Flag untraceable factual claims | `hallucination_checks/grounding.py`; HAL-001 to HAL-004 | Ch 17 | Tested: `test_perception_security.py::test_claim_grounding_accepts_paraphrase_but_not_invented_facts` |
| FR-36 | Escalation triggers (nine types) | `rules/escalation_rules/escalation_rules.yaml` (39 rules) | Ch 18 | Tested: `test_rule_engine.py::test_safety_signal_forces_critical_escalation`; `test_difficult_cases.py::test_security_account_takeover` |
| FR-37 | Six escalation levels | Levels ranked 0 to 5 in `escalation_rules.yaml` | Ch 18 | Tested: `test_rule_engine.py::test_escalation_level_ranking` |
| FR-38 | Escalation notes with six elements | `escalation_notes`; SCH-005, ESC-004 | Ch 18 | Recorded: validation evidence (ESC-004); no dedicated test |
| FR-39 | Python enforces mandatory escalation | ESC-001, ESC-002; `services/pipeline.py` creates the escalation | Ch 18 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[missed_escalation-ESC-001]` |
| FR-40 | Follow-up communication (six types) | `rules/complaint_rules/followup_rules.yaml`; `follow_up_message` | Ch 16, 19 | Recorded: 747 follow-ups in the demo database; no dedicated test |
| FR-41 | Record when follow-up is required | `follow_ups` table; FUP-003 closure confirmation | Ch 19 | Recorded: demo database; no dedicated test |
| FR-42 | Missing-information detection | `rules/complaint_rules/missing_info_rules.yaml` (MIS-001 to MIS-008) | Ch 11, 19 | Tested: `test_difficult_cases.py::test_missing_information_triggers_clarification` |
| FR-43 | Clarification questions instead of invented facts | `clarification_questions`; `POST /complaints/{ref}/clarify` | Ch 16, 19 | Tested: `test_full_chain.py::test_customer_clarification_loop` |
| FR-44 | Structured complaint summary | `summary`, `key_facts`; HAL-003 | Ch 8 | Tested: `test_perception_security.py::test_validated_summary_never_relays_flagged_instructions` |
| FR-45 | Agent guidance | `agent_guidance`; validated guidance | Ch 8, 27 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FR-46 | JSON schema validation | `genai_pipeline/parsing.py`; SCH-001 to SCH-006 | Ch 8, 11; App C | Tested: `test_genai_providers.py::test_schema_violation_is_retried` |
| FR-47 | Invalid-output handling with bounded retries and manual review | `genai_pipeline/runner.py::run_stage`; `ai_runs`; REV-009 | Ch 8, 36 | Tested: `test_genai_providers.py::test_retries_are_bounded_and_the_failure_is_reported`; `reports/genai_pipeline_evidence/invalid_response_and_retry.json` |
| FR-48 | Central, versioned prompts | `prompts/`, `genai_pipeline/prompts.py`, `prompt_versions` | Ch 21, 22; App K | Recorded: `reports/genai_pipeline_evidence/prompt_templates_and_versions.json` |
| FR-49 | Store prompt version, provider, model, timestamp, policy version per analysis | `analyses` table; `ai_runs` | Ch 22, 37 | Recorded: all 780 analyses in the demo database |
| FR-50 | Complaints and documents are untrusted data | `security/injection.py`; nonce-tagged complaint block (`genai_pipeline/context.py`); chunk quarantine | Ch 23 | Tested: `test_difficult_cases.py::test_prompt_injection_is_blocked`; holdout run (6 of 6) |
| FR-51 | Test adversarial complaints (five kinds) | `config/adversarial_scenarios.yaml`, `services/lab.py`; 31 injection cases in the dataset | Ch 23, 34; App G | Tested: `test_defects_and_live_changes.py::test_every_adversarial_scenario_is_caught`; lab 18 of 18 |
| FR-52 | Exact, near-duplicate and repeated submissions | `services/complaints.py` (HTTP 409), `services/history.py` | Ch 20 | Tested: `test_difficult_cases.py::test_exact_duplicate_rejected_and_near_duplicate_linked` |
| FR-53 | Complaint history per customer | `services/history.py`; `complaint_history` | Ch 20 | Tested: `test_difficult_cases.py::test_repeated_complaint_detected` |
| FR-54 | Repeated unresolved complaints; higher escalation | Repeat detection; ESC-017 to ESC-019 | Ch 18, 20 | Tested: `test_difficult_cases.py::test_repeated_complaint_detected`; holdout run (4 of 4) |
| FR-55 | Configurable response and resolution targets | `rules/sla_rules/sla_rules.yaml`; `services/sla.py::ensure_sla` | Ch 19 | Configured; recorded in `reports/operations/sla-status.pdf`; no automated test |
| FR-56 | Flag complaints approaching deadlines | `services/sla.py::evaluate`, `refresh_all` (every 60 s); ESC-039 | Ch 19 | Recorded: 115 ESC-039 breach escalations in the demo database; no automated test |
| FR-57 | Manual-review conditions (six) | `rules/complaint_rules/review_rules.yaml` (REV-001 to REV-014); `engine.py::finalize` | Ch 11 | Tested: `test_difficult_cases.py::test_ambiguous_complaint_goes_to_review`; holdout run (review recall 94.1%) |
| FR-58 | Approve, reject, modify, reclassify, reassign, escalate, regenerate, comment | `services/reviews.py`, `api/v1/reviews.py`, `frontend/src/pages/ReviewWorkspace.tsx` | Ch 11, 27 | Partial testing: approve in `test_full_chain.py::test_complete_complaint_chain`; seven actions untested |
| FR-59 | Original and reviewer decision in the audit trail | `reviews.original_snapshot`, `final_snapshot`; `review_actions`; `audit_logs` | Ch 37 | Tested: `test_full_chain.py::test_complete_complaint_chain`; `test_security_api.py::test_audit_log_is_append_only_in_the_database` |
| FR-60 | Complaint statuses | `services/complaints.py` `LIFECYCLE`, `TRANSITIONS` | Ch 32 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FR-61 | Customer dashboard fields | `frontend/src/pages/Dashboard.tsx` (`CustomerDashboard`) | Ch 27, 38 | Recorded: screenshot `03-customer-dashboard.png` |
| FR-62 | Agent dashboard fields | `AgentDashboard` | Ch 27, 38 | Recorded: screenshot `06-agent-dashboard.png` |
| FR-63 | Administrator dashboard fields | `OpsDashboard`; `GET /api/v1/dashboard` | Ch 38 | Tested: `test_full_chain.py::test_complete_complaint_chain` (total); screenshot `14-manager-dashboard.png` |
| FR-64 | Analytics dimensions | `services/analytics.py`; `GET /api/v1/analytics/*` | Ch 38 | Recorded: screenshots `20-analytics.png`, `21-analytics-ai-vs-rules.png` |
| FR-65 | Trend detection (five kinds) | `services/analytics.py::trend_alerts` | Ch 38 | Recorded: "Emerging trends" in `reports/complaint_intelligence/complaint-intelligence.pdf` |
| FR-66 | Search and filtering (nine fields) | `api/v1/complaints.py::list_complaints`; `frontend/src/pages/Complaints.tsx` | Ch 26, 27 | Tested (paging only): `test_boundaries.py::test_list_pagination_limits`; screenshot `07-complaint-list.png` |
| FR-67 | Eight report types | `reporting/builders.py` `REPORTS` (10 types) | Ch 38, 39 | Recorded: `reports/operations/`, `reports/genai_python_comparison/`; Partial: see DEL-08.02 |
| FR-68 | Export as CSV, PDF, Excel | `reporting/exports.py` (CSV, XLSX, PDF, JSON) | Ch 38, 39 | Tested: `test_documents_exports.py::test_csv_neutralises_formula_injection`, `::test_xlsx_never_contains_formulas`, `::test_pdf_report_renders_unicode_safely` |

## A.6 Functional-Requirement List (SRS 1.6)

**Table A.8 — Functional-requirement list (FL)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| FL-01 | User authentication | `security/auth.py`, `api/v1/auth.py`, `api/middleware.py` | Ch 24 | Tested: `test_security_api.py::test_account_lockout_after_failed_logins`, `::test_cookie_session_requires_csrf_header` |
| FL-02 | Role-based access control for five roles | `security/rbac.py`, `api/deps.py::require` | Ch 24 | Tested: `test_security_api.py::test_role_permission_matrix_enforced_server_side` |
| FL-03 | Complaint submission | As FR-09 | Ch 7, 27 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FL-04 | Complaint validation | As FR-10 | Ch 7 | Tested: `test_boundaries.py` |
| FL-05 | Complaint pre-processing | As FR-11 | Ch 7 | Tested: `test_perception_security.py::test_normalisation_and_duplicate_hash` |
| FL-06 | Knowledge-base upload (PDF, DOCX) | `POST /api/v1/documents`; `UploadDocumentDialog.tsx` | Ch 5 | Tested: `test_defects_and_live_changes.py::test_revised_policy_upload_versioning_and_impact` |
| FL-07 | Document validation | As FR-04 | Ch 5 | Tested: `test_documents_exports.py::test_metadata_validation_and_version_order` |
| FL-08 | Document parsing | As FR-05 | Ch 5 | Tested: `test_documents_exports.py::test_parse_sections_from_real_documents` |
| FL-09 | Document chunking | As FR-06 | Ch 5 | Tested indirectly: `test_full_chain.py::test_document_upload_and_policy_versioning_journey` |
| FL-10 | Document version control | As FR-07 | Ch 5, 9 | Tested: `test_defects_and_live_changes.py::test_revised_policy_upload_versioning_and_impact` |
| FL-11 | Complaint Resolution Rule Matrix | As FR-08 | Ch 10 | Tested: `test_rule_engine.py::test_rule_matrix_integrity` |
| FL-12 | GenAI API integration | `genai_pipeline/providers/` | Ch 8 | Tested: `test_genai_providers.py` (31); 780 live analyses |
| FL-13 | Primary issue identification | As FR-12 | Ch 8 | Tested: holdout run |
| FL-14 | Secondary issue identification | As FR-13 | Ch 8 | Tested: `test_difficult_cases.py::test_multi_issue_multi_department` |
| FL-15 | Category and subcategory classification | As FR-14, FR-15 | Ch 8, 11 | Tested: `test_perception_security.py::test_classification_categories` |
| FL-16 | Entity extraction | As FR-16 | Ch 7, 8 | Tested: `test_perception_security.py::test_entities_extracted` |
| FL-17 | Sentiment analysis | As FR-17 | Ch 8, 14 | Tested: `test_perception_security.py::test_sentiment_is_informational` |
| FL-18 | Urgency classification | As FR-19 | Ch 14 | Tested: `test_difficult_cases.py::test_calm_critical_safety_complaint` |
| FL-19 | Priority assignment | As FR-20 | Ch 14 | Tested: `test_rule_engine.py::test_priority_matrix` |
| FL-20 | Department routing | As FR-22 | Ch 13 | Tested: `test_difficult_cases.py::test_normal_delayed_delivery` |
| FL-21 | Multi-department routing | As FR-24 | Ch 13 | Tested: `test_difficult_cases.py::test_multi_issue_multi_department` |
| FL-22 | Policy retrieval | As FR-25 | Ch 9 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FL-23 | Policy applicability validation | As FR-26 | Ch 9, 11 | Implemented; no dedicated test |
| FL-24 | Resolution generation | As FR-27 | Ch 8, 15 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FL-25 | Resolution validation | As FR-28 | Ch 15 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[prohibited_action-RSP-006]` |
| FL-26 | Refund rule validation | As FR-29 | Ch 15 | Tested: `test_difficult_cases.py::test_unsupported_refund_request` |
| FL-27 | Replacement rule validation | As FR-30 | Ch 15 | Recorded: lab LAB-POL-02; no dedicated test |
| FL-28 | Compensation validation | As FR-31 | Ch 15 | Tested: `test_difficult_cases.py::test_unsupported_compensation_request` |
| FL-29 | Professional response generation | As FR-32 | Ch 16 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FL-30 | Response tone management | As FR-33 | Ch 16 | Implemented; no dedicated test |
| FL-31 | Unsupported promise detection | As FR-34 | Ch 17 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[unsupported_refund-RSP-002]` |
| FL-32 | Hallucination detection | As FR-35 | Ch 17 | Tested: `test_perception_security.py::test_claim_grounding_accepts_paraphrase_but_not_invented_facts` |
| FL-33 | Escalation detection | As FR-36 | Ch 18 | Tested: `test_difficult_cases.py::test_escalation_for_legal_threat` |
| FL-34 | Escalation level assignment | As FR-37 | Ch 18 | Tested: `test_rule_engine.py::test_escalation_level_ranking` |
| FL-35 | Escalation notes generation | As FR-38 | Ch 18 | Recorded: validation evidence (ESC-004) |
| FL-36 | Escalation validation by Python rules | As FR-39 | Ch 18 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[missed_escalation-ESC-001]` |
| FL-37 | Follow-up communication generation | As FR-40 | Ch 16, 19 | Recorded: demo database |
| FL-38 | Follow-up requirement detection | As FR-41 | Ch 19 | Recorded: demo database |
| FL-39 | Missing-information detection | As FR-42 | Ch 19 | Tested: `test_difficult_cases.py::test_missing_information_triggers_clarification` |
| FL-40 | Clarification question generation | As FR-43 | Ch 16, 19 | Tested: `test_full_chain.py::test_customer_clarification_loop` |
| FL-41 | Complaint summary generation | As FR-44 | Ch 8 | Tested: `test_perception_security.py::test_validated_summary_never_relays_flagged_instructions` |
| FL-42 | Agent guidance | As FR-45 | Ch 8, 27 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FL-43 | Structured JSON output | `schemas/ai/*.schema.json`; `genai_pipeline/schemas.py::constrain_codes`, `provider_schema` | Ch 8; App C, D | Tested: `test_genai_providers.py::test_structured_output_schema_uses_only_supported_keywords`, `::test_openai_request_uses_strict_json_schema` |
| FL-44 | JSON schema validation | As FR-46 | Ch 8, 11 | Tested: `test_genai_providers.py::test_schema_violation_is_retried` |
| FL-45 | Python ground-truth validation | `python_validation/engine.py`, `rule_engine/decision.py` | Ch 11 | Tested: `test_rule_engine.py::test_decision_engine_trace_is_explainable`; holdout run (Python key fields 82.7%) |
| FL-46 | Classification comparison | `engine.py::build_comparison`; "AI vs rules" tab | Ch 12 | Tested: holdout run (category agreement 69.7%) |
| FL-47 | Routing comparison | `build_comparison`; RTE-001 | Ch 12, 13 | Tested: holdout run (department agreement 84.9%) |
| FL-48 | Urgency comparison | `build_comparison`; PRI-001 | Ch 12, 14 | Tested: holdout run (urgency agreement 66.5%) |
| FL-49 | Escalation comparison | `build_comparison`; ESC-001 to ESC-003 | Ch 12, 18 | Tested: holdout run (escalation-level agreement 82.9%) |
| FL-50 | Policy traceability | Validated decision cites the rule's sections; `policy_references`; POL-001 to POL-004, HAL-004 | Ch 9, 37 | Tested: `test_perception_security.py::test_fake_policy_ids_versions_sections` |
| FL-51 | Verification score | `engine.py::finalize`; `rules/validation_policy.yaml` | Ch 11 | Implemented; exercised by every pipeline test; no unit test of the formula |
| FL-52 | Prompt template management | As FR-48 | Ch 21, 22 | Recorded: prompt evidence file |
| FL-53 | Prompt version tracking | As FR-49 | Ch 22, 37 | Recorded: demo database |
| FL-54 | Complaint text must not override instructions | As FR-50 | Ch 23 | Tested: `test_perception_security.py::test_injection_attacks_detected`; holdout run (6 of 6, no false positives) |
| FL-55 | Adversarial complaint handling | As FR-51 | Ch 23, 34 | Tested: `test_defects_and_live_changes.py::test_every_adversarial_scenario_is_caught` |
| FL-56 | Duplicate detection | As FR-52 | Ch 20 | Tested: `test_difficult_cases.py::test_exact_duplicate_rejected_and_near_duplicate_linked` |
| FL-57 | Complaint history | As FR-53 | Ch 20 | Tested: `test_difficult_cases.py::test_repeated_complaint_detected` |
| FL-58 | Repeat complaint detection | As FR-54 | Ch 20 | Tested: `test_difficult_cases.py::test_repeated_complaint_detected` |
| FL-59 | SLA tracking | As FR-55 | Ch 19 | Configured; no automated test |
| FL-60 | SLA risk detection | As FR-56 | Ch 19 | Recorded: demo database; no automated test |
| FL-61 | Manual review queue | As FR-57 | Ch 11, 27 | Tested: `test_difficult_cases.py::test_ambiguous_complaint_goes_to_review` |
| FL-62 | Reviewer decision (approve, modify, reassign, escalate) | As FR-58 | Ch 11, 27 | Partial testing: approve only |
| FL-63 | Reviewer override stored | As FR-59 | Ch 37 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FL-64 | Audit trail of original and final decisions | `audit/service.py`; trigger in migration `0001_initial_schema`; `GET /api/v1/audit/verify` | Ch 37 | Tested: `test_security_api.py::test_audit_log_is_append_only_in_the_database`; `test_full_chain.py::test_complete_complaint_chain` (chain valid) |
| FL-65 | Complaint status tracking | As FR-60 | Ch 32 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FL-66 | Customer dashboard | As FR-61 | Ch 27, 38 | Recorded: screenshot `03-customer-dashboard.png` |
| FL-67 | Agent dashboard | As FR-62 | Ch 27, 38 | Recorded: screenshot `06-agent-dashboard.png` |
| FL-68 | Administrator dashboard | As FR-63 | Ch 38 | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| FL-69 | Complaint analytics | As FR-64 | Ch 38 | Recorded: screenshot `20-analytics.png` |
| FL-70 | Trend detection | As FR-65 | Ch 38 | Recorded: complaint intelligence report |
| FL-71 | Search and filtering | As FR-66 | Ch 26, 27 | Tested (paging only): `test_boundaries.py::test_list_pagination_limits` |
| FL-72 | Complaint and model-validation reports | As FR-67 | Ch 38, 39 | Recorded: `reports/`; Partial: see DEL-08.02 |
| FL-73 | Export of selected results | As FR-68 | Ch 38, 39 | Tested: `test_full_chain.py::test_complete_complaint_chain` (PDF, CSV, XLSX) |
| FL-74 | Error handling (API, parsing, validation, database) | `api/errors.py`; `services/pipeline.py::process_complaint`; `genai_pipeline/runner.py` | Ch 36 | Tested: `test_boundaries.py::test_malformed_body_is_a_field_error_not_a_crash`; `test_documents_exports.py::test_corrupted_document_is_rejected_cleanly` |
| FL-75 | Intuitive, responsive web interface | `frontend/src` (React 19, 18 pages) | Ch 27 | Recorded: 31 screenshots with no console errors; 12 tests in `frontend/src/test/core.test.tsx` |
| FL-76 | Source-grounded, validated intelligence, not a GenAI pass-through | Complete dual-pipeline chain | Ch 3, 4, 11 | Tested: `test_full_chain.py::test_complete_complaint_chain`; holdout run |

## A.7 Roles and Stakeholders

**Table A.9 — Roles (ROL) and stakeholders (STK)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| ROL-01 | Customer | Role `customer` (3 permissions); customer portal | Ch 2, 24, 27 | Tested: `test_security_api.py::test_customer_sees_only_own_complaints` |
| ROL-02 | Agent | Role `agent` (10); agent workspace | Ch 2, 24, 27 | Tested: `test_security_api.py::test_role_permission_matrix_enforced_server_side` |
| ROL-03 | Reviewer | Role `reviewer` (14); review queue and workspace | Ch 2, 24, 27 | Tested: `test_security_api.py::test_role_permission_matrix_enforced_server_side` |
| ROL-04 | Manager | Role `manager` (12); operations dashboard | Ch 2, 24, 38 | Tested: `test_security_api.py::test_role_permission_matrix_enforced_server_side` |
| ROL-05 | Administrator | Role `admin` (24); administration, rules, prompts, knowledge base | Ch 2, 24 | Tested: `test_security_api.py::test_role_permission_matrix_enforced_server_side` |
| STK-01 | Project stakeholders | This report; `README.md` | Ch 1, 2 | Documented |
| STK-02 | Developers | Package structure, tests, lint and type checks | Ch 2, 33 | Tested: 206 backend and 12 frontend tests |
| STK-03 | Evaluators | README section 3; demo accounts; Evaluation page; Adversarial Lab | Ch 2, 41, 42 | Tested: `test_defects_and_live_changes.py::test_hidden_dataset_upload_with_minimal_columns` |
| STK-04 | Customer-service teams | Agent role and workspace | Ch 2, 27 | Recorded: screenshot `06-agent-dashboard.png` |
| STK-05 | Support managers | Manager role, analytics and reports | Ch 2, 38 | Recorded: screenshot `14-manager-dashboard.png` |
| STK-06 | Administrators | Admin role | Ch 2, 24 | Recorded: screenshot `27-administration.png` |
| STK-07 | Complaint-resolution specialists | Agents in DEPT-SAF, DEPT-SEC, DEPT-CMP, DEPT-MGT receiving specialist escalations | Ch 2, 18 | Configured (escalation rules name the departments) |

## A.8 Non-Functional Requirements

**Table A.10 — Non-functional requirements (NFR)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| NFR-1 | Initial recommendation within 20 s | Two model calls; millisecond Python stages; `services/worker.py` | Ch 2, 35 | Tested (measured), **Not met** at the median: p50 21.7 s, p95 33.9 s, 32.4% within 20 s; validated decision alone p50 16.2 s (80.8% within 20 s) |
| NFR-2 | 10,000 complaints, 100 categories/subcategories, 1,000 documents | Indexed PostgreSQL schema, paging, taxonomy and documents as data | Ch 25, 35 | **Not verified**: no load test; demo database 800 complaints, 46 taxonomy entries, 24 documents |
| NFR-3 | Usable interface for all five roles | `frontend/src`; role-specific dashboards and navigation | Ch 27 | Recorded: 31 screenshots, 12 frontend tests; no user study |
| NFR-4 | Mandatory escalation and critical routing enforced before verification; valid source references | RTE-001, ESC-001 (critical); SCH-004, POL-001 to POL-004, HAL-004 | Ch 11, 13, 18 | Tested; **Partial**: Python escalation required 94.7%, department 84.9% on unseen cases |
| NFR-5 | 99% availability during evaluation | `/api/health`, `Dockerfile`, `render.yaml` | Ch 40 | **Planned**: not deployed, not measured |
| NFR-6 | Reliability | `genai_pipeline/runner.py`; `services/pipeline.py::process_complaint`; `api/errors.py` | Ch 36 | Tested: 780 of 780 analyses completed; 31 failed attempts recovered; `test_genai_providers.py::test_retries_are_bounded_and_the_failure_is_reported` |
| NFR-7 | Security | `security/`, `api/deps.py`, `api/middleware.py`, `audit/` | Ch 24, 34 | Tested: `test_security_api.py` (30 tests); lab 18 of 18 |
| NFR-8 | Traceability | `analyses`, `ai_runs`, `validation_checks`, `policy_references`, `audit_logs` | Ch 22, 37 | Tested: `test_full_chain.py::test_complete_complaint_chain` (audit chain valid) |
| NFR-9 | Maintainability and configurability | `rules/`, `config/`, `prompts/`, `schemas/`; `services/rules.py` | Ch 10, 42 | Tested: `test_defects_and_live_changes.py::test_new_category_without_code_changes`, `::test_changing_a_rule_parameter_changes_the_decision` |
| NFR-10 | Responsiveness | `frontend/src` responsive layouts | Ch 27 | Recorded: screenshots `30-mobile-dashboard.png`, `31-mobile-complaint-detail.png` |

## A.9 Competition Integrity and Anti-Shortcut Requirements

**Table A.11 — Competition-integrity requirements (CI)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| CI-01 | Unique organisation: industry, products, departments, categories, policies, resolution, escalation and SLA rules | `config/`, `knowledge_base/`, `rules/` (Lumora Home Technologies, consumer electronics and smart home) | Ch 3, 42 | Configured; uniqueness relative to other teams cannot be checked from this repository |
| CI-02 | Own complaint dataset, not shared | `scripts/generate_dataset.py`, `scripts/dataset/scenarios/` (412 scenarios), `data/` | Ch 6, 42 | Configured; generation documented in `docs/dataset.md` |
| CI-03 | Hidden complaints processed without changing the core architecture | `POST /api/v1/evaluation/runs/upload` (JSON, JSONL, CSV); `services/evaluation.py`, `services/datasets.py` | Ch 6, 12, 42 | Tested: `test_defects_and_live_changes.py::test_hidden_dataset_upload_with_minimal_columns`, `::test_evaluation_run_on_unseen_holdout` |
| CI-04.1 | Revised policy: current resolutions affected? | `services/documents.py::impact_analysis` (`affected_complaints`, `affected_resolution_rules`, `affected_parameters`); `GET /documents/{doc_id}/impact` | Ch 5, 9, 42 | Tested: `test_defects_and_live_changes.py::test_revised_policy_upload_versioning_and_impact` (changed sections, `refund_window_days` out of sync, suggested 21) |
| CI-04.2 | Previous policy obsolete? | Old Active version demoted to Previous; `previous_policy_obsolete` | Ch 5, 42 | Tested: same test (2.0 becomes Previous or Superseded) |
| CI-04.3 | Escalation rules changed? | `affected_escalation_rules`, `escalation_rules_changed` | Ch 5, 42 | Implemented; computed but not asserted by the test |
| CI-04.4 | Generated responses require revision? | `responses_requiring_revision` per affected open complaint | Ch 5, 42 | Implemented; computed but not asserted by the test |
| CI-05 | New category handled through configuration | Taxonomy endpoints; a new subcategory gets routing, resolution and category rules | Ch 10, 42 | Tested: `test_defects_and_live_changes.py::test_new_category_without_code_changes` |
| CI-06 | Sentiment-urgency trap | Priority rules ignore sentiment; PRI-003 | Ch 14 | Tested: `test_difficult_cases.py::test_angry_low_priority_complaint`, `::test_calm_critical_safety_complaint` |
| CI-07 | Escalation trap enforced by Python | ESC-001 (critical); escalation created from the rule decision | Ch 18 | Tested: `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[missed_escalation-ESC-001]`; lab LAB-DEF-01 |
| CI-08 | Prompt-injection challenge | `security/injection.py`; nonce-tagged untrusted block; SEC-001 | Ch 23 | Tested: `test_difficult_cases.py::test_prompt_injection_is_blocked`; holdout run (6 of 6) |
| CI-09 | No promise of unauthorised refund, unsupported compensation, free replacement or policy exception | `hallucination_checks/promises.py`; `config/actions.yaml`; ELG-001 to ELG-003; response written from the validated decision | Ch 16, 17 | Tested for refunds, compensation and exceptions: `test_difficult_cases.py::test_unsupported_refund_request`, `::test_unsupported_compensation_request`; lab LAB-REF-01/02, LAB-CMP-01/02. **Partial** for free replacement: no text detector for a promised replacement in the response |
| CI-10 | Contradictory-policy challenge: precedence applied | `rules/precedence/precedence_rules.yaml` (PRC-001 to PRC-005); conflicts in retrieval; POL-006 | Ch 9 | Tested: `test_difficult_cases.py::test_contradictory_policy_resolved_by_precedence` |
| CI-11 | Missing-information challenge | MIS rules; clarification questions | Ch 19 | Tested: `test_difficult_cases.py::test_missing_information_triggers_clarification`; `test_full_chain.py::test_customer_clarification_loop` |
| CI-12 | Multi-issue challenge (three or more issues) | Secondary issues and supporting departments | Ch 8, 13 | Tested: `test_difficult_cases.py::test_multi_issue_multi_department`; dataset: 12 complaints with three or more issues |
| CI-13 | Repeat complaint with different wording | `services/history.py` (same order, subcategory or similar category text within 90 days) | Ch 20 | Tested: `test_difficult_cases.py::test_repeated_complaint_detected`; holdout run (4 of 4) |
| CI-14.1 | Add a complaint category | `POST /api/v1/taxonomy/categories`, `/taxonomy/subcategories` | Ch 10, 42 | Tested: `test_defects_and_live_changes.py::test_new_category_without_code_changes` |
| CI-14.2 | Add a routing rule | `PUT /api/v1/rules/routing/{rule_id}` (validated before saving) | Ch 10, 13 | Implemented; exercised indirectly when a subcategory is created |
| CI-14.3 | Change priority logic | `PUT /api/v1/rules/config/priority_config`; urgency floors | Ch 10, 14 | Implemented; no automated test |
| CI-14.4 | Add a department | `POST /api/v1/taxonomy/departments` | Ch 10 | Implemented; no automated test |
| CI-14.5 | Change an escalation threshold | `PUT /api/v1/rule-parameters/{key}` (e.g. `high_value_supervisor_usd`); escalation rule edit or disable | Ch 10, 18 | Tested: `test_defects_and_live_changes.py::test_changing_a_rule_parameter_changes_the_decision`, `::test_disabling_an_escalation_rule_changes_validation` |
| CI-14.6 | Modify an SLA | `PUT /api/v1/rules/sla/{rule_id}`; `sla_at_risk_pct` parameter | Ch 19 | Implemented; no automated test |
| CI-14.7 | Change the JSON schema | Edit `schemas/ai/*.schema.json`, loaded at runtime; extra fields kept (`extra="allow"`); `scripts/export_schemas.py` | Ch 8; App C | Implemented; no automated test |
| CI-14.8 | Add a new validation rule | New rule data (resolution, escalation, missing-information, review rules) needs no code; a new check type needs a function in `python_validation/engine.py` and an entry in `rules/validation_policy.yaml` | Ch 11, 42 | **Partial**: code change for new check types; `test_defects_and_live_changes.py::test_rule_edit_preview_validates_without_saving` |
| CI-14.9 | Add a dashboard filter | The complaint API already accepts more than 20 filters; a new filter on screen needs a change in `frontend/src/pages/Complaints.tsx` or `Dashboard.tsx` | Ch 27, 42 | **Partial**: frontend code change required |
| CI-15.1 | Deliberate defect in Python validation | Automated suite (`test_rule_engine.py`, fault-profile tests) exposes broken checks | Ch 33, 42 | Supported by tests; the live diagnosis is a team activity |
| CI-15.2 | Defect in routing logic | `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[wrong_department-RTE-001]`; rule integrity checks (`rule_engine/integrity.py`) | Ch 13, 42 | Supported by tests |
| CI-15.3 | Defect in a prompt template | Versioned prompts; roll back with `POST /api/v1/prompts/{key}/versions/{version}/activate`; failures go to manual review | Ch 22, 42 | Implemented; no automated test |
| CI-15.4 | Defect in JSON parsing | `test_genai_providers.py::test_invalid_json_is_retried_with_the_validation_errors_then_accepted`, `::test_schema_violation_is_retried` | Ch 8, 42 | Supported by tests |
| CI-15.5 | Defect in policy mapping | `test_perception_security.py::test_fake_policy_ids_versions_sections`; integrity checks; `POST /api/v1/rules/validate` | Ch 9, 42 | Supported by tests |
| CI-15.6 | Defect in escalation rules | `test_rule_engine.py::test_safety_signal_forces_critical_escalation`, `::test_rule_matrix_integrity`; `POST /api/v1/rules/reset-to-baseline` | Ch 18, 42 | Supported by tests |
| CI-16 | Meaningful commits across all five days | Git repository | Ch 42 | **Not met**: two commits, both dated 2026-09-25 |
| CI-17 | No hard-coded classifications, responses, fake GenAI output, fabricated scores, hard-coded escalations or disguised pre-written resolutions | No mock provider in the application; the score comes only from check results; decisions computed from the Rule Matrix at runtime | Ch 42 | Tested: `test_genai_providers.py::test_there_is_no_mock_provider`; `test_ai_not_configured.py::test_no_api_key_means_no_ai_output_and_manual_review` (the offline test double exists only in `tests/support/offline_llm.py`) |
| CI-18 | GenAI must not replace business rules, validation, schema validation, precedence, escalation, audit or security logic | All of these are deterministic Python (`rule_engine/`, `python_validation/`, `genai_pipeline/parsing.py`, `knowledge_base/`, `audit/`, `security/`) | Ch 4, 11, 42 | Implemented; see SOL-12 |
| CI-19 | AI_USAGE.md with the seven fields; AI-generated code reviewed and understood | `AI_USAGE.md` | Ch 42 | **Partial**: six fields present; verifying-team-members table empty; its test counts (191 backend, 11 frontend) predate the recorded run (206, 12) |
| CI-20 | All functional and non-functional requirements implemented | This matrix | Ch 2; App A | **Partial**: see Section A.14 |

## A.10 Interface Requirements

**Table A.12 — Hardware (IF-HW) and software (IF-SW) requirements**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| IF-HW-1 | Intel Core i5/i7 or higher | Development workstation: Intel Core i5-6500 | Ch 41 | Met by the development workstation |
| IF-HW-2 | 8 GB RAM or higher | Development workstation: 16 GB | Ch 41 | Met by the development workstation |
| IF-HW-3 | Colour SVGA monitor | Environment | Ch 41 | Not checked (environment) |
| IF-HW-4 | 500 GB hard disk | Development workstation: 238 GB disk | Ch 41 | Below the listed size on the development workstation |
| IF-HW-5 | Mouse and keyboard | Environment | Ch 41 | Not checked (environment) |
| IF-SW-01 | Frontend technology | React 19.2, TypeScript 6.0, Tailwind CSS 4.3, Vite 8 (`frontend/package.json`) | Ch 4, 27 | Implemented |
| IF-SW-02 | Backend: Flask, Django, FastAPI or Streamlit | FastAPI 0.141.1 on uvicorn 0.53.0 | Ch 4, 26 | Implemented |
| IF-SW-03 | Python | Python 3.14 for development and tests (3.12 or later supported) | Ch 4, 41 | Implemented |
| IF-SW-04 | Development IDE | Not recorded in the repository; `AI_USAGE.md` names Claude Code as the coding assistant | Ch 41 | Not verifiable from the repository |
| IF-SW-05 | GenAI API | OpenAI gpt-4.1-mini (default); Anthropic and Google Gemini adapters | Ch 8 | Tested: `test_genai_providers.py`; live runs |
| IF-SW-06 | Document processing | PyMuPDF 1.28.2, python-docx 1.2.0 | Ch 5 | Tested: `test_documents_exports.py::test_parse_sections_from_real_documents` |
| IF-SW-07 | Data processing: Pandas, NumPy | NumPy 2.5.3 (vectors, similarity); Pandas is not used | Ch 4, 9 | Implemented (NumPy) |
| IF-SW-08 | Validation methods | Pydantic 2.13.5, jsonschema 4.26.0, regular expressions, the rule engine | Ch 8, 11 | Tested: `test_genai_providers.py`, `test_rule_engine.py` |
| IF-SW-09 | Semantic retrieval | BM25 plus local feature-hashing embeddings (`knowledge_base/bm25.py`, `embeddings.py`); optional OpenAI or Gemini embeddings | Ch 9 | Tested: `test_full_chain.py::test_document_upload_and_policy_versioning_journey` |
| IF-SW-10 | Database | PostgreSQL 17 with SQLAlchemy 2.0.54 and Alembic 1.20.0 | Ch 25 | Tested: API, integration and end-to-end tests run on PostgreSQL |
| IF-SW-11 | Visualisation | Recharts 3.10 web charts | Ch 38 | Recorded: screenshots `20-analytics.png`, `14-manager-dashboard.png` |
| IF-SW-12 | Git and GitHub | Git repository with remote `github.com/AbdullahHamid2003/Supoort-Nova--Gen-AI` | Ch 42 | Implemented; see CI-16 |
| IF-SW-13 | Deployment platform | `render.yaml` (Render), `Dockerfile`, `docker-compose.yml` | Ch 40 | **Planned**: configuration prepared, not deployed |

## A.11 Dataset and Hidden Evaluation

The counts in Table A.13 are those of the development set (`data/sample_complaints/dataset_summary.json`), whose SRS minimum checks all passed (`all_checks_passed: true`).

**Table A.13 — Dataset requirements (DS)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| DS-01 | Own organisation, complaints, policies, SOPs, routing rules and rule matrix | `config/`, `data/`, `knowledge_base/`, `rules/`; `scripts/generate_dataset.py` | Ch 6; App I | Configured |
| DS-02 | At least 500 unique complaints | 617 development (CMP-00001 to CMP-00617) and 154 holdout (EVL-00001 to EVL-00154) | Ch 6; App I | Configured; `scripts/validate_dataset.py` reproduces all 771 label sets |
| DS-03 | At least 10 categories | 11 categories | Ch 6, 10 | Tested: `test_rule_engine.py::test_rule_matrix_meets_srs_minimums` |
| DS-04 | At least 20 subcategories | 35 subcategories, each with at least 10 development complaints | Ch 6, 10 | Tested: `test_rule_engine.py::test_rule_matrix_meets_srs_minimums` |
| DS-05 | At least 8 departments | 10 departments (9 used as primary, all 10 in some role) | Ch 6, 13 | Tested: `test_rule_engine.py::test_rule_matrix_meets_srs_minimums` |
| DS-06 | At least 20 policy/SOP documents | 24 documents, 29 versions | Ch 5 | Tested: `test_documents_exports.py::test_knowledge_base_meets_srs_minimums` |
| DS-07 | At least 100 resolution rules | 116 resolution rules | Ch 10 | Tested: `test_rule_engine.py::test_rule_matrix_meets_srs_minimums` |
| DS-08 | At least 30 escalation rules | 39 escalation rules | Ch 18 | Tested: `test_rule_engine.py::test_rule_matrix_meets_srs_minimums` |
| DS-09 | At least 25 ambiguous or multi-issue complaints | 73 (22 ambiguous, 51 multi-issue) | Ch 6 | Configured (dataset summary) |
| DS-10 | At least 20 contradictory or difficult policy cases | 32 | Ch 6, 9 | Configured (dataset summary) |
| DS-11 | At least 20 prompt-injection/adversarial complaints | 31 | Ch 6, 23 | Configured (dataset summary) |
| DS-12 | At least 25 repeated or near-duplicate complaints | 37 (9 exact duplicates, 11 near-duplicates, 17 repeats) | Ch 6, 20 | Configured (dataset summary) |
| DS-13 | Simple complaints | 350 | Ch 6 | Configured |
| DS-14 | Multi-issue complaints | 51, of which 12 have three or more issues | Ch 6 | Configured |
| DS-15 | Incomplete complaints | 38 | Ch 6 | Configured |
| DS-16 | Emotional complaints | 38 emotional low-priority cases; 306 complaints labelled Negative or Strongly Negative | Ch 6 | Configured |
| DS-17 | Calm but critical complaints | 70 | Ch 6 | Configured |
| DS-18 | High-priority complaints | 97 P0 and 23 P1 | Ch 6 | Configured |
| DS-19 | Low-priority complaints | 187 P3 | Ch 6 | Configured |
| DS-20 | Repeated complaints | 17 repeats (37 including duplicates) | Ch 6, 20 | Configured |
| DS-21 | Contradictory complaints | 32 | Ch 6 | Configured |
| DS-22 | Policy-exception requests | 5 | Ch 6 | Configured |
| DS-23 | Unsupported refund requests | 45 | Ch 6 | Configured |
| DS-24 | Security complaints | 27 | Ch 6 | Configured |
| DS-25 | Privacy complaints | 49 | Ch 6 | Configured |
| DS-26 | Safety complaints | 50 | Ch 6 | Configured |

**Table A.14 — Hidden evaluation requirements (HE)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| HE-01 | Unseen complaints and documents at final evaluation | Evaluation upload; Knowledge Base upload; 154-case holdout set as rehearsal (`data/hidden_test_ready/`) | Ch 6, 12, 42 | Tested: `test_defects_and_live_changes.py::test_evaluation_run_on_unseen_holdout`; holdout run |
| HE-02 | New complaint category | Taxonomy endpoints | Ch 10, 42 | Tested: `test_defects_and_live_changes.py::test_new_category_without_code_changes` |
| HE-03 | New complaint subcategory | `POST /api/v1/taxonomy/subcategories` | Ch 10, 42 | Tested: same test (ENV-RCY) |
| HE-04 | New policy | Upload of `data/hidden_test_ready/documents/ENV-POL-25_v1.0.docx` | Ch 5, 42 | Tested (generic new document): `test_full_chain.py::test_document_upload_and_policy_versioning_journey`; ENV-POL-25 itself not uploaded by a test |
| HE-05 | Revised policy | `REF-POL-02_v2.1.pdf`; impact analysis | Ch 5, 42 | Tested: `test_defects_and_live_changes.py::test_revised_policy_upload_versioning_and_impact` |
| HE-06 | Outdated policy | Previous and Superseded handling; POL-002 | Ch 5, 9 | Tested: same test; lab LAB-POL-03 |
| HE-07 | New routing rule | `PUT /api/v1/rules/routing/{rule_id}` | Ch 13, 42 | Implemented; see CI-14.2 |
| HE-08 | New escalation condition | `PUT /api/v1/rules/escalation/{rule_id}`; signals are configuration | Ch 18, 42 | Tested: `test_defects_and_live_changes.py::test_rule_edit_preview_validates_without_saving` |
| HE-09 | Multi-department complaint | Supporting departments | Ch 13 | Tested: `test_difficult_cases.py::test_multi_issue_multi_department`; 8 holdout cases |
| HE-10 | Ambiguous complaint | REV-005 | Ch 11 | Tested: `test_difficult_cases.py::test_ambiguous_complaint_goes_to_review`; 4 of 4 holdout cases reviewed |
| HE-11 | Prompt-injection complaint | `security/injection.py` | Ch 23 | Tested: holdout run (6 of 6) |
| HE-12 | Unsupported compensation request | ELG-003, RSP-002 | Ch 15 | Tested: `test_difficult_cases.py::test_unsupported_compensation_request` |
| HE-13 | Calmly written critical complaint | Urgency floors, safety signals | Ch 14 | Tested: `test_difficult_cases.py::test_calm_critical_safety_complaint` |
| HE-14 | Angry but low-priority complaint | Sentiment excluded from priority | Ch 14 | Tested: `test_difficult_cases.py::test_angry_low_priority_complaint` |
| HE-15 | Repeat unresolved complaint | ESC-017 to ESC-019 | Ch 20 | Tested: `test_difficult_cases.py::test_repeated_complaint_detected` |
| HE-16 | Missing customer information | MIS rules | Ch 19 | Tested: `test_difficult_cases.py::test_missing_information_triggers_clarification` |
| HE-17 | Contradictory company instructions | Precedence rules; POL-006 | Ch 9 | Tested: `test_difficult_cases.py::test_contradictory_policy_resolved_by_precedence` |
| HE-18 | Process hidden data without changing core code | Configuration-driven taxonomy, rules, prompts and schemas; upload formats JSON, JSONL, CSV | Ch 42 | Tested: `test_defects_and_live_changes.py::test_hidden_dataset_upload_with_minimal_columns` |
| HE-19 | Hidden pack may contain PDF and DOCX | `document_processing/parsers.py` with numbered-heading fallback for unseen layouts | Ch 5 | Tested: `test_documents_exports.py::test_parse_sections_from_real_documents[pdf]`, `[docx]` |

## A.12 Deliverables

**Table A.15 — Deliverables (DEL)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| DEL-00 | Design, build, test, document, deploy and demonstrate the application | Repository and this report | Ch 1-45 | **Partial**: built, tested and documented; deployment and demonstration outstanding |
| DEL-01 | Project report with 32 required items | `documentation/` | See Table A.16 | This report |
| DEL-02 | Repository contents (28 items) | Repository root | Ch 3, 4 | See Table A.17 |
| DEL-03 | Complaint dataset with metadata, categories, subcategories, expected routing, urgency and escalation, difficult, injection, duplicate, incomplete and multi-issue cases | `data/sample_complaints/complaints.jsonl` and `.csv` (617), `data/hidden_test_ready/holdout_complaints.jsonl` and `.csv` (154), `customers.json` (300), `orders.json` (594), `dataset_summary.json`; schema `schemas/dataset/complaint_record.schema.json` | Ch 6; App I | Configured; every record carries an `expected` block and a `difficulty_type` |
| DEL-04 | Knowledge-base dataset: policies, SOPs, FAQs, routing, escalation and resolution rules, metadata, version history, conflict cases | `knowledge_base/` (16 policies, 5 SOPs, 3 FAQs, 2 rule documents, 2 guidelines, 1 template; 29 versions; `manifest.yaml`); `rules/`; 32 contradictory-policy complaints; `GET /api/v1/knowledge/conflicts` | Ch 5, 9; App J | Configured |
| DEL-05 | Rule Matrix with rule ID, category, subcategory, conditions, department, urgency, priority, policy, escalation, required and prohibited actions, follow-up | `reports/rule_matrix/complaint_resolution_rule_matrix.csv`, `.xlsx`, `.pdf`, `.yaml` (155 rows: 116 resolution and 39 escalation rules) | Ch 10; App B | Configured; all twelve SRS columns present, plus supporting departments, impact and status |
| DEL-06 | GenAI evidence: provider, model, templates, versions, generation configuration, sample requests and responses, invalid responses, retries | `reports/genai_pipeline_evidence/` (`provider_and_generation_config.json`, `prompt_templates_and_versions.json`, `sample_request_and_structured_response.json`, `invalid_response_and_retry.json`, `attempt_statistics.json`: 1,560 valid and 31 invalid attempts) | Ch 8, 21, 22; App D, K | Recorded |
| DEL-07 | Python validation evidence (ten types) | `reports/python_validation_evidence/README.md`, `examples.json` | Ch 11; App E | Recorded: one real example per type |
| DEL-08.01 | Comparison of at least 100 unseen cases | Evaluation run 1: 154 holdout cases | Ch 12; App F | Recorded: `reports/genai_python_comparison/summary.md` |
| DEL-08.02 | Per-case columns: ID, expected, GenAI and Python category, department, urgency, escalation, policy reference, match, verification status, explanation | `reporting/builders.py::genai_python_comparison` | Ch 12; App F | **Partial**: the Evaluation run page shows the per-case table correctly (screenshot `24-evaluation-run-holdout.png`), but every export of a run, both the committed `genai-python-comparison.csv`, `.xlsx` and `.pdf` and `GET /evaluation/runs/{id}/report`, shows "None/None" and empty department, urgency, escalation and policy columns with "Match" on all 154 rows, because `_comparison_row` reads a `rows` list that evaluation results do not contain |
| DEL-09 | Complaint Intelligence Report (ten contents) | `reports/complaint_intelligence/complaint-intelligence.pdf`, `.xlsx` (summary, category, priority, sentiment, department, escalation level, repeats, policy usage, AI vs rules disagreements, SLA risk, manual-review cases, emerging trends) | Ch 39 | Recorded |
| DEL-10.01 | Prompt-injection tests | Lab LAB-INJ-01 to LAB-INJ-03; injection corpora | Ch 23, 34; App G | Tested: `test_perception_security.py::test_injection_attacks_detected`; lab 3 of 3 |
| DEL-10.02 | Unsupported refund request | Lab LAB-REF-01, LAB-REF-02 | Ch 34; App G | Tested: `test_difficult_cases.py::test_unsupported_refund_request`; lab 2 of 2 |
| DEL-10.03 | Fake policy statement | Lab LAB-POL-01 (HAL-004 on REF-POL-77) | Ch 17, 34 | Recorded: lab 1 of 1 |
| DEL-10.04 | Invalid policy ID | Lab LAB-POL-02, LAB-POL-03 (SCH-004, POL-002) | Ch 17, 34 | Tested: `test_perception_security.py::test_fake_policy_ids_versions_sections`; lab 2 of 2 |
| DEL-10.05 | Unauthorised compensation request | Lab LAB-CMP-01, LAB-CMP-02 | Ch 34 | Tested: `test_difficult_cases.py::test_unsupported_compensation_request`; lab 2 of 2 |
| DEL-10.06 | Malicious document instruction | `knowledge_base/security_samples/MAL-DOC-99_v1.0.docx`; `POST /api/v1/lab/document-scan`; chunk quarantine | Ch 23, 34 | Tested: `test_defects_and_live_changes.py::test_malicious_document_upload_is_quarantined`, `test_documents_exports.py::test_malicious_document_sections_flagged`. Note: the four quarantined sections listed in `security.xlsx` belong to legitimate documents (ESC-SOP-12 §3.1 in versions 3.0, 3.1 and 3.2, and RET-SOP-23 §3); the active ESC-SOP-12 v3.1 §3.1 ("no additional approval is needed") is a false positive and is excluded from evidence |
| DEL-10.07 | Sensitive data handling | `security/pii.py`; SEC-002; lab LAB-PII-01, LAB-PII-02 | Ch 24, 34 | Tested: `test_perception_security.py::test_pii_redaction`; lab 2 of 2 |
| DEL-10.08 | Unauthorised-access tests | `tests/backend/api/test_security_api.py` | Ch 24, 34 | Tested: 30 tests |
| DEL-11 | Test cases of 20 types | See Table A.21 | Ch 33; App H | Tested |
| DEL-12.01 | Python installation | `README.md` section 1 (Python 3.12 or later required) | Ch 41 | **Partial** in README: the required version is stated, installing Python is not described |
| DEL-12.02 | Virtual environment setup | README section 1, step 1 | Ch 41 | Documented |
| DEL-12.03 | Dependency installation | README section 1, steps 1 and 2 (`requirements-dev.txt`, `npm ci`) | Ch 41 | Documented |
| DEL-12.04 | GenAI API configuration | README section 2 (`AI_PROVIDER`, `AI_MODEL`) | Ch 41 | Documented |
| DEL-12.05 | Secure API-key storage | README section 2 (`.env.secrets`) | Ch 41 | Documented |
| DEL-12.06 | Database configuration | README section 1 step 3 (`scripts/devdb.py`), section 6 (`DATABASE_URL`) | Ch 41 | Documented |
| DEL-12.07 | Knowledge-base setup | README section 1 (seeded on first start: 24 documents, 29 versions) | Ch 41 | Documented |
| DEL-12.08 | Complaint dataset setup | README section 1 (617 complaints imported; `SEED_DATASET_ON_STARTUP`) | Ch 41 | Documented |
| DEL-12.09 | Application startup | README section 1, step 5 | Ch 41 | Documented |
| DEL-12.10 | Test execution | README section 4 | Ch 33, 41 | Documented; the README still states 191 backend tests (206 in the recorded run) |
| DEL-12.11 | Troubleshooting | README section 10 | Ch 41 | Documented |
| DEL-12.12 | API keys never committed | `.gitignore` (`.env`, `.env.*`) | Ch 24, 41 | Configured; see SEC-06 |
| DEL-13 | README execution instructions (14 steps) | README section 5 lists all 14 steps with the screen for each | Ch 41 | Documented |
| DEL-14 | GitHub repository obligations | See Table A.18 | Ch 42 | See Table A.18 |
| DEL-15 | Deployed application | See Table A.19 | Ch 40 | See Table A.19 |
| DEL-16 | Demonstration video (.mp4, 21 contents) | Every feature to be shown exists (Chapters 5 to 39) | Ch 40 | **Not met**: README: "Demonstration video: not recorded yet" |
| DEL-17 | Technical blog of at least 2,000 words (20 topics) | — | — | **Not met**: README: "Technical blog: not published yet" |
| DEL-18 | AI tool usage declaration | `AI_USAGE.md` | Ch 42 | **Partial**: see CI-19 |
| DEL-19 | Final submission checklist | See Table A.20 | — | See Table A.20 |

**Table A.16 — Required report contents (DEL-01)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| DEL-01.01 | Problem definition | `documentation/chapters/` | Ch 1 | This report |
| DEL-01.02 | Background | `documentation/chapters/` | Ch 1 | This report |
| DEL-01.03 | Proposed solution | `documentation/chapters/` | Ch 1, 3 | This report |
| DEL-01.04 | Purpose | `documentation/chapters/` | Ch 1 | This report |
| DEL-01.05 | Scope | `documentation/chapters/` | Ch 1 | This report |
| DEL-01.06 | Constraints | `documentation/chapters/` | Ch 1 | This report |
| DEL-01.07 | Functional requirements | `documentation/chapters/` | Ch 2; App A | This report |
| DEL-01.08 | Non-functional requirements | `documentation/chapters/` | Ch 2, 35 | This report |
| DEL-01.09 | Application architecture | `documentation/chapters/` | Ch 4 | This report |
| DEL-01.10 | Module descriptions | `documentation/chapters/` | Ch 3, 4 | This report |
| DEL-01.11 | Database design | `documentation/chapters/` | Ch 25; App M | This report |
| DEL-01.12 | Data Flow Diagram | `documentation/diagrams/data-flow/` | Ch 28 | This report |
| DEL-01.13 | Use Case Diagram | `documentation/diagrams/uml/` | Ch 29 | This report |
| DEL-01.14 | Activity Diagram | `documentation/diagrams/uml/` | Ch 30 | This report |
| DEL-01.15 | Sequence Diagram | `documentation/diagrams/uml/` | Ch 31 | This report |
| DEL-01.16 | Complaint-processing pipeline | `documentation/chapters/` | Ch 7 | This report |
| DEL-01.17 | Knowledge-base processing | `documentation/chapters/` | Ch 5 | This report |
| DEL-01.18 | Complaint Resolution Rule Matrix | `documentation/chapters/` | Ch 10; App B | This report |
| DEL-01.19 | Prompt design | `documentation/chapters/` | Ch 21 | This report |
| DEL-01.20 | Prompt versions | `documentation/chapters/` | Ch 22; App K | This report |
| DEL-01.21 | GenAI API | `documentation/chapters/` | Ch 8 | This report |
| DEL-01.22 | JSON schema | `documentation/chapters/` | Ch 8; App C | This report |
| DEL-01.23 | Ground-truth validation | `documentation/chapters/` | Ch 11; App E | This report |
| DEL-01.24 | Routing validation | `documentation/chapters/` | Ch 13 | This report |
| DEL-01.25 | Escalation logic | `documentation/chapters/` | Ch 18 | This report |
| DEL-01.26 | Policy validation | `documentation/chapters/` | Ch 9, 11 | This report |
| DEL-01.27 | Hallucination handling | `documentation/chapters/` | Ch 17 | This report |
| DEL-01.28 | Prompt-injection protection | `documentation/chapters/` | Ch 23 | This report |
| DEL-01.29 | Testing | `documentation/chapters/` | Ch 33; App H | This report |
| DEL-01.30 | Security | `documentation/chapters/` | Ch 24, 34; App G | This report |
| DEL-01.31 | Limitations | `documentation/chapters/` | Ch 43 | This report |
| DEL-01.32 | Future enhancements | `documentation/chapters/` | Ch 44 | This report |

**Table A.17 — Required repository contents (DEL-02)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| DEL-02.01 | README.md | `README.md` | Ch 41 | Present |
| DEL-02.02 | AI_USAGE.md | `AI_USAGE.md` | Ch 42 | Present; see CI-19 |
| DEL-02.03 | requirements.txt | `requirements.txt` (runtime pins), `requirements-dev.txt` | Ch 41 | Present |
| DEL-02.04 | LICENSE | `LICENSE` (MIT) | — | Present |
| DEL-02.05 | src/ | `backend/src/supportnova/` | Ch 4 | Present under a different path |
| DEL-02.06 | templates/ | No server-side templates; the React application in `frontend/` renders every page | Ch 4, 27 | Equivalent (single-page application) |
| DEL-02.07 | static/ | Frontend build output served by FastAPI (`SERVE_FRONTEND`); built into `frontend/dist`, which is git-ignored | Ch 4, 40 | Equivalent |
| DEL-02.08 | complaint_processing/ | `backend/src/supportnova/complaint_processing/` | Ch 7 | Present |
| DEL-02.09 | document_processing/ | `backend/src/supportnova/document_processing/` | Ch 5 | Present |
| DEL-02.10 | knowledge_base/ | `knowledge_base/` (documents) and `backend/src/supportnova/knowledge_base/` (retrieval code) | Ch 5, 9 | Present |
| DEL-02.11 | genai_pipeline/ | `backend/src/supportnova/genai_pipeline/` | Ch 8 | Present |
| DEL-02.12 | python_validation/ | `backend/src/supportnova/python_validation/` | Ch 11 | Present |
| DEL-02.13 | complaint_rules/ | `rules/complaint_rules/` | Ch 10 | Present |
| DEL-02.14 | routing_rules/ | `rules/routing_rules/` | Ch 13 | Present |
| DEL-02.15 | escalation_rules/ | `rules/escalation_rules/` | Ch 18 | Present |
| DEL-02.16 | prompt_templates/ | `prompts/` | Ch 21, 22 | Present under a different name |
| DEL-02.17 | schemas/ | `schemas/ai/`, `schemas/dataset/` | Ch 8; App C | Present |
| DEL-02.18 | comparison_engine/ | No separate folder: `python_validation/engine.py::build_comparison` (per complaint) and `services/evaluation.py` (per run) | Ch 12 | Present inside `python_validation/` and `services/` |
| DEL-02.19 | hallucination_checks/ | `backend/src/supportnova/hallucination_checks/` | Ch 17 | Present |
| DEL-02.20 | security/ | `backend/src/supportnova/security/` | Ch 23, 24 | Present |
| DEL-02.21 | database/ | `backend/src/supportnova/database/` (models, Alembic migrations) | Ch 25 | Present |
| DEL-02.22 | tests/ | `tests/` (206 backend tests), `frontend/src/test/` (12) | Ch 33 | Present |
| DEL-02.23 | sample_complaints/ | `data/sample_complaints/` | Ch 6 | Present under `data/` |
| DEL-02.24 | sample_documents/ | `knowledge_base/sample_documents/` | Ch 5 | Present under `knowledge_base/` |
| DEL-02.25 | hidden_test_ready/ | `data/hidden_test_ready/` (154 holdout complaints, ENV-POL-25 v1.0, REF-POL-02 v2.1) | Ch 6, 42 | Present under `data/` |
| DEL-02.26 | documentation/ | `documentation/` (this report), `docs/dataset.md` | — | Present |
| DEL-02.27 | screenshots/ | `screenshots/` (31 images) | Ch 27 | Present |
| DEL-02.28 | reports/ and config/ | `reports/`, `config/` | Ch 38, 39 | Present |

**Table A.18 — GitHub repository obligations (DEL-14)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| DEL-14.01 | Be public | Remote `github.com/AbdullahHamid2003/Supoort-Nova--Gen-AI` | Ch 42 | **Not verified** from the repository |
| DEL-14.02 | Meaningful commits across all five days | Git history | Ch 42 | **Not met**: two commits, both on 2026-09-25 |
| DEL-14.03 | Work from all team members | Git history; `AI_USAGE.md` team review table | Ch 42 | **Not met**: no contribution record |
| DEL-14.04 | Complete Python code | `backend/src/supportnova/` (14 packages), `scripts/` | Ch 4 | Present |
| DEL-14.05 | Prompt templates | `prompts/` | Ch 21 | Present |
| DEL-14.06 | Validation rules | `rules/` including `rules/validation_policy.yaml` | Ch 10, 11 | Present |
| DEL-14.07 | Complaint dataset | `data/` | Ch 6 | Present |
| DEL-14.08 | Sample documents | `knowledge_base/sample_documents/` | Ch 5 | Present |
| DEL-14.09 | Tests | `tests/`, `frontend/src/test/` | Ch 33 | Present |
| DEL-14.10 | Evaluator instructions | README section 3 | Ch 41 | Present |
| DEL-14.11 | Assumptions | README section 9 | Ch 43 | Present |
| DEL-14.12 | Limitations | README section 9 | Ch 43 | Present |
| DEL-14.13 | Blog link | README "Links" | — | **Not met**: blog not published |
| DEL-14.14 | Demonstration-video link | README "Links" | — | **Not met**: video not recorded |
| DEL-14.15 | Secrets and API keys not uploaded | `.gitignore`; key only in `.env.secrets` | Ch 24 | Configured |

**Table A.19 — Deployed application (DEL-15)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| DEL-15.01 | Public application URL | `render.yaml`, `Dockerfile` | Ch 40 | **Not met**: not deployed |
| DEL-15.02 | Evaluator credentials | Demo accounts for all five roles (README section 1; `GET /api/v1/auth/demo-accounts`) | Ch 41 | Configured (local installation) |
| DEL-15.03 | Administrator credentials | `admin@lumora.example` (password in README section 1, `DEMO_PASSWORD`) | Ch 41 | Configured (local installation) |
| DEL-15.04 | Sample complaints | `data/sample_complaints/`; seeded on first start | Ch 6 | Configured |
| DEL-15.05 | Sample policy documents | `knowledge_base/sample_documents/` | Ch 5 | Configured |
| DEL-15.06 | Testing instructions | README sections 3 and 4 | Ch 33, 41 | Documented |

**Table A.20 — Final submission checklist (DEL-19)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| DEL-19.01 | Project report | `documentation/` | Ch 1-45 | This report |
| DEL-19.02 | Public GitHub URL | Git remote | Ch 42 | **Not verified** (see DEL-14.01) |
| DEL-19.03 | Complete Python source code | `backend/`, `scripts/` | Ch 4 | Present |
| DEL-19.04 | Complaint dataset | `data/` | Ch 6 | Present |
| DEL-19.05 | Knowledge-base documents | `knowledge_base/` | Ch 5 | Present |
| DEL-19.06 | Complaint Resolution Rule Matrix | `rules/`, `reports/rule_matrix/` | Ch 10; App B | Present |
| DEL-19.07 | Prompt templates | `prompts/` | Ch 21 | Present |
| DEL-19.08 | Prompt versions | 4 versions in `prompts/` and `prompt_versions` | Ch 22; App K | Present |
| DEL-19.09 | JSON schemas | `schemas/` | Ch 8; App C | Present |
| DEL-19.10 | GenAI pipeline | `genai_pipeline/` | Ch 8 | Present |
| DEL-19.11 | Python Ground-Truth Validation Pipeline | `python_validation/`, `rule_engine/`, `hallucination_checks/` | Ch 11 | Present |
| DEL-19.12 | GenAI/Python comparison report | `reports/genai_python_comparison/` | Ch 12; App F | **Partial** (see DEL-08.02) |
| DEL-19.13 | Complaint Intelligence report | `reports/complaint_intelligence/` | Ch 39 | Present |
| DEL-19.14 | Security testing report | `reports/security_adversarial/` | Ch 34; App G | Present |
| DEL-19.15 | Installation instructions | `README.md` | Ch 41 | Present |
| DEL-19.16 | Execution instructions | `README.md` section 5 | Ch 41 | Present |
| DEL-19.17 | Deployment URL | — | Ch 40 | **Not met** |
| DEL-19.18 | Demonstration video | — | — | **Not met** |
| DEL-19.19 | Technical blog | — | — | **Not met** |
| DEL-19.20 | AI_USAGE.md | `AI_USAGE.md` | Ch 42 | **Partial** (see CI-19) |
| DEL-19.21 | Team contribution record | — | Ch 42 | **Not met** |

## A.13 Testing, Security and Documentation

**Table A.21 — Required test types (TST)**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| TST-01 | Functional tests | `tests/e2e/test_full_chain.py` (3), integration tests | Ch 33; App H | Tested: `test_full_chain.py::test_complete_complaint_chain` |
| TST-02 | Complaint-submission tests | `tests/backend/api/test_boundaries.py` | Ch 33 | Tested: `::test_title_length_edges`, `::test_description_length_edges`, `::test_order_reference_format` |
| TST-03 | Document-upload tests | Upload journeys and upload validation | Ch 33 | Tested: `test_full_chain.py::test_document_upload_and_policy_versioning_journey`; `test_boundaries.py::test_upload_size_edge`; `test_security_api.py::test_executable_upload_rejected` |
| TST-04 | Parsing tests | `tests/backend/unit/test_documents_exports.py` | Ch 33 | Tested: `::test_parse_sections_from_real_documents`, `::test_corrupted_document_is_rejected_cleanly` |
| TST-05 | GenAI API tests | `tests/backend/unit/test_genai_providers.py` (31) | Ch 33 | Tested: `::test_openai_request_uses_strict_json_schema`, `::test_anthropic_request_uses_structured_output_and_parses_the_reply` |
| TST-06 | JSON tests | Schema and parsing tests | Ch 33 | Tested: `test_genai_providers.py::test_structured_output_schema_uses_only_supported_keywords`, `::test_invalid_json_is_retried_with_the_validation_errors_then_accepted` |
| TST-07 | Classification tests | Perception tests | Ch 33 | Tested: `test_perception_security.py::test_classification_categories`, `::test_risk_precedence_beats_higher_scoring_issue` |
| TST-08 | Routing tests | Routing assertions and fault profile | Ch 33 | Tested: `test_difficult_cases.py::test_normal_delayed_delivery`; `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[wrong_department-RTE-001]` |
| TST-09 | Urgency tests | Urgency and priority tests | Ch 33 | Tested: `test_rule_engine.py::test_priority_matrix`, `::test_emotional_language_does_not_raise_priority` |
| TST-10 | Escalation tests | Escalation tests | Ch 33 | Tested: `test_rule_engine.py::test_safety_signal_forces_critical_escalation`; `test_difficult_cases.py::test_validated_steps_follow_one_escalation_path` |
| TST-11 | Resolution tests | Eligibility and action tests | Ch 33 | Tested: `test_difficult_cases.py::test_unsupported_refund_request`; `test_boundaries.py::test_refund_window_edge` |
| TST-12 | Policy tests | Policy and versioning tests | Ch 33 | Tested: `test_difficult_cases.py::test_contradictory_policy_resolved_by_precedence`; `test_documents_exports.py::test_facts_and_version_diff` |
| TST-13 | Hallucination tests | Grounding tests and fault profiles | Ch 33 | Tested: `test_perception_security.py::test_claim_grounding_accepts_paraphrase_but_not_invented_facts`; `test_difficult_cases.py::test_product_name_is_not_a_hazard` |
| TST-14 | Prompt-injection tests | Injection corpora | Ch 33, 34 | Tested: `test_perception_security.py::test_injection_attacks_detected` (9), `::test_benign_text_not_flagged` (5); `test_difficult_cases.py::test_prompt_injection_is_blocked` |
| TST-15 | Duplicate tests | Duplicate and hash tests | Ch 33 | Tested: `test_difficult_cases.py::test_exact_duplicate_rejected_and_near_duplicate_linked`; `test_perception_security.py::test_normalisation_and_duplicate_hash` |
| TST-16 | Missing-information tests | Clarification tests | Ch 33 | Tested: `test_difficult_cases.py::test_missing_information_triggers_clarification`; `test_full_chain.py::test_customer_clarification_loop` |
| TST-17 | Multi-issue tests | Multi-issue test | Ch 33 | Tested: `test_difficult_cases.py::test_multi_issue_multi_department` |
| TST-18 | Hidden-data readiness tests | Live-change and evaluation tests | Ch 33, 42 | Tested: `test_defects_and_live_changes.py::test_new_category_without_code_changes`, `::test_hidden_dataset_upload_with_minimal_columns`, `::test_evaluation_run_on_unseen_holdout` |
| TST-19 | Boundary tests | `tests/backend/api/test_boundaries.py` (29) | Ch 33 | Tested |
| TST-20 | Security tests | `tests/backend/api/test_security_api.py` (30), security unit tests | Ch 34; App G | Tested: `test_security_api.py`; `test_perception_security.py::test_pii_redaction`, `::test_password_hashing_and_tokens` |

**Table A.22 — Security (SEC) and documentation (DOC) requirements**

| Requirement ID | Requirement | Implementation module | Report section | Verification / test |
|---|---|---|---|---|
| SEC-01 | Privacy and confidentiality | `security/pii.py` (redaction before every GenAI call and in AI-run logs); customer-safe serialisation (`api/serializers.py`) | Ch 24 | Tested: `test_perception_security.py::test_pii_redaction`; `test_full_chain.py::test_complete_complaint_chain` (no validation data in the customer view) |
| SEC-02 | Security and access control | `security/rbac.py`, `security/auth.py`, `api/deps.py` | Ch 24 | Tested: `test_security_api.py::test_role_permission_matrix_enforced_server_side` |
| SEC-03 | Secure storage | bcrypt hashes; validated uploads in git-ignored `storage/`; append-only audit table | Ch 24, 25 | Tested: `test_security_api.py::test_audit_log_is_append_only_in_the_database` |
| SEC-04 | API costs | gpt-4.1-mini default; bounded retries; token counts per call in `ai_runs` | Ch 8, 35 | Recorded: token counts in the demo database |
| SEC-05 | Customer-data protection | SEC-002 check; prohibited REQUEST_SENSITIVE_CREDENTIALS and DISCLOSE_OTHER_CUSTOMER_DATA; formula-safe exports | Ch 24 | Tested: `test_documents_exports.py::test_csv_neutralises_formula_injection`; lab LAB-PII-01, LAB-PII-02 |
| SEC-06 | API keys never committed | `.gitignore` excludes `.env` and `.env.*`; key in `.env.secrets` | Ch 24, 41 | Configured; `test_genai_providers.py::test_secrets_file_overrides_the_settings_file` |
| SEC-07 | Secrets never uploaded or exposed | Server-only key; Render dashboard (`sync: false`) | Ch 24, 40 | Tested: `test_security_api.py::test_ai_key_never_exposed` |
| DOC-01 | All significant aspects documented clearly and completely | This report (45 chapters, Appendices A to N), `README.md`, `docs/dataset.md` | Ch 1-45 | This report |

## A.14 Summary of Open Items

Every functional requirement of the SRS is implemented or configured. Table A.23 collects the items that are not met, only partly met or not yet verified, so that they can be closed before the final submission.

**Table A.23 — Open items**

| Requirement ID | Gap | Evidence |
|---|---|---|
| NFR-1 | Median latency above the 20-second target | p50 21.7 s, p95 33.9 s, 32.4% within 20 s; validated decision alone p50 16.2 s |
| NFR-2 | Scalability not load-tested | Demo database: 800 complaints, 46 taxonomy entries, 24 documents |
| NFR-4 | Enforcement depends on Python's fact detection | Holdout: escalation required 94.7%, department 84.9% |
| NFR-5 | Availability not measured | No deployment |
| CI-09 | No detector for promised free replacements in response text | `config/actions.yaml` has no replacement-promise pattern |
| CI-14.8, CI-14.9 | New check types and new dashboard filters need code changes | `python_validation/engine.py`; `frontend/src/pages/` |
| CI-16, DEL-14.02 | Commits not spread over five days | Two commits on 2026-09-25 |
| CI-19, DEL-18, DEL-19.20 | AI_USAGE.md incomplete | Verifying-team table empty; stale test counts |
| DEL-08.02, DEL-19.12 | Per-case comparison export empty | `reporting/builders.py::_comparison_row` reads `comparison["rows"]`, but evaluation results store one entry per field |
| DEL-10.06 (note) | Quarantine false positive on an active policy section | ESC-SOP-12 v3.1 §3.1 flagged by the "no additional approval is needed" pattern |
| DEL-12.01 | README states the Python version but not how to install Python | README section 1 |
| DEL-14.01, DEL-19.02 | Public visibility of the repository not verified | Remote configured |
| DEL-14.03, DEL-19.21 | No team contribution record | `AI_USAGE.md` team table empty |
| DEL-14.13, DEL-17, DEL-19.19 | Technical blog missing | README "Links" |
| DEL-14.14, DEL-16, DEL-19.18 | Demonstration video missing | README "Links" |
| DEL-15.01, DEL-19.17 | No public deployment URL | `render.yaml` prepared only |
| FR-58 | Seven of eight reviewer actions untested | Only "approve" is tested |
| FR-55, FR-56 | SLA tracking and risk detection untested | Recorded in the demo database only |
| FR-26, FR-30, FR-33, FR-38, FR-40, FR-41, FR-61 to FR-66, FL-51 | Verified by recorded runs, screenshots or reports, not by automated tests | See Table A.7 |
| IF-HW-4 | Development workstation disk below the listed 500 GB | 238 GB disk |
