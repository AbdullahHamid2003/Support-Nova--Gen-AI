# Chapter 7 — Complaint Processing Pipeline

This chapter follows one complaint through SupportNova from the moment it is submitted to the moment it receives its final status. Every stage is described as it is implemented in the repository, with the module that performs it, whether it is deterministic Python or a Generative AI call, and what it produces. The orchestration lives in a single function, `process_complaint` in `backend/src/supportnova/services/pipeline.py`; the modules it calls are listed in Table 7.2. The design principle is visible in the control flow itself: **GenAI proposes. Python validates. Ground truth decides.** Only two steps call the model; everything else is deterministic code that runs against the Complaint Resolution Rule Matrix (`rules/*.yaml`, stored in the database, Chapter 10), the Knowledge Base and the simulated order ledger of Lumora Home Technologies.

## 7.1 Overview of the Processing Lifecycle

A complaint passes through two phases. The **intake phase** runs synchronously inside the HTTP request: the API validates the input, rejects unusable or duplicate submissions, stores the complaint with status `New` and returns `202 Accepted`. The **processing phase** runs asynchronously on a bounded thread pool (`services/worker.py`, `BACKGROUND_WORKERS=2`), so the customer never waits on the model. The processing phase advances the column `complaints.processing_stage` through the nine stage codes defined in the constant `STAGES` of `services/pipeline.py`, commits after every stage change and records the duration of each stage in `analyses.stage_timings`. Table 7.1 lists the stages with the label the React frontend shows for each (`frontend/src/lib/format.ts`) and the mean duration measured over the 780 analyses stored in the demo database.

**Table 7.1 — Processing stages and measured mean durations**

| Stage code | UI label | Work performed | Mean duration |
|---|---|---|---|
| `queued` | Queued | Waiting for a worker thread | not timed |
| `preprocessing` | Screening | Normalisation, injection screening, perception, order facts, history, duplicates | 22 ms |
| `retrieval` | Policy search | Hybrid, rule-guided Knowledge Base retrieval | 4 ms |
| `ai_analysis` | AI analysis | GenAI call 1 (`complaint_analysis`), schema validation, controlled retries | 16,919 ms |
| `validation` | Rule check | Pipeline 2 Phase A: Rule Matrix decision and analysis checks | 2 ms |
| `response_generation` | Response drafting | GenAI call 2 (`customer_communication`) from the validated decision | 5,829 ms |
| `response_validation` | Response check | Pipeline 2 Phase B checks and the verification score | 2 ms |
| `finalizing` | Routing & SLA | Persistence, escalation, follow-up, SLA, review queue, status, audit | included in total |
| `completed` | Completed | Terminal state (`failed` is the terminal state after an unhandled error) | — |

The mean end-to-end processing time of the 780 analyses is 22,816 ms, of which the two GenAI stages account for 22,748 ms; the timed deterministic stages together take about 30 ms. The pipeline is started by nine triggers, recorded on every analysis in `analyses.trigger`: `submission` (web form or API), `dataset` (demo import), `evaluation` (evaluation runs), `lab` (Adversarial Lab), `reprocess` (manual re-run), `reopened`, `clarification` (the customer answered a question), `review` (a reviewer reclassified or asked for regeneration) and `recovery` (restart after a crash, `Worker.requeue_stuck`).

Figure 7.1 shows the path from submission to the structured GenAI analysis, and Figure 7.2 the path from the validation of that analysis to the final status. GenAI steps are drawn in indigo, deterministic Python steps in green, data stores in blue.

![Figure 7.1 — Complaint pipeline from intake to GenAI analysis](diagrams/pipelines/fig-07-01-intake-to-analysis.svg)
*Figure 7.1 — Complaint pipeline from intake to GenAI analysis*

![Figure 7.2 — Complaint pipeline from validation to final status](diagrams/pipelines/fig-07-02-validation-to-final-status.svg)
*Figure 7.2 — Complaint pipeline from validation to final status*

## 7.2 Stage Map: Deterministic Python and GenAI Steps

The SRS lists the complaint-intelligence tasks as separate steps (Steps 9–47). In SupportNova most of these tasks are not separate model calls. The GenAI Complaint Intelligence Pipeline (Pipeline 1) makes exactly two calls per complaint: one structured analysis that returns issue, classification, entities, sentiment, urgency, priority, routing, policy citations, resolution steps, eligibility, escalation, follow-up, missing information, clarification questions and agent guidance as one JSON object, and one structured customer communication written from the already validated decision. Every other stage is deterministic Python. For each field the model proposes, the Python Ground-Truth Validation Pipeline (Pipeline 2) computes its own value from the Rule Matrix and never asks a model to approve the proposal. The values stored on the complaint record (`complaints.category_code`, `subcategory_code`, `department_code`, `urgency`, `priority`, `escalation_level`) are taken from the rules decision, not from the model; the only model value stored on the complaint is the sentiment, which is informational. Table 7.2 maps every stage to its code and output.

**Table 7.2 — Stage map of the complaint processing pipeline**

