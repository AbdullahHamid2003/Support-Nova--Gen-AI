# Chapter 17 — Hallucination and Unsupported-Claim Handling

SRS Step 35 requires that "generated factual claims that cannot be traced to the customer complaint, approved policy, approved knowledge base or defined rule matrix" are flagged. Functional requirement xxxii and the Pipeline 2 verification list ("unsupported generated claims", "source-document references") make this the job of the Python Ground-Truth Validation Pipeline. SupportNova treats every factual statement in the structured analysis as a claim that must be traced to a named source. It treats identifiers the system does not know, such as an invented policy, section, order number or amount, as hallucinations. The checks are implemented in `backend/src/supportnova/hallucination_checks/grounding.py` and applied during Phase A in `backend/src/supportnova/python_validation/engine.py`. The customer reply, written later from the validated decision, is checked by the response checks of Chapter 16.

## 17.1 Where unsupported content can appear, and how it is limited

The analysis returned by the first GenAI call (`complaint_analysis.v1`) contains several fields that can carry invented content: the summary, key facts, extracted entities, the list of claims, policy citations (policy ID, section and evidence ID), resolution-step descriptions, agent guidance, the urgency rationale and the classification itself. SupportNova limits this in two ways before any check runs.

First, the prompt `prompts/complaint_analysis/1.2.0.yaml` states the grounding rules explicitly. Entities may only be "values that literally appear in the complaint or in `<verified_facts>`". Claims must list "the important factual statements your analysis relies on, each with its source". The model must "never cite a document or section that is not in `<evidence>`", must not adopt a policy the customer quotes if it is outdated, conflicting or non-existent, and must ask focused clarification questions rather than "invent missing facts".

Second, the structured-output schema is restricted to the live catalog on every request. `constrain_codes()` in `genai_pipeline/schemas.py` writes the active category, subcategory, department, action, follow-up-type and policy-document codes into the schema as enumerations. In strict structured-output mode the model therefore cannot return an unknown category, department, action code or policy ID in those fields. Section numbers and free text are not enumerated, so they can still carry invented content. That is why the checks below assume the model can still be wrong.

## 17.2 The sources a claim can be traced to

Each claim in the analysis has a `statement`, a declared `source_type` and a `source_ref`. `grounding.verify_claims` compares the statement with the text of the declared source. The score is the share of the statement's content words (stemmed, stop words removed) that also occur in the source. Words that only narrate what the customer did or felt, or that point at a source ("customer", "reports", "requests", "strongly", "dislikes", "hate", "concern", "according", "policy", "section", "rule" and similar), are ignored. In the words of the code comment, a model "paraphrases them freely", so they are not facts that need a source. Table 17.1 lists the sources and thresholds.

**Table 17.1 — Sources a claim can be traced to**

| Declared source | Compared with | Accepted when |
|---|---|---|
| complaint | Normalised complaint text (title, description, supporting information) and the product field | At least 50 % of content words found |
| policy, with an evidence ID | Text of that retrieved chunk: document ID, section, heading and body | At least 35 % found |
| policy, other reference | Existence of the referenced policy in the Knowledge Base snapshot | Policy exists |
| metadata | Verified system facts: complaint reference, date, channel, customer type, order ledger, transactions, returns, cancellations, subscriptions, carrier traces, 90-day complaint history | At least 40 % found |
| rule or validated_decision | Rule Matrix decision text (subcategory code and name, department, urgency, priority, escalation level, required actions in customer wording, policy references) plus the complaint | At least 35 % found |
| any other value | — | Never |

The four source kinds correspond to the four origins named in SRS Step 35: the customer complaint (complaint), approved policy and knowledge base (policy), and the defined rule matrix (rule). SupportNova adds the verified system facts (metadata) as a fifth origin, because a statement such as "the order was delivered on 24 June" is correct only if Lumora's own order ledger says so. Policy claims have lower thresholds because policy text is written in formal wording that a model shortens.

## 17.3 Claim verification workflow

Figure 17.1 shows the workflow for one claim. The verdict for every claim, including its score and a note stating what it was compared with (for example "compared with evidence E3"), is stored in the `actual` field of check HAL-001. The reviewer can therefore see exactly which statement failed and why.

![Figure 17.1 — Claim verification workflow](diagrams/security/fig-17-01-claim-grounding-workflow.svg)
*Figure 17.1 — Claim verification workflow*

HAL-001 is not applicable when the analysis lists no claims, passes when every claim is supported, warns when at most 25 % of the claims are unsupported and fails above that. A failure of HAL-001, HAL-002 or HAL-004 fires the manual-review trigger REV-012 (`hallucination_detected` in `rules/complaint_rules/review_rules.yaml`). A flagged case is therefore never verified automatically, even when its overall score is high.

