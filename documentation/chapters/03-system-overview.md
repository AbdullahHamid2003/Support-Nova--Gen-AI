# Chapter 3 — System Overview

This chapter follows one complaint and one policy document through SupportNova, step by step, and names the module that performs each step. SupportNova serves Lumora Home Technologies, a fictional smart-home electronics company. All of its customers, orders, policies and complaints are simulated. Chapter 4 describes the same system as components and layers. Chapter 40 describes how the system is deployed.

## 3.1 Inputs, users and the two workflows

SupportNova has two workflows, and both end at the Python Ground-Truth Validation Pipeline.

- **The complaint workflow.** A customer or a support agent submits a complaint. The complaint is preprocessed, relevant policy evidence is retrieved, and the GenAI Complaint Intelligence Pipeline (Pipeline 1) proposes a structured analysis. The Python Ground-Truth Validation Pipeline (Pipeline 2) then checks that proposal against the Complaint Resolution Rule Matrix, and the Comparison Engine records the result field by field. The outcome is validated intelligence, a customer response, escalation and follow-up records and, when the checks require it, a manual review.
- **The knowledge-base workflow.** An administrator uploads an approved company document. It is validated, parsed into sections and chunks, versioned and indexed, and becomes evidence in the Knowledge Base.

A third input is used by both workflows: the Complaint Resolution Rule Matrix. It is a version-controlled YAML baseline in `rules/` and `config/`, and a live, editable copy is stored in the `rules` database table. The matrix holds 276 rule rows: 116 resolution, 39 escalation, 35 routing, 6 conditional-routing, 15 urgency-floor, 35 classification, 8 missing-information, 4 follow-up, 4 SLA and 14 review rules. It also holds 14 configuration rows, including 59 policy parameters and 35 risk signals. The GenAI model never writes or approves these rules.

Five roles use the workflows. Each role has a fixed permission set defined in `backend/src/supportnova/security/rbac.py`:

- Customer: 3 permissions
- Support Agent: 10
- Reviewer: 14
- Support Manager: 12
- Administrator: 24

Together these cover 27 distinct permissions, and every API route enforces them on the server. Customers submit and track their own complaints. Agents work the complaints of their department. Reviewers work the manual-review queue. Managers read analytics and reports. Administrators maintain the Knowledge Base, the Rule Matrix, the prompts and the users.

## 3.2 The complaint workflow

Figure 3.1 shows the first half of the complaint workflow, from submission to the Comparison Engine. Figure 3.2 shows the second half, from validated intelligence to the outcomes. The whole flow is implemented in one function, `process_complaint` in `backend/src/supportnova/services/pipeline.py`. It records its progress in the `processing_stage` column of the `complaints` table, and Table 3.1 lists those stages.

![Figure 3.1 — Complaint workflow, part 1: from submission to the Comparison Engine](diagrams/pipelines/fig-03-01-complaint-workflow-intake.svg)
*Figure 3.1 — Complaint workflow, part 1: from submission to the Comparison Engine*

**Table 3.1 — Processing stages of a complaint (`complaints.processing_stage`)**

| Stage | Work done | Performed by |
|---|---|---|
| `queued` | Complaint stored, job handed to the worker pool | Complaint API, `services/worker.py` |
| `preprocessing` | Normalisation, injection screen, PII redaction, signals, entities, history, duplicates | Deterministic Python |
| `retrieval` | Hybrid, rule-guided retrieval of Active policy sections | Deterministic Python (`knowledge_base/retriever.py`) |
| `ai_analysis` | Structured complaint analysis, controlled retries | Pipeline 1 (GenAI) |
| `validation` | Rule Matrix decision, Phase A checks, Comparison Engine | Pipeline 2 (Python) |
| `response_generation` | Customer response written from the validated decision | Pipeline 1 (GenAI) |
| `response_validation` | Phase B checks, verification score and decision | Pipeline 2 (Python) |
| `finalizing` | Records, escalation, follow-up, SLA, review, audit entry | Deterministic Python |
| `completed` | Final state; `failed` is set instead if processing raised an error | — |

### 3.2.1 Intake and submission checks

A customer or an agent fills in the **Submit complaint** page (`frontend/src/pages/SubmitComplaint.tsx`). The form collects the fields named in the SRS:

