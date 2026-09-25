# Chapter 37 — Auditability and Traceability

The SRS asks that every analysis store its prompt version, GenAI provider, model, analysis timestamp and policy version (Step 49); that generated actions reference approved sources (section 1.6, item l); that the original recommendation and the reviewer's decision both remain in the audit trail (Step 59); and that original and final decisions are logged (item lxiv). SupportNova answers these requirements with two complementary records. The **case record** is a set of tables written by every pipeline run that together explain why a decision was made: which text the model saw, what it answered, which policy sections and rules were applied, which checks failed, and what a reviewer changed. The **audit log** is an append-only, hash-chained table that records who did what and when, and whose integrity can be verified at any time. This chapter describes both and shows how an evaluator uses them to reconstruct a decision.

## 37.1 The traceability chain

Every analysis of a complaint writes a chain of linked rows, all keyed by the complaint and by the analysis ID (Figure 37.1). Nothing in the chain is overwritten when a complaint is processed again: reprocessing, a customer clarification or a reviewer reclassification creates a new `analyses` row with the next `version_no`, and the earlier analysis with its checks and citations stays in place.

![Figure 37.1 — The records that link a complaint to its final decision](diagrams/architecture/fig-37-01-traceability-chain.svg)
*Figure 37.1 — The records that link a complaint to its final decision*

**Table 37.1 — Records in the traceability chain**

| Record | Table | What is stored | Question it answers |
|---|---|---|---|
| Complaint | `complaints`, `complaint_attachments`, `complaint_history` | Submitted fields, text hash, attachment SHA-256; every event with status change, actor and message | What did the customer submit, and what happened to the case? |
| Preprocessing | `complaints.preprocessing` | Normalised text, injection findings, risk signals, entities, rule classification candidates, sentiment, facts, history, whether the order was found | What did the deterministic screening find before any AI call? |
| AI analysis | `analyses` | Trigger, provider, model, prompt key, version and SHA-256 of both prompts, policy versions of the evidence, ruleset hash, the AI's JSON output, the response JSON, the retrieval result, stage timings, fault profile, timestamps | Which model, prompt and rule set produced this analysis, and when? |
| AI attempts | `ai_runs` | One row per attempt: stage, attempt number, prompt key and version, request metadata (prompt SHA-256, prompt sizes, redacted preview, correction, vendor request ID, serving model, stop reason), raw response, parse result, error, latency, tokens | Exactly what was sent and received, including failed attempts and retries? |
| Policy evidence | `policy_references` | Each section retrieved, cited by the AI or required by a rule, with version, section, chunk UID, applicability, active-version flag, validity and a note | Which approved sources support the decision, and was each citation real and current? |
| Rule decision | `validation_results.python_expected`, `validated_decision` | The Rule Matrix decision: selected resolution rule and its condition, fired escalation rules with reasons, the decision trace, pending rules, applicability, timelines | Which rule decided each field, and why did it apply? |
| Validation | `validation_results`, `validation_checks` | Score, decision, dimension scores, review reasons; for each of the 52 checks the status, severity, message, expected and actual values, rule and policy references | Which checks passed or failed, and what was expected? |
| Comparison | `validation_results.comparison` | Field by field: AI value, rules value, match or mismatch, explanation | Where did the AI and the rules disagree? |
| Resolution | `resolutions` | AI steps, validated steps (each with its source), AI and validated eligibility | Which steps did the rules keep, add or reject? |
| Escalation | `escalations` | Level, rank, reason, source (`rule`, `rule+ai`, `agent`, `reviewer` or `sla`), rule IDs, departments, notes, status | Who or what required the escalation? |
| Response | `customer_responses` | Version, tone, subject, body, status, source (provider, agent or reviewer), the validation checks, approver and time, sent time and channel | Which reply was drafted, checked, approved and sent? |
| Follow-up and SLA | `follow_ups`, `sla_records` | Follow-up type, due time and source rule; SLA targets, states, at-risk and breach times | Which commitments and deadlines apply? |
| Review | `reviews`, `review_actions` | Reason codes; the original snapshot (AI output, validated decision, score); each action with payload, comment, before and after snapshots and the actor; the final snapshot | What did a person decide, and what did the case look like before and after? |
| Audit | `audit_logs` | Actor, role, action, entity, summary, details, address, request ID, previous hash, hash | Who did what, when, and has the record been altered? |

## 37.2 Prompt, model and rule-set traceability