| Stage | Module / file | Deterministic or GenAI | Output |
|---|---|---|---|
| Submission | `api/v1/complaints.py` `submit_complaint`; `services/complaints.py` `create_complaint` | Deterministic | `complaints` row (status New, stage queued), 202 with `complaint_ref` |
| Input validation | `ComplaintIn` (Pydantic), `validate_submission`, `security/files.py` | Deterministic | 422 field errors or 409 `duplicate_complaint` |
| Preprocessing | `services/pipeline.py` preprocessing block | Deterministic | `complaints.preprocessing` JSON |
| Normalisation | `security/sanitization.py` `normalize_text`, `text_hash` | Deterministic | Normalised text, SHA-256 text hash |
| Sanitisation and screening | `security/injection.py`, `security/pii.py` | Deterministic | Injection report, flagged spans, redacted model text |
| Metadata extraction | `complaint_processing/fact_builder.py`, `perception.py`, `order_facts.py` | Deterministic | Signals, entities, facts |
| Complaint history retrieval | `services/history.py` `analyse_history` | Deterministic | 90-day history, prior same-issue counts |
| Duplicate / repeat detection | `services/history.py`, `services/pipeline.py` | Deterministic | Duplicate link and closure, or repeat flag |
| Issue identification | GenAI `primary_issue`, `secondary_issues`; Python `classify` | GenAI proposes; Python classifier is the reference | Primary and secondary issues |
| Category and subcategory | GenAI `issue_category`, `subcategory`; `run_phase_a` | GenAI proposes; rules decide | `category_code`, `subcategory_code` |
| Entity extraction | `perception.extract_entities`; GenAI `entities` | Both; AI entities grounded by Python | Entities (HAL-002, CLS-005) |
| Sentiment | `perception.lexicon_sentiment`; GenAI `sentiment` | Both; informational only | Sentiment and emotion indicators |
| Urgency | `rule_engine/decision.py` rule and urgency floors | Rules decide; GenAI proposes | Urgency (PRI-001, PRI-003) |
| Priority | `RuleMatrix.compute_priority` (priority matrix) | Rules decide; GenAI proposes | Priority (PRI-002, PRI-004) |
| Department routing | `decision.py` routing and conditional routing | Rules decide; GenAI proposes | Primary and supporting departments |
| Policy retrieval | `knowledge_base/retriever.py` `retrieve` | Deterministic | Evidence E1–E10, outdated versions, conflicts |
| Policy applicability | `python_validation/engine.py` `assess_applicability` | Deterministic | Applicable, Conditionally Applicable, Not Applicable, Outdated |
| Resolution recommendation | GenAI `resolution_steps`; `build_validated_decision` | GenAI proposes; rules filter and complete | Validated steps, excluded AI steps |
| Eligibility validation | `order_facts.py`, `decision.py`, checks ELG-001 to ELG-003 | Deterministic | Refund, replacement, compensation status |
| Escalation analysis | `decision.py` escalation rules; GenAI escalation fields | Rules decide; GenAI writes notes | `escalations` row, level, notes |
| Customer response | GenAI `customer_communication` 1.0.0 | GenAI | `customer_responses` row |
| Follow-up | `decision.py` FUP rules; GenAI `follow_up_message` | Rules schedule; GenAI words the message | `follow_ups` row with due time |
| Agent guidance | GenAI `agent_guidance`; rule-derived guidance | Both | AI and validated guidance lists |
| Structured JSON | `genai_pipeline/parsing.py`, `runner.py` | Deterministic checks on GenAI output | Validated JSON objects, `ai_runs` rows |
| Independent Python validation | `python_validation/engine.py` `run_phase_a`, `run_phase_b` | Deterministic | 52 checks, validated decision |
| Comparison | `engine.py` `build_comparison` | Deterministic | 18-field AI vs rules table |
| Final status | `engine.py` `finalize`; `services/pipeline.py`; `services/sla.py` | Deterministic | Score, Verified or Manual Review, status, SLA |

## 7.3 Intake

### 7.3.1 Complaint Submission

Complaints are submitted through the **Submit complaint** page of the React application (Figure 7.3) or directly to `POST /api/v1/complaints`, which requires the `complaint:create` permission (customer, agent and administrator roles). The form collects the fields named in SRS Step 9: title, description, product or service, order reference, transaction reference, previous complaint reference, supporting information, preferred contact channel, requested resolution and reply tone, with up to five attachments. The customer form has no customer-type field; the type is taken from the customer profile, and the live precheck applies the same rule (`tests/backend/api/test_boundaries.py::test_customer_precheck_uses_the_profile_customer_type`). Agents and administrators can submit on a customer's behalf by giving a `customer_ref`, which must exist. The endpoint accepts JSON or `multipart/form-data`; a body that is not valid JSON, or is a JSON list instead of an object, is answered with 422 rather than an unhandled error (`test_malformed_body_is_a_field_error_not_a_crash`).

![Figure 7.3 — Customer complaint submission form](../screenshots/04-customer-submit-complaint.png)
*Figure 7.3 — Customer complaint submission form*

Besides interactive submission, the same `create_complaint` function is used by the demo dataset import, by evaluation runs and by the Adversarial Lab. These bulk sources call it with `lenient=True`: only a missing or unusable title or description blocks the record; unsupported option values fall back to documented defaults (`LENIENT_DEFAULTS`), and malformed references are kept so that the pipeline flags them later (review trigger REV-014) instead of silently dropping the case. Every created complaint receives the next sequential reference (`CMP-00001` onwards), a history event `complaint.submitted` and an entry `complaint.created` in the hash-chained audit log.

### 7.3.2 Input Validation

Input is validated in three layers. The frontend applies the same limits with a zod schema (`frontend/src/pages/SubmitComplaint.tsx`) so that most errors are shown before submission. On the server, the Pydantic model `ComplaintIn` enforces types and hard length caps (title 200, description 10,000, product text 200, supporting information 6,000 characters); any violation is converted into a `ValidationFailed` error, which the API renders as HTTP 422 with the body `{"error": {"code": "validation_error", "message": ..., "details": [{"field": ..., "message": ...}]}}`. The business rules in `services/complaints.py::validate_submission` then apply the tighter length limits and check the option values and reference formats configured in `config/organization.yaml`. Table 7.3 lists the rules and the boundary tests that probe both sides of each edge.

**Table 7.3 — Complaint input validation rules and boundary tests**

| Field or rule | Accepted | Rejected | Evidence |
|---|---|---|---|
| Title | 5 to 180 characters | empty, 4 characters, 181 characters; above 200 is a Pydantic 422 | `test_title_length_edges`, `test_title_over_the_hard_cap_is_a_field_error_not_a_crash` |
| Description | at least 20 characters and 4 words, at most 8,000 | empty, whitespace only, 18 characters, one 30-letter word, 8,001 characters; above 10,000 is a Pydantic 422 | `test_description_length_edges`, `test_description_over_the_hard_cap_is_a_field_error_not_a_crash` |
| Customer type and channel | required; configured codes only | missing or unknown code | `validate_submission` |
| Preferred contact, requested resolution, tone | configured codes only | unknown code | `validate_submission` |
| Order reference | `^LMR-\d{6}$` (e.g. LMR-123456) | LMR-12345, ORDER-1 | `test_order_reference_format` |
| Transaction reference | `^TXN-\d{8}$` | other formats | `validate_submission` |
| Previous complaint | `^CMP-\d{5,}$`, must exist and belong to the customer | unknown or foreign reference | `validate_submission` |
| Attachments | at most 5; PDF, PNG, JPEG or TXT checked by magic bytes and extension; at most `MAX_ATTACHMENT_MB` (5 MB) | executables, type mismatches, empty or oversized files | `test_upload_validation_rejects_executables_and_mismatches`, `test_upload_size_edge` |
| Exact duplicate | new text for this customer | same canonical text from the same customer within `DUPLICATE_WINDOW_HOURS` (24 h): 409 `duplicate_complaint` | `test_exact_duplicate_rejected_and_near_duplicate_linked` |

