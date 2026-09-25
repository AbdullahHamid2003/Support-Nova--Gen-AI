# Chapter 44 — Future Enhancements

Everything in this chapter is **Future Enhancement**: none of it is implemented in the submitted version of SupportNova, and no result is claimed for it. The enhancements are chosen because they answer a measured limitation from Chapter 43 or a scope boundary set by the SRS, and because they fit the existing architecture without breaking its central rule: GenAI proposes. Python validates. Ground truth decides. None of the proposals moves business rules, escalation enforcement, schema validation, policy precedence, audit or security logic into the model. Table 44.1 at the end of the chapter lists each enhancement with the limitation it addresses and what it depends on.

## 44.1 Meeting the 20-Second Target

The largest measured gap is latency: the full pipeline runs at p50 21.7 s, although the validated recommendation exists at p50 16.2 s and within 20 s for 80.8 % of complaints (Section 43.3). Three changes would address this without weakening validation. First, the pipeline could commit the validated decision as soon as the 52 checks finish and generate the customer response as a second, separately recorded step, so that agents see the recommendation and the SLA clock records it before the response call returns. Second, the response call could use a smaller or faster model than the analysis call, because it only writes text from an already validated decision and is itself checked by the RSP and HAL checks. Third, the analysis prompt could request shorter free-text fields (summary, agent guidance and rationales), which make up a large part of the roughly 1,390 output tokens per analysis. Each change can be measured with the existing evaluation runs, which already report p50 and p95 per run.

## 44.2 Model Routing and Comparative Model Evaluation

The provider abstraction already contains OpenAI, Anthropic and Google Gemini adapters selected by `AI_PROVIDER` and `AI_MODEL`, and the evaluation runner records the provider, model, prompt versions and ruleset hash of every run. A future release could use this to run the same 154 holdout cases on several models and publish the comparison, and then route by risk: a faster model for routine complaints and a stronger model for complaints whose Python signals indicate safety, security, privacy or legal risk. The routing decision would be made by Python from the deterministic signals, not by the model, and every routed call would still pass the same validation. The expected benefit is a lower manual-review rate on routine cases at a controlled cost; it has not been measured.

## 44.3 Better Retrieval

Retrieval currently combines BM25, a local feature-hashing embedder and rule-guided expansion (Section 43.5). The configuration already accepts an external embedding provider (`EMBEDDING_PROVIDER`), and a neural embedding model could be evaluated behind that setting. A re-ranking step, applied to the fused candidates before the top ten are sent to the model, is a further option. The dataset makes the effect measurable: every record carries the expected policy references, so retrieval recall at k can be computed per run and compared with the current baseline before any change is adopted. The `VECTOR_DATABASE_URL` and `REDIS_URL` configuration keys are reserved for an external vector store and queue but are not used by the current code; the in-memory snapshot would be replaced only if a load test showed that it is needed.

## 44.4 A Human Feedback Loop

Every manual review already stores the original and final snapshots of the decision, the actions taken and the reviewer's comments (`reviews` and `review_actions` tables). These records are labelled data about where the AI and the rules went wrong. A future feedback loop would aggregate them by check code, subcategory and prompt version, show the recurring failure patterns to administrators, and support three governed responses: a new prompt version (created and activated through the existing prompt versioning with a changelog), a proposed Rule Matrix correction (edited, previewed and audited through the existing rule editor), or a Knowledge Base update. The loop would inform people who make these changes; it would not retrain a model or change rules automatically.

## 44.5 Reducing the Manual-Review Workload Safely

On the holdout set 84.4 % of cases went to review, against 33 % expected (Section 43.1). Part of this load comes from minor disagreements on fields where the Python decision already prevails, such as the follow-up type. A future version could let an administrator configure, per check and per category, that a minor disagreement is recorded and corrected by the Python decision without holding the case, while every critical check, every mandatory escalation and every sensitive case (REV-008) continues to require a person. Such a change would alter the validation policy (`rules/validation_policy.yaml`), so it would be versioned, audited and measured on the holdout set before release. Ordering the review queue by priority, SLA state and review reason is a simpler first step.

## 44.6 Scalability and Deployment

NFR 2 has not been load-tested (Section 43.4). The next steps are a reproducible load test at 10,000 complaints and 1,000 documents; replacing the in-process thread pool with an external job queue so that several application instances can share the work; moving the rate-limit counters into a shared store; and, if the load test requires it, storing embeddings in PostgreSQL with a vector index instead of rebuilding an in-memory snapshot in each process. A public deployment from the prepared Render blueprint (`render.yaml`) with uptime monitoring would provide the evidence for NFR 5, and a continuous-integration workflow that runs the 206 backend tests, the 12 frontend tests and the linters on every commit would protect the codebase during further development.

## 44.7 Event-Driven Integration With Enterprise Systems