## 17.4 Identifier and detail checks

Claim verification covers only the statements the model chooses to list. The prompt allows at most five claims, so other checks look for the typical signs of a hallucination anywhere in the answer: an identifier or amount that the case does not contain. Table 17.2 lists these checks with their results on the latest validation result of each of the 780 complaints analysed with `gpt-4.1-mini` in the demo database.

**Table 17.2 — Grounding and traceability checks with live results**

| Check | Severity | What Python verifies | Results on 780 analyses |
|---|---|---|---|
| HAL-001 Claims backed by the complaint, policies or rules | major | Claim verdicts (Table 17.1) | 550 pass, 189 warn, 41 fail |
| HAL-002 Extracted details appear in the complaint | major | Every entity value, reduced to letters and digits, occurs in the complaint or verified facts. Product, service, location, person and department names pass with 50 % word overlap. An unknown order, transaction, amount, date or complaint reference fails; other types warn | 750 pass, 6 warn, 24 fail |
| HAL-003 Summary sticks to the facts | minor | Reference numbers and currency amounts in the summary and key facts occur in the complaint or verified facts | 761 pass, 19 fail |
| HAL-004 Policies named in the text exist | major | Every policy ID pattern (for example `REF-POL-02`) in the summary, guidance, step descriptions and urgency rationale exists in the Knowledge Base | 778 pass, 2 fail |
| SCH-004 Cited policies exist | major, critical for an unknown document | Every cited policy ID and section resolves in the Knowledge Base snapshot | 744 pass, 36 fail |
| POL-002 No outdated policy cited | critical | Every cited document has an active version | 777 pass, 3 fail |
| POL-003 Cited policies are in the case evidence | major | Every cited section matches a retrieved evidence item | 683 pass, 88 warn, 9 fail |

Three further mechanisms stop an unsupported value from being used as a fact.

- **Unsupported categories.** `ai_classification_supported()` refuses to use an AI subcategory as the provisional reference when neither it nor its category appears among the deterministic classifier's candidates, that is, when no term or signal in the complaint supports it. The case that motivated this test is a Spark smart plug that is simply offline: the product name must not be read as "sparks" (`tests/backend/unit/test_perception_security.py::test_unsupported_genai_category_is_never_the_provisional_reference`, `tests/backend/integration/test_difficult_cases.py::test_product_name_is_not_a_hazard`).
- **Customer-quoted policies.** `security/injection.unknown_policy_findings()` flags any policy ID, version or section in the complaint that does not exist in the Knowledge Base, before the model sees the text (Chapter 23).
- **Reply amounts and references.** RSP-004 applies the same idea to the customer reply: every amount and reference must be traceable to the case (Chapter 16).

The SCH-004 results show that invented citations are a real behaviour of the model, not only a lab scenario. Of its 36 failures, 33 came from ordinary cases without fault injection. Examples are sections that do not exist, such as `STF-POL-21:10`, `DEL-POL-04:2.2`, `REF-POL-02:5.0` and `WAR-POL-07:7.3`, and section values that do not resolve, such as "general", "N/A", "Troubleshooting" and "3, 5".

## 17.5 What happens to a flagged claim

A flagged claim is recorded, not corrected. The original AI output stays unchanged in `analyses.output`, and the reviewer workspace shows it under "Original AI output". The fields that decide the outcome of the case do not depend on AI claims: classification (when the rules are confident), department, urgency, priority, eligibility, escalation and required actions come from the Rule Matrix decision. The AI summary and key facts are carried into the validated decision only after sentences that repeat flagged injection text have been removed (Chapter 23). A hallucinated fact in the summary is flagged but stays visible, so that the reviewer sees what the model wrote.

Lab scenario LAB-DEF-04 (case LAB-00016, fictional lab data) shows this behaviour. Its fault profile adds the order number LMR-999999, which does not occur in the complaint, to the entities and the summary, and adds "We have located your order LMR-999999." to the reply. HAL-002 failed on the entity, HAL-003 failed on the summary and RSP-004 failed on the reply. The case scored 91.2, above the verification threshold of 80. It still went to Manual Review because HAL-002 fired REV-012. The validated summary still contains the invented sentence, marked by the HAL-003 failure, and the draft stayed at `requires_review`. Table 17.3 lists this and the other deliberate hallucinations used to test the checks.

**Table 17.3 — Deliberate hallucinations and their detection**

