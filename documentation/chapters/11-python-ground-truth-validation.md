# Chapter 11 — Python Ground-Truth Validation Pipeline

The Python Ground-Truth Validation Pipeline (Pipeline 2) is the part of SupportNova that decides whether the output of the GenAI Complaint Intelligence Pipeline (Pipeline 1) can be trusted. It is implemented in `backend/src/supportnova/python_validation/engine.py` and runs for every complaint. It is independent from GenAI: it never calls a language model, it never uses a GenAI API to approve the output of Pipeline 1, and no value reported by the model, such as a confidence, enters its score or its decision. Pipeline 2 derives its own classification and its own rule outcome from the complaint, the Complaint Resolution Rule Matrix, the order ledger and the approved policy versions, and then checks the GenAI answer against that ground truth field by field with 52 deterministic checks. Its result is a verification score, a decision of Verified or Manual Review with the reasons for review, and the *validated decision*, which is what the system acts on. In the user interface Pipeline 2 is labelled "rules" or "rule check".

## 11.1 Purpose and Independence

The SRS states that the second pipeline "must be developed independently using Python", that it "must not use a Generative AI API to approve the output of Pipeline 1" and that it "must not simply accept everything returned by the Generative AI model". SupportNova treats the GenAI analysis as the object under test, never as a source of truth. Six properties of the implementation make the independence concrete.

1. **No model call.** The engine imports no GenAI provider. Its inputs are the Rule Matrix, the knowledge snapshot, the deterministic perception of the complaint, the injection-screening report, the retrieved evidence and the parsed GenAI answer (Section 11.2).
2. **Its own ground truth.** The classification comes from the category rules, the outcome from `DecisionEngine` (Chapter 10), eligibility from the order ledger and the parameters, and policy status from the document registry.
3. **No model-reported confidence.** The structured output schema `complaint_analysis.v1` contains no confidence field, and the verification score is computed only from deterministic check results, as the header of `rules/validation_policy.yaml` states.
4. **The model cannot confirm itself.** When the rule classifier is not confident and the GenAI subcategory is used provisionally, the case always goes to manual review (trigger REV-005, Section 11.5.3).
5. **The rules decide the final fields.** The category, subcategory, department, urgency, priority and escalation stored on the complaint are taken from the rules decision, not from the GenAI answer (`backend/src/supportnova/services/pipeline.py`).
6. **The rules still decide without GenAI.** If no usable GenAI answer exists, check SCH-001 fails, the case goes to manual review and the rules decision is still applied; `tests/backend/integration/test_ai_not_configured.py::test_no_api_key_means_no_ai_output_and_manual_review` asserts this behaviour for a server without an API key. **Tested.**

Pipeline 2 occupies two processing stages of `services/pipeline.py`. In the `validation` stage, directly after the GenAI analysis, `run_phase_a()` validates the analysis and builds the validated decision. The `response_generation` stage then asks the GenAI model for the customer response and follow-up message, written from the validated decision rather than from the model's own proposal. In the `response_validation` stage `run_phase_b()` validates that text and `finalize()` computes the score and the decision. Across the 780 analyses stored in the demonstration database, Phase A took a median of 2 ms (95th percentile 4 ms, maximum 7 ms) and Phase B a median of 2 ms, against a median of 16.0 s for the GenAI analysis call, so the deterministic validation adds no noticeable latency.

## 11.2 Inputs

The engine receives one `ValidationInput` object per complaint, assembled by `services/pipeline.py`. Table 11.1 lists its fields.

**Table 11.1 — Fields of ValidationInput**

| Field | Content | Produced by |
|---|---|---|
| `matrix` | The live `RuleMatrix` (rules, parameters, signals, validation policy) | `RuleService.matrix()` |
| `snapshot` | `KnowledgeSnapshot`: every document version with status, effective and expiry dates and section index | `knowledge_service.snapshot()` |
| `as_of` | Complaint date, the reference date for windows and policy status | complaint record |
| `complaint_ref`, `complaint` | Complaint reference, title and product text | complaint record |
| `perception` | Deterministic view of the complaint: signals, entities, rule classification, lexicon sentiment, fact namespaces, order reference, product SKU | `complaint_processing/fact_builder.py` |
| `injection` | Injection-screening report: suspicious flag, risk score, finding types and flagged spans | `security/injection.py` |
| `retrieval` | Retrieved evidence sections, outdated versions of those sections and resolved policy conflicts | `knowledge_base/retriever.py` |
| `ai` | Parsed and schema-validated GenAI answer (`ComplaintAnalysis`), or `None` | Pipeline 1 |
| `ai_error` | Reason when no usable answer exists, for example `not_configured` | Pipeline 1 runner |
| `facts_text` | Verified system facts (order ledger, history) given to the model, used for grounding checks | `genai_pipeline/context.py` |

The perception is the Python pipeline's own reading of the complaint, built by `build_perception()` from the normalised title, description and supporting information. Signals are detected with the 35 definitions of `rules/complaint_rules/signals.yaml`, each a list of phrases and regular expressions; a phrase preceded within three tokens by a negation cue such as "no" or "never" does not count, so "there was no smoke and no fire" raises no fire signal (`tests/backend/unit/test_perception_security.py::test_negation_suppresses_signal`). Entities are extracted with regular expressions for order references (`LMR-######`), transaction references (`TXN-########`), complaint references (`CMP-#####`), amounts, dates and durations, and products are matched through the aliases in `config/products.yaml`. The rule classifier scores every subcategory with the weighted terms of `rules/complaint_rules/category_rules.yaml` (title matches count 1.3 times, negative terms subtract, signals and products add boosts), applies the risk-first precedence of RTE-RUL-14 section 5, keeps secondary issues and marks the result ambiguous when the two best candidates of different categories are within 15 percent of each other. Its confidence is `high` for a score of at least 8 without ambiguity, `medium` for at least 5, `low` below that and `none` below the minimum score of 3.0. The lexicon sentiment adds and subtracts the weights of the sentiment lexicon, with boosts for repeated exclamation marks and capitalised words, and maps the total to Positive, Neutral, Negative or Strongly Negative; it is informational only (Chapter 14).

