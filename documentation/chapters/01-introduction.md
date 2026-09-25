# Chapter 1 — Introduction

This chapter explains why SupportNova was built and what it is meant to achieve. It sets out the background and the specific problems named in the SupportNova Software Requirements Specification (SRS, Version 1.0), describes the solution that was implemented, and defines the purpose, objectives, scope and constraints that the rest of the report refers to. Chapter 2 turns the SRS into a list of traceable requirements. Chapters 3 to 45 describe how each part of the system works and how it was tested.

## 1.1 Background and Necessity

Organisations receive large numbers of customer complaints through e-mail, web forms, chat, messaging platforms and customer-service portals. The complaints concern product defects, billing problems, delivery delays, service failures, refund requests, account issues, technical problems, poor service experiences and urgent safety concerns (SRS 1.1). SupportNova was built for Lumora Home Technologies, a fictional consumer-electronics and smart-home company created for this project. Lumora sells 15 products and services, ranging from the Aura Smart Thermostat, the Sentinel cameras, the Keystone Smart Lock and the PowerCell Portable Power Station to the Care+ Protection Plan, the Cloud Vault subscription and the Pro Install service. It accepts complaints through seven channels: web form, e-mail, live chat, transcribed phone calls, the mobile app, social media and uploaded letters. Its complaint taxonomy has 11 categories, the same issue types listed in SRS Step 12 (Product Defect, Billing, Delivery, Refund, Account, Technical Support, Service Quality, Warranty, Privacy, Safety and Staff Behavior), divided into 35 subcategories. Ten departments, from Billing Operations to Product Safety and Management Escalations, own the resulting work. All customers, orders, policies and complaints are simulated, as the disclaimer in `config/organization.yaml` states.

In traditional complaint handling an agent reads each complaint, identifies the issue, judges its urgency, chooses a department, looks up the relevant policies, writes a response, decides whether to escalate and records a follow-up. The SRS observes that this is slow and produces inconsistent classification, delayed routing, inappropriate responses, missed escalations and incomplete resolutions. At Lumora each of these steps depends on detailed and changing policy. The Knowledge Base holds 24 policy documents in 29 versions, and several superseded versions contradict the active ones. The superseded Refund Policy REF-POL-02 v1.0 allowed returns for 60 days, while the active v2.0 allows 30 (parameter `refund_window_days` = 30, REF-POL-02 §3.1). The legacy Returns Handling SOP RET-SOP-23 v1.4 let agents issue a USD 50 goodwill credit, while the active Compensation and Goodwill Policy limits an agent to USD 25 (CPN-POL-11 §5.1). An agent who remembers the old figure, or a customer who quotes it, can easily produce a wrong answer.

Some complaints are also dangerous even though they are written calmly, while others are furious about something minor. "No rush, but my PowerCell got very hot and hissed while charging in my son's room" describes a battery hazard that Lumora's rules classify as Critical, priority P0, with a mandatory safety escalation. "WORST APP EVER!!! The dark mode colours are awful!!!" is a minor app complaint, and because tone never raises priority it keeps the priority of an ordinary app issue. A triage process that reacts to tone will get both wrong. Safety, account security, privacy, legal threats, high-value disputes and repeated unresolved complaints must all be escalated, and a missed escalation is the most harmful error an agent can make.

Generative AI can read free text, summarise it and draft a reply within seconds, which makes it attractive for this work. It is not reliable enough to be trusted on its own. In the evaluation reported in Chapter 12, the model used by SupportNova (OpenAI gpt-4.1-mini) got at least one of six key decision fields wrong in 93 of 154 unseen complaints. Because the model reads the customer's own words, it is also exposed to instructions planted in a complaint (Chapter 23). The SRS therefore requires an application that is secure, reliable and traceable, that reduces manual triage and improves routing consistency, and that prevents unsupported or inappropriate GenAI responses (SRS 1.1). It requires two separate pipelines: a GenAI pipeline that analyses the complaint and drafts communication, and an independent Python Ground-Truth Validation Pipeline that checks the result against predefined business rules and approved organisational knowledge.

## 1.2 Problem Definition

The SRS background, the Step 21 priority traps and the competition challenges in SRS 1.8 describe nine concrete problems. Table 1.1 lists them, explains what goes wrong when complaints are handled manually or by an unchecked model, and names the SupportNova mechanism that addresses each one.