- title and description
- product or service
- order, transaction and previous-complaint references
- customer type and channel
- preferred contact method, requested resolution and requested tone
- supporting information and up to five attachments

The page can call `POST /api/v1/complaints/validate` for a field-level pre-check before the complaint is submitted. It then sends `POST /api/v1/complaints`.

The Complaint API validates the submission in `validate_submission` (`backend/src/supportnova/services/complaints.py`):

- The title must be 5 to 180 characters.
- The description must have at least 20 characters and four words, and at most 8,000 characters.
- Option values must come from the lists in `config/organization.yaml`.
- Reference numbers must match the configured formats, for example `LMR-123456` for orders and `CMP-00042` for complaints.
- A previous-complaint reference must exist and must belong to the same customer.
- Attachments must be PDF, PNG, JPEG or text files of at most 5 MB each (`MAX_ATTACHMENT_MB`). Their magic bytes are checked as well as their extensions.

A text identical to one the same customer submitted within the last 24 hours (`DUPLICATE_WINDOW_HOURS`) is refused with HTTP 409 and the reference of the original complaint.

An accepted complaint is stored twice: the original text is kept unchanged, and a normalised copy with a text hash and a similarity vector is stored alongside it. The API answers `202 Accepted` at once, and the in-process worker pool (`BACKGROUND_WORKERS`, default 2) runs the pipeline in the background. While the stages advance, the complaint page polls `GET /api/v1/complaints/{ref}` and shows the progress.

### 3.2.2 Preprocessing

Preprocessing is deterministic Python and never calls a model. It produces the facts that both pipelines later rely on.

1. **Normalisation.** `normalize_text` (`security/sanitization.py`) applies NFKC normalisation and removes zero-width, bidirectional and control characters. It also strips HTML and script markup, maps typographic punctuation and collapses whitespace.
2. **Manipulation screening.** `injection.scan` (`security/injection.py`) matches the complaint against pattern families: instruction overrides, fake system messages, role hijacking, output manipulation, fake authority, data exfiltration, code injection and others. It also decodes base64 payloads and counts invisible characters. `unknown_policy_findings` flags any policy ID, version or section cited by the customer that does not exist in the Knowledge Base, so a quoted "policy" that Lumora never published is recorded as a fake policy reference.
3. **Order and eligibility facts.** The order reference is looked up in the simulated order ledger (`orders` table). The perception layer (`complaint_processing/fact_builder.py`) then derives, from the Rule Matrix configuration:
   - the risk signals (35 defined in `rules/complaint_rules/signals.yaml`)
   - entities, rule-based category candidates and a lexicon sentiment
   - the eligibility facts that the resolution rules evaluate
4. **History, duplicates and repeats.** `analyse_history` (`services/history.py`) compares the complaint with the same customer's complaints from the last 90 days (parameter `repeat_window_days`):
   - An identical text hash marks an exact duplicate.
   - A similarity of at least 0.86 (`NEAR_DUPLICATE_THRESHOLD`) marks a near-duplicate.
   - Earlier complaints that share the previous reference, the order, the subcategory, or the category with a similarity of at least 0.30 (`REPEAT_SIMILARITY_THRESHOLD`) are counted as the same issue. The number of those that are still unresolved later drives escalation rules ESC-017 and ESC-018.

A duplicate or near-duplicate is linked to the original complaint and closed at this point, with the history note "no second case opened (CHP-POL-01 s7.1)". Such a complaint does not enter the GenAI stages.

### 3.2.3 Knowledge retrieval (RAG)

Retrieval (`knowledge_base/retriever.py`) searches only chunks that are Active, within their effective and expiry dates and not quarantined. It works in four steps:

1. BM25 lexical ranking is combined with vector ranking. By default the vectors come from a local feature-hashing embedder, so retrieval needs no external API.
2. The result is expanded with the policy sections that the Rule Matrix cites for the (at most three) strongest Python subcategory candidates. This rule-guided expansion means every policy that a rule relies on can be cited with a valid source reference.
3. The rankings are fused by reciprocal rank, ties are broken by document-type precedence, and at most four results are taken from any one document.
4. Outdated versions of the retrieved sections are returned separately, as context only. Conflicts between documents that were resolved by precedence are attached to the evidence.