Step 49 is met by the `analyses` row and by every `ai_runs` row. `analyses.prompt_versions` stores, for both GenAI stages, the prompt key, version and SHA-256 fingerprint of the template. `provider` and `model` identify the configured vendor, and each attempt additionally records the model name the vendor reported (`served_by`, for example `gpt-4.1-mini-2025-04-14` in `reports/genai_pipeline_evidence/invalid_response_and_retry.json`). `created_at` and `completed_at` timestamp the analysis, and `policy_versions` maps each cited document to the version used as evidence. The fingerprint connects a run to the exact template text: the Prompts & AI page shows `complaint_analysis@1.2.0` with the fingerprint `428c297c112322b45fb08b033ce715f87b3009f2110fe3092537b2b7cfc4008f`, and the same value appears as `prompt_sha256` in the request metadata of the recorded attempts. Creating and activating prompt versions is audited (`prompt.version_created`, `prompt.activated`).

The rule set is traced the same way. Each analysis, validation result and evaluation run stores the `ruleset_hash` of the Rule Matrix it used; evaluation run #1, for example, recorded `be81124c2a1df0d5`. A later edit to the rules therefore shows up as a different hash, and the result of an older analysis can be attributed to the rule set that was live at the time. Rule edits themselves are versioned in the `rules` table (`version`, `updated_by_id`, `updated_at`) and audited (`rule.created`, `rule.updated`, `rule.config_updated`, `rule.parameter_changed`, `rules.reset_to_baseline`, and the `taxonomy.*` actions). The demo audit log contains 15 such entries: on 25 September 2026 the `validation_policy` configuration and the review rules REV-001 to REV-014 were updated to version 2.

## 37.3 Policy evidence traceability

The model is given the retrieved sections as numbered evidence items (E1 to E10), each tagged with its document ID, version, status, section and heading. Its citations name the evidence ID, the policy ID and the section. After the analysis the pipeline writes three kinds of `policy_references` rows: `retrieval` for every section that was retrieved (with its applicability as judged by Pipeline 2), `ai` for every citation the model made (with `valid` set only if the document and section exist), and `rule` for every section the selected Rule Matrix rule requires. In the demo data the operational complaints have 7,185 retrieval rows, 1,772 AI citations (26 of them invalid) and 1,490 rule citations. The retrieval result stored with the analysis also records each evidence chunk's UID in the form `DOC-ID@version#section-cN`, the retrieval methods that found it, the precedence-resolved conflicts between documents, and the outdated versions of the same sections. Outdated versions are marked "not used as the primary basis for decisions (CHP-POL-01 s10.4)". Each document version keeps its file SHA-256, uploader, status history and, for a revision, the impact analysis listing the changed sections and the affected rules and complaints.

## 37.4 Human decisions and overrides

A reviewer's decision never replaces the evidence of what the system proposed. When a case is queued, the review stores an `original_snapshot` containing the AI output, the validated decision and the score. Every reviewer action (approve, reject, modify, reclassify, reassign, escalate, regenerate, comment) writes a `review_actions` row with the payload, the comment and snapshots of the complaint's key fields before and after the action, and an audit entry `review.<action>` with the same before and after data (`services/reviews.py`). A comment is mandatory for reject, modify, reclassify and reassign. When the review completes, the `final_snapshot` records the decision, the resulting complaint state, the reviewer and the time. A reclassification does not edit the stored analysis; it triggers a new analysis with the reviewer's subcategory as the reference, and the validated decision then shows the classification source "reviewer". Edited customer responses become new response versions with the source `agent` or `reviewer`, and they are checked again by the same promise and prohibited-behaviour checks.

![Figure 37.2 — The review workspace keeps the original AI output next to the validated decision and records every action](../screenshots/13-review-workspace.png)
*Figure 37.2 — The review workspace keeps the original AI output next to the validated decision and records every action*

Figure 37.2 shows the review workspace for CMP-00111. It lists why the case needs review, the 13 of 18 fields on which the AI and the rules disagree (each with the rule that decided it, for example RES-SAF-OVH-02 for urgency), and tabs for the final decision, the original AI output and the draft response. The reviewer panel states that "Every action is recorded in the audit log."

## 37.5 The audit log

`audit_logs` stores, for every entry, the time, the actor (user ID, label and role), the action, the entity type and ID, a summary, a JSONB `details` object, the client address, the request ID, and the hash chain fields `prev_hash` and `hash` (`backend/src/supportnova/audit/service.py`).