**Table 1.1 — Problems addressed by SupportNova**

| Problem | What goes wrong | SupportNova mechanism | Chapter |
|---|---|---|---|
| Manual classification | Every complaint must be read and labelled; labels vary between agents | Pipeline 1 proposes category and subcategory from the configured taxonomy (11 / 35); a Python keyword-and-signal classifier (35 category rules) checks them (CLS-001, CLS-002) | 8, 11 |
| Incorrect routing | The complaint waits in the wrong queue | 35 routing rules and 6 conditional routing rules decide the primary department; RTE-001 is a critical check and RTE-002 checks supporting departments | 13 |
| Delayed escalation | Safety, security, privacy or legal cases reach the right team late or never | 39 escalation rules over six levels; a missing required escalation fails the critical check ESC-001 and Python creates the escalation itself; P0/P1 SLA breaches escalate under ESC-039 | 18, 19 |
| Policy inconsistency | Superseded or conflicting policy text is quoted | Versioned Knowledge Base (Active, Previous, Superseded, Draft), precedence rules PRC-001 to PRC-005, checks POL-002 and POL-006 | 5, 9 |
| Unsupported responses | Replies promise refunds, compensation, exceptions or deadlines that policy does not allow | The response is written from the validated decision; RSP-002, RSP-003 and RSP-006 flag unsupported promises, timelines and prohibited statements | 16, 17 |
| Missing resolution actions | Required steps (verification, safety advice, notifications) are skipped | Resolution rules list required, recommended and prohibited actions from a 66-action catalogue; checks RES-001 to RES-004 | 15 |
| Lack of traceability | Nobody can show why a decision was made or which source supports it | Each analysis stores prompt versions and hashes, provider, model, policy versions and ruleset hash; every AI call and check result is stored; the audit log is append-only and hash-chained | 22, 37 |
| Repeat complaints | Resubmissions open new cases and unresolved repeats are not escalated | Exact-duplicate hashing, near-duplicate similarity and repeat detection over a 90-day window; ESC-017 to ESC-019 raise the escalation level | 20 |
| SLA risk | Deadlines are noticed only after they have passed | Four SLA rules by priority (from P0: 1 h first response, 24 h resolution, to P3: 48 h, 240 h); a monitor flags At Risk at 75% of the window | 19 |

These nine problems share one cause. A complaint is unstructured, untrusted text, but the decisions it requires are structured, policy-bound and sometimes safety-critical. Stated as an engineering problem, SupportNova must turn such text into a structured decision and a customer response that are correct under the organisation's approved rules and traceable to their sources. The result must stay safe when the GenAI model is wrong or is being manipulated, and it should be available in about 20 seconds (NFR-1). The SRS states the minimum standard directly: "merely sending complaint text to a Generative AI API and displaying the generated response will not satisfy the project requirements" (SRS 1.6).

## 1.3 Proposed Solution

SupportNova is a web-based complaint-intelligence application with a Python backend (FastAPI 0.141.1, SQLAlchemy 2.0, Alembic, PostgreSQL 17) and a React 19 and TypeScript frontend. Its design follows one principle: **GenAI proposes. Python validates. Ground truth decides.** Figure 1.1 shows how the problems of Section 1.2 lead to the dual-pipeline design.

![Figure 1.1 — SupportNova at a glance](diagrams/architecture/fig-01-01-supportnova-at-a-glance.svg)
*Figure 1.1 — SupportNova at a glance*

Two bodies of approved knowledge sit underneath both pipelines. The **Knowledge Base** stores Lumora's policies, SOPs, guidelines, FAQs, rule documents and templates: 24 documents in 29 versions (13 PDF, 15 DOCX and one Markdown file). Uploads are validated, parsed into sections and split into 484 chunks, each identified as `<DOC_ID>@<version>#<section>-c<n>` and carrying heading and page references. Only Active versions within their effective and expiry dates can be used as evidence, and the precedence rules in `rules/precedence/precedence_rules.yaml` settle conflicts: policies and rule documents rank above SOPs, SOPs above guidelines, guidelines above FAQs and FAQs above templates, and within one type the most recent effective date prevails. The **Complaint Resolution Rule Matrix** holds the decision criteria as version-controlled YAML in `rules/`. It is loaded into the database, where administrators can edit it with validation, versioning and audit. It contains 276 rule rows: 116 resolution rules, 39 escalation rules, 35 routing rules, 6 conditional routing rules, 15 urgency floors, 35 category rules, 8 missing-information rules, 4 follow-up rules, 4 SLA rules and 14 manual-review rules, plus 59 parameters and 35 risk and intent signals. The Knowledge Base provides evidence and the Rule Matrix provides decision criteria. They are related, since every rule cites the policy sections it implements, but they are not the same thing.