At most `RETRIEVAL_TOP_K` (default 10) evidence items are returned. Each carries its document ID, version, status, section and page.

### 3.2.4 GenAI analysis and structured JSON (Pipeline 1)

The GenAI Complaint Intelligence Pipeline takes the active version of the `complaint_analysis` prompt from the `prompts` table. The recorded runs used version 1.2.0; versions 1.0.0 and 1.1.0 are retired. The prompt is built in two parts:

- **The system prompt** carries trusted reference data: the taxonomy, the department and action catalogues, the escalation levels, the priority matrix with SLA-RUL-15 section 5, the routing policy RTE-RUL-14 sections 3 to 5, and the follow-up types.
- **The user prompt** carries the retrieved evidence, the policy conflicts, the facts the system has verified (for example the order ledger entry), and the complaint itself. The complaint is PII-redacted, its flagged spans are marked as inert customer text, and it is wrapped in a `<complaint_NONCE>` element whose tag changes on every request.

The structured-output schema sent to the provider is narrowed per request by `constrain_codes` (`genai_pipeline/schemas.py`). Every category, department, action and policy field is limited to the codes that exist at that moment.

The provider is chosen by configuration. The default is OpenAI `gpt-4.1-mini`, which was used for all recorded runs; Anthropic and Google Gemini adapters are also available. The runner (`genai_pipeline/runner.py`) makes at most `1 + AI_MAX_RETRIES` attempts, three by default:

- If the answer is not valid JSON or breaks the schema, the validation errors are sent back to the model on the next attempt.
- Rate limits, timeouts and connection errors are retried with a bounded back-off.
- Authentication errors, refusals and a missing key are not retried.

Every attempt is stored in the `ai_runs` table with the provider, model, prompt version and SHA-256, raw response, token counts, latency and error type.

A usable answer must parse as JSON and pass two checks: the committed JSON Schema `schemas/ai/complaint_analysis.v1.schema.json` (37 required fields) and then the Pydantic model `ComplaintAnalysis`. The required fields cover:

- summary and key facts
- primary and secondary issues, category and subcategory
- sentiment, urgency, impact and priority
- entities, departments and policy references
- resolution steps and refund, replacement and compensation eligibility
- escalation, follow-up, missing information and clarification questions
- agent guidance, claims and manipulation flags

The result is a proposal. Nothing in it is final until Pipeline 2 has checked it.

### 3.2.5 Independent Python ground-truth validation (Pipeline 2)

Pipeline 2 (`python_validation/engine.py`) never calls a model. From `genai_pipeline` it imports only the two output data models, so that it can read the proposal; it has no import path to a provider. It first decides which subcategory it will treat as the reference:

- Python's own classification, when that classification is confident (source `python_rules`)
- the AI's subcategory, marked provisional, when Python is unsure and the complaint supports the AI's choice or at least does not contradict it (`ai_unconfirmed`)
- Python's best match, when neither is reliable (`python_low_confidence`)
- a reviewer's reclassification, when a reviewer has made one (`reviewer_override`)

The decision engine (`rule_engine/decision.py`) then applies the Rule Matrix to the verified facts and signals. It produces the expected outcome, and every value in that outcome carries the rule IDs that produced it:

- primary and supporting departments
- urgency, impact and priority
- escalation level
- refund, replacement and compensation eligibility
- required, recommended and prohibited actions
- follow-up, missing information, the timelines that may be quoted, and the policy references

Phase A runs 44 checks on the analysis, covering schema, classification, routing, priority, policy, resolution, eligibility, escalation, follow-up, grounding and security. Examples are SCH-004 (cited policies exist), RTE-001 (primary department), PRI-001 (urgency), ESC-001 (required escalation identified) and HAL-002 (extracted details appear in the complaint).

### 3.2.6 Comparison Engine

The Comparison Engine is the function `build_comparison` in `python_validation/engine.py`. It writes one row for each of 18 fields:

- category, subcategory, department and supporting departments
- sentiment, urgency, impact and priority
- entities, policy references and resolution actions
- refund, replacement and compensation eligibility
- escalation required and escalation level
- follow-up required and follow-up type