**Recording.** Code records an entry with `audit.record(...)`, which stages it on the current database transaction. A `before_commit` hook seals all staged entries: it takes a process-wide lock and the PostgreSQL advisory transaction lock `pg_advisory_xact_lock(5318008424)`, reads the hash of the latest entry, and computes each new hash as the SHA-256 of the previous hash followed by a canonical JSON serialisation (sorted keys) of the entry's time in UTC, actor, action, entity, summary and details. Because sealing happens inside the committing transaction, concurrent API requests, pipeline workers and even several server processes always extend one linear chain, and the entries of a transaction that rolls back are discarded together with it.

**Immutability.** Two independent guards prevent changes. In the application, SQLAlchemy `before_update` and `before_delete` listeners raise `AuditImmutableError` for any audit row. In the database, migration 0001 creates the trigger `audit_logs_immutable` (before `UPDATE` or `DELETE`, for each row) and the trigger `audit_logs_no_truncate` (before `TRUNCATE`), both raising "audit_logs is append-only: … blocked". The triggers also stop anyone who bypasses the application: `test_audit_log_is_append_only_in_the_database` connects to PostgreSQL directly and confirms that `UPDATE` and `DELETE` statements fail.

**Verification.** `verify_chain` recomputes every hash from the first entry and returns `valid`, the number of entries checked and the ID of the first broken entry, if any. `GET /api/v1/audit/verify` (permission `audit:read`, administrators only) runs it and records an `audit.verified` entry. The Audit log page offers the same check as "Verify chain integrity" (Figure 37.3). While this report was being written, the chain of the demo database was recomputed independently with the same formula, read-only: all 2,138 entries were intact. The verify endpoint itself had not yet been called on the demo database, which is why the screenshot reads "Not verified in this session yet".

**Access.** `GET /api/v1/audit` filters by action prefix, entity type, entity ID, actor and date range, 50 entries per page and at most 500. Reviewers and managers hold only `audit:read_complaint`, so they see complaint, review, report and evaluation entries; administrators see everything and can export the log as CSV, Excel or PDF (up to 20,000 rows, itself audited as `report.exported`). `GET /api/v1/complaints/{ref}/audit` returns the entries for one complaint.

![Figure 37.3 — The Audit log page: chain verification, activity by action and filters](../screenshots/26-audit-log.png)
*Figure 37.3 — The Audit log page: chain verification, activity by action and filters*

**Table 37.2 — Actions recorded in the audit log, with counts in the demo database**

| Area | Actions (count on 25 Sep 2026) |
|---|---|
| Sign-in and users | `auth.login` (50), `auth.logout` (3), `auth.login_failed` (0), `access.denied` (0), `user.created` (1), `user.updated` (0) |
| Complaint processing | `complaint.created` (800), `complaint.processed` (780), `complaint.duplicate_linked` (20), `complaint.processing_failed` (0), `complaint.sla_breach_escalated` (115) |
| Case work | `complaint.status_changed`, `complaint.assigned`, `complaint.escalated`, `complaint.clarified`, `complaint.reprocess_requested`, `response.sent`, `response.edited`, `follow_up.completed` (0 each in the demo log) |
| Reviews | `review.claimed` (0), `review.approve` (300), `review.modify` (1), and the other `review.<action>` entries (0) |
| Knowledge base and rules | `document.uploaded` (29), `document.status_changed` (0), `rule.updated` (14), `rule.config_updated` (1), `rule.created`, `rule.parameter_changed`, `rules.reset_to_baseline`, `taxonomy.*` (0), `prompt.version_created`, `prompt.activated` (0) |
| Reports and audit | `report.exported` (0), `audit.verified` (0) |
| Quality and data | `lab.run_started` (18), `evaluation.started` (2), `evaluation.completed` (2), `dataset.imported` (1), `dataset.lifecycle_simulated` (1) |
| Total | 2,138 entries |

The counts describe the demo database only. For example, the deliverable reports in `reports/` were exported by `scripts/export_deliverables.py` directly from the database rather than through the API, so they left no `report.exported` entries. The 300 `review.approve` entries were written by the demo time-lapse and are attributed to "Demo Data Seeder (simulated history)"; the one `review.modify` entry is a real action by the administrator.

