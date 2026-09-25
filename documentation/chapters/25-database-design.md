# Chapter 25 — Database Design

## 25.1 Scope and technology

SupportNova keeps every piece of operational, AI and validation data in one PostgreSQL 17 database. The schema is declared as SQLAlchemy 2.0.54 models in `backend/src/supportnova/database/models/` and is created and evolved by Alembic 1.20.0 migrations in `backend/src/supportnova/database/migrations/versions/`. The models are split into five modules that follow the application's packages: `identity.py` (7 models), `complaints.py` (5), `intelligence.py` (9), `knowledge.py` (4) and `workflow.py` (10). Development uses the embedded cluster started by `scripts/devdb.py` on 127.0.0.1:5433; `docker-compose.yml` uses the `postgres:17-alpine` image. `database/base.py` also supports SQLite, but only for zero-dependency unit tests; the PostgreSQL-specific parts of the design (JSONB, the audit trigger and the trigram index) are skipped on that dialect.

The figures in this chapter were checked against the live catalog of the demo database with read-only queries on 2026-09-25. At that time the database held 35 application tables plus Alembic's `alembic_version` table, 427 columns, 48 foreign keys and 119 indexes, and occupied 69 MB. The column types were 157 `varchar`, 108 `integer`, 55 `timestamptz`, 52 `jsonb`, 28 `text`, 16 `boolean`, 6 `double precision`, 3 `date` and 2 `bytea`. Uploaded policy documents and complaint attachments are stored as files under the storage directory; the database keeps their path, size and SHA-256 digest, so every stored file can be checked against its record.

The schema is built around the project principle **GenAI proposes. Python validates. Ground truth decides.** The AI's answer (`analyses.output`, `ai_runs`), the deterministic rule decision (`validation_results.python_expected`, `validated_decision`) and every human decision (`reviews`, `review_actions`) are stored in separate rows, and none of them overwrites another. The `complaints` row carries only the final, validated values, copied there so that search, dashboards and analytics can filter on indexed columns. Appendix M lists every table with its columns and indexes; Appendix L lists the API routes that read and write them.

## 25.2 Domain model overview

The 35 tables fall into eight functional domains. Table 25.1 lists them with the number of rows each table held in the demo database, which gives a sense of how the data grows: on average one analysed complaint produced one `analyses` row, about two `ai_runs` rows, one `validation_results` row with 52 `validation_checks`, about seventeen `policy_references` and about eleven `complaint_history` events.

**Table 25.1 — Tables by domain, with rows in the demo database (2026-09-25)**

| Domain | Tables (rows) |
|---|---|
| Identity and access | roles (5), users (17), departments (10) |
| Complaints and customers | customers (301), orders (607), complaints (800), complaint_attachments (111), complaint_history (8,770) |
| Knowledge Base | documents (24), document_versions (29), document_sections (482), document_chunks (484) |
| Rule Matrix, taxonomy and prompts | rules (290), system_settings (2), categories (11), subcategories (35), products (15), prompts (2), prompt_versions (4) |
| AI analysis and validation | analyses (780), ai_runs (1,591), policy_references (13,515), validation_results (780), validation_checks (40,560), resolutions (780) |
| Case workflow and review | customer_responses (780), escalations (380), follow_ups (747), sla_records (780), reviews (451), review_actions (301) |
| Evaluation | evaluation_runs (2), evaluation_results (160), evaluation_cases (0) |
| Audit | audit_logs (2,138) |

Of the 800 complaints, 617 came from the dataset import, 160 from evaluation runs, 18 from the Adversarial Lab and 5 from the web form. All 780 analyses had status `completed` and were produced by OpenAI gpt-4.1-mini; the 20 complaints without an analysis are duplicates, which are linked to their original instead of being analysed again (Section 25.4.2). The case lifecycle after analysis is partly simulated in the demo data. To give the dashboards a realistic history, the seeder (`services/seed.py`, setting `SEED_SIMULATE_LIFECYCLE`) approved 300 reviews, recorded all 414 sent responses and resolved or closed the older dataset complaints together with their escalations and follow-ups. Every such change carries the actor label "Demo Data Seeder (simulated history)" and can therefore be told apart from real work; the analyses, AI calls and rule checks are real.

Figure 25.1 shows how the domains that carry a complaint through its life are connected, and Figure 25.2 shows the reference and quality data that the analysis draws on. Solid arrows are foreign keys drawn from the parent to the child table; dotted arrows are references by code, hash or ID string that deliberately have no foreign-key constraint (Section 25.3). The colours follow the convention of the whole report: indigo for GenAI output, green for the Rule Matrix and rule-check records, amber for human decisions and blue for operational data.

![Figure 25.1 — Database domains that carry a complaint: identity, complaints, AI analysis, rule check, workflow, review and audit](diagrams/database/fig-25-01-database-domain-map.svg)
*Figure 25.1 — Database domains that carry a complaint: identity, complaints, AI analysis, rule check, workflow, review and audit*

![Figure 25.2 — Reference and quality domains: taxonomy, prompts, Knowledge Base, Rule Matrix and evaluation](diagrams/database/fig-25-02-database-reference-domains.svg)
*Figure 25.2 — Reference and quality domains: taxonomy, prompts, Knowledge Base, Rule Matrix and evaluation*

## 25.3 Modelling conventions