The fact namespaces combine what the text says with what the records say. `complaint_processing/order_facts.py` derives order and eligibility facts from the simulated order ledger, for example `within_refund_window` (30 days from delivery, 45 days for Care+ members), `within_doa_window` (7 days), `within_warranty` (product warranty, at least 36 months with Care+), `replacement_limit_reached`, `duplicate_charge_verified` and `refund_late`. `services/history.py` supplies the history facts from the customer's complaints of the last 90 days (`repeat_window_days`): the number of prior same-issue complaints, how many of them are unresolved and whether the complaint reopens a resolved one. Every fact that cannot be established is left unknown, so that the three-valued conditions of the Rule Matrix report "requires verification" rather than guessing (Chapter 10).

## 11.3 Ground-Truth Sources

The SRS lists the sources against which Pipeline 2 must compare the GenAI output. Table 11.2 shows the artefact that plays each role in SupportNova and the checks that use it.

**Table 11.2 — Ground-truth sources of Pipeline 2**

| SRS source | SupportNova artefact | Decides | Used by checks |
|---|---|---|---|
| Complaint Resolution Rule Matrix | 116 resolution rules, `DecisionEngine` | Rule selected, actions, eligibility, follow-up, timelines | RES, ELG, FUP, POL-004, RSP-003 |
| Department-routing rules | 35 routing rules and 6 conditional routing rules | Primary and supporting departments | RTE-001, RTE-002 |
| Urgency thresholds | Base urgency of the rule, 15 urgency floors, priority matrix, principles URG-100 to URG-102 | Urgency, impact, priority | PRI-001 to PRI-004 |
| Escalation rules | 39 escalation rules, 6 levels, 6 required note fields | Escalation requirement, level, departments | ESC-001 to ESC-004 |
| Approved policy versions | Document registry: 24 documents, 29 versions with status and dates | Whether a cited document and section exist and are Active | SCH-004, POL-001 to POL-003, HAL-004 |
| Complaint-category rules | 35 category rules and classifier settings | The rules' own category and subcategory | CLS-001, CLS-002, CLS-003 |
| Customer eligibility rules | Eligibility of the selected rule, order-ledger facts, 59 parameters | Refund, replacement, compensation and amount | ELG-001 to ELG-003, RES-004 |
| Resolution rules | Required, recommended and prohibited actions; action catalogue with 12 prohibited behaviours | Which steps are required or forbidden | RES-001 to RES-004, RSP-006 |
| Follow-up requirements | 4 follow-up rules, rule follow-ups, 8 missing-information rules | Follow-up type and due time, blocking gaps | FUP-001, FUP-002, MIS-001, MIS-002 |
| Source-document metadata | Document ID, version, status, effective and expiry dates, section IDs; retrieval precedence and conflicts | Applicability, outdated versions, conflict winners | POL-002, POL-005, POL-006 |

Three further configuration files complete the ground truth: `rules/complaint_rules/response_rules.yaml` defines the required elements, tone rules and timeline patterns of customer text, `rules/complaint_rules/review_rules.yaml` the 14 manual-review triggers, and `rules/validation_policy.yaml` the catalogue of the 52 checks with their dimensions, default severities and the scoring policy.

## 11.4 Validation Process

Figure 11.1 shows the complete process: the reference classification, the rules decision, the 44 checks of Phase A, the validated decision and the comparison rows, the GenAI customer response, the 8 checks of Phase B and the final scoring.

![Figure 11.1 — Python Ground-Truth Validation Pipeline, Phase A and Phase B](diagrams/pipelines/fig-11-01-validation-pipeline.svg)
*Figure 11.1 — Python Ground-Truth Validation Pipeline, Phase A and Phase B*

### 11.4.1 Reference Classification and the Evidence Gate

Every rule outcome depends on the subcategory, so Pipeline 2 must first decide which subcategory is the reference. It prefers its own classification and uses the GenAI subcategory only when its own evidence is weak and the GenAI choice is supported by the complaint. `run_phase_a()` chooses among four reference sources, listed in Table 11.3.

**Table 11.3 — Reference sources for the classification**

| Reference source | Condition | Consequence |
|---|---|---|
| `reviewer_override` | A reviewer reclassified the case and the pipeline was re-run | The reviewer's subcategory decides; treated as confident |
| `python_rules` | Rule classifier confidence `high` or `medium` and not ambiguous | The rules' subcategory decides; a different GenAI category fails CLS-001 |
| `ai_unconfirmed` | Rules not confident, GenAI subcategory exists in the taxonomy and passes the evidence gate | The GenAI subcategory decides provisionally; CLS-001 warns; REV-005 sends the case to manual review |
| `python_low_confidence` | Rules not confident and the GenAI subcategory is invalid or fails the evidence gate | The rules' best candidate decides provisionally; CLS-001 fails if the GenAI category had no support; REV-005 applies |

The evidence gate is the function `ai_classification_supported()`. It accepts the GenAI subcategory only if that subcategory, or its category, appears among the scored candidates of the rule classifier, or if the classifier found no candidate at all that could contradict it. A GenAI category for which the complaint contains no matching term and no signal is treated as a probable hallucination and is never used as the provisional reference. The unit test `tests/backend/unit/test_perception_security.py::test_unsupported_genai_category_is_never_the_provisional_reference` shows the case that motivated the gate: Lumora's smart plug is called "Spark", and a complaint that the Spark plug "stopped responding in the app" produces no safety candidate, so the subcategory SAF-ELC is rejected while the classifier's own top candidate is accepted. The integration test `tests/backend/integration/test_difficult_cases.py::test_product_name_is_not_a_hazard` asserts through the API that such a complaint is neither classified as SAF nor escalated at Critical Management level. **Tested.** In the holdout evaluation run (152 validated cases) the reference source was `python_rules` in 76 cases, `ai_unconfirmed` in 63 and `python_low_confidence` in 13.

The comparison with the GenAI answer always shows the rules' own classifier result, even when it was not used as the reference, so a reviewer can see both readings (Chapter 12).

### 11.4.2 The Rules Decision

With the reference subcategory and the classifier's secondary issues, `run_phase_a()` calls `DecisionEngine.decide()` on a fresh copy of the perception's evaluation context (Chapter 10, Section 10.8). The resulting `Decision` fixes the selected resolution rule and any pending rules, the urgency, impact and priority with the rule identifiers that set them, the primary and supporting departments, the fired escalation rules and the resulting level, the required, recommended and prohibited actions, the eligibility, the missing information, the follow-up, the policy references, the quotable timelines and the SLA targets. The decision is computed whether or not a GenAI answer exists. When the GenAI answer names a different valid subcategory, the engine also computes the decision that the rules would give for that subcategory and keeps it with the Phase A result for inspection; it does not enter any check.

### 11.4.3 Phase A Checks