The endpoint `POST /api/v1/complaints/validate` runs the same validation and the duplicate lookup without creating anything; the submission form calls it while the user types. The 24-hour duplicate rule is controlled by `REJECT_EXACT_DUPLICATES=true` and compares the SHA-256 `text_hash` described in Section 7.4.1. The 29 tests of `tests/backend/api/test_boundaries.py` pass in the recorded test run (206 of 206 backend tests).

### 7.3.3 Storage and Hand-off to the Background Worker

A valid submission is stored unchanged: the original title, description and supporting information are kept exactly as typed, and the normalised copy is stored separately in `description_normalized`. At creation the service also stores the canonical `text_hash` and a 512-dimension local similarity vector (`knowledge_base/embeddings.py::similarity_vectors`, a deterministic feature-hashing embedder over stemmed words, word pairs and character trigrams) that later drives near-duplicate and repeat detection. Attachments are written under `storage/attachments/<complaint_ref>/` with a sanitised file name and their SHA-256 in `complaint_attachments`. The request commits, hands the complaint identifier to `worker.submit` together with `PipelineOptions(trigger="submission")`, and returns `{"complaint_ref", "status": "New", "processing_stage": "queued"}` with status 202. The worker ignores a second submission of a complaint that is already in flight. On restart, `requeue_stuck` re-queues every non-evaluation complaint left in `New` or `Processing` with an unfinished stage, so a crash never strands a case. The complaint page polls `GET /api/v1/complaints/{ref}/pipeline` and shows the seven intermediate stages; customers see only stage progress, never validation internals.

## 7.4 Preprocessing

The preprocessing stage starts by setting the status to `Processing` and loading the live Rule Matrix (`rule_service.matrix`). The reference date for every time-dependent rule is the complaint date, not the processing date, so a dataset complaint dated months ago is judged by the windows and policy versions that applied on that day.

### 7.4.1 Normalisation

`security/sanitization.py::normalize_text` produces the text that is analysed (SRS Step 11): Unicode NFKC normalisation, conversion of Windows and old Mac line endings, removal of zero-width and bidirectional control characters and of other control characters, HTML entity unescaping, removal of `script` and `style` blocks and of any other markup tag, mapping of typographic quotes, dashes and ellipses to ASCII, collapse of runs of spaces and tabs, trimming of every line and reduction of three or more blank lines to one. The original text is never modified; rendering in the browser is escaped by React. For exact-duplicate detection, `canonical_for_hash` goes further (lower case, every non-alphanumeric run replaced by a single space) and `text_hash` stores the SHA-256 of that canonical form, so "Order LATE!!  Please help" and "order late please help" produce the same hash (`tests/backend/unit/test_perception_security.py::test_normalisation_and_duplicate_hash`).

### 7.4.2 Sanitisation and Manipulation Screening

Complaint text is untrusted data (SRS Step 50). `security/injection.py::scan` screens the normalised text with 28 regular-expression patterns in 13 families: instruction override, role hijack, fake system message, tag injection, output manipulation, code injection, security bypass, concealment, data exfiltration, directive to the system, fake authority, policy-override claim and prompt exfiltration. It also decodes base64 runs of 40 or more characters (including payloads split by spaces) and rescans the decoded text, reports three or more invisible characters found in the original text, and re-scans the original text for instructions hidden inside markup that normalisation removed. A second function, `unknown_policy_findings`, marks fake policy statements: a cited document ID that is not in the Knowledge Base, a version the document never had, or a section that does not exist (`test_fake_policy_ids_versions_sections`). Each finding carries a severity; the risk score is 1 − Π(1 − w) with weights 0.6 (high), 0.3 (medium) and 0.1 (low), and the complaint is flagged when any finding is high or the risk reaches 0.5. The flag is stored in `complaints.injection_detected`; the full report is stored in `complaints.preprocessing.injection`.

Screening never decides the outcome of a complaint. It has four consumers: the flagged spans are wrapped as `[[FLAGGED-CUSTOMER-TEXT type=...]]…[[/FLAGGED-CUSTOMER-TEXT]]` inside the text sent to the model (`injection.annotate`, `test_injection_annotation_marks_untrusted_span`); the review trigger REV-010 forces manual review; check SEC-001 later verifies that the model's answer did not obey the instruction; and the validated summary drops any AI sentence that repeats a flagged instruction (`test_validated_summary_never_relays_flagged_instructions`). Chapter 23 describes the prompt-injection protection in full. Before any text leaves the server, `security/pii.py::redact` replaces Luhn-valid payment card numbers (keeping the last four digits), CVV codes, one-time codes, passwords, e-mail addresses and phone numbers with placeholders (`test_pii_redaction`). The unit tests show nine attack styles detected, from "Ignore all previous instructions" to a base64-encoded instruction, and five benign sentences such as "Please flag this as urgent, my heating is not working" left unflagged (`test_injection_attacks_detected`, `test_benign_text_not_flagged`). In the demo database 42 complaints were flagged, 31 of them from the dataset.

### 7.4.3 Metadata Extraction and Perception

`complaint_processing/fact_builder.py::build_perception` builds Pipeline 2's own view of the complaint from the normalised title, description and supporting information. It is fully deterministic and independent of the GenAI output, and it is configured entirely by the Rule Matrix:

- **Signals.** `detect_signals` looks for the 35 risk and intent signals of `rules/complaint_rules/signals.yaml` (for example `fire_event`, `overheating`, `lock_security`, `privacy_breach`, `legal_threat`, `repeat_indicator`, `compensation_request`, `embedded_policy_claim`), using term lists and regular expressions. A term preceded within three tokens by one of 18 negation cues ("not", "never", "without", "didn't" …) is ignored (`test_negation_suppresses_signal`).
- **Entities.** `extract_entities` recognises order references (`LMR-` plus six digits, also "order number 123456"), transaction references (`TXN-` plus eight digits), complaint references (`CMP-` plus five or more digits), currency amounts, dates in ISO, day-month, month-day and numeric formats, durations (converted to elapsed days or outage hours), and products by name or alias from the product catalogue (longest alias first, so "smart lock" is not swallowed by "lock"). An amount followed or preceded by words such as "compensation", "credit" or "voucher" is recorded as the requested compensation amount (`test_entities_extracted`).
- **Classification.** `classify` scores every active subcategory with the weighted terms of `rules/complaint_rules/category_rules.yaml`: title matches count 1.3 times, negative terms subtract, and signals and products add configured boosts. The best candidate needs a score of at least 3.0. Risk-first precedence from `rules/routing_rules/routing_rules.yaml` (order SAF, ACC-UNA, PRV, LEGAL, BIL, PRD, DEL, WAR, policy RTE-RUL-14 section 5) then lets a candidate from a higher-precedence group that scores at least 4.0 outrank a higher-scoring candidate from a lower group, so a calmly mentioned safety risk wins over a louder delivery complaint (`test_risk_precedence_beats_higher_scoring_issue`). Up to three secondary issues from other categories are kept when they score at least 4.0 and either 35% of the primary score or 5.0. The result carries a confidence (high at a score of 8 or more without ambiguity, medium at 5 or more, otherwise low, or none below the minimum) and an ambiguity flag when the runner-up from another category is within 15% of the winner.
- **Sentiment.** `lexicon_sentiment` scores negative and positive terms, repeated exclamation marks and capitalised words into Positive, Neutral, Negative or Strongly Negative. This value is informational only and never enters urgency or priority (`test_sentiment_is_informational`, rule URG-100).

The complaint-level facts built here (word count, presence of order and transaction references, product SKU and product line, photo evidence from an image attachment or the `photo_evidence` signal, dates, largest amount, requested compensation, elapsed days, outage hours) become the `complaint.*` namespace of the fact model against which Rule Matrix conditions are evaluated.

### 7.4.4 Order-Ledger Facts

When the complaint names an order, the pipeline looks it up in the simulated order ledger (`orders` table); if no order reference was typed but perception found one in the text, the lookup is repeated with that reference and perception is rebuilt. `complaint_processing/order_facts.py::derive_order_facts` turns the order record into the `order.*` and `eligibility.*` fact namespaces: whether the order exists and belongs to the customer, delivery status, business days late against the estimated date, days since delivery and order, hazardous products, verified duplicate charges (two charges of the same amount within three days), overcharges, return, refund and cancellation state, subscription renewal, and the eligibility windows (dead-on-arrival, defect refund, refund window of 30 days or 45 days for Care+ members, warranty, replacement limit, delivery-delay credit, billing-dispute window, cooling-off period, refund lateness). Unknown values are left as `None`, so that rule conditions evaluate to *unknown* under the Rule Matrix's three-valued logic and the decision becomes "requires verification" instead of a guess (`tests/backend/unit/test_rule_engine.py::test_three_valued_conditions`). This is what makes refund, replacement and compensation eligibility a Python decision rather than model opinion (SRS Steps 29–31).

### 7.4.5 Complaint History Retrieval

`services/history.py::analyse_history` loads up to 50 earlier complaints of the same customer whose complaint date lies within `repeat_window_days` (90 days, ESC-SOP-12 section 4.5) before the current one. The scope is isolated by source: operational complaints only see operational history (web, API and dataset), Adversarial Lab cases also see earlier lab cases, and an evaluation case sees operational history plus earlier cases of its own run, never other runs. For each earlier complaint the function records reference, date, subcategory, status, order and cosine similarity of the stored vectors. The history list is later written into the `<verified_facts>` block of the analysis prompt (at most six entries), so the model sees the customer's recent complaints without seeing any other customer.

### 7.4.6 Duplicate and Repeat Detection

Three relationships are distinguished (SRS Steps 52–54), as Table 7.4 shows.

**Table 7.4 — Duplicate and repeat detection outcomes**

| Relationship | Test | Outcome |
|---|---|---|
| Exact duplicate at intake | same `text_hash`, same customer, within 24 hours | 409 `duplicate_complaint`; no complaint is created |
| Exact duplicate in processing | same `text_hash` within the 90-day history | linked to the original (`duplicate_of_id`), status Closed, no AI call |
| Near duplicate | similarity of at least `NEAR_DUPLICATE_THRESHOLD` (0.86) | linked and closed as above (CHP-POL-01 section 7.1) |
| Repeat | same previous-complaint reference, same order, same subcategory, or same category with similarity of at least 0.30 | `is_repeat`, `repeat_of_id`; counts feed escalation rules ESC-017, ESC-018, ESC-019 |

For a repeat, the function counts the prior same-issue complaints and how many of them are still unresolved, and detects whether the complaint reopens a complaint resolved within `reopen_window_days` (14 days). These three facts (`history.prior_same_issue_count`, `history.unresolved_prior_same_issue`, `history.references_resolved_complaint`) are merged into the fact model, where escalation rules ESC-017 (two unresolved priors, Supervisor Review), ESC-018 (three or more, Department Manager) and ESC-019 (reopened complaint, Supervisor Review) use them. Duplicate linking applies to the triggers submission, dataset, evaluation and lab; re-processing, reopening and clarification skip it so that a case is never closed as a duplicate of itself. A linked duplicate receives history events on both complaints, an audit entry `complaint.duplicate_linked`, and no analysis. In the demo database 20 complaints were linked as duplicates (18 dataset, 2 evaluation) and 33 were flagged as repeats; the integration tests `test_exact_duplicate_rejected_and_near_duplicate_linked` and `test_repeated_complaint_detected` cover all three relationships. Chapter 20 describes duplicate and repeat detection in detail.

## 7.5 Policy Retrieval

The retrieval stage (SRS Step 25) builds a snapshot of the Knowledge Base as of the complaint date and calls `knowledge_base/retriever.py::retrieve` with the title, normalised description and product text as the query. Only chunks that are Active, already effective, not expired and not quarantined are eligible, so outdated, draft and quarantined content can never become evidence. Three rankings are fused by reciprocal-rank fusion (k = 60): BM25 lexical search (top 30), vector search with the local embedder (top 30 above similarity 0.05), and **rule-guided retrieval**, weighted 1.4, which adds the policy sections that the Rule Matrix cites for the deterministic classifier's three best candidate subcategories. Ties are broken by document-type precedence (`rules/precedence/precedence_rules.yaml`), at most four chunks may come from one document, and the ten best (`RETRIEVAL_TOP_K=10`) become evidence items E1 to E10, each carrying document ID, title, version, type, status, section, heading, page and text. Every one of the 780 stored analyses has exactly ten evidence items.

