# Appendix N — Glossary

This glossary defines the terms as they are used in SupportNova and in this report. Where a term has a wider meaning outside the project, the SupportNova meaning is the one given here.

## N.1 Project and Architecture Terms

**Table N.1 — Project and architecture terms**

| Term | Meaning in SupportNova |
|---|---|
| SupportNova | The Customer Complaint Resolution Intelligence application described in this report (theme ResponseX Intelligence, category Generative AI PowerPlay). |
| Lumora Home Technologies | The fictional smart-home electronics company whose products, customers, orders, policies and complaints the system uses. All of its data is simulated. |
| GenAI Complaint Intelligence Pipeline (Pipeline 1) | The stages that call the GenAI provider: the structured complaint analysis (`complaint_analysis` prompt) and the customer response written from the validated decision (`customer_communication` prompt). It proposes; it never decides. |
| Python Ground-Truth Validation Pipeline (Pipeline 2) | The independent, deterministic Python stages that derive the rule-based expectation for a complaint, run the 52 validation checks on the AI output and produce the validated decision. It never uses GenAI to approve Pipeline 1. |
| Complaint Resolution Rule Matrix (Rule Matrix) | The deterministic decision criteria in `rules/*.yaml` — resolution, escalation, routing, conditional routing, urgency floor, category, missing-information, follow-up, SLA and review rules plus parameters and signals — stored in the database, editable, versioned and audited. It is the ground truth. |
| Knowledge Base | The approved policy, SOP, guideline, FAQ, rule and template documents, their versions, sections and chunks. It provides the evidence that recommendations cite; the Rule Matrix provides the criteria. |
| Ground truth | The outcome the Rule Matrix derives for a complaint from the facts Python can establish. When the AI proposal and the ground truth differ, the ground truth prevails or the case goes to a person. |
| Validated decision | The final classification, routing, urgency, priority, actions, eligibility, escalation and follow-up that the organisation acts on, assembled by Pipeline 2. |
| Comparison Engine | The field-by-field comparison of the AI proposal and the rule outcome, shown in the user interface as the "AI vs rules" view. |
| Rule check | The label the user interface uses for Pipeline 2 and its results. |
| Reference data | The fixed catalog content sent in the system prompt: taxonomy, departments, action catalog, escalation levels, urgency and priority rules (SLA-RUL-15 section 5), the routing policy (RTE-RUL-14 sections 3–5) and follow-up types. |
| Provider adapter | The code that sends a structured request to one GenAI vendor (OpenAI, Anthropic or Google Gemini), selected by `AI_PROVIDER` and `AI_MODEL`. |

## N.2 Rule Matrix Terms

**Table N.2 — Rule Matrix terms**

| Term | Meaning in SupportNova |
|---|---|
| Category / subcategory | The two-level complaint taxonomy: 11 categories (for example SAF Safety) and 35 subcategories (for example SAF-OVH Overheating or Fire Hazard), stored in the database. |
| Resolution rule (RES-…) | A rule for one subcategory that sets urgency, impact, required, recommended and prohibited actions, refund, replacement and compensation eligibility, escalation, follow-up, timelines and policy references. The highest-precedence rule whose condition is true is selected. |
| Precedence (rule) | The number that orders resolution rules for the same subcategory; a more specific rule has a higher precedence. |
| Condition | The `when` clause of a rule, written over facts such as `eligibility.within_doa_window`. Conditions are three-valued: true, false or unknown; a rule whose condition is unknown is reported as pending rather than applied. |
| Signal | A risk or intent indicator detected deterministically in the complaint text, for example `fire_event`, `legal_threat` or `refund_request` (35 signals, `rules/complaint_rules/signals.yaml`). |
| Parameter | A named policy value used by the rules, for example `refund_window_days` = 30 (REF-POL-02 section 3.1); 59 parameters in `rules/parameters.yaml`. |
| Routing rule (RTE-…) | The primary and supporting departments for a subcategory. Conditional routing rules add departments when a condition holds. |
| Escalation rule (ESC-…) | A rule that requires an escalation level and departments when a signal or condition is present, for example ESC-001 fire, smoke or explosion to Critical Management Escalation. |
| Escalation level | One of six ranked levels: No Escalation, Supervisor Review, Department Manager, Specialist Team, Compliance Review, Critical Management Escalation. The highest level required by any fired rule applies. |
| Urgency floor (URG-…) | A minimum urgency and impact forced by a signal, for example URG-001 fire to Critical urgency and High impact; emotional language cannot lower or raise it. |
| Priority matrix | The table that maps urgency and impact to priority P0 (highest) to P3. |
| Review rule (REV-…) | One of 14 triggers that send a case to manual review, for example REV-002 critical validation failure or REV-008 sensitive case. |
| Missing-information and follow-up rules | Rules that list the facts a complaint must contain for a subcategory and the follow-up type and due time that apply. |
| Action catalog | The 66 permitted resolution actions (for example VERIFY_ORDER, SHIP_REPLACEMENT) and 12 prohibited actions (for example PROMISE_REFUND_BEFORE_VERIFICATION). |
| Ruleset hash | A hash of the active Rule Matrix stored with every analysis and evaluation run, so each decision can be traced to the rule version that produced it. |
| Policy reference | A citation in the form `DOC-ID:section`, for example `REF-POL-02:3.1`. |