**Keys.** Every table except `system_settings` has an integer surrogate primary key `id`; `system_settings` is keyed by its setting name. Business identifiers are separate unique columns: `complaints.complaint_ref` (CMP-00001 for customer complaints, LAB-00001 for lab runs, R1-EVL-00001 for evaluation cases), `customers.customer_ref`, `orders.order_ref`, `documents.doc_id`, `document_chunks.chunk_uid`, `products.sku`, `users.email`, `prompts.prompt_key` and the `code` columns of roles, departments, categories and subcategories. Composite unique constraints protect the version relationships: `uq_analyses_complaint_version` (complaint_id, version_no), `uq_document_versions_doc_version` (document_id, version), `uq_prompt_versions_prompt_version` (prompt_id, version) and `uq_rules_type_id` (rule_type, rule_id). Two one-to-one relationships are enforced by unique foreign keys: `sla_records.complaint_id` and `validation_results.analysis_id`.

**Names and types.** `database/base.py` sets a SQLAlchemy naming convention (`pk_%(table_name)s`, `fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`, `uq_…`, `ix_…`), so constraint names are deterministic and readable, for example `fk_reviews_validation_result_id_validation_results`. All timestamps are timezone-aware (`timestamptz`), and `TimestampMixin` gives most tables a `created_at` column with the server default `now()`. Python annotations `dict[str, Any]` and `list[Any]` are mapped to one JSON type that becomes JSONB on PostgreSQL (`JSONType = JSON().with_variant(JSONB(), "postgresql")`).

**Codes instead of foreign keys for Rule Matrix values.** The classification and routing values of a complaint (`category_code`, `subcategory_code`, `department_code`, `product_sku`), the subcategory of a rule (`rules.subcategory_code`) and the policy cited by an analysis (`policy_references.doc_id`, `version`, `section_id`, `chunk_uid`) are stored as codes, not as foreign keys. This is deliberate. The codes are the vocabulary of the Complaint Resolution Rule Matrix and of the AI's JSON schema (for example `SAF-OVH`, `DEPT-SAF`, `REF-POL-02:4.3`), so the Python Ground-Truth Validation Pipeline compares them directly. A historical record stays readable when a subcategory is deactivated, a policy version becomes Superseded or the Rule Matrix is reset to its YAML baseline, and a new subcategory added at run time (`POST /api/v1/taxonomy/subcategories`) needs no migration. The integrity of these codes is enforced in Python instead of by the database: checks SCH-002 (category and subcategory are valid), SCH-003 (departments are valid) and SCH-004 (cited policies exist) run on every analysis, and every Rule Matrix edit is rejected if the rule integrity validator (`rule_engine/integrity.py`) finds an unknown code.

**Nothing is overwritten.** Re-running the pipeline adds a new `analyses` row with the next `version_no`; editing a customer response adds a new `customer_responses` version; every reviewer action stores before and after snapshots; every accepted rule edit increments `rules.version`; and audit entries can only be appended. The only delete statement in the application code is the explicit Rule Matrix reset (`services/rules.py`, `seed_from_yaml(force=True)`), whose previous state remains in the audit trail.

## 25.4 Entities by domain

### 25.4.1 Identity and access

Figure 25.3 shows the identity tables together with the audit trail, whose only foreign key points at `users`. `roles` holds the five roles of the RBAC model described in Chapter 24 (customer, agent, reviewer, manager, admin) and their permission lists in the JSON column `permissions`. The authoritative definition is `security/rbac.py`; the seeder (`services/seed.py`) writes and re-synchronises these rows on start-up, so the table always matches the code, with 3, 10, 14, 12 and 24 permissions respectively. `departments` holds the ten Lumora Home Technologies departments (DEPT-BIL to DEPT-MGT), which serve both as the organisational unit of staff accounts and as routing targets of the Rule Matrix.

`users` stores the sign-in accounts: a unique `email`, a bcrypt `password_hash` (12 rounds), the `role_id`, an optional `department_id` (agents are auto-assigned within their department) and an optional `customer_id` that links a customer's login to the simulated customer profile. `failed_logins` and `locked_until` implement the lockout of the login endpoint: after five failed attempts the account is locked for five minutes (`api/v1/auth.py`). The demo database held 17 accounts: one customer, ten agents, four reviewers (one disabled), one manager and one administrator. Accounts are never deleted; they are deactivated through `is_active`, which the foreign-key rules in Section 25.5 also require.

![Figure 25.3 — Identity and audit tables](diagrams/database/fig-25-03-er-identity-audit.svg)
*Figure 25.3 — Identity and audit tables*

### 25.4.2 Complaints and customers

Figure 25.4 shows the complaint-centred tables. `customers` holds the 301 fictional customer profiles of the dataset with their `customer_type` (individual, care_plus, business, vip). `orders` is the simulated order ledger that the pipeline uses to verify order references and eligibility windows. Its `data` JSON column holds the full simulated order record: items, order, dispatch, estimated and actual delivery dates, shipping method and fee, tracking trace, payment transactions, cancellation, return and subscription details, the replacement count and Care+ claims in the last twelve months. There is no live commerce or payment integration, which the SRS places outside the mandatory scope.