Direct integration with CRM, payment, call-centre and Zendesk systems is outside the SRS mandatory scope (section 1.4). If it is added, the cleanest route is event-driven: the complaint lifecycle already writes history events (`complaint_history`) and audit entries, so a transactional outbox could publish events such as complaint submitted, decision validated, escalation raised, response released and case closed. A Zendesk or CRM connector would subscribe to these events and create or update tickets, and inbound tickets would enter SupportNova through the existing submission API. The simulated order ledger would be replaced by a read-only adapter to the order and payment systems, so that eligibility facts come from the system of record while the eligibility decision stays in the Rule Matrix.

## 44.8 More Channels and Real Delivery

Complaints already record seven channels (web form, e-mail, live chat, phone transcript, mobile app, social media and uploaded complaint), but they enter the system only through the web application — the customer portal, or staff intake where an agent selects the channel on the customer's behalf — and through the dataset and evaluation imports. Future intake adapters could read a support mailbox or a chat widget and create complaints through the same API, with the same validation, injection screening and duplicate detection. On the outbound side, the simulated delivery would be replaced by e-mail and SMS gateways, sending only responses that a user with the `complaint:respond` permission has released, and recording the gateway's delivery status in the timeline.

## 44.9 Multilingual Support

Multilingual support needs more than a translated prompt. The deterministic side of SupportNova — signal detection, negation handling, stemming, claim grounding and injection screening — is written for English text, and the Knowledge Base and templates are in English. A multilingual release would add language detection at intake, approved policy and template versions in each supported language, language-specific lexicons and tests for the deterministic checks, and holdout cases in each language, so that Python validation is as strong for those complaints as it is for English ones.

## 44.10 SLA Prediction and Advanced Analytics

SLA states are rule-based today: the first-response and resolution clocks of each record are On Track, At Risk once the elapsed share of the window passes the `sla_at_risk_pct` parameter, Breached after the deadline, or Met when completed in time (`backend/src/supportnova/services/sla.py`). A future version could estimate breach risk from the department's open workload, historical resolution times per subcategory and the case's review status, and show the estimate next to the rule-based state; the rule-based state would remain the authority for escalation. Analytics could add product-level root-cause views (complaints per SKU and subcategory over time), policy-gap reporting from REV-004 (no policy supports the decision) and REV-007 (conflicting policy information), and trends in validation failures per prompt version.

## 44.11 Security Hardening

The security enhancements follow directly from Section 43.11: multi-factor authentication for staff roles, single sign-on through the organisation's identity provider, antivirus scanning of uploaded documents and attachments before parsing, secrets held in a managed secrets store instead of a local file, and periodic anchoring of the audit hash chain outside the database so that even a database superuser could not rewrite history undetected. Structured PII detection, for example of postal addresses, would extend the current pattern-based redaction.

## 44.12 Policy and Rule Alignment

One enhancement is a data change rather than code: publishing an SLA-RUL-15 version whose urgency section states the same levels as the Rule Matrix (for example for PRV-BRC and PRV-CON), through the normal document versioning and impact analysis. This would remove a known source of AI and rule disagreement and the manual reviews it causes (Section 43.6).

**Table 44.1 — Future enhancements, the limitation each addresses and its dependencies**

| Enhancement | Addresses | Depends on | Status |
|---|---|---|---|
| Commit the validated decision before the response call; faster response model; shorter free text | 20-second target (NFR 1) | Pipeline change; evaluation runs to measure | Future Enhancement |
| Model routing by Python risk signals; multi-model holdout comparison | GenAI answer quality, cost | Existing provider adapters and evaluation runner | Future Enhancement |
| Neural embeddings, re-ranking, retrieval recall measurement | Retrieval quality | `EMBEDDING_PROVIDER`; expected policy references in the dataset | Future Enhancement |
| Reviewer feedback loop | Recurring AI and rule errors | `reviews` / `review_actions` snapshots; prompt and rule versioning | Future Enhancement |
| Configurable handling of minor disagreements; queue ordering | Manual-review workload | Versioned validation policy; holdout measurement | Future Enhancement |
| Load test, external job queue, shared rate limits, vector index | Scale (NFR 2) | Deployment environment | Future Enhancement |
| Public deployment with uptime monitoring; CI workflow | Availability (NFR 5); regression protection | Render blueprint; test suite | Planned |
| Event-driven CRM / Zendesk integration; order-system adapter | SRS scope boundary (section 1.4) | Outbox events from complaint history | Future Enhancement |
| E-mail, chat and SMS intake and delivery | Simulated delivery | Submission API; response release permission | Future Enhancement |
| Multilingual complaints | English-only deterministic checks | Translated policies, lexicons and test cases | Future Enhancement |
| SLA breach prediction; root-cause and policy-gap analytics | Rule-based SLA states only | SLA records, review reasons, product data | Future Enhancement |
| MFA, SSO, antivirus scanning, secrets store, audit anchoring | Security gaps | Identity provider; scanning service | Future Enhancement |
| SLA-RUL-15 version aligned with the Rule Matrix | Urgency mismatches (PRV-BRC, PRV-CON) | Document versioning and impact analysis | Future Enhancement |
