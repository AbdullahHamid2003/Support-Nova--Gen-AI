# Appendix K — Prompt Version Record

This appendix records every prompt version held by SupportNova: the two prompt families `complaint_analysis` and `customer_communication`, their four versions, status, output schema, generation parameters, SHA-256 fingerprints and changelogs, and how each version was used in the demo database. The values are read from the `prompt_versions` table of the demo database and compared with the files in `prompts/`; Chapter 22 explains the versioning process.

## K.1 Version Record

**Table K.1 — Prompt versions**

| Key | Version | Status | Output schema | Parameters | File |
|---|---|---|---|---|---|
| `complaint_analysis` | 1.0.0 | retired | `complaint_analysis.v1` | temperature 0.1, max_output_tokens 6000 | `prompts/complaint_analysis/1.0.0.yaml` |
| `complaint_analysis` | 1.1.0 | retired | `complaint_analysis.v1` | temperature 0.1, max_output_tokens 6000 | `prompts/complaint_analysis/1.1.0.yaml` |
| `complaint_analysis` | 1.2.0 | active | `complaint_analysis.v1` | temperature 0.1, max_output_tokens 6000 | `prompts/complaint_analysis/1.2.0.yaml` |
| `customer_communication` | 1.0.0 | active | `customer_communication.v1` | temperature 0.3, max_output_tokens 2500 | `prompts/customer_communication/1.0.0.yaml` |

## K.2 Fingerprints

The fingerprint is the SHA-256 of the system template, a separator line `---` and the user template, computed as `sha256(system_template + "\n---\n" + user_template)` (`PromptTemplate.sha256` in `backend/src/supportnova/genai_pipeline/prompts.py`). For each version, the value stored in the database equals the value recomputed from the YAML file, and the stored templates equal the file templates.

**Table K.2 — SHA-256 fingerprints and template sizes**

| Key and version | SHA-256 fingerprint (database) | Equals file | Template sizes (system, user) |
|---|---|---|---|
| `complaint_analysis` 1.0.0 | `37247a83c9d0a2bbba6d34d204476330254a671a2181bef05fb11a901a3ed804` | yes | 4,874 and 257 characters |
| `complaint_analysis` 1.1.0 | `a2df8a7e77df7225bb27e47b3ef285f61c0cd0f474cd9df8b7c037e337d0b77e` | yes | 5,147 and 257 characters |
| `complaint_analysis` 1.2.0 | `428c297c112322b45fb08b033ce715f87b3009f2110fe3092537b2b7cfc4008f` | yes | 6,501 and 257 characters |
| `customer_communication` 1.0.0 | `908eec6961cdbcbafa37423515b5f4503d83e5152be2679087640d25cd2474ff` | yes | 2,549 and 429 characters |

## K.3 Changelog Summaries

The full changelogs are stored with each version (`prompt_versions.changelog`) and shown on the Prompts & AI page; version 1.2.0 repeats the 1.1.0 entry below its own. Table K.3 summarises them.

**Table K.3 — Changelog summaries**

| Key and version | Changelog summary |
|---|---|
| `complaint_analysis` 1.0.0 | Initial version: role and proposal framing, three trust boundaries, eleven analysis rules, reference blocks (taxonomy, departments, action catalogue, escalation levels, urgency and priority, follow-up types), nonce-tagged user template. |
| `complaint_analysis` 1.1.0 | Rule 1 states which code goes where (category code in issue_category, full subcategory code in subcategory) after a live run put a subcategory code in issue_category; rule 12 asks for brief text to cut response time; the request schema restricts every code field to the live catalogue. |
| `complaint_analysis` 1.2.0 | Routing policy RTE-RUL-14 sections 3-5 supplied as reference data (routing was the most frequent critical mismatch and was retrieved for 6% of complaints); complete, ordered resolution steps with the escalation action per level; supervisor triggers named; urgency guide adds SLA-RUL-15 section 5. |
| `customer_communication` 1.0.0 | Initial version: reply written only from the validated decision, eligibility wording rules, supported timelines only, safety and credential rules, tone definitions, nonce-tagged complaint. |

## K.4 Creation, Activation and Use

All four versions were inserted by one seeding run from the files in `prompts/`, so they share one creation time and have no creating user. Because `complaint_analysis` 1.0.0 and 1.1.0 were loaded with the status `retired` written in their files and 1.2.0 was loaded as the first active version, no activation took place in this database, and it contains no audit entries for prompts. Activation dates are therefore not recorded for the demo database; in a database where a version is activated through the Prompts page, the API or seeding over an existing active version, the audit log records the entry `prompt.activated` with the time, the actor and the previously active versions.

**Table K.4 — Creation and use of each version in the demo database**

| Key and version | Created (UTC+05:00) | Activation recorded | AI calls logged | Analyses recording it | First and last use (UTC+05:00) |
|---|---|---|---|---|---|
| `complaint_analysis` 1.0.0 | 2026-09-24 19:32:17, seeded from file | seeded as retired; never active in this database | 0 | 0 | not used in this database |
| `complaint_analysis` 1.1.0 | 2026-09-24 19:32:17, seeded from file | seeded as retired; never active in this database | 0 | 0 | not used in this database |
| `complaint_analysis` 1.2.0 | 2026-09-24 19:32:17, seeded from file | seeded as active; no audit entry needed | 789 | 780 | 2026-09-24 19:32 to 2026-09-24 23:33 |
| `customer_communication` 1.0.0 | 2026-09-24 19:32:17, seeded from file | seeded as active; no audit entry needed | 802 | 780 | 2026-09-24 19:32 to 2026-09-24 23:33 |

Evaluation runs record the versions active at their start in `evaluation_runs.prompt_versions`: run 1 on the holdout set (completed, 154 cases) and run 2 (cancelled after 6 cases) both record `{"complaint_analysis": "1.2.0", "customer_communication": "1.0.0"}`. The analyses produced with `complaint_analysis` 1.0.0 and 1.1.0, including the baseline of the A/B comparison described in Chapter 22, were made in earlier databases and are not part of the demo database.