`complaints` is the central table, with 50 columns in four groups. The submitted fields (`title`, `description`, `supporting_info`, `channel`, `product_text`, `order_ref`, `transaction_ref`, `previous_complaint_ref`, `preferred_contact`, `requested_resolution`, `requested_tone`, `complaint_date`) are stored exactly as received and are never modified. The preprocessing fields hold what Python derived before any AI call: `description_normalized`, the SHA-256 `text_hash` of the normalised title and description, a float32 similarity `embedding`, and the `preprocessing` JSON with the detected risk signals, entities, rule classification candidates, sentiment estimate, prompt-injection screening report, order lookup result and customer history. The lifecycle fields are `status` (New, Processing, Analyzed, Assigned, In Progress, Awaiting Customer, Escalated, Resolved, Closed, Reopened), `processing_stage` (queued to completed, or failed), `verification_status` (Pending, Verified, Manual Review, Human Verified), `verification_score`, `needs_review`, `assigned_agent_id` and the timestamps `analyzed_at`, `resolved_at` and `closed_at`. The final-decision fields (`category_code`, `subcategory_code`, `department_code`, `urgency`, `priority`, `sentiment`, `product_sku`, `escalation_level`, `escalation_required`, `sla_state`, `injection_detected`) are copies of the validated decision made for filtering; the authoritative record of the decision is `validation_results.validated_decision`. `ai_python_agreement` is true only when the AI and the rules agree on category, department and whether escalation is required.

Duplicate and repeat handling (Chapter 20) uses the same table. An exact duplicate from the same customer within `DUPLICATE_WINDOW_HOURS` (24) is rejected at submission with HTTP 409 and never stored. A duplicate or near-duplicate found by the history analysis during preprocessing is stored, linked through the self-referencing `duplicate_of_id`, closed and not analysed again; the demo data contained 18 such links, and 2 further duplicates came from evaluation runs. A repeat of an earlier unresolved complaint is linked through `repeat_of_id` and is analysed normally, so that the repeat-escalation rules can take effect.

`complaint_attachments` records each uploaded file (at most five per complaint, `MAX_ATTACHMENT_MB` 5 MB each) with its content type, size, SHA-256 digest and storage path; dataset records carry attachment metadata only. `complaint_history` is the case timeline shown in the complaint view: 8,770 events such as `complaint.submitted`, `knowledge.retrieved`, `ai.analysis_completed`, `validation.completed`, `review.queued`, `escalation.created`, `status.changed`, `response.sent` and `sla.breached`, each with an actor label and a JSON payload. The timeline is an operational record; the tamper-evident record is `audit_logs` (Section 25.4.8). `products` (Section 25.4.4) is related to complaints only through the `product_sku` code and is shown in Figure 25.4 for that reason.

![Figure 25.4 — Complaints, customers, orders, attachments and history](diagrams/database/fig-25-04-er-complaints-customers.svg)
*Figure 25.4 — Complaints, customers, orders, attachments and history*

### 25.4.3 Knowledge Base

The Knowledge Base, whose processing is described in Chapter 5, is stored in four tables with a strict parent-child chain (Figure 25.5). `documents` holds one row per policy, SOP, guideline, FAQ, rules document or template (`doc_type`), identified by its `doc_id` such as REF-POL-02, with its owner department and topic list. `document_versions` holds each uploaded version: version label, lifecycle `status` (Active, Previous, Superseded, Draft), `effective_date` and `expiry_date`, file name and format, MIME type, size, a unique SHA-256 `sha256`, storage path, page count, parse status, section and chunk counts, the version it `supersedes`, the injection-screening findings (`security_findings`), the policy values extracted from the text (`facts`) and an `extra` JSON with upload warnings, detected metadata and the revision-impact analysis. The demo database held 24 documents in 29 versions: 23 Active, 3 Previous, 2 Superseded and 1 Draft.

`document_sections` keeps the numbered structure of each version (section ID such as 4.3, heading, level and page span), and `document_chunks` holds the retrieval units. Each chunk has a unique `chunk_uid` of the form `<DOC_ID>@<version>#<section>-c<n>`, so every piece of evidence shown to the AI or to a reviewer can be traced to its document, version, section and page. A chunk also stores its token count, a float32 `embedding` with the name of the `embedding_model` that produced it (the default local feature-hashing embedder, so a model change triggers re-embedding), and `is_quarantined` with a `quarantine_reason`. Four chunks were quarantined in the demo database because the injection screener found instruction-like text; such chunks are never used as evidence.

![Figure 25.5 — Knowledge Base tables and the policy-reference link](diagrams/database/fig-25-05-er-knowledge-base.svg)
*Figure 25.5 — Knowledge Base tables and the policy-reference link*

### 25.4.4 Rule Matrix, taxonomy and prompts

Figure 25.6 shows the configuration tables that the pipeline reads at run time. `categories` (11) and `subcategories` (35) hold the complaint taxonomy, and `products` (15) holds the Lumora product catalogue with warranty months, hazard class and name aliases used for entity extraction. All three are seeded from the version-controlled YAML files in `rules/` and `config/`.

`rules` is the database copy of the Complaint Resolution Rule Matrix (Chapter 10), the deterministic ground truth. Each of the 290 rows stores one rule or one configuration block in the JSON column `body`, exactly as it appears in the YAML baseline, together with `rule_type`, `rule_id`, `subcategory_code` (for resolution, routing and category rules), `is_active`, an integer `version` and `updated_by_id`. The rows comprise 276 rules of ten types (resolution 116, escalation 39, routing 35, category 35, urgency_floor 15, review 14, missing_info 8, conditional_routing 6, followup 4 and sla 4) and 14 `config` rows (for example `parameters`, `signals`, `priority_config`, `validation_policy` and `precedence_rules`). `services/rules.py` rebuilds the in-memory Rule Matrix from these rows whenever the `rules_revision` counter in `system_settings` changes; the same table also holds `kb_revision`, the counter that invalidates the cached knowledge snapshot. In the demo database the counters stood at 16 and 30.