Retrieval also returns two kinds of context that are never evidence: the outdated versions of each retrieved section (labelled "not used as the primary basis for decisions", CHP-POL-01 section 10.4) and the precedence-resolved policy conflicts that touch the evidence (140 of the 780 analyses carried at least one). The rule-guided step is how the classifier influences what the model reads: the model receives the policy text that the rules rely on, but never the classification itself. Chapter 5 describes how the documents are parsed and chunked, and Chapter 9 describes retrieval, precedence and policy grounding in detail.

## 7.6 GenAI Analysis and Structured JSON

The ai_analysis stage creates an `analyses` row (version number, trigger, provider `openai`, model `gpt-4.1-mini`, ruleset hash) and performs GenAI call 1. The active prompt `complaint_analysis` 1.2.0 is rendered with the reference data, the evidence, the policy conflicts, the verified facts and the complaint, which is annotated, redacted and wrapped in an element whose tag carries a random eight-character nonce. The request asks for strict JSON-schema structured output whose code fields are restricted to the live catalogue, and the reply is validated with `jsonschema` and Pydantic, with at most three attempts. Chapter 8 describes this call in full; Chapter 21 describes the prompt.

This single call is where the SRS tasks "identify the primary issue", "identify complaint category and subcategory", "extract important entities", "detect sentiment", "determine urgency and priority", "recommend the responsible department", "identify relevant policies", "generate resolution steps", "determine whether escalation may be required", "generate escalation notes", "generate clarification questions" and "generate agent guidance" are performed. They are fields of one `complaint_analysis.v1` object (37 required fields), not separate prompts. If no valid answer is obtained after the permitted attempts, the pipeline does not stop: the analysis is marked `invalid_output`, check SCH-001 fails, review trigger REV-009 sends the case to manual review, and the Rule Matrix decision described next is still computed and enforced (`tests/backend/integration/test_ai_not_configured.py::test_no_api_key_means_no_ai_output_and_manual_review`).

## 7.7 Independent Python Validation (Phase A)

The validation stage runs `python_validation/engine.py::run_phase_a` (the Python Ground-Truth Validation Pipeline is described as a whole in Chapter 11). It never calls a model. It derives the expected outcome from perception, facts, the Rule Matrix and the Knowledge Base snapshot, compares the AI proposal field by field, and produces the validated decision that the second GenAI call must follow.

### 7.7.1 Issue Identification, Category and Subcategory

Phase A first selects the **reference classification** that the rules decision is computed for. When the deterministic classifier is confident (high or medium confidence, not ambiguous), its primary subcategory is the reference (`python_rules`). When it is not, a valid AI subcategory is used provisionally (`ai_unconfirmed`), but only if the complaint contains some evidence for it (the AI subcategory or its category is among the classifier's scored candidates); an AI category with no supporting term or signal at all is treated as a likely hallucination and the classifier's best match is used instead (`python_low_confidence`, `test_unsupported_genai_category_is_never_the_provisional_reference`). A reviewer's reclassification overrides both (`reviewer_override`). Any reference source other than confident rules, or an ambiguous classification, fires review trigger REV-005, so a provisional classification is always confirmed by a person. Checks CLS-001 (category), CLS-002 (subcategory) and CLS-003 (secondary issues) then compare the AI's primary and secondary issues with the reference, and SCH-002 verifies that the AI codes exist and that the subcategory belongs to the category.

### 7.7.2 Urgency, Priority and Department Routing

`rule_engine/decision.py::DecisionEngine.decide` evaluates the Rule Matrix for the reference subcategory. The active resolution rules of the subcategory are tried in descending precedence; the first whose condition is true is selected, and rules whose condition is unknown are kept as pending. The selected rule gives the base urgency and impact; the 15 urgency floors then raise them when a condition holds (for example URG-001 to URG-004 set Critical urgency for fire, overheating, electrical hazard and injury signals), whatever the tone of the message. Priority is looked up in the configurable priority matrix (for example Critical urgency and High impact give P0; High and Medium give P2). The primary department comes from the routing rule of the subcategory (RTE-001 to RTE-035, possibly overridden by the selected rule); supporting departments are added from the routing rule, the resolution rule, the primary departments of secondary issues, the six conditional routing rules (RTE-101 to RTE-106, for example a privacy signal adds Compliance & Privacy) and the departments of every fired escalation rule. Checks PRI-001 to PRI-004 and RTE-001 to RTE-002 compare the AI values. An AI urgency below the rules level fails PRI-001, with critical severity when the rules require High or Critical; an AI urgency above the rules level without any risk signal is reported by PRI-003 as urgency inflated by emotional language (`test_calm_critical_safety_complaint`, `test_angry_low_priority_complaint`, `test_emotional_language_does_not_raise_priority`). Routing validation is detailed in Chapter 13 and urgency and priority validation in Chapter 14.

### 7.7.3 Entities and Sentiment

Entity extraction runs on both sides. HAL-002 checks that every entity the AI extracted appears in the complaint or the verified facts; an ungrounded order ID, transaction ID, amount, date or complaint reference fails the check, other types produce a warning. CLS-005 checks the opposite direction: every order, transaction and complaint reference found by Python must appear among the AI entities. Sentiment is compared by CLS-004 with severity `info`, which carries zero weight in the verification score, because sentiment describes tone and never drives urgency.

### 7.7.4 Policy Applicability

`assess_applicability` labels every evidence item (SRS Step 26): **Applicable** when the selected rule or a fired escalation rule cites the section, **Conditionally Applicable** when another rule of the same issue cites it (it applies only if certain facts or secondary issues hold), **Not Applicable** when it was retrieved for context only, and **Outdated** for the older versions returned by retrieval. The AI's own citations are checked by SCH-004 (the policy and section exist), POL-001 (at least one policy is cited), POL-002 (no outdated version is cited), POL-003 (every citation is in the case evidence), POL-004 (the sections the rules require are cited), POL-005 (the AI's applicability agrees) and POL-006 (in a policy conflict, the higher-ranking source was followed). Every applicability label, every AI citation and every rule-required reference is stored in `policy_references` with the source that produced it (`retrieval`, `ai` or `rule`).

### 7.7.5 Resolution Recommendation and Eligibility Validation