The **complaint timeline** (`complaint_history`) complements the audit log. It is the case-level narrative shown on the "Timeline & audit" tab, in customer-safe wording for customers (`api/serializers.py`). For dataset complaints, which were submitted on their dataset dates but processed on the import day, `align_timeline` shifts the pipeline's timeline events to the submission time, while the audit entries keep their real time. Simulated history is always labelled: the 1,478 timeline events written by the demo data seeder (the seeded dataset statuses and the demo time-lapse) carry the actor "Demo Data Seeder (simulated history)".

## 37.6 How an evaluator determines why a decision was made

An evaluator can reconstruct any decision from the case page, the case report or the API, without access to the database. Table 37.3 maps the typical questions to the place where each is answered.

**Table 37.3 — Where each question about a decision is answered**

| Question | Case page (UI) | API or file |
|---|---|---|
| What is the final decision, and which rule is it based on? | Overview: final decision with "Basis: RES-…", escalation rule IDs, validated steps marked "AI · checked" or "added by rules", rejected AI proposals with the reason | `GET /complaints/{ref}` (`validation.validated_decision`) |
| Where did the AI and the rules disagree? | "AI vs rules" tab: AI value, rules value, result and basis for each field | `validation.comparison`, `validation.checks` |
| Which policy sections were used? | "Evidence" tab: evidence with document, version, status, section and score; conflicts and outdated versions | `analysis.retrieval` |
| What exactly did the model receive and return? | "AI runs" tab: every attempt with prompt version, latency, tokens, request metadata and raw JSON | `GET /complaints/{ref}/ai-runs` |
| What happened, in order, and who did it? | "Timeline & audit" tab: events and the audit entries with the first 12 characters of each hash | `GET /complaints/{ref}/timeline`, `GET /complaints/{ref}/audit` |
| What did a reviewer change? | Review workspace: reasons, original AI output, review history | `GET /reviews/{id}` (`review_actions` before and after) |
| Everything in one document | "Case report" button | `GET /complaints/{ref}/report.pdf` |
| Has the record been altered? | Audit log page: "Verify chain integrity" | `GET /audit/verify` |

The **case report PDF** is built by `complaint_case_pdf` in `backend/src/supportnova/reporting/exports.py` from the same data as the case page. It contains the complaint and its facts; the final decision checked against the rules (category with its classification source, departments, urgency, impact and priority with their sources, escalation with the fired rules, eligibility, selected rule and its condition, required and prohibited actions, policy references, missing information, clarification questions, follow-up and quotable timelines, and the validated steps with their source); the AI-vs-rules comparison; every validation check with the review reasons; the policy evidence; the customer response; the escalations; the manual review with each action, actor, time and comment; the complete timeline; and a traceability section with the AI provider and model, the prompt versions, the rule-set version, the processing time and the number of AI attempts. The endpoint requires `complaint:read_all`, and each download is audited.

![Figure 37.4 — A case page: the pipeline tracker, the final decision with its basis rule and the rejected AI proposals](../screenshots/08-complaint-detail-final-intelligence.png)
*Figure 37.4 — A case page: the pipeline tracker, the final decision with its basis rule and the rejected AI proposals*

Figure 37.4 shows such a reconstruction for CMP-00616, "Front door found unlocked". The rules classified the complaint with low confidence, so the AI category (Unauthorized Account Access) is marked "Provisional (AI)". Urgency Critical and priority P0 have the basis RES-ACC-UNA-03. The Critical Management Escalation comes from ESC-009 (suspected unauthorised access or account takeover) and ESC-010 (physical home security compromised by an unexplained smart-lock event). Two steps are marked "added by rules" (ADVISE_PHYSICAL_KEY and REVOKE_SESSIONS). Three AI proposals are listed as rejected because they are "not required or recommended by rule RES-ACC-UNA-03 - commitments must come from the Rule Matrix". The pipeline tracker at the top shows that the rule check sent the case to Manual Review with a score of 94.

## 37.7 Limitations

The hash chain proves that no stored entry was changed or deleted after it was written, but it is anchored only in the same database. A database superuser who disables the triggers could rewrite the whole chain consistently. Periodically copying the latest hash to storage outside the database would detect this (**Future Enhancement**). `verify_chain` reads the complete log on each call; with 2,138 entries this is quick, but its cost grows linearly with the log and has not been measured. `ai_runs.response_text` keeps up to 20,000 characters of each answer, which is well above the observed average of 1,405 output tokens for the analysis call. Finally, parts of the demo history are simulated, as described in Section 37.5: the simulated entries are labelled and can be filtered by their actor, but they are not evidence of real reviewer work.