`prompts` and `prompt_versions` are the prompt registry. `prompt_versions` stores the system and user templates of each version, its status (active, draft or retired), the name of the JSON output schema (`complaint_analysis.v1` or `customer_communication.v1`), the generation parameters (for example temperature 0.1 and max_output_tokens 6000), a changelog and a SHA-256 fingerprint of the templates. The demo database held two prompts in four versions: `complaint_analysis` 1.0.0 and 1.1.0 (retired) and 1.2.0 (active), and `customer_communication` 1.0.0 (active). Chapters 21 and 22 describe the prompt design and its versioning.

![Figure 25.6 — Rule Matrix, taxonomy and prompt registry](diagrams/database/fig-25-06-er-rules-prompts.svg)
*Figure 25.6 — Rule Matrix, taxonomy and prompt registry*

### 25.4.5 AI analysis and validation

Each run of the two pipelines on a complaint produces the set of rows in Figure 25.7. `analyses` is the header of one run. It records the `trigger` (submission, dataset, reprocess, clarification, reopened, reclassification, regenerate, evaluation, lab or recovery), the `status` (running, then completed or invalid_output), the provider and model, any lab `fault_injection` profile, the prompt versions and their fingerprints for both stages (`prompt_versions`), the document versions used as evidence (`policy_versions`), the `ruleset_hash` of the Rule Matrix, the AI's structured answer (`output`, schema `complaint_analysis.v1`), the generated customer communication (`communication`, schema `customer_communication.v1`), the retrieval result with evidence, conflicts and outdated versions (`retrieval`), per-stage timings and the total latency. This satisfies SRS Step 49, which requires the prompt version, provider, model, timestamp and policy version of every analysis to be stored.

`ai_runs` stores every call attempt to the AI provider, including failed and retried ones: stage (analysis or communication), attempt number, provider, model, prompt key and version, request metadata including the prompt fingerprint, the raw `response_text`, `parsed_ok`, the error type and message, latency and token counts. In the demo database the 780 analyses needed 1,591 attempts: 789 analysis attempts and 802 communication attempts, of which 780 of each were parsed successfully, so every invalid answer or connection failure was recovered by the controlled retry policy (Section 8.9).

`policy_references` records each policy citation of an analysis and who made it (`cited_by`): `retrieval` for every evidence item with its applicability (Applicable, Conditionally Applicable, Not Applicable or Outdated), `ai` for each policy the AI cited, with `valid` showing whether the document and section exist, and `rule` for the sections required by the selected resolution rule. The demo database held 9,296, 2,280 and 1,939 rows of these three kinds.

`validation_results` holds the outcome of the Python Ground-Truth Validation Pipeline (Chapter 11) for one analysis (a unique `analysis_id`): overall status (pass, warn or fail), `verification_score`, `decision` (Verified or Manual Review), the scores of the twelve validation dimensions, the rules' own decision (`python_expected`), the field-by-field AI-versus-rules `comparison` of the Comparison Engine (Chapter 12; 18 fields when an AI answer exists, with an agreement ratio), the final `validated_decision` that the user interface shows, the manual-review reasons, the check counts and the `ruleset_hash`. `validation_checks` stores all 52 checks of every result, including those that were not applicable, with code, name, dimension, severity, status, message, expected and actual values and the rule and policy references behind them; 780 results therefore produced 40,560 check rows. `resolutions` keeps the AI's proposed resolution steps (`ai_steps`) next to the steps enforced by the rules (`validated_steps`) and the AI and validated eligibility, with status `proposed` or `validated` (587 and 193 rows in the demo data).

![Figure 25.7 — AI analysis records and rule-check records](diagrams/database/fig-25-07-er-analysis-validation.svg)
*Figure 25.7 — AI analysis records and rule-check records*

### 25.4.6 Case workflow: responses, reviews, escalations, follow-ups and SLA

Figure 25.8 shows how decisions and human review are recorded. `customer_responses` holds every version of the reply to the customer. A draft produced by the pipeline takes the `version_no` of its analysis; an edit by an agent or reviewer adds a new row with the next number, so earlier drafts remain visible. `status` is `ready` when the rule check passed and the response checks found nothing, `requires_review` otherwise, `approved` after a reviewer approval, `rejected` after a reviewer rejection and `sent` once the reply has been recorded as delivered through the customer's preferred channel (`sent_via`; delivery is simulated, as there is no live e-mail or SMS integration). The `validation` JSON keeps the response checks that were applied, and for pipeline drafts also the generated follow-up message. The demo data held 414 sent (all recorded by the simulated history), 321 requires_review and 45 ready responses.

`reviews` is the manual review queue. A review is created when the rule check decides Manual Review (never for evaluation cases), or with reason `pipeline_error` when processing fails, and only one open review can exist per complaint. It stores the reason codes and reasons (REV-001 to REV-014 of the Rule Matrix), the priority, the claiming reviewer (`assigned_to_id`), start and completion times, the `final_decision`, and two snapshots: `original_snapshot` with the AI output, the validated decision and the score at the moment the case was queued, and `final_snapshot` with the decision, the complaint fields, the reviewer and the time after completion. `review_actions` records each of the eight reviewer actions (approve, reject, modify, reclassify, reassign, escalate, regenerate, comment) with its payload, comment and `before` and `after` snapshots of the complaint's status, verification status, classification, department, urgency, priority, escalation, assignee and sentiment. Together these tables meet SRS Step 59: the original recommendation and the reviewer decision both remain on record. The demo data held 301 completed reviews, 300 of them approved by the simulated history and one completed by an administrator, and 150 pending reviews.