When a complaint arrives, Python first normalises the text, screens it for prompt injection, redacts personal data, extracts entities and signals, and looks up the order in the simulated order ledger and the customer's complaint history. The retrieval step then selects the relevant active policy sections by combining BM25 lexical search with vector similarity and adding the sections the Rule Matrix cites for the likely subcategories. The **GenAI Complaint Intelligence Pipeline (Pipeline 1)** sends the complaint, the verified facts and this evidence to OpenAI gpt-4.1-mini with the versioned prompt `complaint_analysis` 1.2.0. It receives a structured analysis that must satisfy the 37-field JSON schema `complaint_analysis.v1`. The model's strict structured-output mode restricts every code field to the live catalogue of categories, departments, actions and policies. An answer that still fails validation is sent back to the model with the errors, up to two retries. Anthropic and Google Gemini adapters are available through the same provider interface and are selected by configuration (`AI_PROVIDER`, `AI_MODEL`).

The **Python Ground-Truth Validation Pipeline (Pipeline 2)** is written separately and never calls a model. From the detected signals, the order facts, the complaint history and the Rule Matrix it computes its own expected decision: classification, department, urgency and priority, required and prohibited actions, eligibility, escalation, follow-up and missing information. It then checks the AI's answer against that decision and against the Knowledge Base, using 52 checks in 12 dimensions from schema and classification to grounding and security. The **Comparison Engine** records each field side by side, and the user interface presents it as "AI vs rules". Where the AI and the rules disagree, the rules decide. The result is the validated decision, from which a second GenAI call (prompt `customer_communication` 1.0.0) writes the customer response and follow-up message. Python then checks that text for missing elements, unsupported promises, unsupported timelines, amounts that cannot be traced, wrong tone and sensitive data.

The verification score is computed only from the check results, never from a confidence reported by the model. It weights each check by severity (critical 5, major 3, minor 1) and by status (pass 1, warn 0.5, fail 0). A case is **Verified** when no critical check has failed, the score is at least 80 and none of the 14 manual-review triggers has fired. Otherwise it enters the **manual review** queue with its reasons listed. Reviewers can approve, reject, modify, reclassify, reassign, escalate, regenerate the response or comment, and the original recommendation and the final decision are both stored. Python also records the escalation, the scheduled follow-up and the SLA deadlines. Role-based dashboards, trend alerts, ten report types with PDF, Excel and CSV export, an evaluation runner for unseen datasets and an adversarial lab complete the system. Chapters 3 and 4 describe the components and the architecture in detail.

## 1.4 Purpose

SupportNova has two purposes. The first is operational: to reduce the manual effort of complaint triage for Lumora's support teams while making routing, prioritisation, escalation and resolution consistent with approved policy. In one processing run, every complaint receives a structured analysis, a validated decision, a draft response, and the escalation, follow-up and SLA deadlines that its rules require. The second purpose is assurance: to make Generative AI safe to use in a process where mistakes have consequences. Every AI proposal is checked by an independent deterministic pipeline and every disagreement is visible. Every decision can be traced to the prompt, model, policy versions and rules that produced it.

This report documents how both purposes were achieved and where they were not. In line with SRS 1.3, it is written for the project stakeholders and developers, the evaluators, and the customer-service teams, support managers, administrators and complaint-resolution specialists who would operate the system. It serves as the design description, the implementation record and the evidence base: Chapter 2 and Appendix A trace every SRS requirement to the module that implements it and to the test or recorded run that verifies it.

## 1.5 Objectives

The objectives in Table 1.2 are derived from the SRS. Each is stated so that its achievement can be checked against measured evidence.

**Table 1.2 — Objectives derived from the SRS**