Phase A compares the GenAI analysis with the rules decision in eleven dimensions. Each check records a status (`pass`, `warn`, `fail` or `not_applicable`), a message, the expected and actual values and the rule and policy references involved. Several checks raise their severity at runtime when the context is high-risk; the default severities are listed in Table 11.4.

**Schema.** SCH-001 fails when no usable GenAI answer exists after the controlled retries (Chapter 21); the other schema checks run only when an answer exists. SCH-002 verifies that the category and subcategory codes exist, that the subcategory belongs to the category, that the main issue carries the same subcategory and that every secondary subcategory is valid. SCH-003 verifies every department code. SCH-004 resolves each cited `policy_id:section` in the document registry; a citation of a document that does not exist fails with critical severity as a likely invention, and a non-existent section of a real document fails with major severity. SCH-005 verifies that the escalation flag agrees with the escalation level and that an escalated answer contains escalation notes. SCH-006 verifies that every resolution step uses an action code from the catalogue.

**Classification.** CLS-001 compares the GenAI category with the reference category: it passes when they agree and the rules are confident, warns when they agree but the rules could not confirm the category, fails when the confident rules disagree, and fails when the GenAI category has no support in the complaint. CLS-002 compares subcategories and warns when only the subcategory differs within the same category. CLS-003 warns when the rules found a secondary issue in a category the GenAI answer does not mention. CLS-004 compares the GenAI sentiment with the lexicon sentiment (pass for the same value, warn for a neighbouring value, fail for a larger gap); its severity is `info`, which carries a weight of zero, so sentiment can never change the score. CLS-005 warns when an order, transaction or complaint reference found by Python is missing from the GenAI entities.

**Routing.** RTE-001 fails with critical severity when the GenAI primary department differs from the department of the routing rule for the reference subcategory. RTE-002 compares the required supporting departments with the GenAI supporting departments: all covered passes, some covered warns, none covered fails. Chapter 13 describes routing validation in detail.

**Priority.** PRI-001 compares urgency on the ordered scale Low, Medium, High, Critical. An AI urgency below the rules fails, with critical severity when the rules require High or Critical, and the message states that calm wording does not reduce risk; an AI urgency above the rules warns. PRI-002 compares the priority with the priority matrix and fails when the AI priority is less severe. PRI-003 warns when the AI urgency is above the rules while the lexicon sentiment is negative and no risk signal is present, citing principle URG-100 that sentiment never raises urgency. PRI-004 warns when the AI priority does not follow from the AI's own urgency and impact. Chapter 14 describes these checks.

**Policy.** POL-001 fails when no policy is cited, because every resolution must cite the approved policy (CHP-POL-01 section 6.2). POL-002 fails with critical severity when a cited document has no Active version on the complaint date, for example the superseded Legacy Returns Handling SOP RET-SOP-23, because outdated policies must not be the primary basis of a resolution (SRS Step 7, CHP-POL-01 section 10.4). POL-003 compares the citations with the retrieved evidence: citations outside the case evidence warn, and the check fails when none is in the evidence. POL-004 warns when none of the policy references required by the selected rule is cited. POL-005 warns when the GenAI answer labels a section Applicable that the rules label Not Applicable or Outdated; the rules label each retrieved section Applicable when the selected rule or a fired escalation rule cites it, Conditionally Applicable when another rule of the same issue cites it, Not Applicable otherwise, and Outdated for previous, superseded or draft versions (SRS Step 26). POL-006 fails when the answer relies on the lower-ranking side of a policy conflict that retrieval resolved by the precedence rules of CHP-POL-01 section 10.

**Resolution.** RES-001 verifies that every required action of the selected rule is present, where an `any_of` group is satisfied by any of its members; missing actions warn when none of them is critical and at least 60 percent of the required actions are present, and otherwise fail, with critical severity when a missing action belongs to the critical set of safety, security, privacy and escalation actions (for example `ADVISE_STOP_USING`, `REVOKE_SESSIONS`, `ESCALATE_COMPLIANCE`). RES-002 fails with critical severity when the answer proposes an action that the rule prohibits or when a step description contains a prohibited behaviour, detected with the patterns of the action catalogue. RES-003 warns when none of the recommended actions is considered. RES-004 fails for contradictory steps: processing a refund while the AI itself marks the refund not eligible, offering credit while compensation is not eligible, shipping a replacement while replacement is not eligible, or an escalation step without an escalation.

**Eligibility.** ELG-001, ELG-002 and ELG-003 compare the GenAI refund, replacement and compensation eligibility with the rules. An AI "eligible" against a rules "not eligible" fails with critical severity; an AI "eligible" against "requires verification" or "not applicable", and an AI denial or omission of an entitlement, fail with major severity; other differences warn. ELG-003 also verifies a compensation amount: any amount when the rule allows none, or an amount above the amount or ceiling fixed by the rule, fails with critical severity, and the message states the agent approval limit of USD 25. Chapter 15 describes eligibility validation.

**Escalation.** ESC-001 fails with critical severity when the rules require an escalation that the GenAI answer does not identify, naming the escalation rules that require it; the escalation is enforced regardless. ESC-002 fails when the GenAI level ranks below the required level, with critical severity when the required level is Compliance Review or Critical Management Escalation. ESC-003 warns about an escalation that no rule requires. ESC-004 fails when escalation notes lack any of the six fields required by ESC-SOP-12 section 5: summary, key facts, reason, actions taken, relevant policy and required next action.

**Follow-up and missing information.** FUP-001 fails when the rules require a follow-up that the answer omits and warns about a follow-up the rules do not require. FUP-002 warns when the follow-up type differs. MIS-001 fails when a blocking information gap found by the missing-information rules is not identified by the answer, and MIS-002 fails when no clarification question covers it; both use the keywords of the missing-information rules, for example "order", "reference" and "lmr" for a missing order number.

**Grounding.** HAL-001 verifies each claim that the answer lists with its source type. A claim attributed to the complaint must share at least half of its content words with the complaint text; a claim attributed to a policy must overlap its retrieved evidence by at least 35 percent or name an existing policy; a claim attributed to system metadata must overlap the verified facts by 40 percent; a claim attributed to the rules or the validated decision must overlap the decision text by 35 percent. The check passes when every claim is supported, warns when at most a quarter are unsupported and fails otherwise. HAL-002 fails when an extracted order ID, transaction ID, amount, date or complaint reference does not appear in the complaint or the verified facts. HAL-003 fails when the summary or key facts contain a reference number or amount absent from the complaint and facts. HAL-004 fails when the summary, guidance, step descriptions or urgency rationale name a policy identifier that does not exist in the Knowledge Base. The unit test `tests/backend/unit/test_perception_security.py::test_claim_grounding_accepts_paraphrase_but_not_invented_facts` shows that paraphrases pass while an invented promise does not.