![Figure 25.8 — Decisions, customer responses and manual review](diagrams/database/fig-25-08-er-decisions-reviews.svg)
*Figure 25.8 — Decisions, customer responses and manual review*

Figure 25.9 shows the remaining workflow tables together with the evaluation tables. `escalations` records each escalation (Chapter 18) with its level and `rank` (0 for No Escalation to 5 for Critical Management Escalation), the reason, the `source` (rule when only the rules required it, rule+ai when the AI also identified it, agent, reviewer, or sla when the SLA monitor escalated a breached P0 or P1 case under ESC-039), the IDs of the escalation rules that fired, the departments to notify, the escalation notes and a status. The demo data held 380 escalations (218 rule+ai, 115 sla and 47 rule). `follow_ups` schedules follow-up communication with its type (one of the six SRS follow-up types), message, `due_at`, status and source rule. `sla_records` (Chapter 19) holds exactly one row per complaint with the priority, the SLA rule, the first-response and resolution deadlines, the actual first-response and resolution times, the response and resolution states (On Track, At Risk, Breached, Met), the times the case was flagged at risk and breached, and `breach_escalated`, which stops the monitor from escalating the same breach twice.

![Figure 25.9 — Escalations, follow-ups, SLA records and evaluation](diagrams/database/fig-25-09-er-escalation-sla-evaluation.svg)
*Figure 25.9 — Escalations, follow-ups, SLA records and evaluation*

Several status columns declare more values than the current code writes, and Table 25.2 states which values are actually produced. The two most visible cases are escalations and follow-ups: no API route acknowledges or resolves an escalation, so `acknowledged_at` is never set and the 228 `resolved` escalations in the demo data were closed by the seeded simulated history (`services/seed.py`, `SEED_SIMULATE_LIFECYCLE`); follow-ups move from `scheduled` to `completed` only.

**Table 25.2 — Status columns: values declared and values written by the current code**

| Column | Written by the code | Declared, not written | Status |
|---|---|---|---|
| analyses.status | running, completed, invalid_output | failed | Implemented |
| customer_responses.status | ready, requires_review, approved, rejected, sent | draft (default only) | Implemented |
| customer_responses.kind | response | follow_up, clarification | Implemented |
| resolutions.status | proposed, validated | approved, overridden | Implemented |
| escalations.status | open; resolved only by the demo seeder | acknowledged | Implemented; closing Planned |
| follow_ups.status | scheduled, completed | sent, cancelled, overdue | Implemented |
| reviews.status | pending, in_review, completed | — | Implemented |
| evaluation_runs.status | queued, running, completed, cancelled, failed | — | Implemented |

### 25.4.7 Evaluation and the Adversarial Lab

`evaluation_runs` records each evaluation of a labelled dataset: split or upload label, provider and model, fault-injection profile, prompt versions, ruleset hash, the number of cases planned and done, the computed metrics, duration and status. `evaluation_results` holds one row per case with the expected labels, the AI values, the rules' values, the three-way comparison, the verification status and score and an explanation. The demo database held two runs: run 1 over the 154-case holdout set and run 2, which was cancelled after 6 cases, giving 160 result rows. Each evaluated case is processed as a real complaint with `source` evaluation, `complaint_ref` R&lt;run&gt;-&lt;case_id&gt; and `dataset_case_id` equal to the case ID. That link is by value, not by foreign key (dotted line in Figure 25.9). Evaluation complaints are excluded from the operational lists, the review queue and the SLA monitor.

The Adversarial Lab has no tables of its own. Each lab run is stored as a complaint with `source` lab and a LAB-##### reference, analysed by the same pipeline with an optional fault-injection profile recorded in `analyses.fault_injection` and `ai_runs.fault_injection` (18 lab complaints in the demo data). `evaluation_cases` is defined in the schema but is not written by any code path: datasets are read directly from `data/sample_complaints/` and `data/hidden_test_ready/` (`services/datasets.py`), so the table was empty.

### 25.4.8 Audit trail

`audit_logs` (Figure 25.3) is the permanent, tamper-evident record of security-relevant and decision-relevant events: sign-ins and failed sign-ins, denied accesses (HTTP 403 responses are recorded as `access.denied`), complaint creation and processing, reviewer actions with before and after values, escalations, responses sent, exports, Rule Matrix and prompt changes, document uploads and status changes, and audit-chain verifications. Each entry stores the time, the actor (`actor_id`, `actor_label`, `actor_role`), `action`, `entity_type` and `entity_id`, a summary, a JSON `details` payload, the client IP address, the request ID, and the two chain fields `prev_hash` and `hash`. Entries refer to the entity they describe by type and ID string rather than by foreign key, so the trail does not depend on any other row. The demo database held 2,138 entries, of which 2,034 concerned complaints, 54 users, 29 documents, 15 rules, 4 evaluation runs and 2 datasets. Section 25.6 describes how the table is protected, and Chapter 37 how the trail is used.

## 25.5 Relationships and foreign-key behaviour

