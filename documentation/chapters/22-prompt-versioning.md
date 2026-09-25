# Chapter 22 — Prompt Versioning

SRS Step 48 requires prompts to be centrally stored and versioned, and Step 49 requires every analysis to record the prompt version, provider, model, analysis timestamp and policy version. This chapter describes how SupportNova identifies, stores, activates, logs, tests and rolls back prompt versions, and records the history of the versions that exist. The prompt text itself is analysed in Chapter 21; the complete version record is in Appendix K.

## 22.1 Prompt Identity

A prompt version is identified by its **key** and its **version** and fingerprinted by the **SHA-256** of its templates. Table 22.1 lists the elements that make up a version, as defined by `PromptTemplate` in `backend/src/supportnova/genai_pipeline/prompts.py` and stored in the tables `prompts` and `prompt_versions`.

**Table 22.1 — Elements of a prompt version**

| Element | Meaning | Stored in |
|---|---|---|
| Key | Prompt family: `complaint_analysis` or `customer_communication` | `prompts.prompt_key` |
| Description | Purpose of the family | `prompts.description` |
| Version | Semantic version `major.minor.patch`; the API enforces the pattern `^\d+\.\d+\.\d+$` | `prompt_versions.version` |
| Status | `draft`, `active` or `retired`; one active version per key | `prompt_versions.status` |
| Output schema | Name of the JSON schema the output must satisfy, for example `complaint_analysis.v1` | `prompt_versions.output_schema` |
| Parameters | Generation parameters, for example temperature 0.1 and 6,000 output tokens | `prompt_versions.params` |
| System and user templates | The prompt text with `$placeholders` | `system_template`, `user_template` |
| Changelog | What changed and why | `prompt_versions.changelog` |
| Fingerprint | SHA-256 of the system template, a line `---` and the user template | `prompt_versions.sha256` |
| Created | Creation time and creating user (empty for versions seeded from files) | `created_at`, `created_by_id` |

The fingerprint is computed as `sha256(system_template + "\n---\n" + user_template)`. It identifies the exact text a model received, independently of the version label: the fingerprint recorded with each analysis is computed from the template text that was actually rendered, so a template changed in the database without a new version would show a fingerprint that differs from the stored one. The fingerprints of the four versions in the demo database match those recomputed from the files in `prompts/` (Appendix K). The fingerprint covers the templates only; a change of parameters or output schema changes the version record but not the fingerprint.

## 22.2 Storage in Files and in the Database

The shipped prompt versions are YAML files under `prompts/<key>/<version>.yaml`, version-controlled with the rest of the repository. On startup (`AUTO_SEED=true`), `seed_prompts` loads every file: it creates the prompt family if it does not exist and inserts each version that is not yet in the database, with the status written in the file. When a file with status `active` introduces a version the database does not have, the currently active version of that key is set to `retired` and an audit entry `prompt.activated` records which versions were retired and the new fingerprint. A version that already exists in the database is never overwritten by its file, so a database activation or rollback survives restarts and a file cannot silently change a version that analyses have already used.

At run time the pipeline reads prompts from the database, not from the files: `active_prompt(db, key)` returns the active version of the key and falls back to the active file only when the database has no active version of that key. Prompt templates therefore exist in exactly two controlled places, the version files and the `prompt_versions` table. Apart from the fixed labels with which `genai_pipeline/context.py` formats the case data (for example "Use the prevailing source." after each policy conflict), the only instruction wording in application code is the corrective message of a controlled retry and its `<validation_feedback>` wrapper (`genai_pipeline/runner.py`, `providers/base.py`); it is fixed, is not part of any template and is therefore not covered by the version fingerprint.

In the demo database the two prompt families and four versions were created by one seeding run, all with the timestamp 2026-09-24 19:32:17 (UTC+05:00) and without a creating user. Versions 1.0.0 and 1.1.0 of `complaint_analysis` were loaded with the status `retired` written in their files, and 1.2.0 was loaded as `active` while no version was active yet, so no `prompt.activated` audit entry was needed and none exists in this database.

## 22.3 Active and Retired Versions