The selected rule defines required actions (some as "any of" groups), recommended actions and prohibited actions from the 66-action catalogue and the 12 prohibited behaviours. RES-001 fails when a required action is missing (with critical severity if the missing action is a safety, security or escalation action), RES-002 when the AI proposes a prohibited action or its step descriptions contain prohibited wording, RES-003 reports recommended actions not considered, and RES-004 detects contradictions such as `PROCESS_REFUND` while the refund is not eligible or an `ESCALATE_*` step without an escalation. Eligibility for refund, replacement and compensation is read from the selected rule; wherever a pending rule would give a different result, the value becomes `requires_verification`. ELG-001 to ELG-003 compare the AI statuses: an AI "eligible" where the rules say "not_eligible" is a critical failure, and a compensation amount above the rule amount or maximum fails ELG-003 with critical severity (`test_unsupported_refund_request`, `test_unsupported_compensation_request`; Chapter 15).

The **validated resolution steps** are then assembled. AI steps are kept when they are known actions, not prohibited, not an escalation action for a level the rules did not set, and either required or recommended by the rule or purely investigative (verification and information groups); every other AI step is moved to `excluded_ai_steps` with the reason ("commitments must come from the rules"). Every required action the AI missed is appended with source `rule` (`test_validated_steps_follow_one_escalation_path`). Both lists are stored in the `resolutions` table next to the AI's original steps.

### 7.7.6 Escalation Analysis

The 39 escalation rules of the Rule Matrix are evaluated against the same facts and signals (SRS Steps 36–39); a rule an administrator has deactivated is skipped. The escalation level is the highest rank among the fired rules and any escalation inherent in the selected resolution rule; the level's action (for example `ESCALATE_CRITICAL_MANAGEMENT`) is added to the required actions, and the departments of the fired rules become supporting departments. ESC-001 fails critically when the rules require an escalation the AI missed, ESC-002 when the AI level is lower than required, ESC-003 warns about an escalation no rule supports, and ESC-004 requires all six parts of the escalation notes (summary, key facts, reason, actions taken, relevant policy, required next action, ESC-SOP-12 section 5). The AI's notes are kept when an escalation is required, with sentences that repeat flagged instructions removed; if the AI provided none, the rules build notes from the fired rules. A missed escalation is therefore never lost: the escalation is created from the rules whether or not the model identified it (Chapter 18; `test_safety_signal_forces_critical_escalation`, `tests/backend/integration/test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[missed_escalation-ESC-001]`).

### 7.7.7 Follow-up and Missing Information

The eight missing-information rules (MIS-001 to MIS-008) detect absent or unverifiable data such as a missing order number, transaction reference or date, product, evidence or problem description, an order reference that is not in the ledger and an order that belongs to another customer. Missing information never blocks Safety, Privacy or unauthorized-account-access (ACC-UNA) cases (`never_block_categories`, `never_block_subcategories`), which are handled and escalated regardless. The follow-up is chosen by the global follow-up rules: blocking missing information gives "Request for additional information" due in 24 hours (FUP-001); an escalation gives "Escalation acknowledgement" due at the priority's first-response target (FUP-002, one hour for P0); otherwise the selected rule's follow-up applies. FUP-001 and FUP-002 compare the AI's follow-up flag and type, MIS-001 checks that the AI identified the blocking gaps and MIS-002 that its clarification questions cover them. Rule-required questions the AI did not ask are appended to the validated questions, so the customer is asked for missing facts rather than having them invented (`test_missing_information_triggers_clarification`). Follow-up scheduling and SLA tracking are described in Chapter 19.

### 7.7.8 Grounding, Security and Agent Guidance

Four grounding checks look for hallucination (SRS Step 35, Chapter 17): HAL-001 traces each of the AI's claims to the complaint, a cited evidence item, the verified facts or the rules decision, HAL-002 grounds entities, HAL-003 rejects identifiers and amounts in the summary that are not in the case, and HAL-004 rejects policy IDs named in free text that do not exist. For a flagged complaint, SEC-001 fails when the answer appears to follow the embedded instruction (refund or compensation marked eligible against the rules, a required escalation dropped, urgency lowered, or the answer repeating the injected text). SEC-003 records the screening result. Agent guidance is kept in two lists: the AI's recommendations as proposed, and validated guidance generated from the rules (the selected rule and its condition, the mandatory escalation with its rule IDs, up to four "Do not" statements from the prohibited actions, each missing-information item, and a warning when eligibility depends on unverified facts).

### 7.7.9 The Validated Decision

Phase A ends with `build_validated_decision`, the "Final intelligence" shown on the complaint page. Table 7.5 shows where each part comes from; it is the concrete form of the principle that the rules decide and the model contributes content that survived validation.

**Table 7.5 — Source of each part of the validated decision**

| Part | Source |
|---|---|
| Category and subcategory | Reference classification: rules, or AI unconfirmed pending review, or reviewer |
| Department and supporting departments | Rule Matrix routing, conditional routing and escalation departments |
| Urgency, impact, priority, SLA targets | Selected rule, urgency floors, priority matrix, SLA rules |
| Escalation required, level, fired rules | Escalation rules and the selected rule |
| Escalation notes | AI notes (flagged sentences removed) or rule-built notes |
| Eligibility | Selected and pending resolution rules with order-ledger facts |
| Resolution steps | AI steps allowed by the rule plus missing required steps from the rule |
| Timelines the response may quote | Rule timeline parameters and SLA targets, each with its policy source |
| Clarification questions | AI questions plus questions required by missing-information rules |
| Summary and key facts | AI text with sentences repeating flagged instructions removed |
| Agent guidance | AI recommendation and rule-validated guidance, side by side |

## 7.8 Customer Response Generation and Validation (Phase B)

GenAI call 2 (SRS Steps 32–34, Chapter 16) uses the active prompt `customer_communication` 1.0.0. Its input is the validated decision, not the AI analysis: the issue and category names, the department name, priority, escalation state and level, the eligibility statuses, up to five customer-facing next steps (plain-language phrases for the validated actions, for example "we are signing out all active sessions"), the names of the prohibited actions, the safety flag and the summary; further, the timelines the response may quote, the clarification questions, the follow-up type and due time, only those evidence items that the AI cited or that were Applicable, and the complaint under a fresh nonce. The requested tone (professional, empathetic, concise or formal) and the customer's first name are passed as well. The reply is a `customer_communication.v1` object with subject, response, follow-up message and claims.