The 48 foreign keys fall into three groups by their `ON DELETE` rule (Table 25.3). The rules express ownership: rows that exist only as part of a complaint, an analysis, a document version, a review or an evaluation run are deleted with their owner; rows that must survive the loss of the analysis that produced them keep their data with a null link; and references to people and reference data block the deletion of the referenced row.

**Table 25.3 — Foreign keys by ON DELETE rule**

| Rule | Count | Foreign keys |
|---|---|---|
| CASCADE | 22 | complaint_id in analyses, ai_runs, complaint_attachments, complaint_history, customer_responses, escalations, follow_ups, resolutions, reviews, sla_records, validation_results; analysis_id in ai_runs, policy_references, validation_results; validation_checks.result_id; review_actions.review_id; document_versions.document_id; document_sections and document_chunks version_id; prompt_versions.prompt_id; subcategories.category_id; evaluation_results.run_id |
| SET NULL | 4 | customer_responses.analysis_id, resolutions.analysis_id, reviews.analysis_id, reviews.validation_result_id |
| NO ACTION | 22 | the 15 actor columns that reference users (for example submitted_by_id, assigned_agent_id, approved_by_id, assigned_to_id, uploaded_by_id, updated_by_id, created_by_id, audit_logs.actor_id); users.role_id, department_id, customer_id; orders.customer_id; complaints.customer_id, duplicate_of_id, repeat_of_id |

Because the application never deletes complaints, analyses, users or documents, the cascade rules define what would be removed together if an administrator deleted a record directly in the database, for example to honour a data-erasure request. The NO ACTION rule on every user reference, including `audit_logs.actor_id`, means that an account that has acted in the system cannot be deleted at all; it can only be deactivated, which keeps every actor identifiable in the trail. The SQLAlchemy relationships add the same ownership in the ORM with `cascade="all, delete-orphan"` for document versions, sections and chunks, prompt versions, validation checks, review actions and complaint attachments.

## 25.6 Audit relationships and tamper evidence

The audit table is protected at three levels, and each level has been tested.

1. **No update or delete path in the application.** `audit/service.py` offers only `record()`, which stages an entry in the caller's transaction.
2. **ORM guard.** SQLAlchemy `before_update` and `before_delete` listeners on `AuditLog` raise `AuditImmutableError`.
3. **Database triggers.** Migration 0001 creates the PL/pgSQL function `supportnova_audit_immutable()`, which raises `audit_logs is append-only: <operation> blocked`, and two triggers that call it: `audit_logs_immutable` (BEFORE UPDATE OR DELETE, for each row) and `audit_logs_no_truncate` (BEFORE TRUNCATE, for each statement). Both were present and enabled in the demo database.

The migration creates the triggers as follows (excerpt from `0001_initial_schema.py`):

```sql
CREATE OR REPLACE FUNCTION supportnova_audit_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION USING MESSAGE = 'audit_logs is append-only: ' || TG_OP || ' blocked';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER audit_logs_immutable BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW EXECUTE FUNCTION supportnova_audit_immutable();
CREATE TRIGGER audit_logs_no_truncate BEFORE TRUNCATE ON audit_logs
    FOR EACH STATEMENT EXECUTE FUNCTION supportnova_audit_immutable();
```

On top of immutability, the entries form a hash chain. A `before_commit` session hook seals all staged entries under a process lock and the PostgreSQL advisory transaction lock `pg_advisory_xact_lock(5318008424)`, so concurrent API requests, pipeline workers and server processes always extend one linear chain, and entries of a rolled-back transaction are discarded with it. For each entry, `prev_hash` is the `hash` of the preceding entry (empty for the first), and `hash` is the SHA-256 of `prev_hash` followed by the canonical JSON of the entry's time, actor, action, entity, summary and details. The IP address and request ID are recorded but are not part of the digest. `verify_chain()` recomputes every digest in ID order and reports the first entry whose stored values no longer match; it is exposed as `GET /api/v1/audit/verify` (Chapter 26).

For this report the chain was also recomputed independently, outside the application, with a read-only connection that followed the digest rule above. All 2,138 entries of the demo database matched their stored hashes and every `prev_hash` matched the preceding entry. IDs ran from 1 to 2,156; the gaps are sequence values that PostgreSQL does not reuse, and they do not affect verification because the chain follows ID order.

**Table 25.4 — Audit and history integrity mechanisms**

| Mechanism | Where | Status |
|---|---|---|
| Append-only triggers on audit_logs | migration 0001_initial | Implemented, Tested: tests/backend/api/test_security_api.py::test_audit_log_is_append_only_in_the_database |
| ORM update/delete guard | audit/service.py | Implemented |
| SHA-256 hash chain sealed at commit | audit/service.py | Implemented, Tested: tests/e2e/test_full_chain.py::test_complete_complaint_chain |
| Denied access recorded | api/errors.py | Tested: tests/backend/api/test_security_api.py::test_denied_access_is_audited |
| Reviewer before/after snapshots | reviews, review_actions | Implemented |
| Case timeline | complaint_history | Implemented (no database-level protection) |

## 25.7 Version relationships

Four kinds of versioned data make every decision reproducible: the policies a decision relied on, the rules that produced it, the prompts that produced the AI answer, and the analysis itself. Table 25.5 summarises how each is versioned, and the paragraphs below explain the links.

**Table 25.5 — Versioned entities and how decisions refer to them**