Each row holds the AI value, the Python value, a result of `match`, `partial` or `mismatch`, and the basis of the Python value, such as the routing rule, the urgency rule or the priority matrix. The share of matching rows is stored as the agreement ratio in `validation_results.comparison`. The complaint page shows this table in the **AI vs rules** tab; in the user interface, Pipeline 2 is called "the rules".

![Figure 3.2 — Complaint workflow, part 2: from validated intelligence to outcomes](diagrams/pipelines/fig-03-02-complaint-workflow-outcomes.svg)
*Figure 3.2 — Complaint workflow, part 2: from validated intelligence to outcomes*

### 3.2.7 Validated intelligence

`build_validated_decision` assembles the final intelligence, which the UI calls the Final decision. It takes two kinds of content:

- **Rule-enforced fields.** Classification, department, urgency, priority, escalation, eligibility, required and prohibited actions, follow-up, quotable timelines and policy references come from the Rule Matrix decision.
- **AI content that passed the checks.** The summary, the key facts, the clarification questions and the AI's agent guidance are kept, with these corrections:
  - Sentences that repeat instructions flagged in the complaint are removed.
  - An AI resolution step is excluded, with its reason recorded, when it is unknown, prohibited by the selected rule, or a commitment such as a refund or credit that the rule does not require or recommend.
  - A required action the AI left out is added with the source `rule`.
  - A clarification question is added for every blocking missing-information rule the AI did not cover.

If the complaint needs escalation and the model supplied no escalation notes, Python builds minimal notes from the fired rules and marks them with the source `rule`.

### 3.2.8 Customer response, verification score and decision

The customer response is a second GenAI call. It uses the `customer_communication` prompt, version 1.0.0, and it is written from the validated decision, not from the AI's own analysis. The prompt receives:

- the requested tone and the decision block
- the timelines the rules allow; if there are none, it is told "(no timelines may be quoted)"
- the clarification questions and the follow-up
- only the evidence that was cited or found applicable

Phase B then runs eight checks on the text. RSP-001 to RSP-007 cover the required parts, unsupported promises, timelines, amounts and references, tone, prohibited statements and the follow-up message; SEC-002 checks for sensitive data. Unsupported promises are always judged against the Python decision (`hallucination_checks/promises.py`).

`finalize` computes the verification score from the 52 check results alone, using the weights in `rules/validation_policy.yaml`. The score is 100 times the sum of weight times value, divided by the sum of weights, over all applicable checks. The weights are 5 for critical, 3 for major, 1 for minor and 0 for info; the values are 1.0 for pass, 0.5 for warn and 0.0 for fail.

A case is **Verified** only when three conditions all hold: no critical check failed, the score is at least 80, and none of the 14 review triggers (REV-001 to REV-014) fired. Otherwise the decision is **Manual Review**, and the triggered reasons are listed. The triggers include an AI and rules category mismatch, a critical failure, a missing policy basis, an ambiguous complaint, a policy contradiction, a sensitive case, prompt injection, an unsupported promise, hallucination and an unverified order reference.

Measured on the 617-complaint demo import (four complaints in parallel), the full pipeline took a median of 21.7 s and a 95th percentile of 33.9 s. The two model calls take most of that time: about 16.5 s for the analysis and 5.6 s for the response, while the Python validation takes milliseconds. Only 32.4% of complaints completed within the 20-second target of the SRS, and this gap is stated here rather than hidden.

### 3.2.9 Outcomes: resolution, response, escalation, follow-up and SLA

In the `finalizing` stage, the pipeline writes the following records in one transaction:

- **The analysis.** An `analyses` row stores the provider, model, prompt versions, policy versions and ruleset hash. A `validation_results` row stores the score, the Comparison Engine rows and the validated decision, and each check gets a `validation_checks` row. Separate `policy_references` rows record the policies cited by retrieval, by the AI and by the rules.
- **A resolution.** It holds the AI's steps and the validated steps, with the status `validated` when the case is Verified and `proposed` otherwise.
- **A customer response.** Its status is `ready` only when the case is Verified and no response or security check failed; otherwise it is `requires_review`.
- **An escalation, when an escalation rule fired.** The record carries the level, rank, fired rule IDs, departments and notes, and its source is `rule` or `rule+ai`. If the model missed the escalation, the timeline states "the AI missed it, the rules require it".
- **A follow-up, when the selected rule requires one.** Its type and due time come from the rule; for example, RES-PRD-DOA-01 requires a "Request for additional information" within 24 hours.
- **An SLA record.** Its response and resolution targets come from the SLA rule for the priority. A monitor thread flags the case as At Risk when 75% of the window has elapsed (parameter `sla_at_risk_pct`).