| Scenario or test | Injected content | Detected by | Outcome |
|---|---|---|---|
| LAB-DEF-04 (LAB-00016) | Order LMR-999999 added to entities, summary and reply | HAL-002, HAL-003, RSP-004 | Manual Review (REV-012) |
| LAB-POL-02 (LAB-00009) | Citation of `REF-POL-99:9.9`, which does not exist | SCH-004 (critical), POL-003 warning | Manual Review; final decision cites RPL-POL-03 and WAR-POL-07 |
| LAB-POL-01 (LAB-00008) | Customer quotes "REF-POL-77 section 9"; the AI mentions it | Screening (`fake_policy_reference`), HAL-004 | Manual Review; REF-POL-77 never in the final decision |
| LAB-POL-03 (LAB-00010) | Citation of the superseded RET-SOP-23 section 3 | POL-002 (critical) | Manual Review |
| `test_fault_profile_on_custom_complaint[hallucinated_entity-HAL-002]` | Invented order number | HAL-002 fails | Manual Review |
| `test_fault_profile_on_custom_complaint[hallucinated_policy-SCH-004]` | Invented policy | SCH-004 fails | Manual Review |
| `test_claim_grounding_accepts_paraphrase_but_not_invented_facts` | Paraphrase and invented statements | `verify_claims` | Paraphrase accepted; invented fact and invented promise rejected |
| `test_fake_policy_ids_versions_sections` | Unknown policy ID, section and version | `unknown_policy_findings` | All three flagged; a real section is not |

The two fault-profile tests are in `tests/backend/integration/test_defects_and_live_changes.py`, and the two unit tests in `tests/backend/unit/test_perception_security.py`. The integration tests use the offline test double for the GenAI call, while the lab cases above were run with `gpt-4.1-mini` and are summarised in `reports/security_adversarial/summary.md`.

## 17.6 Limitations and false positives

The grounding checks are lexical, and this has consequences in both directions.

**Hallucinations that can pass.** A word-overlap score measures shared vocabulary, not meaning. A statement that reuses the complaint's own words but reverses or combines them differently can reach the threshold. A fact stated only in free text, outside the listed claims, is checked only for identifiers, amounts and policy IDs. The customer-communication call also returns a list of claims, but Phase B does not verify it. The reply is grounded only through its timelines, amounts, references and promise wording (Chapter 16). This is the main reason why SupportNova does not rely on the grounding checks alone. Safety and privacy cases always need human approval (REV-008), a draft is sent only by a user with `complaint:respond`, and every decision field comes from the Rule Matrix.

**False positives observed on live output.** The first live runs showed that the claim check rejected faithful paraphrases. `AI_USAGE.md` lists "paraphrase-aware claim grounding" among the fixes made after the live OpenAI runs. The fix is the narration word list described in Section 17.2, and the unit test above keeps it working with the example of a real model paraphrase ("Customer strongly dislikes the new app icon …" for "I HATE it"). Other measures that reduce false positives are the lower thresholds for policy and rule claims, the acceptance of a policy claim whose reference exists even if it was not retrieved, the 50 % name overlap for product and location entities, the warning band of HAL-001 and the minor severity of HAL-003. False positives remain, and the stored results show where. Table 17.4 gives examples found by inspecting failed checks in the demo database. The examples were chosen by inspection; they are not a measured false-positive rate, because the dataset has no labels for individual claims.

**Table 17.4 — Examples of false positives in live runs**

| Case | Check | What the AI wrote | Why it was flagged |
|---|---|---|---|
| CMP-00225 | HAL-001 | "Customer received an empty box with no product inside." | The complaint says "the box was empty - no Sentinel indoor cam, just packing"; the paraphrase shares too few words |
| CMP-00093 | HAL-001 | A policy claim with source reference "E2,E3" | Two evidence IDs in one field are not recognised as retrieved evidence |
| CMP-00040 | HAL-002 | Date entity "2026-05-04" | The complaint says "since 4 May"; the ISO rewriting is not matched |
| CMP-00004 | HAL-002 | Amount "149.00" | The order ledger holds "USD 149.0"; the extra decimal digit breaks the match |
| CMP-00328 | HAL-003 | "… below the USD 500 high-value threshold" in the key facts | The amount is a Rule Matrix parameter, and HAL-003 accepts only complaint and ledger amounts |
| CMP-00512 | HAL-004 | "… a non-existent policy REF-POL-99" | The AI correctly called the customer's policy fake, but any mention of an unknown ID fails |
| R1-EVL-00081 | RSP-004 | "charged $20 more" in the reply | USD 20 is the difference between USD 199 and USD 179; derived amounts are not traced |

Every false positive in Table 17.4 sends the case to a reviewer instead of verifying it, so it costs review time but cannot release an incorrect reply. Normalising dates and amounts before comparison, accepting several evidence IDs in one reference and accepting rule parameters in HAL-003 would remove most of these cases. None of these refinements is implemented yet (Future Enhancement), and Chapter 43 summarises the grounding limitations.