| Versioned entity | Version key | How an analysis refers to it |
|---|---|---|
| Policy document | document_versions (document_id, version), status | analyses.policy_versions; policy_references doc_id, version, section_id, chunk_uid |
| Rule Matrix | rules.version per row; rules_revision counter | analyses.ruleset_hash, validation_results.ruleset_hash, evaluation_runs.ruleset_hash |
| Prompt | prompt_versions (prompt_id, version), status, sha256 | analyses.prompt_versions; ai_runs.prompt_key, prompt_version |
| Analysis | analyses (complaint_id, version_no) | customer_responses.version_no, reviews.analysis_id |

**Document versions.** Uploading a new Active version demotes the current Active version to Previous and an existing Previous version to Superseded (`services/documents.py`). An upload is rejected with HTTP 409 when the same file (same SHA-256) or the same version label already exists, and with HTTP 422 when an Active upload is older than the current Active version. Only a version that is Active, already effective and not expired is eligible as primary evidence. Older versions of retrieved sections are returned separately and shown to reviewers as context only; they are never passed to the AI as evidence (`knowledge_base/retriever.py`). When a version replaces an Active one, the impact analysis compares the two versions' sections and extracted facts, and uses `policy_references` to list the open complaints whose decisions cited a changed section of the old version, the affected resolution and escalation rules and any rule parameters whose policy value changed. The result is stored in the new version's `extra` JSON.

**Rule versions.** Every accepted edit through `PUT /api/v1/rules/{rule_type}/{rule_id}` or `PUT /api/v1/rule-parameters/{key}` first builds a candidate Rule Matrix and runs the integrity validator on it. Only a valid candidate is saved; the row's `version` is then incremented, an audit entry with the before and after bodies is written, and `rules_revision` is bumped so that every worker rebuilds its cached matrix. The 16-character `ruleset_hash` identifies the exact matrix a decision was made with. In the demo database 15 rows were at version 2 after one editing session on 2026-09-25 (review rules REV-001 to REV-014 and the `validation_policy` configuration, recorded as 14 `rule.updated` entries and one `rule.config_updated` entry), and the hash of the live matrix was 2ce6e64257758104, compared with 62789e435529c023 for the YAML baseline. `POST /api/v1/rules/reset-to-baseline` replaces the live rows with the YAML baseline and records both hashes in the audit trail.

**Prompt versions.** A new prompt version is created as a draft and is accepted only if its templates contain the `$complaint` and `$nonce` placeholders that isolate untrusted complaint text. Activating a version retires the previously active one, so one version per prompt is active at a time; this rule is enforced by the service (`genai_pipeline/prompts.py`), not by a database constraint. Because each analysis stores the key, version and fingerprint of both prompts it used, and each attempt in `ai_runs` stores its prompt version, a change of prompt can be traced to exactly the analyses it affected.

**Analysis versions.** Each pipeline run adds an `analyses` row with `version_no` one higher than the complaint's previous maximum, and the unique constraint (complaint_id, version_no) prevents two runs from taking the same number. Earlier analyses, their AI attempts, checks and policy references stay in the database, and `GET /api/v1/complaints/{ref}/analyses` lists them. In the demo data every complaint had been analysed once, so all 780 analyses had `version_no` 1; re-analysis is exercised by the automated tests rather than by the demo data.

## 25.8 Indexes

Besides the 35 primary keys and 6 unique constraints, the schema has 78 named indexes: 14 unique indexes on business keys, 63 ordinary B-tree indexes (four of them composite) and one GIN trigram index. Table 25.6 lists the indexes that serve the main queries of the application.

**Table 25.6 — Important indexes and the queries they serve**

| Index | Columns | Serves |
|---|---|---|
| ix_complaints_status_created | status, created_at | complaint list filtered by status and sorted by date |
| ix_complaints_category_created | category_code, created_at | category trends and alerts |
| ix_complaints_department_status | department_code, status | department performance and routing views |
| ix_complaints_customer_created | customer_id, created_at | customer dashboard and customer history analysis |
| ix_complaints_text_hash | text_hash | exact-duplicate check at submission |
| ix_complaints_needs_review, _priority, _sla_state, _verification_status | one column each | dashboard counters and list filters |
| ix_complaints_assigned_agent_id | assigned_agent_id | agent dashboard ("assigned to me") |
| ix_complaints_title_trgm | GIN on lower(title), gin_trgm_ops | case-insensitive substring search on titles |
| ix_sla_records_resolution_due_at, _resolution_state | one column each | SLA monitor and SLA reports |
| ix_follow_ups_due_at, _status | one column each | follow-up scheduling |
| ix_validation_checks_code, _dimension, _status | one column each | rule-check statistics in analytics |
| ix_policy_references_doc_id | doc_id | policy-usage report and revision impact analysis |
| ix_audit_logs_created_at, _action, _entity_type, _entity_id | one column each | audit-log filters and per-complaint audit trail |
| ix_document_versions_sha256 (unique) | sha256 | duplicate-document rejection |

The trigram index is created by migration 0001 inside a guarded block: it enables the `pg_trgm` extension and creates `ix_complaints_title_trgm`, and if the extension cannot be installed (insufficient privilege or missing extension files) it logs a notice and skips the index, so the migration still succeeds on restricted hosting. In the demo database the extension (version 1.6) and the index were present. A read-only `EXPLAIN` on the demo database showed that a predicate on `lower(title)` alone uses the index. The free-text search of `GET /api/v1/complaints?q=` combines title, complaint reference, order reference and customer name in a single OR condition, however, and PostgreSQL planned that query as a sequential scan even with sequential scans discouraged. At 800 complaints this is not noticeable. For the SRS scalability target of 10,000 complaints, adding trigram indexes on the other searched columns, or splitting the search into separately indexed parts, is a Future Enhancement.