`run_phase_b` then checks the text against the validated decision, never against what the model believes: RSP-001 requires acknowledgement and a next step (missing empathy or issue summary is a warning), RSP-002 detects refund, compensation and policy-exception promises and "guarantee" language that the validated eligibility does not allow, RSP-003 accepts only durations and deadlines that match an allowed timeline, RSP-004 accepts only amounts and references found in the case, RSP-005 checks the tone rules (for example at most 120 words for concise, no contractions and a formal salutation for formal), RSP-006 detects prohibited statements such as requests for passwords or card numbers, admissions of liability or asking for a damaged battery to be posted, RSP-007 applies the same checks to the follow-up message, and SEC-002 rejects card numbers, CVV codes, one-time codes, passwords and phone numbers in the text. A failed RSP or SEC check keeps the response in status `requires_review`; only a Verified case with a clean response is stored as `ready` and may be sent. If the second call fails, RSP-001 fails with "No usable customer response could be drafted" and no response is stored.

## 7.9 Comparison, Verification Score and Final Status

### 7.9.1 Comparison Engine

`build_comparison` produces the field-by-field comparison that the complaint page shows in the "AI vs rules" tab: 18 rows for category, subcategory, department, supporting departments, sentiment, urgency, impact, priority, reference entities, policy references, resolution actions, the three eligibility statuses, escalation required, escalation level, follow-up required and follow-up type. Each row holds the AI value, the Python value, the result (match, partial for overlapping sets, or mismatch) and an explanation such as the routing rule or the priority-matrix source. The classification rows always show the Python classifier's own result, also when it was not confident enough to be the reference. The share of matching rows is stored as the agreement, and the complaint flag `ai_python_agreement` is set when category, department and escalation-required all agree. Chapter 12 describes the Comparison Engine, its reports and the evaluation on unseen cases.

### 7.9.2 Verification Score and Decision

`finalize` computes the verification score from all Phase A and Phase B checks using the policy in `rules/validation_policy.yaml`: each check that is not "not applicable" contributes its severity weight (critical 5, major 3, minor 1, info 0) multiplied by its status value (pass 1.0, warn 0.5, fail 0.0), and the score is 100 × Σ(weight × value) / Σ weight, reported overall and per dimension. The 14 review triggers (REV-001 to REV-014) are then evaluated, from AI and rules disagreeing on the category to an order that does not belong to the customer. The decision is **Verified** only when no critical check failed, the score is at least 80 and no review trigger fired; otherwise it is **Manual Review**. Sensitive categories (Safety and Privacy) and sensitive signals such as legal threats, staff harassment, injury and smart-lock security always require a person (REV-008).

### 7.9.3 Persistence

The finalizing stage writes the complete, traceable result in one transaction, as Table 7.6 lists.

**Table 7.6 — Records written by the finalizing stage**

| Table | Content |
|---|---|
| `analyses` | Status, AI output, communication, prompt key, version and SHA-256 for both stages, policy versions used, retrieval result, stage timings, total latency |
| `policy_references` | Applicability labels, AI citations and rule-required references with validity |
| `validation_results` | Score, decision, dimension scores, rules decision, comparison, validated decision, review reasons, ruleset hash |
| `validation_checks` | One row per check with expected and actual values, rule and policy references |
| `resolutions` | AI steps, validated steps, AI and validated eligibility |
| `customer_responses` | Subject, body, tone, status `ready` or `requires_review`, Phase B results |
| `escalations` | Level, rank, reason, fired rule IDs, departments, notes; source `rule` or `rule+ai` |
| `follow_ups` | Type, message, due time, source rule, status `scheduled` |
| `sla_records` | First-response and resolution due times from the SLA rule of the priority |
| `reviews` | Pending review with reason codes and the original snapshot (Manual Review only) |
| `audit_logs` | `complaint.processed` with provider, model, prompt and policy versions, ruleset hash, attempts, score, timings |

An escalation row is created only if no open escalation of the same or higher rank exists, so re-processing does not duplicate it. Evaluation runs never fill the review queue; their results are stored in the evaluation tables instead.

### 7.9.4 Final Status, Assignment and SLA

The complaint record receives the rules decision (category, subcategory, department, urgency, priority, escalation), the verification score and status, and `needs_review`. `ensure_sla` creates or updates the SLA record from the priority's SLA rule (P0: first response 1 hour, resolution 24 hours; P1: 4 and 48; P2: 24 and 120; P3: 48 and 240) and evaluates its state; the SLA monitor thread later marks a complaint At Risk when 75% of a window has elapsed (`sla_at_risk_pct`). The status becomes **Escalated** when the rules require an escalation and **Analyzed** otherwise; a reopened complaint that needs no escalation moves to **In Progress**. If no agent is assigned yet, the complaint is auto-assigned to the active agent of the routed department with the fewest open complaints, and an Analyzed complaint then becomes **Assigned**. The final history event records the rule check result, for example "Rule check: Manual Review, score 94/100 (1 failed, 4 warnings)".

### 7.9.5 After the Pipeline

The later lifecycle is driven by people. An agent may send a response only when its status is `ready` or, after reviewer approval, `approved`; sending records simulated delivery through the preferred contact channel (there is no e-mail or SMS gateway), sets the SLA first-response time, and moves the complaint to **Awaiting Customer** when blocking information is missing or to **In Progress** otherwise. When the customer answers through `POST /api/v1/complaints/{ref}/clarify`, the text is appended to the supporting information and the complaint is processed again with the trigger `clarification` (`tests/e2e/test_full_chain.py::test_customer_clarification_loop`). Resolving a complaint schedules a closure-confirmation follow-up (FUP-003, 48 hours). The audit trail that keeps the original recommendation next to every later decision is described in Chapter 37.

### 7.9.6 Failure Handling and Recovery

`process_complaint` wraps the whole pipeline. If any unexpected exception occurs, the complaint is marked with stage `failed`, `needs_review` and verification status Manual Review, its status returns from Processing to New, a history event and an audit entry `complaint.processing_failed` record the error type, and (outside evaluation runs) a pending review with the reason `pipeline_error` is created. No complaint is left in Processing. GenAI failures are not exceptions at this level: they are handled inside the GenAI stage by the controlled retry policy (Chapter 8) and then by SCH-001 and REV-009 as described in Section 7.6. Chapter 36 covers error handling across the application.

## 7.10 Worked Example: CMP-00616

