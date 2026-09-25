# Chapter 45 — Conclusion

## 45.1 The Problem and the Approach

The SRS describes a support organisation that must read every complaint, decide what it is about, how urgent it is, which department owns it, which policy applies, what the customer is entitled to, whether it must be escalated and what to say to the customer, and must do this consistently and with an audit trail. A generative model can read a complaint and draft all of these answers, but it can also misread urgency, cite a policy that does not apply, promise a refund the policy does not allow, miss a mandatory escalation or follow instructions hidden in the complaint text. SupportNova addresses this by separating proposal from decision. The GenAI Complaint Intelligence Pipeline produces a structured analysis and a customer response; the Python Ground-Truth Validation Pipeline checks that analysis, independently, against the Complaint Resolution Rule Matrix and the approved Knowledge Base; the validated decision, not the AI proposal, is what the organisation acts on; and cases the checks cannot confirm are decided by a person. The principle is carried through the whole implementation: GenAI proposes. Python validates. Ground truth decides.

## 45.2 What Was Built

SupportNova is a working web application for the fictional Lumora Home Technologies: a FastAPI backend in Python 3.14, a React 19 and TypeScript frontend, and a PostgreSQL 17 database of 35 tables managed through Alembic migrations, exposed through 95 role-protected REST endpoints (Chapters 4, 25 and 26). Its main parts are the following.

The **Knowledge Base** holds 24 policy, SOP, guideline, FAQ, rule and template documents in 29 versions, in PDF, DOCX and Markdown, parsed into sections and 484 chunks with version status, effective dates, supersession and precedence, so that only active and approved content is used as evidence and outdated versions are shown only as context (Chapters 5 and 9).

The **Complaint Resolution Rule Matrix** encodes the decision criteria as 276 rule rows — 116 resolution rules, 39 escalation rules, 35 routing rules, 6 conditional routing rules, 15 urgency floors, 35 category rules and the missing-information, follow-up, SLA and review rules — together with 59 parameters, 35 signals and six escalation levels. The rules are stored in the database, edited through the application, previewed before saving, versioned and audited (Chapter 10). The Knowledge Base supplies the evidence; the Rule Matrix supplies the criteria; the two are linked through the policy references carried by every rule.

The **GenAI Complaint Intelligence Pipeline** calls the configured provider (OpenAI `gpt-4.1-mini` for all recorded runs, with Anthropic and Gemini adapters selectable by configuration) with versioned prompts, strict JSON schemas whose enumerations come from the live catalogs, source-grounded evidence and screened, PII-redacted complaint text, and it retries in a controlled way when the output is invalid (Chapters 8, 21 and 22). Without a configured key it reports that no AI output exists; it never fabricates one.

The **Python Ground-Truth Validation Pipeline** runs 52 deterministic checks in 12 dimensions — schema, classification, routing, priority, policy, resolution, eligibility, escalation, follow-up, communication, grounding and security — and combines them into a weighted verification score and a decision of Verified or Manual Review, with 14 manual-review triggers (Chapters 11 to 18). The **Comparison Engine** shows the AI and rule outcomes field by field in the "AI vs rules" view, so an agent or reviewer can see why a case was held (Chapter 12).

Around these pipelines the application provides customer, agent, reviewer, manager and administrator workspaces, a manual-review queue with approve, modify, reclassify and regenerate actions, SLA tracking and follow-ups, duplicate and repeat detection, dashboards, analytics and exportable reports, an adversarial lab and an append-only, hash-chained audit log (Chapters 19, 20, 27, 37 and 38).

## 45.3 What the Evidence Shows

The system was run end to end with the real model. All 780 recorded analyses completed with genuine AI output; the 31 failed attempts during those runs were recovered by retries. On the 154 unseen holdout cases the Python pipeline caught 92 of the 93 AI answers that contained a key-field error (98.9 %) — either the rules supplied the correct value or the case went to manual review — detected all 6 prompt injections with no false positives, linked both duplicates and all four repeat complaints, and reached 82.7 % key-field accuracy against the expected labels, compared with 79.2 % for the AI alone. The 18 adversarial lab scenarios — prompt injection, fake and invalid policies, unsupported refunds and compensation, sensitive data and deliberate AI defects — were all caught. The automated test suite of 206 backend tests and 12 frontend tests passes, including on a fresh clone of the repository (Chapters 33 and 34).

The same evidence shows the costs of the design. The validation pipeline is deliberately conservative, so 84.4 % of holdout cases went to manual review against 33 % expected; the validated decision is ready at p50 16.2 s, but the full pipeline including the response draft takes p50 21.7 s, above the 20-second target; the scale requirements have been designed for but not load-tested; and the application is not yet publicly deployed. These points, and the remaining limitations of retrieval, lexical checks and synthetic data, are recorded in Chapter 43 rather than hidden, and Chapter 44 describes realistic ways to address them.

## 45.4 Value for a Support Organisation

For a support organisation the value of SupportNova lies less in the drafting speed of the model than in what surrounds it. Every recommendation arrives with the policy sections it relies on, the rules that were applied and the checks that passed or failed. Mandatory escalations and critical routing rules are enforced by Python before a case can be verified, which is what SRS NFR 4 requires, so a model error on a safety, security or privacy complaint does not reach the customer. Customer responses are written from the validated decision, checked for unsupported promises and released only by an authorised person. Policies and rules can be changed by administrators, with impact analysis, previews and an audit trail, without changing code. The result is a system in which the model saves reading and writing effort while accountability stays with the organisation's own rules and people.

## 45.5 SRS Requirements Satisfied

Table 45.1 summarises how the submitted system stands against the main SRS requirement groups. Appendix A traces each requirement to its implementation, report section and verification, and Appendix O lists the report completeness audit and the open gaps.

**Table 45.1 — Status of the main SRS requirement groups**

| SRS requirement group | Where it is met | Status |
|---|---|---|
| Web application with role-based workspaces | Chapters 24 and 27 | Implemented, Tested |
| Knowledge-base upload, validation, versioning and retrieval | Chapters 5 and 9 | Implemented, Tested |
| GenAI analysis with structured JSON output and controlled retries | Chapters 8, 21 and 22 | Implemented, Tested |
| Independent Python ground-truth validation and comparison | Chapters 11 and 12 | Implemented, Tested |
| Routing, urgency, priority, resolution, eligibility, escalation, follow-up and SLA | Chapters 13 to 15, 18 and 19 | Implemented (Configured through the Rule Matrix), Tested |
| Customer response generation and unsupported-promise checks | Chapters 16 and 17 | Implemented, Tested |
| Prompt-injection protection and security controls | Chapters 23, 24 and 34 | Implemented, Tested |
| Duplicate and repeat complaints | Chapter 20 | Implemented, Tested |
| Manual review, audit trail, dashboards and reports | Chapters 37 to 39 | Implemented, Tested |
| Complaint dataset (617 development and 154 holdout cases) | Chapter 6 | Implemented |
| Performance within 20 seconds (NFR 1) | Chapters 35 and 43 | Partly met: validated decision p50 16.2 s (80.8 % within 20 s); full pipeline with the response draft p50 21.7 s |
| Scale of 10,000 complaints and 1,000 documents (NFR 2) | Chapters 35 and 43 | Designed; not load-tested |
| Public deployment and 99 % availability (NFR 5) | Chapters 40 and 43 | Planned (Render blueprint prepared) |
| Demonstration video, technical blog and team contribution record | Appendix O | Not yet produced |

SupportNova therefore meets the functional requirements of the SRS with measured, reproducible evidence, and it states openly where the non-functional targets and the remaining submission items are not yet met.