## 25.9 JSON columns and why they are used

JSONB is used where the structure is defined outside the relational schema, by a versioned JSON Schema, a YAML rule format or a snapshot of other rows, and where the value is read and written as a whole. The 52 JSONB columns in 23 tables fall into the families in Table 25.7.

**Table 25.7 — JSONB column families**

| Family | Examples | Why JSON |
|---|---|---|
| AI evidence | analyses.output, communication, retrieval, prompt_versions, policy_versions, stage_timings; ai_runs.request | keeps the schema-validated AI answer and its context verbatim; its shape is governed by complaint_analysis.v1 and customer_communication.v1 |
| Rule-check results | validation_results.python_expected, comparison, validated_decision, dimension_scores, review_reasons, counts; validation_checks.expected, actual, rule_refs, policy_refs | expected and actual values differ by check (strings, lists, eligibility objects) |
| Rule definitions | rules.body; system_settings.value | ten rule types with different fields; rules can be added or edited at run time without a migration |
| Snapshots for traceability | reviews.original_snapshot, final_snapshot; review_actions.before, after, payload; resolutions.ai_steps, validated_steps, eligibility | preserve what the AI proposed and what a person decided, exactly as it was |
| Small lists and payloads | roles.permissions, products.aliases, documents.topics, escalations.rule_ids, departments, notes; reviews.reason_codes; complaint_history.data; audit_logs.details | variable-length lists without join tables |
| Documents and evaluation | document_versions.security_findings, facts, extra; complaints.preprocessing; orders.data; evaluation_runs.metrics, report_paths, prompt_versions; evaluation_results.expected, ai, python, comparison; evaluation_cases.record | parser, screening and metric outputs whose shape evolves with the code |

The trade-off is that the database does not constrain the inside of these values. SupportNova compensates in two ways. First, the contents are validated before they are written: AI output must pass the JSON Schema and Pydantic models before it is stored as `analyses.output` (an invalid answer is stored only as raw text in `ai_runs`), and rule bodies must pass the Rule Matrix integrity validator. Second, every value the application filters or aggregates on is copied into a typed, indexed column: priority, urgency, category, department, verification status and SLA state on `complaints`; code, dimension, severity and status on `validation_checks`; and `cited_by`, `applicability` and `doc_id` on `policy_references`. Analytics therefore never needs to search inside JSON. The two binary columns, `complaints.embedding` and `document_chunks.embedding`, hold float32 vectors produced by the embedder in `knowledge_base/embeddings.py`; similarity search runs in the application, and no external vector database is required (`VECTOR_DATABASE_URL` is optional).

## 25.10 Migrations

The schema has two Alembic revisions (Table 25.8). On start-up, `main.py` calls `database/migrate.py:upgrade_to_head()` when `AUTO_MIGRATE` is true (the default). If a database already contains the tables but no `alembic_version` row, as a database created before migrations existed would, it is first stamped at the baseline revision and then upgraded, so no table is recreated. The demo database was at revision `0002_drop_mock_flags`.

**Table 25.8 — Alembic migrations**

| Revision | Date | Changes | Downgrade |
|---|---|---|---|
| 0001_initial | 2026-09-23 | creates all 35 tables with their keys, constraints and indexes; on PostgreSQL also the audit immutability function and the two triggers, and the pg_trgm extension with ix_complaints_title_trgm (skipped with a notice if unavailable) | drops the index, triggers and function, then all tables in dependency order |
| 0002_drop_mock_flags | 2026-09-24 | drops five Boolean columns left over from a development mock mode: complaints.is_mock_analysis, analyses.is_mock, ai_runs.is_mock, customer_responses.is_mock and evaluation_runs.is_mock | re-adds the five columns with server default false |

Revision 0002 records a design decision rather than a structural change: every stored AI output now comes from the configured model, and the test suite asserts that no mock provider exists (`tests/backend/unit/test_genai_providers.py::test_there_is_no_mock_provider`). The columns are removed with `batch_alter_table`, which works on PostgreSQL and on SQLite. The dropped columns are still visible in the catalog as gaps in the column positions of the five tables (for example position 40 of `complaints`), which is normal for PostgreSQL after `DROP COLUMN`.

## 25.11 Limitations of the current design

The following points were found while verifying the schema against the code and the demo database, and are stated here so that the design is not over-claimed:

- The complaint free-text search cannot use the trigram index because of its OR shape (Section 25.8); it is fast at the demo volume but will not scale to the SRS target without the change described there (Future Enhancement).
- Rule Matrix codes, policy references and audit entity IDs are not foreign keys (Section 25.3). Their integrity depends on the validation checks and the Rule Matrix integrity validator, which are tested, rather than on the database.
- `evaluation_cases` is never written, and several declared status values are never produced (Table 25.2). Acknowledging and closing escalations has columns but no API support (Planned).
- `complaint_history` has no database-level protection. The seeder adjusts the timestamps of simulated history events, which is acceptable for the labelled demo data; the tamper-evident record is `audit_logs`.
- The one-active-prompt rule and the one-open-review-per-complaint rule are enforced in the services, not by partial unique indexes.