The complaint status becomes Escalated when a rule requires escalation, and Analyzed otherwise. If the responsible department has active agents, the complaint is assigned to the least-loaded one. An Analyzed complaint then becomes Assigned, while an escalated complaint keeps the status Escalated.

### 3.2.10 Manual review

A case with the decision Manual Review enters the review queue with its reasons, its priority and a snapshot of the original AI output and validated decision (`reviews` table). A reviewer can take eight actions (`services/reviews.py`):

- approve, reject, modify, reclassify, reassign, escalate, regenerate and comment

Rejecting, modifying, reclassifying and reassigning each require a comment. Reclassifying runs the pipeline again with the reviewer's subcategory as the reference. Regenerating runs it again with a new tone.

The original AI output and the original validation result are never changed. Every action stores before and after snapshots with the reviewer's identity in `review_actions`, and it is written to the audit log.

### 3.2.11 Audit, analytics and reports

Each processed complaint writes an audit entry, `complaint.processed`. It records:

- the provider and model
- the prompt and policy versions
- the ruleset hash
- the number of AI attempts
- the decision, score and review reasons
- the timing of each stage

The audit log is append-only and hash-chained, and a PostgreSQL trigger blocks UPDATE, DELETE and TRUNCATE on it. Analytics, trends, the reports and their CSV, Excel and PDF exports are computed from the database at request time (`services/analytics.py`, `reporting/`). Lab and evaluation complaints are excluded from the operational dashboards.

### 3.2.12 Failure paths

Three failure paths are handled explicitly:

- **No API key.** The GenAI step fails with `not_configured`. Check SCH-001 fails, no customer response is drafted, and the case goes to manual review. The Python decision, including any safety escalation, is still enforced. The test `tests/backend/integration/test_ai_not_configured.py::test_no_api_key_means_no_ai_output_and_manual_review` covers this path.
- **Invalid AI output after the last retry.** The analysis is stored with the status `invalid_output`, and the case goes to manual review with trigger REV-009 (no usable AI answer).
- **An exception inside the pipeline.** The complaint is marked `failed` and sent to manual review with the reason `pipeline_error`, and the error is audited. On restart, complaints left in the queued or processing states are requeued (`worker.requeue_stuck`).

## 3.3 The knowledge-base workflow

Figure 3.3 shows how an approved document becomes evidence. Every step is deterministic Python in `services/documents.py` and `document_processing/`; no GenAI step takes part in parsing, versioning or approving documents.

![Figure 3.3 — Knowledge-base workflow: from upload to the approved Knowledge Base](diagrams/pipelines/fig-03-03-knowledge-base-workflow.svg)
*Figure 3.3 — Knowledge-base workflow: from upload to the approved Knowledge Base*

An administrator opens **Knowledge base → Upload document** and chooses a file. PDF and DOCX are mandatory; Markdown, TXT and CSV are optional. The file is sent with its metadata. `POST /api/v1/documents/preview` shows the metadata detected in the file before anything is stored. `POST /api/v1/documents` then ingests the file in these steps:

1. **File validation** (`security/files.py`). The file must not be empty and must be at most 15 MB (`MAX_UPLOAD_MB`). It must not be an executable, judged by both extension and magic bytes. Its extension must be allowed, and its content must match that extension. A DOCX must be a valid Office archive without macros or embedded binaries, and must stay below the zip-bomb limits.
2. **Duplicate check.** A file whose SHA-256 is already stored is refused as a duplicate.
3. **Parsing** (`document_processing/parsers.py`). PyMuPDF reads PDF and python-docx reads DOCX. Section detection uses font size and weight in PDFs, heading styles in DOCX and `#` markers in Markdown. When none of these are present, numbered headings such as "5.2 Delay Compensation" are used, so previously unseen documents are handled too.
4. **Metadata validation** (`document_processing/validation.py`). This checks the document ID, version, type, status, and the effective and expiry dates. A version that already exists is refused. So is an Active upload that is older than an existing Active version.
5. **Section extraction.** Each section keeps its number, heading, level and page span, and is stored in `document_sections`.
6. **Chunking** (`document_processing/chunking.py`). Chunks follow section boundaries and carry the ID `<DOC_ID>@<version>#<section>-c<n>`. Each chunk keeps its document, section, heading, page reference and version. Each chunk also receives a vector, and numeric policy facts such as "refunds within 5 business days" are extracted from it for conflict detection (`document_processing/facts.py`).
7. **Instruction screen.** Every chunk passes through the same injection screen as complaints. A suspicious chunk is quarantined, with its reason recorded, and is never used as evidence.
8. **Version control.** Uploading a new Active version demotes the previous Active version to Previous, and an older Previous version to Superseded. Draft versions are never used as evidence. An impact analysis compares the old and new sections. It lists the changed sections, the resolution and escalation rules that cite them, the policy parameters whose source value changed (with a suggested new value), and the open complaints whose responses may need revision.
9. **Index refresh.** The knowledge revision counter is increased, so the in-memory retrieval index is rebuilt on the next request without a restart. The upload is audited as `document.uploaded`.

The repository's own Knowledge Base was loaded through this same pipeline on the first start. `bootstrap_knowledge_base` reads `knowledge_base/manifest.yaml`: 24 documents in 29 versions, stored as 13 PDF, 15 DOCX and 1 Markdown file. The demo database therefore holds 24 documents, 29 versions and 484 chunks.

## 3.4 The central principle

SupportNova is built on one rule: **GenAI proposes. Python validates. Ground truth decides.** Figure 3.4 shows how the rule splits the system into two pipelines, which meet in the Comparison Engine.

![Figure 3.4 — The central principle: two independent pipelines meet in the Comparison Engine](diagrams/pipelines/fig-03-04-central-principle.svg)
*Figure 3.4 — The central principle: two independent pipelines meet in the Comparison Engine*

The GenAI Intelligence Pipeline interprets language: it summarises, classifies, cites and writes. The Ground-Truth Validation Pipeline derives its own view of the same complaint from deterministic perception, the order ledger and the Rule Matrix. It then checks the proposal against that view.

The two pipelines are independent in both directions:

- **What the model sees.** It receives the Rule Matrix's controlled vocabularies (categories, departments, action codes, escalation levels, follow-up types) and the priority matrix, so that it can return valid codes. It never receives the decision rules themselves: the resolution, routing, escalation, urgency-floor, eligibility and missing-information rules, and the parameters.
- **What Python does not do.** Python never asks a model whether the proposal is correct.

Where the two disagree on a rule-governed field, the Rule Matrix value is used and the disagreement is recorded. Where the complaint is sensitive, ambiguous, manipulative or not supported by policy, a person decides. The recorded holdout evaluation shows the effect, with 154 unseen cases processed by `gpt-4.1-mini` (`reports/genai_python_comparison/summary.md`):

- Python caught 92 of the 93 cases in which the AI had a key-field error (98.9%).
- All 6 prompt injections were detected, with no false positives.
- 22 cases were Verified, 130 went to manual review and 2 were linked as duplicates.

## 3.5 Knowledge Base and Rule Matrix: evidence versus decision criteria

Both the Knowledge Base and the Rule Matrix come from Lumora's approved documents, but they are different things. **The Knowledge Base gives evidence; the Rule Matrix gives decision criteria.** Figure 3.5 shows how they relate, and Table 3.2 compares them.

![Figure 3.5 — Knowledge Base and Rule Matrix: evidence versus decision criteria](diagrams/data-flow/fig-03-05-knowledge-base-vs-rule-matrix.svg)
*Figure 3.5 — Knowledge Base and Rule Matrix: evidence versus decision criteria*

The Knowledge Base holds the documents themselves: sections and chunks that can be quoted and cited with a document ID, version and section. The Rule Matrix was authored from those documents as structured, machine-checkable logic. Each rule and parameter keeps a trace to its source section. For example, parameter `refund_window_days = 30` traces to REF-POL-02:3.1, and resolution rule RES-PRD-DOA-02 cites RPL-POL-03:3.1 and three further sections.

The two meet at three points:

- **Retrieval.** Retrieval pulls in the sections that the rules cite.
- **Validation.** Validation looks up every citation in the Knowledge Base; check SCH-004 tests that the cited policy exists and POL-002 that no outdated version is cited.
- **Revision impact.** When a revised policy is uploaded, the impact analysis marks the Rule Matrix parameters whose source value changed. An administrator then updates them in the Rule Matrix editor; the matrix is never rewritten by the upload itself.

**Table 3.2 — Knowledge Base and Complaint Resolution Rule Matrix compared**

| Aspect | Knowledge Base | Complaint Resolution Rule Matrix |
|---|---|---|
| Purpose | Source-grounded evidence and citations | Decision criteria (ground truth) |
| Content | 24 documents, 29 versions, 484 chunks | 276 rule rows, 14 configuration rows, 59 parameters |
| Source files | `knowledge_base/` (PDF, DOCX, Markdown) | `rules/*.yaml`, `config/*.yaml` |
| Storage | `documents`, `document_versions`, `document_sections`, `document_chunks` | `rules`, revision counter in `system_settings` |
| Used by GenAI | Yes, as the evidence block in the prompt | Only the vocabularies and priority matrix |
| Used by Python | Section, version and status lookup; conflict detection | Decision engine; the expected value of every check |
| Changed through | Upload, status change (Active, Previous, Superseded, Draft) | Rule Matrix editor, parameter edits, taxonomy manager |
| Change control | Versioned, impact analysis, audited | Integrity-checked before saving, versioned, audited |

## 3.6 How the workflow appears in the application

Staff follow a complaint on the complaint page (`frontend/src/pages/ComplaintDetail.tsx`). A pipeline tracker shows the stages; its labels are Complaint, AI analysis, Evidence, Rule check, Resolution, Response, Escalation and Audit trail. Table 3.3 maps the tabs of the page to the steps of this chapter.

**Table 3.3 — Complaint page tabs**

| Tab | Content | Workflow step |
|---|---|---|
| Overview | Final decision: classification, routing, urgency, eligibility, validated steps | 3.2.7 |
| AI vs rules | Score by area, review reasons, the 18-field comparison, all 52 checks | 3.2.5, 3.2.6, 3.2.8 |
| Evidence | Retrieved and cited policy sections, conflicts | 3.2.3 |
| Response | Drafted response, its Phase B checks, approve, edit and send | 3.2.8 |
| Escalation & SLA | Escalation records, follow-ups, SLA targets and state | 3.2.9 |
| Timeline & audit | Status history and audit entries | 3.2.11 |
| AI runs | Every model call with prompt version, latency, tokens and raw JSON | 3.2.4 |

Figures 3.6 and 3.7 show one fictional complaint from the demo dataset, CMP-00616 ("Front door found unlocked"). The customer calmly reports that the Lumora Keystone Smart Lock was opened remotely at night. The rules classification had low confidence, so the Overview marks the category Unauthorized Account Access as "Provisional (AI)".

The rules enforced the following:

- **Priority and escalation.** Rule RES-ACC-UNA-03 set Critical urgency, which the priority matrix turns into P0, and escalation rules ESC-009 and ESC-010 set Critical Management Escalation.
- **Added steps.** ADVISE_PHYSICAL_KEY and REVOKE_SESSIONS were added as steps "added by rules".
- **Rejected steps.** Three AI steps were rejected because rule RES-ACC-UNA-03 neither requires nor recommends them.

On the AI vs rules tab, the case scored 94 of 100: 39 checks passed, 4 gave warnings and 1 failed. It still went to manual review, for three reasons:

- the critical check RES-001 failed, because the AI had left out two required security actions
- the rules classification had low confidence
- it is a sensitive case (a lock-security signal), which a person must approve

![Figure 3.6 — Complaint page, Overview tab: the Final decision for CMP-00616](../screenshots/08-complaint-detail-final-intelligence.png)
*Figure 3.6 — Complaint page, Overview tab: the Final decision for CMP-00616*

![Figure 3.7 — Complaint page, AI vs rules tab: score by area, review reasons and the field-by-field comparison](../screenshots/09-complaint-ai-vs-rules.png)
*Figure 3.7 — Complaint page, AI vs rules tab: score by area, review reasons and the field-by-field comparison*