## N.3 Knowledge Base and Retrieval Terms

**Table N.3 — Knowledge Base and retrieval terms**

| Term | Meaning in SupportNova |
|---|---|
| Document / version | A policy document (for example REF-POL-02 Refund Policy) and one of its uploaded versions with its own file, hash, effective date and status. |
| Version status | Active (usable as evidence within its effective and expiry dates), Previous, Superseded or Draft (never primary evidence; shown as outdated context). |
| Document precedence | The order used when active documents conflict: Policy = Rules > SOP > Guideline > FAQ > Template, then the most recent effective date (PRC-001 to PRC-005, `rules/precedence/precedence_rules.yaml`). |
| Section / chunk | A heading-delimited part of a parsed document, and the smaller retrievable text unit made from it; 484 chunks in the demo Knowledge Base. |
| Quarantine | The exclusion of a chunk that contains instruction-like or malicious content from retrieval, recorded with a reason. |
| Evidence | The retrieved, active, non-quarantined chunks given to the model and checked by the policy validation. |
| RAG (retrieval-augmented generation) | Supplying retrieved evidence to the model so that its answer is grounded in approved sources rather than its own knowledge. |
| Hybrid retrieval | The combination of BM25 lexical search, vector search, rule-guided expansion and reciprocal-rank fusion used to select evidence. |
| BM25 | A lexical relevance ranking function based on term frequency and document length. |
| Local hashing embedder | The default deterministic embedder that maps text features to a 768-dimensional vector by hashing; not a neural model. |
| Reciprocal-rank fusion (RRF) | A method that merges several rankings by summing 1 / (k + rank), with k = 60. |
| Rule-guided expansion | Adding the sections that the Rule Matrix cites for the candidate subcategories, so that required policies can be cited. |
| Policy conflict | Different values for the same fact (for example a refund time) in active documents, detected by pattern and resolved by precedence. |

## N.4 GenAI and Validation Terms

**Table N.4 — GenAI and validation terms**

| Term | Meaning in SupportNova |
|---|---|
| Prompt template / prompt version | A versioned YAML file with system and user templates, parameters, output schema and changelog; exactly one version per prompt key is active. |
| Structured output | A model response constrained to a JSON schema (`complaint_analysis.v1`, 37 required fields; `customer_communication.v1`, 7 required fields). |
| Catalog-restricted schema | A schema whose enumerations for categories, departments, actions and levels are filled from the live catalogs at request time, so the model cannot return an unknown code. |
| Controlled retry | A bounded retry of a failed AI call; invalid JSON or schema violations are retried with the validation errors, transient errors are retried, and authentication errors are not. |
| AI run | One recorded call to the GenAI provider with its prompt version, model, request, raw response, parse result, latency and token counts (`ai_runs` table). |
| Validation check | One of 52 deterministic tests with a code (for example RTE-001), a dimension, a severity (critical, major, minor, info) and a result (pass, warn, fail). |
| Dimension | One of 12 groups of checks: schema, classification, routing, priority, policy, resolution, eligibility, escalation, follow-up, communication, grounding, security. |
| Verification score | The weighted result of the checks on a scale of 0 to 100 (weights 5, 3, 1 and 0 by severity; pass 1.0, warn 0.5, fail 0). |
| Verification status | Pending, Verified (score at least 80 and no review trigger), Manual Review, or Human Verified (approved by a reviewer). |
| Manual review | The queue in which a reviewer claims a held case and approves, rejects, modifies, reclassifies or regenerates it; the original and final decisions are both kept. |
| Hallucination | AI output that is not supported by the complaint, the evidence or the Rule Matrix, such as an invented policy, amount, reference or fact. |
| Claim grounding | The check that each important fact in the AI output can be traced to a source (HAL-001 to HAL-004). |
| Unsupported promise | A statement in customer-facing text that commits to an outcome the validated decision does not allow, such as a refund before verification (RSP-002, RSP-006). |
| Prompt injection | Text in a complaint or document that tries to instruct the model; it is screened, annotated inside a nonce-tagged complaint element, forces review and is checked by SEC-001. |
| Fault injection (fault profile) | A deliberate corruption of the AI output used by the Adversarial Lab and tests (for example `missed_escalation`, `wrong_department`) to prove that Pipeline 2 catches the defect. |
| PII redaction | Replacement of payment-card numbers, security codes, passwords, one-time codes, e-mail addresses and phone numbers before text is sent to the provider or written to AI-run logs. |