Each key has one active version, which every new GenAI call of that stage uses. Figure 22.1 shows the lifecycle. A version created through the API or the Prompts page starts as a `draft` and is never used by the pipeline until it is activated. Activation (`activate_version`) sets the chosen version to `active`, sets every other active version of the key to `retired` and writes an audit entry `prompt.activated` with the previously active versions. Retired versions are kept with their full text, parameters, changelog and fingerprint; nothing is deleted, so any analysis can be traced back to the exact prompt that produced it and any retired version can be activated again.

![Figure 22.1 — Lifecycle of a prompt version](diagrams/uml/fig-22-01-prompt-version-lifecycle.svg)
*Figure 22.1 — Lifecycle of a prompt version*

## 22.4 Version History

### 22.4.1 complaint_analysis 1.0.0

The initial version (changelog "Initial version.") established the structure that all later versions keep: the role statement with the proposal framing, the three trust boundaries, eleven analysis rules, the reference-data blocks for taxonomy, departments, action catalogue, escalation levels, urgency and priority guide and follow-up types, and the user template with evidence, policy conflicts, verified facts and the nonce-tagged complaint element. Its parameters (temperature 0.1, 6,000 output tokens) have not changed since.

### 22.4.2 complaint_analysis 1.1.0

Version 1.1.0 responded to two observations from live OpenAI runs. First, a run put a subcategory code into `issue_category`. Rule 1 was reworded to say which code goes where ("issue_category is the CATEGORY code (for example SAF) and subcategory is the full SUBCATEGORY code (for example SAF-OVH)"), and in the same change the structured-output schema began to restrict every code field to the live catalogue (`schemas.constrain_codes`, Section 8.5), so that the model can no longer return a code of the wrong kind. Second, to cut the response time towards the SRS 20-second target, rule 12 was added and asks for brief free text: summary at most two sentences, one-sentence reasons, at most five key facts, five claims and four guidance items. The user template and the parameters were unchanged; the system template grew from 4,874 to 5,147 characters.

### 22.4.3 complaint_analysis 1.2.0

Version 1.2.0 came from a failure analysis of the first live runs on the development set. Its changelog records the findings and the changes:

```text
1.2.0 - From the failure analysis of the first live dev-set runs: the approved routing policy (RTE-RUL-14
sections 3-5) is now reference data, because retrieval surfaced it for only 6% of complaints and routing
was the most frequent critical mismatch; resolution steps must be complete (verification first, safety or
security containment, remedy, notifications) and include the escalation action for the escalation level;
the escalation procedure's supervisor triggers are named; the urgency guide adds SLA-RUL-15 section 5
(when several levels apply, the highest is used).
```