| ID | Objective | SRS basis | Evidence (chapter) |
|---|---|---|---|
| O-1 | Produce structured complaint intelligence for every complaint: issue, category, subcategory, sentiment, urgency, priority, entities, department, escalation, resolution, response | 1.1, 1.2, 1.4 | 37-field schema; per-field accuracy on 154 unseen cases (8, 12) |
| O-2 | Validate every GenAI field in Python against the Rule Matrix and approved policy versions, never using GenAI to approve GenAI | 1.2 Pipeline 2; 1.6 (xlv) | 52 checks; 92 of 93 AI key-field errors caught (11, 12) |
| O-3 | Enforce mandatory escalation and critical routing before a case can be verified | 1.7 (4); 1.8 (7); Step 39 | ESC-001 and RTE-001 are critical checks; fault-injection tests (13, 18) |
| O-4 | Ground recommendations and responses in active, approved policy sections with valid references | Steps 25-27; 1.6 (l) | Evidence from Active chunks only; POL-001 to POL-006 (9) |
| O-5 | Generate professional, tone-controlled responses and follow-ups without unsupported promises | Steps 32-34, 40 | RSP-001 to RSP-007; only ready or approved responses can be sent (16, 17) |
| O-6 | Treat complaints and documents as untrusted data and withstand prompt injection | Steps 50-51; 1.8 (8) | 6 of 6 holdout injections detected; 18 of 18 lab scenarios (23, 34) |
| O-7 | Route uncertain, sensitive or conflicting cases to a human and keep both the original and the final decision | Steps 57-59 | 14 review triggers; review snapshots; audit chain (11, 37) |
| O-8 | Track follow-ups, SLA deadlines, duplicates and repeat complaints | Steps 41, 52-56 | Follow-up and SLA records; duplicate and repeat tests (19, 20) |
| O-9 | Give each role a dashboard, analytics, trend alerts, reports and exports | Steps 61-68 | Role dashboards; ten report types in PDF, XLSX, CSV (38, 39) |
| O-10 | Process unseen complaints, new categories and revised policies through configuration rather than code changes | Hidden evaluation; 1.8 (3)-(5), (14) | New-category and revised-policy tests; hidden-dataset upload (42) |
| O-11 | Return an initial validated recommendation within 20 seconds and scale to the SRS volumes | 1.7 (1), (2) | p50 21.7 s measured, target not met; scale not load-tested (35) |

## 1.6 Scope

### 1.6.1 In scope

SupportNova implements every area the SRS makes mandatory. Table 1.3 summarises the scope. The requirement-level detail is in Chapter 2, and the status of each item is in Appendix A.

**Table 1.3 — Scope of SupportNova**

| Area | Included in SupportNova | SRS basis |
|---|---|---|
| Organisation and data | Fictional Lumora Home Technologies; 617 development and 154 holdout complaints; 300 customers; a 594-order simulated ledger | Step 1; Hint; 1.10 (3) |
| Knowledge Base | Upload, validation, parsing (PDF, DOCX, Markdown, TXT, CSV), chunking, version control, conflict detection, revision impact analysis | Steps 2-7; 1.8 (4) |
| Rule Matrix | 276 rule rows and 14 configuration rows, editable with validation, versioning and audit; a simulator previews edits | Step 8; 1.8 (14); 1.10 (5) |
| Complaint intake | Web submission with all SRS complaint fields and attachments, validation, normalisation, duplicate and repeat detection, complaint history | Steps 9-11, 52-54 |
| Pipeline 1 | Structured analysis and customer communication through OpenAI gpt-4.1-mini, with Anthropic and Gemini adapters, versioned prompts, JSON schemas and bounded retries | 1.2; Steps 12-49 |
| Pipeline 2 | Deterministic decision engine, 52 checks, comparison, verification score, manual-review triggers | 1.2; Steps 23-47; 1.6 (xlv)-(li) |
| Operations | Routing, escalation over six levels, follow-ups, SLA tracking, the complaint status lifecycle, manual review | Steps 22-24, 36-41, 55-60 |
| Security | Authentication, five-role RBAC, prompt-injection screening, redaction of personal data, upload validation, hash-chained audit log | 1.5; 1.6 (i), (ii), (liv), (lv) |
| Insights | Role dashboards, analytics, trend alerts, search and filtering, ten report types, PDF, Excel and CSV export | Steps 61-68 |
| Quality evidence | Evaluation runs on unseen and uploaded datasets, an adversarial lab, 206 backend and 12 frontend tests, evidence reports | 1.10 (6)-(11) |
| Delivery | This report, installation and execution instructions, Docker and Render configuration, screenshots | 1.10 (1), (12)-(15) |