## N.5 Operations, Security and Evaluation Terms

**Table N.5 — Operations, security and evaluation terms**

| Term | Meaning in SupportNova |
|---|---|
| Complaint status | The workflow state: New, Processing, Analyzed, Assigned, In Progress, Awaiting Customer, Escalated, Resolved, Closed, Reopened. |
| Processing stage | The pipeline step: queued, preprocessing, retrieval, ai_analysis, validation, response_generation, response_validation, finalizing, completed. |
| Duplicate / near-duplicate / repeat | Compared with the same customer's earlier complaints: an exact duplicate has the same normalised text hash (and is rejected at submission within `DUPLICATE_WINDOW_HOURS` = 24); a near-duplicate is a lightly edited resubmission with similarity of at least 0.86; a repeat is a new complaint about the same issue (same referenced complaint, order or subcategory, or same category with similarity of at least 0.30), which can raise the escalation level (ESC-017 to ESC-019). |
| SLA record | The first-response and resolution deadlines for a complaint's priority, each in state On Track, At Risk, Breached or Met. |
| Follow-up | A scheduled customer contact of one of six types, for example Request for additional information or Refund-status update. |
| Clarification | A request to the customer for missing information; the customer's answer re-runs the analysis. |
| RBAC | Role-based access control: five roles (customer, agent, reviewer, manager, admin) with permissions checked on the server for every endpoint. |
| CSRF header | The token header required with cookie-authenticated requests that change data. |
| Audit log | The append-only, hash-chained record of security-relevant and business actions; each entry stores the hash of the previous entry, and `GET /api/v1/audit/verify` recomputes the chain. |
| Evaluation run | A batch run of the full pipeline on a dataset split with a recorded model, prompt versions, ruleset hash and metrics. |
| Development split / holdout split | The 617 complaints used during development and the 154 unseen complaints reserved for the GenAI vs Python comparison. |
| Adversarial Lab | The page and API that run 18 scripted attack and defect scenarios through the production pipeline. |
| Key-field accuracy | The share of key fields (for example category, urgency, department, escalation level) that match the expected labels. |
| AI error catch rate | The share of cases with an AI key-field error that Pipeline 2 flagged. |
| p50 / p95 | The median and 95th-percentile processing time of complaints. |

## N.6 Abbreviations

**Table N.6 — Abbreviations**

| Abbreviation | Expansion |
|---|---|
| API | Application Programming Interface |
| BM25 | Best Matching 25 (Okapi ranking function) |
| CSRF | Cross-Site Request Forgery |
| CSV | Comma-Separated Values |
| DFD | Data Flow Diagram |
| DOCX | Office Open XML word-processing document |
| ER | Entity–Relationship |
| GenAI | Generative Artificial Intelligence |
| JSON | JavaScript Object Notation |
| JWT | JSON Web Token |
| KB | Knowledge Base |
| LLM | Large Language Model |
| MFA | Multi-Factor Authentication |
| NFR | Non-Functional Requirement |
| PII | Personally Identifiable Information |
| RAG | Retrieval-Augmented Generation |
| RBAC | Role-Based Access Control |
| REST | Representational State Transfer |
| RRF | Reciprocal-Rank Fusion |
| SLA | Service Level Agreement |
| SOP | Standard Operating Procedure |
| SRS | Software Requirements Specification |