In the template this means a new `<routing_policy>` reference block, a rewritten rule 3 that routes with that block, an extended rule 5 that prescribes complete, ordered steps and maps each escalation level to its action code, and an extended rule 7 that names the Supervisor Review triggers of the escalation procedure (a refund requested outside the eligibility window, a late billing dispute, compensation above an agent's authority, a chargeback or bank-dispute mention, a warranty-denial appeal). The system template grew to 6,501 characters. The change also touched code: `genai_pipeline/context.py` now supplies RTE-RUL-14 sections 3 to 5 and SLA-RUL-15 section 5 as reference data on every call.

The new version was compared with 1.1.0 in an A/B run on 57 development complaints with the real model; the result recorded with the change is shown in Table 22.2.

**Table 22.2 — A/B comparison of complaint_analysis 1.1.0 and 1.2.0 (57 development complaints)**

| Measure | 1.1.0 | 1.2.0 |
|---|---|---|
| GenAI subcategory matching the expected label | 82.5% | 89.5% |
| GenAI department matching the expected label | 87.7% | 89.5% |
| Misrouted complaints | 9 | 6 |

Three qualifications apply. The figures are recorded in the commit message of the 1.2.0 change and are not exported to `reports/`. The sample of 57 complaints is small. And the comparison was between two complete builds: besides the prompt text, the 1.2.0 build contained the new context builder and a PDF-parser fix made in the same change (tables read row by row, which affects the text of the RTE-RUL-14 routing table; regression test `tests/backend/unit/test_documents_exports.py::test_pdf_keeps_repeated_body_text_and_reads_tables_by_row`), so the improvement belongs to the change as a whole rather than to the wording alone. Version 1.2.0 has been the active version for every analysis in the demo database.

### 22.4.4 customer_communication 1.0.0

The communication prompt has a single version (changelog "Initial version.", temperature 0.3, 2,500 output tokens). Its rules have not required a change, because its output is constrained by the validated decision it receives and checked by Phase B (Chapter 21).

**Table 22.3 — Prompt version history**

| Key and version | Status | Change | Driven by |
|---|---|---|---|
| `complaint_analysis` 1.0.0 | retired | Initial structure: role, trust boundaries, 11 rules, reference data, nonce-tagged user template | Initial design |
| `complaint_analysis` 1.1.0 | retired | Explicit category and subcategory codes; brevity rule 12; live code enums in the request schema | A live run put a subcategory code in `issue_category`; response time towards the 20-second target |
| `complaint_analysis` 1.2.0 | active | Routing policy as reference data; complete, ordered resolution steps with the escalation action; named supervisor triggers; SLA-RUL-15 section 5 | Failure analysis of dev-set runs: routing the most frequent critical mismatch, routing policy retrieved for 6% of complaints |
| `customer_communication` 1.0.0 | active | Initial version | Initial design |

## 22.5 Per-Analysis Logging

Every analysis records which prompts produced it, at three levels of detail. The `analyses` row stores the key, version and fingerprint of both stages in `prompt_versions`, together with the other data required by SRS Step 49 (Table 22.4). For complaint CMP-00616 (fictional data) the stored value is:

```json
{
  "analysis": {"key": "complaint_analysis", "version": "1.2.0",
               "sha256": "428c297c112322b45fb08b033ce715f87b3009f2110fe3092537b2b7cfc4008f"},
  "communication": {"key": "customer_communication", "version": "1.0.0",
                    "sha256": "908eec6961cdbcbafa37423515b5f4503d83e5152be2679087640d25cd2474ff"}
}
```

Each model call is logged separately in `ai_runs` with `prompt_key`, `prompt_version` and, inside the request metadata, `prompt_sha256`, so that even a stage that needed several attempts shows which template every attempt used. The audit entry `complaint.processed` repeats the prompt versions with provider, model, policy versions and ruleset hash in its hash-chained details (Chapter 37). Evaluation runs store the active versions at the start of the run in `evaluation_runs.prompt_versions` (run 1 on the holdout set: `{"complaint_analysis": "1.2.0", "customer_communication": "1.0.0"}`), which makes runs with different prompt versions comparable. The case report PDF prints the same information in its traceability section (`reporting/exports.py`), and the API exposes it through `GET /api/v1/complaints/{ref}/analyses`, `GET /api/v1/complaints/{ref}/ai-runs` and `GET /api/v1/ai/runs`.

**Table 22.4 — Where the data required by SRS Step 49 is stored**

| SRS Step 49 item | Stored in | Value for CMP-00616 |
|---|---|---|
| Prompt version | `analyses.prompt_versions`; `ai_runs.prompt_key`, `prompt_version`, `request.prompt_sha256` | `complaint_analysis` 1.2.0, `customer_communication` 1.0.0 |
| GenAI provider | `analyses.provider`; `ai_runs.provider` | `openai` |
| Model | `analyses.model`; `ai_runs.model`; served model in `ai_runs.request.served_by` | `gpt-4.1-mini` (served `gpt-4.1-mini-2025-04-14`) |
| Analysis timestamp | `analyses.created_at`, `completed_at`; `ai_runs.created_at` | 2026-09-24 20:11:58 to 20:12:24 (UTC+05:00) |
| Policy version | `analyses.policy_versions` (document and version of each evidence item) | ESC-SOP-12 3.1, INS-POL-24 1.0, SEC-POL-09 2.0, STF-POL-21 1.0, TEC-GDL-20 3.0, WAR-POL-07 2.0 |

In the demo database all 780 analyses record `complaint_analysis` 1.2.0 and `customer_communication` 1.0.0 with their fingerprints, and all 1,591 logged model calls (789 analysis, 802 communication) carry the key, version and fingerprint of the template they used. The analyses produced with versions 1.0.0 and 1.1.0 belonged to earlier databases, including the baseline of the A/B run, and are not part of the demo database.

## 22.6 Creating, Activating and Rolling Back Versions

Prompt versions are managed on the **Prompts & AI** page (Figure 22.2) or through the API. The page lists the versions of each family with status, changelog and creation date, shows the selected version's output schema, parameters, fingerprint (with a copy button), system and user templates and placeholders, and checks that `$complaint` and `$nonce` are present. **New version** opens a form pre-filled from the selected version; the new version is saved as a draft unless "Activate immediately" is ticked. **Activate vX** appears for every version that is not active and asks for confirmation with the text "The active version vX will be retired. New AI calls use this version right away; past analyses keep the version they used." Table 22.5 lists the operations.

![Figure 22.2 — Prompts & AI page with the versions of complaint_analysis](../screenshots/19-prompts-and-ai.png)
*Figure 22.2 — Prompts & AI page with the versions of complaint_analysis*

**Table 22.5 — Prompt management operations**

| Operation | API | Permission | Validation and audit |
|---|---|---|---|
| List prompts and versions | `GET /api/v1/prompts` | `rules:read` (agent, reviewer, manager, administrator) | — |
| Create a version | `POST /api/v1/prompts/{key}/versions` | `prompts:manage` (administrator) | Semantic version, unique per key, system template at least 50 and user template at least 20 characters, a changelog, `$complaint` and `$nonce` required; audit `prompt.version_created` with fingerprint and changelog |
| Activate a version (including rollback) | `POST /api/v1/prompts/{key}/versions/{version}/activate` | `prompts:manage` | Previous active version retired; audit `prompt.activated` with the previously active versions |

**Rollback** is activation of an older version. It takes effect for the next GenAI call without a restart or deployment, it does not change any past analysis (each keeps the version and fingerprint it recorded), and it survives restarts because seeding never overwrites a version that is already in the database. A rollback is undone the same way, by activating the newer version again. The role restriction is enforced server side and tested for the list endpoint (`tests/backend/api/test_security_api.py::test_role_permission_matrix_enforced_server_side[/prompts-allowed10]`); customers cannot see prompts at all.

## 22.7 Testing of Prompt Versions

Prompt versions are tested at three levels. The automated suite (206 backend tests, Chapter 33) runs every GenAI call through the offline test double in `tests/support/offline_llm.py`, which parses the rendered prompt of the active version, including the nonce-tagged complaint element and the reference blocks, so a template change that breaks the placeholders or the element structure breaks the integration and end-to-end tests (`tests/e2e/test_full_chain.py::test_complete_complaint_chain`). The behavioural effect of a prompt change can only be measured with the real model; for 1.2.0 this was the A/B run of Table 22.2, and evaluation runs record the prompt versions so that runs before and after a change can be compared on the same labelled dataset. The version lifecycle itself (creation, activation, retirement by seeding and rollback) is **Implemented** but not covered by a dedicated automated test; only the permission check of the list endpoint is tested.

## 22.8 Limitations

Four limitations of the versioning scheme are recorded. The fingerprint covers the templates but not the parameters or the output schema, so two versions that differ only in temperature share a fingerprint and are distinguished by their version label. The corrective retry message is defined in code and is not versioned with the prompts (Section 22.2). The create endpoint does not check that `output_schema` names an existing schema; a version pointing to an unknown schema would make every analysis of that stage fail into manual review until an administrator activates a correct version. And the evidence for the 1.2.0 improvement is held in the commit message rather than in an exported report. None of these affects the traceability of the recorded analyses, which all used the two active versions listed in Appendix K.

**Table 22.6 — Status of the prompt versioning requirements**

| Requirement | Status | Evidence |
|---|---|---|
| Prompts centrally stored and versioned (Step 48, 1.6 lii) | Implemented | `prompts/`, `prompt_versions`, `seed_prompts` |
| Prompt version logged per analysis (Step 49, 1.6 liii) | Implemented, Tested | `analyses.prompt_versions`, `ai_runs`; `test_complete_complaint_chain` reads the AI runs |
| Provider, model, timestamp and policy version per analysis (Step 49) | Implemented | Table 22.4 |
| Active and retired versions, audited activation, rollback | Implemented | `activate_version`, Prompts & AI page; no dedicated automated test |
| Prompt versions as a deliverable (1.10, items 6 and 19) | Implemented | `reports/genai_pipeline_evidence/prompt_templates_and_versions.json`, Appendix K |