### 1.6.2 Out of scope

SRS 1.4 places direct integration with live enterprise CRM applications, payment gateways, banking applications, commercial call-centre platforms and production Zendesk environments outside the mandatory scope. SupportNova therefore connects to none of them. Order and transaction facts come from a simulated ledger (`data/sample_complaints/orders.json`, loaded into the `orders` table), which Python uses to check order ownership, delivery dates and refund windows. Refunds, replacements and credits are recommended and recorded as validated resolution steps, but they are never executed against a payment system. Phone complaints arrive as transcribed text. When an agent sends an approved response, SupportNova records the send and the customer's preferred contact method in the application (`customer_responses.sent_via`); there is no e-mail or SMS gateway, which the SRS does not require. Real customer data is excluded by SRS Step 1, so every record in the system is fictional.

Some deliverables are incomplete but they are not out of scope. The public deployment, the demonstration video and the technical blog are mandatory under SRS 1.10 and are not yet produced. Their status is reported in Chapter 40 and Appendix A.

## 1.7 Constraints

The SRS imposes technical, organisational and competition constraints (SRS 1.5, 1.8, 1.9 and 1.10). Table 1.4 lists them together with the design decision each one led to.

**Table 1.4 — Constraints and how SupportNova responds**

| Constraint | SRS source | How SupportNova handles it |
|---|---|---|
| Python implementation with an approved GenAI API | 1.2; 1.9.2 | Python backend (FastAPI); OpenAI gpt-4.1-mini by default through a provider abstraction with Anthropic and Gemini adapters, selected by `AI_PROVIDER` and `AI_MODEL` |
| Fictional organisation, no real customer data | Step 1; 1.8 (1), (2) | Lumora and all its customers, orders and complaints are synthetic; the dataset is generated reproducibly by `scripts/generate_dataset.py` from a scenario bank |
| Results depend on the quality of complaints and policies | 1.5 ¶1 | Complaint and document validation, eight missing-information rules (MIS-001 to MIS-008), policy conflict detection, manual review when evidence is missing |
| Model behaviour, prompt quality, context limits and API availability | 1.5 ¶2 | Strict JSON schema restricted to live code catalogues, versioned prompts, 60 s timeout, at most two retries, an explicit "not configured" state without a key; the 31 failed calls in the demo run were all recovered by retries |
| Wording varies between runs and AI and rules may disagree | 1.5 ¶3 | Temperature 0.1 for analysis; the comparison works on structured fields, not free text; every disagreement is shown in the AI vs rules view |
| Generated content must be verified before approval | 1.5 ¶4 | Pipeline 2 checks every analysis and every draft; only responses with status ready or approved can be sent, and a reviewer must approve the rest |
| Privacy, security, confidentiality, API cost, data protection, access control, secure storage | 1.5 ¶4 | Personal data redacted before any GenAI call; five-role RBAC on the server; bcrypt password hashes; API key held on the server only; token counts logged for every call |
| No hard-coded outputs; GenAI must not replace rules, validation, precedence, escalation, audit or security logic | 1.8 (17), (18) | The application has no mock or fallback model (`test_there_is_no_mock_provider`); scores come only from check results; every control is deterministic Python |
| Hidden data processed without changing core code | Hidden evaluation; 1.8 (3), (5) | Taxonomy, rules, prompts and schemas are data; hidden datasets are uploaded on the Evaluation page as JSON, JSONL or CSV |
| API keys never committed | 1.10 (12), (14) | The key lives only in the git-ignored `.env.secrets` on the server; for Render it is entered in the dashboard |
| Development across five competition days with meaningful commits | 1.8 (16) | A process constraint; the repository history contains two commits, both dated 2026-09-25, so this requirement is not met (Appendix A, CI-16) |
| Hardware and software environment | 1.9 | Developed and measured on a Windows 10 Pro workstation with an Intel Core i5-6500 and 16 GB RAM; every technology comes from the SRS lists |

These constraints explain several choices described later: strict schemas and bounded retries (Chapter 8), the rule that the Rule Matrix, not the model, decides (Chapter 11), and the treatment of every complaint and document as untrusted input (Chapter 23).