**Security.** SEC-001 runs only when the injection screening flagged the complaint. It fails with critical severity when the answer shows that the instructions in the complaint influenced it: a refund or compensation marked eligible against the rules, a required escalation dropped, urgency lowered, or wording that repeats the injected instruction ("as instructed", "pre-approved") or a flagged span. SEC-003 records the screening result and warns when the complaint was suspicious. Prompt-injection protection itself is described in Chapter 23.

### 11.4.4 The Validated Decision

`build_validated_decision()` assembles what the system will act on: the fields that the rules enforce combined with the GenAI content that passed validation. It is stored in `validation_results.validated_decision` and shown in the case view as the Final decision (Figure 11.4).

The rule-enforced fields are the classification (with its reference source and the rule classifier's candidates and confidence), the primary and supporting departments, urgency, impact and priority with their sources, the SLA targets, the escalation requirement, level, fired rules and departments, the eligibility, the required, recommended and prohibited actions, the follow-up, the missing information, the policy references, the timelines and the selected and pending rules with the decision trace.

The GenAI resolution steps are filtered one by one. A step is excluded, with a stated reason, when its action is unknown, when the rule prohibits it, when it escalates although no escalation rule applies, when it escalates to a level other than the one the rules set, when it asks for an order reference that was already provided, or when it is a commitment that the selected rule neither requires nor recommends. Investigative steps from the verification and information groups are always acceptable, whereas commitments such as refunds, credits, replacements and cancellations "must come from the Rule Matrix". Every required action that the answer omitted is then appended as a step with the source `rule`. Clarification questions are kept and, for each blocking gap that no question covers, the question text of the missing-information rule is added. The timelines that the customer response may quote are the timeline parameters of the selected rule, each with its value, unit and source section, plus the first-response and resolution targets of the SLA rule. When an escalation is required, the escalation notes are taken from the GenAI answer if it wrote them and are otherwise generated from the fired rules. When the complaint was flagged for manipulation, any sentence of the GenAI summary, key facts or escalation notes that repeats a flagged instruction is removed and a note records how many sentences were left out (`tests/backend/unit/test_perception_security.py::test_validated_summary_never_relays_flagged_instructions`). The agent guidance keeps the GenAI recommendation separately from the validated guidance, which states the applicable rule, the mandatory escalation, the prohibited behaviours and the missing information.

The GenAI customer response is written from this validated decision: the prompt `customer_communication` 1.0.0 receives the decision block, the permitted timelines, the clarification questions, the follow-up and only the evidence that was cited or found applicable (Chapter 16). The response therefore starts from the rules' outcome, and Phase B verifies that it stays within it.

### 11.4.5 Phase B Checks

Phase B validates the customer response and the follow-up message produced by the communication stage. RSP-001 verifies the required elements defined in `response_rules.yaml`, namely an acknowledgement, empathy, a summary of the issue and the next step; a missing acknowledgement or next step fails and other missing elements warn, and the check fails with major severity when no response could be drafted at all. RSP-002 detects unsupported promises against the validated eligibility: a refund promised while the validated refund is not eligible, a refund stated without the verification condition, guaranteed or cash compensation, a policy exception without reviewer approval, and "guarantee" language for outcomes (CPN-POL-11 section 8). RSP-003 extracts every duration and deadline and fails unless each matches a permitted timeline after unit normalisation, where a figure stated in business days must match a business-day timeline and deadline words such as "tomorrow" are allowed only in safety advice such as "stop using it immediately". RSP-004 fails when an amount or reference in the response cannot be traced to the complaint, the verified facts, the validated compensation or the entitlement parameters (delay credit USD 10, Care+ service fee USD 29, agent limit USD 25). RSP-005 applies the tone rules RSP-101 to RSP-106 of `response_rules.yaml`, for example at most 120 words for the concise tone and no contractions for the formal tone. RSP-006 fails when the response contains any other prohibited behaviour of the action catalogue, such as asking for a password or a full card number or dismissing a safety concern. RSP-007 applies the prohibited-behaviour, promise and timeline checks to the follow-up message. SEC-002 fails when the response contains sensitive data such as a card number or a password. Chapters 16 and 17 describe response generation and unsupported-promise detection in detail.

### 11.4.6 Check Catalogue

Table 11.4 lists all 52 checks of `rules/validation_policy.yaml` in their current wording, with the phase in which they run and what they validate. Phase A contains 44 checks and Phase B 8.

**Table 11.4 — The 52 checks of the Python Ground-Truth Validation Pipeline**

| Code | Name | Dimension | Default severity | Phase | What is validated |
|---|---|---|---|---|---|
| SCH-001 | AI answer is complete and well-formed | schema | critical | A | A usable, schema-valid answer exists after retries |
| SCH-002 | Category and subcategory are valid | schema | critical | A | Codes exist, subcategory belongs to category, issues consistent |
| SCH-003 | Departments are valid | schema | critical | A | Primary and supporting department codes exist |
| SCH-004 | Cited policies exist | schema | major | A | Cited documents and sections exist (invented document: critical) |
| SCH-005 | Escalation details are consistent | schema | major | A | Flag agrees with level; notes present when escalated |
| SCH-006 | Resolution steps use known actions | schema | major | A | Every step uses a catalogue action code |
| CLS-001 | Category matches the rules | classification | major | A | Category equals the reference; GenAI category supported by evidence |
| CLS-002 | Subcategory matches the rules | classification | minor | A | Subcategory equals the reference |
| CLS-003 | Secondary issues identified | classification | minor | A | Rule-detected secondary issues are mentioned |
| CLS-004 | Sentiment matches the rule check | classification | info | A | Sentiment against the lexicon estimate, weight 0 |
| CLS-005 | Reference numbers captured | classification | minor | A | Order, transaction and complaint references are extracted |
| RTE-001 | Primary department matches the routing rules | routing | critical | A | Primary department equals the routing rule |
| RTE-002 | Required supporting departments included | routing | major | A | Required supporting departments are covered |
| PRI-001 | Urgency matches the rules | priority | critical | A | Urgency equal; lower fails, higher warns |
| PRI-002 | Priority matches the priority matrix | priority | major | A | Priority equals the matrix value |
| PRI-003 | Urgency not inflated by emotional language | priority | minor | A | Higher urgency without risk signal and with negative sentiment |
| PRI-004 | AI priority fits its urgency and impact | priority | minor | A | AI priority follows from its own urgency and impact |
| POL-001 | At least one policy cited | policy | major | A | Citation present |
| POL-002 | No outdated policy cited | policy | critical | A | Cited documents have an Active version |
| POL-003 | Cited policies are in the case evidence | policy | major | A | Citations match retrieved evidence |
| POL-004 | Policies required by the rules are cited | policy | minor | A | Rule's references are cited |
| POL-005 | Policy applicability matches the rules | policy | minor | A | Applicability labels agree |
| POL-006 | Higher-ranking policy followed in conflicts | policy | major | A | Overridden conflict sources are not relied on |
| RES-001 | Required actions present | resolution | major | A | Required actions and `any_of` groups (critical actions: critical) |
| RES-002 | No prohibited actions | resolution | critical | A | No prohibited code or behaviour in the steps |
| RES-003 | Recommended actions considered | resolution | minor | A | At least one recommended action present |
| RES-004 | No contradictory actions | resolution | major | A | Steps consistent with the answer's eligibility and escalation |
| ELG-001 | Refund eligibility matches the rules | eligibility | major | A | Refund status (unsupported eligible: critical) |
| ELG-002 | Replacement eligibility matches the rules | eligibility | major | A | Replacement status (unsupported eligible: critical) |
| ELG-003 | Compensation and amount match the rules | eligibility | major | A | Compensation status and amount (excess amount: critical) |
| ESC-001 | Required escalation identified | escalation | critical | A | Mandatory escalation not missed |
| ESC-002 | Escalation level meets the rules | escalation | major | A | Level at least the required level (rank 4 or 5 missed: critical) |
| ESC-003 | No unnecessary escalation | escalation | minor | A | No escalation without a rule |
| ESC-004 | Escalation notes are complete | escalation | major | A | Six note fields of ESC-SOP-12 s5 |
| FUP-001 | Follow-up requirement matches the rules | follow_up | minor | A | Follow-up required or not |
| FUP-002 | Follow-up type matches the rules | follow_up | minor | A | Follow-up type |
| MIS-001 | Missing information identified | follow_up | major | A | Blocking gaps identified |
| MIS-002 | Questions ask for the missing information | follow_up | major | A | A question covers each blocking gap |
| HAL-001 | Claims backed by the complaint, policies or rules | grounding | major | A | Claims traced to their stated source |
| HAL-002 | Extracted details appear in the complaint | grounding | major | A | Entities found in complaint or facts |
| HAL-003 | Summary sticks to the facts | grounding | minor | A | No invented IDs or amounts in summary |
| HAL-004 | Policies named in the text exist | grounding | major | A | Policy IDs in free text exist |
| SEC-001 | AI ignored instructions in the complaint | security | critical | A | Flagged instructions did not change the outcome |
| SEC-003 | Complaint screened for manipulation | security | info | A | Screening result recorded, weight 0 |
| RSP-001 | Response includes the required parts | communication | major | B | Acknowledgement, empathy, summary, next step |
| RSP-002 | No unsupported promises | communication | critical | B | Promises against validated eligibility |
| RSP-003 | Timelines supported by policy or SLA | communication | major | B | Every duration and deadline permitted |
| RSP-004 | Amounts and references match the case | communication | major | B | Amounts and IDs traceable |
| RSP-005 | Requested tone used | communication | minor | B | Tone rules RSP-101 to RSP-106 |
| RSP-006 | No prohibited statements in the response | communication | critical | B | Prohibited behaviours absent |
| RSP-007 | Follow-up message is safe to send | communication | minor | B | Follow-up message checks |
| SEC-002 | No sensitive data in the response | security | major | B | No card numbers, passwords or similar |

The catalogue groups the checks into the twelve dimensions of the validation policy: schema (6 checks), classification (5), routing (2), priority (4), policy (6), resolution (4), eligibility (3), escalation (4), follow-up (4), communication (7), grounding (4) and security (3). When no GenAI answer exists, Phase A records only SCH-001 and SEC-003; when no customer response could be drafted either, Phase B records only RSP-001.

## 11.5 Validation Result

### 11.5.1 Check Results

Each check produces a `CheckResult` with the fields `code`, `name`, `dimension`, `severity`, `status`, `message`, `expected`, `actual`, `rule_refs` and `policy_refs`. The results are stored one row per check in the table `validation_checks`; the demonstration database holds 40,560 rows, 52 for each of its 780 validation results. The case view lists them under Rule checks in the "AI vs rules" tab, with the expected value from the rules, the actual value from the AI and the rules and policy sections involved (Chapter 12). Stored messages keep the wording in force when they were written; the API layer `backend/src/supportnova/api/wording.py` serves older records in the current wording without rewriting them, which `tests/backend/unit/test_wording.py` tests.

### 11.5.2 Verification Score

The verification score required by SRS 1.6 (li) is computed by `finalize()` from the check results alone, according to `rules/validation_policy.yaml`:

```yaml
# score = 100 * sum(weight(severity) * value(status)) / sum(weight(severity))
#         over applicable checks (status != not_applicable)
# value: pass = 1.0, warn = 0.5, fail = 0.0
# decision: Verified  if no critical failure, score >= verified_min_score and
#                     no manual-review trigger fired; otherwise Manual Review.
# =============================================================================
decision:
  verified_min_score: 80
  review_below_score: 80
severity_weights: {critical: 5, major: 3, minor: 1, info: 0}
status_values: {pass: 1.0, warn: 0.5, fail: 0.0}
```

A check that does not apply to the case is left out entirely. A check with severity `info` contributes a weight of zero, which is why sentiment (CLS-004) and the screening record (SEC-003) never change the score. The weight is that of the severity recorded for the case, so a runtime escalation to critical, for example PRI-001 for a missed Critical urgency, weighs 5 instead of the default. The same formula applied to the checks of one dimension gives the dimension scores shown as "Score by area". The weights, values and threshold are data in the `validation_policy` configuration row and can be changed like any rule (Chapter 10). Figure 11.2 shows how the score and the triggers lead to the decision.

![Figure 11.2 — Verification score and decision logic](diagrams/pipelines/fig-11-02-score-and-decision.svg)
*Figure 11.2 — Verification score and decision logic*

### 11.5.3 Verification Decision and Review Reasons

A complaint is **Verified** only if three conditions hold together: no check with critical severity failed, the score is at least 80, and none of the 14 manual-review triggers of `rules/complaint_rules/review_rules.yaml` fired. Otherwise the decision is **Manual Review**, and every trigger that fired is recorded as a review reason with its code, rule identifier, name and detail. The overall status is `fail` when any check failed, `warn` when any warned and `pass` otherwise. Table 11.5 lists the triggers, the condition on which `finalize()` fires each one, and how often each fired in the 780 validation results of the demonstration database, which record 1,156 review reasons in total.

**Table 11.5 — Manual-review triggers and their firing conditions**

| Trigger | Code | Fires when | Fired |
|---|---|---|---|
| REV-001 | `ai_python_category_mismatch` | CLS-001 failed | 94 |
| REV-002 | `critical_validation_failure` | Any check with critical severity failed | 339 |
| REV-003 | `low_verification_score` | Score below 80 | 48 |
| REV-004 | `missing_policy_support` | POL-001 or POL-003 failed, the rules decision has no policy reference, or no evidence was retrieved | 9 |
| REV-005 | `ambiguous_complaint` | Not a reviewer override, and the rule classification is ambiguous, has no confidence, or was not the reference | 244 |
| REV-006 | `escalation_unclear` | ESC-003 warned or ESC-002 failed | 112 |
| REV-007 | `policy_contradiction` | POL-006 failed; a conflict matters for this case (the customer quotes the overridden statement or document, or the AI cited it); or the customer cites a policy and SCH-004 or POL-002 failed | 10 |
| REV-008 | `sensitive_case` | Primary category SAF or PRV, or signal `legal_threat`, `staff_harassment`, `injury` or `lock_security` | 144 |
| REV-009 | `invalid_ai_output` | SCH-001 failed | 0 |
| REV-010 | `prompt_injection_detected` | The injection screening flagged the complaint | 42 |
| REV-011 | `unsupported_promise` | RSP-002, RSP-003 or RSP-006 failed | 39 |
| REV-012 | `hallucination_detected` | HAL-001, HAL-002 or HAL-004 failed | 66 |
| REV-013 | `unknown_category` | SCH-002 failed | 0 |
| REV-014 | `reference_mismatch` | The order reference could not be verified or belongs to another customer (missing-information rules MIS-007, MIS-008) | 9 |

REV-009 and REV-013 did not fire in the stored results because every stored analysis contained a usable answer with valid codes; both are exercised by tests and by the lab (Section 11.7). All 14 triggers are enabled. A trigger is disabled by setting the `enabled` field of its review rule to false; the generic active switch of the Rule Matrix page does not affect review triggers (Chapter 10, Section 10.9). The firing conditions themselves are code in `finalize()`.

The reference classification of Section 11.4.1 feeds the decision directly, as Figure 11.3 shows. Whenever the rules could not classify with confidence, whether the GenAI subcategory or the rules' best candidate is used provisionally, REV-005 fires and a person confirms the classification. This is the mechanism that prevents the GenAI answer from approving its own category.

![Figure 11.3 — Reference classification and its effect on the decision](diagrams/pipelines/fig-11-03-evidence-gate.svg)
*Figure 11.3 — Reference classification and its effect on the decision*

### 11.5.4 What the System Acts On

The persistence step of `services/pipeline.py` applies the rules decision, never the unvalidated GenAI answer. The complaint's category, subcategory, department, urgency, priority, escalation level and escalation flag are set from the rules decision; only the sentiment shown on the complaint is the GenAI value, because sentiment has no operational effect. An escalation record is created at the rules' level, with the source `rule` when the GenAI answer missed the escalation and `rule+ai` when it identified it, and the timeline notes that "the AI missed it, the rules require it" where applicable. The follow-up is scheduled from the rules' follow-up type and due time, and the SLA record is opened for the rules' priority. The resolution record keeps the GenAI steps and the validated steps side by side, and the customer response is stored with the status `ready` only when the decision is Verified and no communication or security check of Phase B failed; otherwise its status is `requires_review` and it cannot be sent unreviewed. A Manual Review decision opens a review in the queue with the reason codes and an original snapshot of the GenAI output, the validated decision and the score, so that the original recommendation and the reviewer's decision both remain on record; evaluation runs never fill the queue. The complaint also receives the flag `ai_python_agreement`, true when the GenAI answer agrees with the rules on category, department and the escalation requirement, which feeds the "AI matches rules" indicator in Analytics. Finally an audit entry records the provider, model, prompt versions, policy versions, ruleset hash, decision, score and review reasons.

![Figure 11.4 — Final decision of CMP-00616: rule-enforced fields and validated steps](../screenshots/08-complaint-detail-final-intelligence.png)
*Figure 11.4 — Final decision of CMP-00616: rule-enforced fields and validated steps*

### 11.5.5 Worked Example: CMP-00616

The dataset complaint CMP-00616, "Front door found unlocked" (fictional customer, email channel, product Lumora Keystone Smart Lock, no order reference), was processed on 24 September 2026 by `openai/gpt-4.1-mini` with prompts `complaint_analysis` 1.2.0 and `customer_communication` 1.0.0 under ruleset `be81124c2a1df0d5`. The customer writes that the door was found unlocked and that the lock log shows a remote unlock at 4:40 am, adding "I live alone and I am rather shaken". Figures 11.4 and 12.3 show the case; Appendix E reproduces the stored result.

The perception detected the signal `lock_security`. The rule classifier's best candidate was ACC-UNA with a score of 4.0, contributed entirely by the signal boost, with SVC-SUP a distant second, so its confidence was `low`. The GenAI answer also chose ACC-UNA, which is among the rule candidates, so the evidence gate accepted it and the reference source became `ai_unconfirmed`. The rules decision selected RES-ACC-UNA-03 (condition `signal:lock_security`, precedence 40), which sets Critical urgency and High impact and hence P0 with the SLA targets of SLA-P0 (first response 1 hour, resolution 24 hours). Escalation rules ESC-009 (unauthorized access, Specialist Team) and ESC-010 (smart-lock unexplained unlock, Critical Management Escalation) fired, so the level is Critical Management Escalation with DEPT-SEC as primary and DEPT-MGT as supporting department. The follow-up is FUP-002, an escalation acknowledgement due at the P0 first-response target of 1 hour.

The GenAI answer agreed on the category, department, urgency, priority and escalation level. Of its seven resolution steps, four were accepted (`VERIFY_IDENTITY`, `VERIFY_ACCOUNT`, `REVIEW_ACCOUNT_ACTIVITY`, `ESCALATE_CRITICAL_MANAGEMENT`) and three were excluded because rule RES-ACC-UNA-03 neither requires nor recommends them (`ADVISE_STOP_USING`, `LOCK_ACCOUNT`, `SCHEDULE_FOLLOW_UP`). The answer omitted two required actions, `ADVISE_PHYSICAL_KEY` and `REVOKE_SESSIONS`; both belong to the critical set, so RES-001 failed with critical severity and both actions were added to the validated steps with the source `rule`. Of the 52 checks, 39 passed, 4 warned (CLS-001, CLS-004, POL-005, FUP-002), 1 failed (RES-001) and 8 did not apply. Table 11.6 reproduces the score computation from the stored checks.

**Table 11.6 — Verification score of CMP-00616 by dimension**

| Dimension | Applicable weighted checks and outcome | Sum of weight × value | Sum of weights | Score |
|---|---|---|---|---|
| Schema | SCH-001 to SCH-006 pass | 24.0 | 24 | 100.0 |
| Classification | CLS-001 warn (major), CLS-002 pass | 2.5 | 4 | 62.5 |
| Routing | RTE-001 pass (critical), RTE-002 pass | 8.0 | 8 | 100.0 |
| Priority | PRI-001 to PRI-004 pass | 10.0 | 10 | 100.0 |
| Policy | POL-001 to POL-004 pass, POL-005 warn | 12.5 | 13 | 96.2 |
| Resolution | RES-001 fail (critical), RES-002 pass, RES-004 pass | 8.0 | 13 | 61.5 |
| Eligibility | ELG-001 to ELG-003 pass | 9.0 | 9 | 100.0 |
| Escalation | ESC-001 to ESC-004 pass | 12.0 | 12 | 100.0 |
| Follow-up | FUP-001 pass, FUP-002 warn | 1.5 | 2 | 75.0 |
| Communication | RSP-001, RSP-002, RSP-004 to RSP-007 pass | 18.0 | 18 | 100.0 |
| Grounding | HAL-001 to HAL-004 pass | 10.0 | 10 | 100.0 |
| Security | SEC-002 pass | 3.0 | 3 | 100.0 |
| **Total** | | **118.5** | **126** | **94.0** |

The score of 94.0 is above the threshold, but the decision is Manual Review because three triggers fired: REV-002 for the critical RES-001 failure, REV-005 because the rules' own classification had low confidence, and REV-008 because the `lock_security` signal marks a sensitive case that a person must approve. Recomputing the score from the 52 stored check rows reproduces 118.5 / 126 = 94.0 and every dimension score exactly. The complaint was set to Escalated, and the validated decision given to agents contains the six validated steps, the Critical Management Escalation with its rules, the prohibition of asking for credentials and of dismissing the safety concern, and the one-hour timelines of SEC-POL-09:4.3 and SLA-P0. The POL-005 warning is discussed in Section 11.8.

## 11.6 Measured Behaviour

The demonstration database contains 780 validation results, one for each processed complaint, all produced with `openai/gpt-4.1-mini`. Table 11.7 shows the decisions by source.

**Table 11.7 — Stored verification decisions by complaint source**

| Source | Verified | Manual Review | Total |
|---|---|---|---|
| Dataset complaints | 171 | 428 | 599 |
| Holdout evaluation (runs 1 and 2) | 22 | 136 | 158 |
| Adversarial lab | 0 | 18 | 18 |
| Web submissions | 0 | 5 | 5 |
| **All** | **193** | **587** | **780** |

The scores range from 64.8 to 100.0 with a mean of 90.0; the lowest Verified score is 86.6. Of the 587 Manual Review decisions, 539 had a score of 80 or more, so in nine cases out of ten a case is held because a critical check failed or a trigger fired, not because of a low score. Conversely, a Verified decision does not mean that every check passed: 120 of the 193 Verified results contain at least one failed check of major, minor or info severity, most often RES-001 (67 results, a missing non-critical required action) and RSP-007 (23). In these cases the validated decision has already corrected the gap, for example by adding the missing action as a rule step, and a failed communication check keeps the response in `requires_review`.

Pipeline 2 does not simply accept the GenAI answer. Table 11.8 shows how often key checks failed or warned across the 780 stored results.

**Table 11.8 — Outcomes of selected checks in the 780 stored validation results**

| Check | Pass | Warn | Fail | Not applicable |
|---|---|---|---|---|
| RES-001 Required actions present | 335 | 56 | 389 | 0 |
| PRI-001 Urgency matches the rules | 511 | 172 | 97 | 0 |
| CLS-001 Category matches the rules | 468 | 218 | 94 | 0 |
| RTE-001 Primary department matches the routing rules | 699 | 0 | 81 | 0 |
| ESC-002 Escalation level meets the rules | 163 | 0 | 55 | 562 |
| ELG-001 Refund eligibility matches the rules | 472 | 252 | 56 | 0 |
| ESC-001 Required escalation identified | 218 | 0 | 47 | 515 |
| RES-002 No prohibited actions | 734 | 0 | 46 | 0 |
| SCH-004 Cited policies exist | 744 | 0 | 36 | 0 |
| HAL-002 Extracted details appear in the complaint | 750 | 6 | 24 | 0 |
| SEC-001 AI ignored instructions in the complaint | 25 | 0 | 17 | 738 |
| POL-002 No outdated policy cited | 777 | 0 | 3 | 0 |

In 47 cases the GenAI answer missed a mandatory escalation that the rules enforced, and in 81 cases it proposed a primary department that the routing rules did not support; each of these failures is critical and sent the case to manual review. On the 154 unseen holdout cases of evaluation run #1, the GenAI answer contained at least one key-field error in 93 cases, and 92 of them (98.9 percent) were either corrected by the rules or sent to manual review (`reports/genai_python_comparison/summary.md`, Chapter 12).

## 11.7 Tests and Recorded Evidence

Table 11.9 lists the automated tests and recorded runs that demonstrate the pipeline. The automated integration tests run the real API and the real Python validation against a dedicated test database, and answer every GenAI call with the offline test double `tests/support/offline_llm.py`, so that they are deterministic and need no API key; the test double reads only the rendered prompts and never the Rule Matrix. The recorded runs in the demonstration database used the real model.

**Table 11.9 — Tests and recorded evidence for Pipeline 2**

| Evidence | What it demonstrates | Status |
|---|---|---|
| `tests/backend/integration/test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint` (6 cases) | Fault profiles corrupt the GenAI answer; the named check fails and the case goes to Manual Review: missed escalation → ESC-001, wrong department → RTE-001, invented policy → SCH-004, unsupported refund → RSP-002, prohibited action → RSP-006, invented entity → HAL-002 | Tested |
| `tests/backend/integration/test_defects_and_live_changes.py::test_every_adversarial_scenario_is_caught` | Every scenario of `config/adversarial_scenarios.yaml` meets its expectation and no corrupted output is Verified | Tested |
| `tests/backend/integration/test_ai_not_configured.py::test_no_api_key_means_no_ai_output_and_manual_review` | Without GenAI the rules decide and the case goes to review | Tested |
| `tests/backend/integration/test_difficult_cases.py` (18 tests) | Calm critical safety, angry low priority, injection, unsupported refund and compensation, missing information, ambiguity, multi-issue, legal threat, account takeover, privacy exposure | Tested |
| `tests/backend/unit/test_perception_security.py` (33 tests) | Signals, negation, classification, risk precedence, evidence gate, claim grounding, removal of flagged instructions | Tested |
| `tests/backend/unit/test_wording.py` (15 tests) | Older stored text is served in the current wording | Tested |
| Adversarial lab runs LAB-00001 to LAB-00018 (real model, fault profiles applied to its answer) | All 18 went to Manual Review; for example LAB-00013 missed escalation → ESC-001 fail, LAB-00014 wrong department → RTE-001 fail, LAB-00010 outdated policy → POL-002 fail, LAB-00012 request for card number and password → RSP-006 fail | Tested (recorded run) |
| Holdout evaluation run #1, 154 unseen cases | 92 of 93 GenAI key-field errors caught; prompt-injection recall and precision 1.0 | Tested (recorded run) |
| `reports/python_validation_evidence/README.md` and `examples.json` | One real example per validation type (SRS Deliverable 7); written with the earlier check names | Implemented |

## 11.8 Known Limitations

The pipeline is deliberately conservative, and the evidence shows where this costs accuracy or reviewer time.

- **Vocabulary of the rule classifier.** The rules' own classification depends on the terms of `category_rules.yaml`. In holdout case EVL-00030 a damaged-on-arrival hub was classified as STF-MIS (technician misconduct) because the only matching term was "took pictures", which exists for technicians taking photographs; the correct GenAI category PRD-DOA then had no support among the candidates and failed the evidence gate. The case went to manual review with six reasons, so no wrong decision was acted on unreviewed, but the rule classifier is less accurate than the GenAI model on category (75.7 percent against 89.5 percent on the holdout set, Chapter 12).
- **Review rate.** On the holdout set 84.4 percent of cases went to manual review, against 33 percent expected by the dataset labels; the recall of the expected reviews was 94.1 percent. The rate follows from the design choice that sensitive categories, provisional classifications and any critical failure always require a person.
- **Policy applicability lookup.** POL-005 looks up the rules' applicability label by the section reference, and when retrieval also returned outdated versions of the same section, the Outdated entry replaces the Applicable one. CMP-00616 received a minor POL-005 warning for ESC-SOP-12:4.2 although version 3.1 of that section is Active and cited by the rule. In the stored results, 274 of the 520 POL-005 warnings name an Outdated label. The effect on the score is small, because POL-005 has minor severity and a warning costs half of its weight of 1, and POL-005 is not a review trigger; the lookup should nevertheless prefer the Active entry.
- **Verified is not proof of correctness.** In holdout case EVL-00111 both pipelines read a restocking-fee dispute on a wrong-item return as DEL-WRG, while the dataset label is REF-PAR; no critical check failed and no trigger fired, so the case was Verified with a score of 88.9. Agreement between the pipelines is evidence, not proof.
- **Stored wording.** Stored check messages and review reasons keep the wording of the time they were written; the API serves them in the current wording, but exports read directly from the database and the evidence report `reports/python_validation_evidence/README.md` show the earlier names.

## 11.9 Requirement Coverage

Table 11.10 relates the verification requirements of the SRS for Pipeline 2 to the checks that implement them.

**Table 11.10 — SRS verification requirements for Pipeline 2**

| SRS requirement | Checks and mechanism | Status |
|---|---|---|
| Independent Python pipeline; no GenAI API to approve Pipeline 1 | `engine.py` has no provider; score from checks only; REV-005 for provisional classifications | Implemented, Tested |
| Must not simply accept everything | 52 checks; 587 of 780 stored results held for review | Implemented, Tested |
| Complaint category and subcategory | SCH-002, CLS-001, CLS-002, evidence gate | Implemented, Tested |
| Department assignment (Step 23) | SCH-003, RTE-001, RTE-002 | Implemented, Tested |
| Urgency and priority | PRI-001 to PRI-004 | Implemented, Tested |
| Mandatory escalation (Step 39) | ESC-001 to ESC-004; the rules' level is always applied | Implemented, Tested |
| Policy applicability and policy version (Steps 7, 26) | POL-002, POL-005, SCH-004 | Implemented, Tested |
| Resolution eligibility and compensation eligibility (Steps 29 to 31) | ELG-001 to ELG-003, RES-004 | Implemented, Tested |
| Required, prohibited and missing mandatory actions (Step 28) | RES-001, RES-002, RSP-006; missing actions added to validated steps | Implemented, Tested |
| Follow-up requirements | FUP-001, FUP-002, MIS-001, MIS-002 | Implemented |
| Source-document references | SCH-004, POL-001, POL-003, POL-004, HAL-004 | Implemented, Tested |
| Unsupported generated claims (Step 35) | HAL-001 to HAL-003, RSP-002, RSP-004 | Implemented, Tested |
| Contradictory instructions | RES-004, POL-006, REV-007 | Implemented, Tested |
| JSON schema validation (Step 46) | Strict structured output and schema validation before Phase A (Chapter 21); SCH-001 to SCH-006 | Implemented, Tested |
| Verification score (1.6 li) | Weighted formula of `validation_policy.yaml` | Implemented |
| NFR 4: mandatory escalations and critical routing enforced before final verification | Final fields from the rules; ESC-001 and RTE-001 are critical and force Manual Review | Implemented, Tested |

Chapter 12 describes the Comparison Engine, which presents the same contrast between the GenAI answer and the rules field by field, and measures both pipelines against the labels of unseen complaints.