Complaint CMP-00616 from the demo dataset (fictional data) is a calmly written security incident: a customer found the front door unlocked, and the Lumora Keystone Smart Lock log showed a remote unlock at 4:40 am. Preprocessing found one signal, `lock_security`, no manipulation (risk 0.0) and a low-confidence classification (ACC-UNA scored 4.0 from the signal alone, SVC-SUP 1.0). Retrieval returned ten evidence items, among them SEC-POL-09 sections 5, 5.1 and 5.2 and ESC-SOP-12 section 4.2. The GenAI analysis (prompt 1.2.0, one attempt, 20,024 ms, 9,690 input and 1,919 output tokens) proposed ACC-UNA, Account Security, Critical urgency, P0, Critical Management Escalation and seven resolution steps.

Because the classifier's confidence was low, the AI subcategory became the provisional reference (`ai_unconfirmed`), supported by the `lock_security` signal. The rules selected RES-ACC-UNA-03 ("Smart-lock security incident", condition `signal:lock_security`), fired escalation rules ESC-009 and ESC-010, and confirmed Critical urgency, P0, Account Security with Management Escalations as the supporting department, and Critical Management Escalation. The AI had omitted two required actions, so RES-001 failed with critical severity and the rules added `ADVISE_PHYSICAL_KEY` and `REVOKE_SESSIONS`; three AI steps that the rule does not provide (`ADVISE_STOP_USING`, `LOCK_ACCOUNT`, `SCHEDULE_FOLLOW_UP`) were excluded. The follow-up became "Escalation acknowledgement" due in one hour (FUP-002) instead of the AI's "Resolution confirmation", a FUP-002 warning. The response, written from the validated decision, told the customer to use the physical key and that all active sessions had been signed out, both steps the rules had added. The score was 94.0 with 39 passes, 4 warnings and 1 failure, and the decision Manual Review because of REV-002 (a critical check failed), REV-005 (rule confidence low) and REV-008 (sensitive case with the `lock_security` signal). The complaint became Escalated and was auto-assigned to an Account Security agent. Figure 7.4 shows the final intelligence and Figure 7.5 the comparison; Appendix D reproduces the stored JSON.

![Figure 7.4 — Final intelligence for CMP-00616](../screenshots/08-complaint-detail-final-intelligence.png)
*Figure 7.4 — Final intelligence for CMP-00616*

![Figure 7.5 — AI vs rules comparison for CMP-00616](../screenshots/09-complaint-ai-vs-rules.png)
*Figure 7.5 — AI vs rules comparison for CMP-00616*

## 7.11 Measured Pipeline Performance

The demo database holds 780 completed analyses, all produced by OpenAI gpt-4.1-mini with prompts `complaint_analysis` 1.2.0 and `customer_communication` 1.0.0. Table 7.7 summarises the measured timing.

**Table 7.7 — Measured processing time**

| Measure | Value | Source |
|---|---|---|
| Full pipeline, dataset complaints (599 analysed) | p50 21.7 s, p95 33.9 s | `analyses.total_latency_ms` |
| Share of dataset complaints within 20 s | 32.4% | `analyses.total_latency_ms` |
| Full pipeline, holdout evaluation run 1 (154 cases) | p50 21.2 s, p95 33.8 s | `reports/genai_python_comparison/summary.md` |
| Mean GenAI analysis call (valid attempts) | 16.5 s | `ai_runs.latency_ms` |
| Mean GenAI response call (valid attempts) | 5.6 s | `ai_runs.latency_ms` |
| All deterministic stages together | about 30 ms | `analyses.stage_timings` |

The SRS performance requirement (analysis, validation and an initial recommendation within 20 seconds) is therefore **partially met**. The validated recommendation exists after about 17 seconds on average, when Phase A completes, but it is stored together with the drafted response, so only 32.4% of complaints finish the whole pipeline within 20 seconds. Almost all of the time is spent waiting for the two model calls; the Python stages are negligible. Chapter 35 analyses the performance in detail, and Chapter 43 records this as a limitation.

## 7.12 Implementation Status of the Processing Requirements

**Table 7.8 — Status of the SRS complaint-processing steps**

| SRS step | Requirement | Status | Evidence |
|---|---|---|---|
| 9 | Complaint submission | Implemented, Tested | `test_complete_complaint_chain` |
| 10 | Complaint validation | Implemented, Tested | `tests/backend/api/test_boundaries.py` (29 tests) |
| 11 | Pre-processing | Implemented, Tested | `test_normalisation_and_duplicate_hash`, `test_pii_redaction` |
| 12–13 | Primary and secondary issues | Implemented, Tested | `test_multi_issue_multi_department` |
| 14–15 | Category and subcategory, configurable | Implemented, Configured, Tested | `test_classification_categories`, `test_new_category_without_code_changes` |
| 16 | Entity extraction | Implemented, Tested | `test_entities_extracted` |
| 17–18 | Sentiment and emotion, not driving priority | Implemented, Tested | `test_sentiment_is_informational` |
| 19–21 | Urgency, priority, tricky cases | Implemented, Configured, Tested | `test_calm_critical_safety_complaint`, `test_angry_low_priority_complaint` |
| 22–24 | Routing, routing validation, multi-department | Implemented, Configured, Tested | `test_multi_issue_multi_department` |
| 25–26 | Policy retrieval and applicability | Implemented, Tested | `test_contradictory_policy_resolved_by_precedence` |
| 27–31 | Resolution, refund, replacement, compensation | Implemented, Configured, Tested | `test_unsupported_refund_request`, `test_unsupported_compensation_request` |
| 32–35 | Response, tone, promises, hallucination | Implemented, Tested | `test_fault_profile_on_custom_complaint` (6 profiles) |
| 36–39 | Escalation detection, level, notes, validation | Implemented, Configured, Tested | `test_escalation_for_legal_threat`, `test_safety_signal_forces_critical_escalation` |
| 40–43 | Follow-up, scheduling, missing information, clarification | Implemented, Tested | `test_missing_information_triggers_clarification`, `test_customer_clarification_loop` |
| 44–45 | Summary and agent guidance | Implemented, Tested | `test_complete_complaint_chain` |
| 46–47 | JSON schema validation, invalid output handling | Implemented, Tested | `tests/backend/unit/test_genai_providers.py` (Chapter 8) |
| 52–54 | Duplicates, history, repeats | Implemented, Tested | `test_exact_duplicate_rejected_and_near_duplicate_linked`, `test_repeated_complaint_detected` |
| NFR 1 | Recommendation within 20 seconds | Partially met | Table 7.7 |
