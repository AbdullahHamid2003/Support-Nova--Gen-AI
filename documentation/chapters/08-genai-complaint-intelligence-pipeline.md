# Chapter 8 — GenAI Complaint Intelligence Pipeline

The GenAI Complaint Intelligence Pipeline (Pipeline 1) is the part of SupportNova that calls a Generative AI model. It is implemented in `backend/src/supportnova/genai_pipeline/` (context assembly in `context.py`, prompt management in `prompts.py`, output contracts in `schemas.py`, parsing in `parsing.py`, the controlled retry runner in `runner.py`, test-only defect injection in `fault_injection.py` and the vendor adapters in `providers/`) and is driven by the complaint pipeline of Chapter 7. This chapter describes how the model's input is assembled, how the request is built, how the structured output is validated and retried, how the provider is abstracted and configured, and what the pipeline actually did on the demo data.

## 8.1 Purpose

Pipeline 1 turns one complaint, its verified context and the relevant approved policy text into structured complaint intelligence, and then writes the customer-facing reply. Its output is a proposal. The analysis prompt states this to the model directly ("Your analysis is a proposal: an independent Python rule engine validates it afterwards"), and the code enforces it: every field the model returns is checked by the Python Ground-Truth Validation Pipeline (Pipeline 2), and wherever the two disagree the Complaint Resolution Rule Matrix value is used. The model generates and interprets content; it never replaces the business rules, the schema validation, the policy precedence, the escalation enforcement, the audit logic or the security logic (SRS 1.8, item 18).

Pipeline 1 has two stages, each with its own prompt family and JSON schema (Figure 8.1). Stage 1, **complaint analysis**, uses prompt `complaint_analysis` (active version 1.2.0) and returns a `complaint_analysis.v1` object with 37 fields. Stage 2, **customer communication**, runs only after Pipeline 2 has produced the validated decision; it uses prompt `customer_communication` (version 1.0.0) and returns a `customer_communication.v1` object with 7 fields. There are no other prompts: escalation notes, the follow-up message, clarification questions and agent guidance are fields of these two outputs.

![Figure 8.1 — The two stages of the GenAI Complaint Intelligence Pipeline](diagrams/pipelines/fig-08-01-genai-pipeline.svg)
*Figure 8.1 — The two stages of the GenAI Complaint Intelligence Pipeline*

Table 8.1 maps the GenAI tasks listed in SRS section 1.2 to the output fields that carry them.

**Table 8.1 — SRS GenAI tasks and the output fields that carry them**

| SRS GenAI task | Output field(s) | Stage |
|---|---|---|
| Analyze the complaint | `summary`, `key_facts`, `claims` | 1 |
| Identify the primary issue | `primary_issue`, `secondary_issues` | 1 |
| Identify category and subcategory | `issue_category`, `subcategory` | 1 |
| Detect sentiment | `sentiment`, `emotion_indicators` | 1 |
| Determine urgency and priority | `urgency`, `urgency_rationale`, `impact`, `priority` | 1 |
| Extract important entities | `entities` | 1 |
| Recommend the responsible department | `department`, `supporting_departments` | 1 |
| Identify relevant company policies | `policy_references`, `policy_id`, `policy_section` | 1 |
| Generate resolution steps | `resolution_steps`, the three eligibility objects | 1 |
| Determine whether escalation may be required | `escalation_required`, `escalation_level`, `escalation_reason` | 1 |
| Generate escalation notes | `escalation_notes` (six parts) | 1 |
| Generate clarification questions | `missing_information`, `clarification_questions` | 1 |
| Generate internal agent guidance | `agent_guidance`, `response_type` | 1 |
| Generate a professional response | `subject`, `customer_response`, `tone` | 2 |
| Generate follow-up communication | `follow_up_required`, `follow_up_type` (stage 1); `follow_up_message` (stage 2) | 1 and 2 |

## 8.2 Inputs

The SRS requires the application to send "complaint information, customer context, and relevant approved knowledge-based content" to the model. Table 8.2 lists what each stage receives and where it comes from.

**Table 8.2 — Inputs of the two GenAI stages**

| Input | Content | Produced by | Stage 1 | Stage 2 |
|---|---|---|---|---|
| Complaint block | Title, product, references and requested resolution as entered, attachment names, complaint text (normalised, flagged, redacted) | `context.complaint_block` | yes | yes |
| Verified facts | Complaint reference, date, channel, customer type and reference, order-ledger lines, 90-day complaint history | `context.verified_facts` | yes | no |
| Evidence | Evidence items E1–E10 from the Active Knowledge Base | `retriever.retrieve`, `context.evidence_block` | all ten | cited or Applicable items only |
| Policy conflicts | Conflicts resolved by the documented precedence | `context.conflicts_block` | yes | no |
| Reference data | Taxonomy, departments, action catalogue, escalation levels, priority guide, routing policy, follow-up types | `context.reference_values` | yes | no |
| Validated decision | Issue, category, department, priority, escalation, eligibility, next steps, prohibited actions, safety flag, summary | `context.decision_block` | no | yes |
| Timelines, questions, follow-up | Supported timelines, clarification questions, follow-up type and due time | Phase A validated decision | no | yes |
| Tone and customer name | Requested tone, the customer's first name | complaint record, customer profile | no | yes |

## 8.3 Context Assembly

Context assembly follows one rule: stable instructions and trusted reference data go into the system prompt; case data goes into the user prompt, and each part is labelled with its level of trust. The trust statements themselves are part of the prompt (Chapter 21).

### 8.3.1 The Complaint

The complaint text sent to the model is the normalised title, description and supporting information (Section 7.4.1) after two transformations. `injection.annotate` wraps every span flagged by the screener (Chapter 23) in `[[FLAGGED-CUSTOMER-TEXT type=...]]` markers, and `pii.redact` replaces card numbers, CVV and one-time codes, passwords, e-mail addresses and phone numbers. `context.complaint_block` places this text under a header that repeats the title, product or service, order, transaction and previous-complaint references and the requested resolution as the customer entered them, plus the attachment names and types. The whole block is inserted into an element whose tag name carries a random nonce, `<complaint_{nonce} id="CMP-…">`, created per request by `secrets.token_hex(4)`; because the customer cannot know the nonce, text in the complaint cannot close the element. Each stage uses its own nonce. The header lines are passed as entered; only the complaint text body is flagged and redacted, so sensitive data typed into the title or product field would reach the provider unredacted.

### 8.3.2 Customer Context and Complaint History

`context.verified_facts` writes a plain-text block from Lumora's own records, which the prompt declares trustworthy: the complaint reference, submission date, channel, customer type and customer reference; for an order found in the ledger, one line with items, total, shipping method, order, estimated, dispatch and delivery dates, status, Care+ flag and previous replacements, followed by up to six transactions and any return, cancellation, subscription and carrier-trace record; the statement "order reference … was NOT found in the order ledger" when the reference does not exist; and the complaint history of the last 90 days for the same customer (at most six entries, each with reference, date, subcategory, status and order). The customer's name, e-mail and phone number are not part of this block.

### 8.3.3 Evidence and Policy Conflicts

`context.evidence_block` renders each retrieved evidence item as an `<item>` element with the attributes `id` (E1–E10), `policy_id`, `title`, `version`, `type`, `status`, `section`, `heading` and, where known, `page`, followed by the section text. The analysis prompt instructs the model to cite only these items, with the exact `policy_id`, section and `evidence_id` shown, which is what lets check POL-003 trace every citation back to the case evidence (Chapter 9). `context.conflicts_block` lists the precedence-resolved conflicts that touch the evidence, each ending with "Use the prevailing source.", or the word "none".

### 8.3.4 Reference Data

The system prompt of `complaint_analysis` carries seven reference blocks, filled by `context.reference_values` from the live Rule Matrix and the active Knowledge Base versions (Table 8.3). Because they are rebuilt for every request, a category, department or action added by an administrator appears in the next prompt without a code change. Rendered, the analysis system prompt is 24,141 characters long in every one of the 780 valid analysis calls in the demo database.

**Table 8.3 — Reference data blocks in the analysis system prompt**

| Block | Placeholder | Content |
|---|---|---|
| `<taxonomy>` | `$taxonomy` | 35 active subcategories, each as "subcategory SAF-OVH (category SAF - Safety): name - description" |
| `<departments>` | `$departments` | 10 department codes with name and description |
| `<action_catalog>` | `$actions` | 66 action codes with names |
| `<escalation_levels>` | `$escalation_levels` | The 6 escalation levels with their rank |
| `<urgency_and_priority>` | `$priority_guide` | The priority matrix (urgency by impact) and SLA-RUL-15 sections 5, 5.1–5.4 and 6 (urgency and impact levels) |
| `<routing_policy>` | `$routing_policy` | RTE-RUL-14 sections 3 (routing table), 4, 4.1–4.4 (multi-department routing) and 5 (routing precedence) |
| `<follow_up_types>` | `$follow_up_types` | The 6 follow-up types |

### 8.3.5 What the Model Never Receives

The analysis model receives the approved policy text and the catalogues so that its proposal is informed, but it never receives the Rule Matrix decisions for the complaint: not the selected resolution rule, its required and prohibited actions or eligibility outcome, not the urgency floors or escalation rules that fired, not the routing result, and not the deterministic classifier's category, confidence or detected signals. It also never sees other customers' data, the validation checks of Pipeline 2, or any secret. This separation is what makes the AI vs rules comparison (Section 7.9.1, Chapter 12) meaningful: when the model and the rules agree, they agree independently. The only indirect influence is retrieval, which adds the policy sections the Rule Matrix cites for the classifier's best candidates (Section 7.5); the model sees those sections as evidence but is not told why they were chosen. The communication model, in contrast, deliberately receives the validated decision, because its task is to explain that decision, not to form an opinion.

The following excerpt is the end of the user prompt that was rendered for complaint CMP-00616 (fictional data), as stored in the redacted 1,200-character preview of its `ai_runs` record:

```text
</item>
</evidence>
<policy_conflicts>
none
</policy_conflicts>
<verified_facts>
complaint_reference: CMP-00616
submitted: 2026-09-21
channel: email
customer_type: individual
customer_reference: CUST-10150
order_ledger: no order reference supplied.
complaint_history (last 90 days, same customer):
  CMP-00290 on 2026-07-07: PRD-MAL - status Assigned - order LMR-356894
</verified_facts>
<complaint_d0f1400d id="CMP-00616">
Title: Front door found unlocked
Product/service (as entered): Lumora Keystone Smart Lock
Order reference (as entered): (not provided)
…
Complaint text:
Front door found unlocked
Dear Lumora Support,

Good morning. When I came downstairs today I found the door was unlocked, and the Lumora Keystone
Smart Lock log shows it unlocked remotely at 4:40am. I live alone and I am rather shaken. …
</complaint_d0f1400d>
Return the JSON analysis for complaint CMP-00616.
```

## 8.4 Prompt Construction

The prompt text is not written in code. Each version is a YAML file under `prompts/<key>/<version>.yaml` with a system template and a user template that contain `$placeholders`; the files are seeded into the `prompt_versions` table and the active version is loaded from the database for every call (`prompts.active_prompt`). `PromptTemplate.render` substitutes the values with Python's `string.Template.safe_substitute`, which performs plain text replacement: no expression is evaluated, a `$` sign typed by a customer is inserted literally, and an unknown placeholder is left as it is instead of raising an error. The analysis stage fills `$taxonomy`, `$departments`, `$actions`, `$escalation_levels`, `$priority_guide`, `$routing_policy` and `$follow_up_types` in the system template and `$evidence`, `$conflicts`, `$verified_facts`, `$nonce`, `$complaint_id` and `$complaint` in the user template. The communication stage fills `$tone`, `$customer_name`, `$decision`, `$timelines`, `$questions`, `$follow_up`, `$evidence`, `$nonce`, `$complaint_id` and `$complaint`. A new prompt version is refused unless it contains both `$complaint` and `$nonce` (`prompts.create_version`), so the untrusted-data isolation cannot be dropped by an edit. The SHA-256 of each template pair is its fingerprint and is logged with every call. The prompt text is analysed in Chapter 21 and its versions in Chapter 22.

## 8.5 GenAI Request

The pipeline packs each call into an `AIRequest` (`providers/base.py`): stage, system text, user text, schema name, the provider-adapted JSON schema, temperature, maximum output tokens, timeout, attempt number and an optional correction. For the configured provider, `OpenAIProvider.generate` (`providers/http_providers.py`) sends it as one HTTPS request to the OpenAI chat-completions endpoint. Table 8.4 lists the request fields, and the listing below shows the request shape built for CMP-00616 (message content abridged; the request body itself is not stored, the sizes are taken from `ai_runs.request`).

**Table 8.4 — Structured-output request sent to OpenAI**

| Request element | Value |
|---|---|
| Endpoint | `POST {AI_BASE_URL or https://api.openai.com/v1}/chat/completions` |
| Authentication | `Authorization: Bearer` with `AI_API_KEY`, read from `.env.secrets` on the server only |
| `model` | `gpt-4.1-mini` (served as snapshot `gpt-4.1-mini-2025-04-14` in all recorded calls) |
| `messages` | one system message (rendered system template) and one user message (rendered user template, plus validation feedback on a retry) |
| `response_format` | `{"type": "json_schema", "json_schema": {"name": "complaint_analysis_v1", "strict": true, "schema": …}}` |
| `max_completion_tokens` | 6000 for analysis, 2500 for communication (prompt parameters) |
| `temperature` | 0.1 for analysis, 0.3 for communication; sent only for `gpt-4*` and `gpt-3.5*` model names |
| Timeout | `AI_TIMEOUT_SECONDS` = 60 s, applied by the HTTP client to each attempt |

```json
{
  "model": "gpt-4.1-mini",
  "messages": [
    {"role": "system", "content": "You are the SupportNova Complaint Intelligence Analyst for Lumora Home Technologies, … (24,141 characters)"},
    {"role": "user", "content": "<evidence>\n<item id=\"E1\" policy_id=\"SEC-POL-09\" … </complaint_d0f1400d>\nReturn the JSON analysis for complaint CMP-00616. (6,919 characters)"}
  ],
  "response_format": {
    "type": "json_schema",
    "json_schema": {"name": "complaint_analysis_v1", "strict": true, "schema": {"type": "object", "additionalProperties": false, "…": "…"}}
  },
  "max_completion_tokens": 6000,
  "temperature": 0.1
}
```

The schema in the request is not the committed file itself but an adapted copy. `schemas.provider_schema` removes the keywords that strict structured-output modes reject (`minLength`, `maxLength`, `minimum`, `maximum`, `pattern`, `default`, `title`, `examples` and similar), drops `$schema` and `$id`, turns a one-value `const` into an `enum`, sets `additionalProperties: false` on every object and lists every property as required, so that optional fields are expressed as nullable. It never strips a property whose name happens to look like a keyword (`test_schema_adaptation_keeps_field_names_that_look_like_keywords`), and for Gemini it inlines the `$ref` definitions. The adapted schemas of both stages are checked for unsupported keywords in four parametrised tests (`test_structured_output_schema_uses_only_supported_keywords`).

For the analysis stage, `schemas.constrain_codes` then restricts every code field to the live catalogue returned by `context.catalog`. The field names `issue_category` and `category` receive the 11 active category codes as an `enum`, `subcategory` the 35 subcategory codes, `department` and `supporting_departments` the 10 department codes, `action_code` the 66 action codes, `policy_id` the 24 document IDs of the Knowledge Base snapshot and `follow_up_type` the 6 follow-up types; nullable fields stay nullable. The constraint was introduced with prompt 1.1.0 after a live run put a subcategory code into `issue_category`. Because the catalogue is read from the database for each request, a category or policy added at runtime is accepted at once (`tests/backend/integration/test_defects_and_live_changes.py::test_new_category_without_code_changes`). The response is read from `choices[0].message.content`; token usage, the finish reason, the `x-request-id` header and the served model name are kept for the AI-run log, and a `refusal` in the message becomes a non-retryable error (`test_openai_refusal_is_reported`). The exact request each adapter sends is asserted against fake vendor servers, without network access or API key (`test_openai_request_uses_strict_json_schema`, `test_openai_compatible_gateway_via_base_url`).

## 8.6 Structured JSON Generation

With strict JSON-schema mode, the model's reply is a single JSON object with every required field. Its field names follow the SRS sample output wherever the sample has one (`complaint_id`, `issue_category`, `subcategory`, `sentiment`, `urgency`, `priority`, `department`, `policy_id`, `policy_section`, `resolution_steps`, `escalation_required`, `response_type`, `follow_up_required`) and extend it with the fields the other SRS steps need. One deliberate difference from the SRS sample is that classification, department and policy values are codes (`DEL`, `DEL-DLY`, `DEPT-LOG`, `DEL-POL-04`) rather than display names ("Delivery", "Logistics Support"): codes can be validated against the live catalogue, and the user interface shows the names. Resolution steps are objects with an action code from the catalogue, a description and a policy reference instead of free-text strings, which is what allows Pipeline 2 to check required and prohibited actions.

The committed files `schemas/ai/complaint_analysis.v1.schema.json` and `schemas/ai/customer_communication.v1.schema.json` are the runtime contract. They are generated from the Pydantic models in `genai_pipeline/schemas.py` by `scripts/export_schemas.py` and are reproduced in full in Appendix C. In the demo database every one of the 1,560 valid calls ended with the finish reason `stop`, so no output was truncated at the token limit; an analysis reply averaged 1,405 output tokens against the limit of 6,000.

## 8.7 Output Schema Validation

A vendor's structured-output guarantee is not trusted on its own: every reply, from any provider, passes the validation layers of Table 8.5 in `genai_pipeline/parsing.py::validate_output` before the pipeline uses it.

**Table 8.5 — Validation layers applied to every GenAI reply**

| Layer | Tool | What it rejects | Result on failure |
|---|---|---|---|
| JSON extraction | `extract_json` | Empty reply, text that is not JSON; a single code fence or text around one object is tolerated | `invalid_output` with the parser message and position |
| Object check | `validate_output` | A JSON value that is not an object | `invalid_output` |
| JSON Schema | `jsonschema` `Draft202012Validator` with the committed schema | Missing required fields, wrong types, values outside enums, unexpected properties (first 25 errors, with JSON paths) | `invalid_output` with the error list |
| Pydantic | `ComplaintAnalysis` / `CustomerCommunication` `model_validate` | Anything the typed models reject, including extra fields in nested objects | `invalid_output` with the error list |
| Rule Matrix codes | Pipeline 2 checks SCH-001 to SCH-006 (Chapter 11) | Unknown category, subcategory, department, policy, section or action; inconsistent escalation fields | Check failures, review triggers |

This covers each item of SRS Step 46. Required fields and data types are enforced by the JSON Schema and Pydantic layers; valid urgency values and a valid escalation status are schema enums (with SCH-005 checking that `escalation_required` agrees with `escalation_level` and that notes exist when escalating); valid category values, department IDs and policy IDs are enforced twice, by the live enums of the strict request schema and by checks SCH-002, SCH-003 and SCH-004 against the live Rule Matrix and Knowledge Base. The top-level model allows extra fields (`extra="allow"`) so that a field added to the schema file during a live schema change is kept, while the nested objects forbid them.

## 8.8 Invalid Output Handling

SRS Step 47 asks the application to detect incomplete or invalid output, retry in a controlled way, log the failure, prevent infinite retries and route unresolved failures to manual review. `genai_pipeline/runner.py::run_stage` implements all five. Detection is the validation of Section 8.7. Every attempt, valid or not, is written to the `ai_runs` table through the `on_attempt` callback, with stage, attempt number, provider, model, prompt key, version and SHA-256, request metadata (schema name, system and user prompt sizes, a redacted preview of the last 1,200 characters of the user prompt, the correction sent), the response text (up to 20,000 characters), `parsed_ok`, `error_type`, `error_message`, latency, token counts and any fault-injection profile. The number of attempts is fixed by configuration (Section 8.9), so a retry loop cannot run away.

When a stage still has no valid output after its last attempt, the pipeline does not invent one. The analysis is stored with status `invalid_output` and the last error, check SCH-001 fails with the reason ("No usable AI answer after retries …"), review triggers REV-009 (no usable AI answer) and REV-002 (a critical check failed) place the case in the manual review queue, and the Rule Matrix decision is still computed and enforced, including any mandatory escalation. There is no mock or fallback provider: without an API key the configured provider raises `not_configured` on every call, which is not retried, and the complaint goes to review with the rules decision and no drafted response (`test_there_is_no_mock_provider`, `test_a_missing_key_fails_honestly_and_is_not_retried`, `tests/backend/integration/test_ai_not_configured.py::test_no_api_key_means_no_ai_output_and_manual_review`).

Invalid output can also be produced on purpose to test the validation pipeline. `genai_pipeline/fault_injection.py` defines 13 fault profiles, for example `invalid_json` (the first analysis reply is cut to a third of its length), `schema_violation` (required fields removed from the first reply), `missed_escalation`, `wrong_department`, `hallucinated_policy` and `unsupported_refund`. A profile is applied after the provider returns, only when an administrator or reviewer selects it in the Adversarial Lab or an evaluation run, and it is recorded in `ai_runs.fault_injection`, `analyses.fault_injection` and the audit log; it is never applied to normal processing. In the demo database 12 lab analyses were produced with a fault profile, and the six profiles tested in `test_fault_profile_on_custom_complaint` are each caught by the expected check.

## 8.9 Retry Mechanism

`run_stage` makes at most `1 + AI_MAX_RETRIES` attempts per stage, three with the configured `AI_MAX_RETRIES=2`, so one processing run of a complaint makes at most six model calls. What happens after a failed attempt depends on the kind of failure (Table 8.6, Figure 8.2).

**Table 8.6 — Retry policy by error kind**

| Error kind | Raised when | Retried | Pause before the next attempt n + 1 |
|---|---|---|---|
| `invalid_output` | Reply fails JSON, schema or Pydantic validation | yes, with validation feedback | 0.25 s × n |
| `rate_limited` | HTTP 429 | yes | 2 s × 2^(n−1), at most 8 s |
| `connection` | Network or DNS failure | yes | 2 s × 2^(n−1), at most 8 s |
| `timeout` | No response within `AI_TIMEOUT_SECONDS` | yes | 0.5 s × 2^(n−1), at most 8 s |
| `server_error` | HTTP 5xx, including Anthropic's 529 (overloaded) | yes | 0.5 s × 2^(n−1), at most 8 s |
| `authentication` | HTTP 401 or 403 | no | — |
| `bad_request` | Other HTTP 4xx | no | — |
| `refusal` | The model declined (OpenAI refusal, Claude stop reason, Gemini safety block) | no | — |
| `not_configured` | No `AI_API_KEY` on the server | no | — |

![Figure 8.2 — Controlled retry and invalid-output handling in run_stage](diagrams/pipelines/fig-08-02-retry-invalid-output.svg)
*Figure 8.2 — Controlled retry and invalid-output handling in run_stage*

A retry after invalid output is not a blind repeat. The runner builds a correction from the first six validation errors, and the provider appends it to the user message inside a `<validation_feedback>` element (`AIProvider.user_content`), so the model sees exactly what was wrong:

```text
<validation_feedback>
Your previous response failed validation: <up to 6 errors with JSON paths>. Return only one JSON object
that matches the schema exactly.
Return a corrected JSON object only.
</validation_feedback>
```

Provider errors are retried with exponential back-off because rate limits and network drop-outs need a few seconds to clear. For the Anthropic adapter the SDK's own retries are disabled (`max_retries=0`), so that the pipeline runner owns the policy and every attempt is logged as retry evidence. The retry logic is exercised with the real OpenAI adapter against a scripted fake server: invalid JSON is retried with the validation errors and then accepted (`test_invalid_json_is_retried_with_the_validation_errors_then_accepted`), a missing required field is retried (`test_schema_violation_is_retried`), five invalid replies stop after exactly three requests with an `invalid_output` error (`test_retries_are_bounded_and_the_failure_is_reported`), and a 503 is retried while a 401 is sent only once (`test_transient_errors_are_retried_but_authentication_errors_are_not`). The mapping of HTTP statuses to error kinds is tested for OpenAI (429, 503, 401, 400) and Anthropic (429, 529, 500, 401, 400).

The one invalid-output attempt in the demo database shows the mechanism end to end. Lab complaint LAB-00018 was run with the `invalid_json` profile; its first analysis reply was cut short and rejected, and the second attempt, carrying the correction, was accepted (Table 8.7). The complete attempt records are exported in `reports/genai_pipeline_evidence/invalid_response_and_retry.json`.

**Table 8.7 — Recorded retry of LAB-00018 (fault profile invalid_json)**

| Attempt | Stage | parsed_ok | error_type | Error message or correction | Latency |
|---|---|---|---|---|---|
| 1 | analysis | false | `invalid_output` | "The response is not valid JSON (Expecting property name enclosed in double quotes at position 1760)." | 16,318 ms |
| 2 | analysis | true | — | correction: "Your previous response failed validation: The response is not valid JSON (…). Return only one JSON object that matches the schema exactly." | 10,322 ms |
| 1 | communication | true | — | — | 5,868 ms |

## 8.10 AI Provider Abstraction

Pipeline code depends only on the abstract class `AIProvider` in `providers/base.py`, whose single method `generate(request: AIRequest) -> AIResponse` returns the raw reply text with provider, model, latency, token counts, stop reason, request ID and served model; validation always happens in the runner, never in an adapter. `providers/__init__.py::build_provider` selects the adapter from configuration: `AI_PROVIDER` is `openai`, `anthropic`, `gemini` or `real` (which infers the vendor from the key prefix `sk-ant-` or `AIza`, or from the model name), and `AI_MODEL` overrides the vendor's default model. `get_provider` caches the instance and rebuilds it when the provider, model or key presence changes. Switching vendor is therefore a configuration change, with no code change (`test_factory_selects_the_configured_provider`). The value `mock` is rejected by the settings validator, and the test suite answers model calls with an offline test double that exists only in `tests/support/offline_llm.py` and is installed with `providers.use_provider`; it reads only the rendered prompt text, like a real model, and never the Rule Matrix. Table 8.8 compares the three adapters.

**Table 8.8 — Provider adapters**

| Adapter | Transport | Structured output | Default model | Notable behaviour | Status |
|---|---|---|---|---|---|
| `OpenAIProvider` | REST, `httpx` | `response_format` `json_schema`, `strict: true` | `gpt-4.1-mini` | `AI_BASE_URL` allows an OpenAI-compatible gateway | Implemented, Tested, used for all recorded runs |
| `AnthropicProvider` | Official `anthropic` SDK | `output_config.format` with the JSON schema | `claude-opus-5` | System prompt marked for prompt caching; `AI_EFFORT`; server-side refusal fallback for supporting models; no sampling parameters sent | Implemented, Tested against a fake server |
| `GeminiProvider` | REST, `httpx` | `responseMimeType: application/json` with `responseJsonSchema` | `gemini-2.5-flash` | Key sent in the `x-goog-api-key` header, never in the URL; falls back to JSON mode if the schema field is rejected | Implemented, Tested against a fake server |

The Anthropic and Gemini adapters are tested only against fake vendor servers (`test_anthropic_request_uses_structured_output_and_parses_the_reply`, `test_anthropic_refusal_is_not_retried_as_invalid_output`, `test_gemini_key_travels_in_a_header_never_the_url`, `test_gemini_falls_back_to_json_mode_when_schema_is_rejected`, `test_gemini_safety_block_is_a_refusal`); no live run with those vendors has been recorded.

## 8.11 Generation Configuration

Table 8.9 lists the generation settings in force for the recorded runs and where each is defined. Per-stage temperature and output limit come from the `params` of the active prompt version, so they are versioned with the prompt; the environment settings `AI_TEMPERATURE` and `AI_MAX_OUTPUT_TOKENS` are only fallbacks for a prompt version without parameters. The file `reports/genai_pipeline_evidence/provider_and_generation_config.json` exports the environment-level values (temperature 0.1, 4,096 output tokens), which is why it shows a lower token limit than the 6,000 actually used for analysis.

**Table 8.9 — Generation configuration**

| Setting | Value | Defined in |
|---|---|---|
| Provider | `openai` | `AI_PROVIDER`; default in `core/config.py` |
| Model | `gpt-4.1-mini` | `AI_MODEL`; `DEFAULT_MODELS` in `core/config.py` |
| Analysis temperature | 0.1 | `params` of `prompts/complaint_analysis/1.2.0.yaml` |
| Analysis maximum output tokens | 6,000 | `params` of `prompts/complaint_analysis/1.2.0.yaml` |
| Communication temperature | 0.3 | `params` of `prompts/customer_communication/1.0.0.yaml` |
| Communication maximum output tokens | 2,500 | `params` of `prompts/customer_communication/1.0.0.yaml` |
| Timeout per attempt | 60 s | `AI_TIMEOUT_SECONDS` |
| Retries after the first attempt | 2 (3 attempts per stage) | `AI_MAX_RETRIES` |
| Fallback temperature and output limit | 0.1 and 4,096 | `AI_TEMPERATURE`, `AI_MAX_OUTPUT_TOKENS` |
| Structured output | strict JSON schema from `schemas/ai/`, live code enums for analysis | `schemas.provider_schema`, `constrain_codes` |
| Claude-only settings | `AI_EFFORT=medium`, `AI_REFUSAL_FALLBACK=true` | `core/config.py`; not used by the OpenAI runs |
| API key | `AI_API_KEY` in `.env.secrets`, server side only | `core/config.py` `_env_files` |

The key is never returned to the browser; `GET /api/v1/ai/status` reports only whether a key is configured (`tests/backend/api/test_security_api.py::test_ai_key_never_exposed`), and `.env.secrets` takes precedence over `.env` (`test_secrets_file_overrides_the_settings_file`). The Prompts & AI page shows the resolved provider, model, key status, timeout per attempt, attempts per stage and the 13 fault profiles (Chapter 22, Figure 22.2).

## 8.12 Required GenAI Output Schema

### 8.12.1 complaint_analysis.v1

The analysis output has 37 top-level fields, all required; optional content is expressed as `null`. Table 8.10 documents each field, its type, its meaning and the check that validates it. "jsonschema" means that only the structural validation of Section 8.7 applies; "live enum" means that the strict request schema restricts the value to the live catalogue.

**Table 8.10 — Fields of complaint_analysis.v1**

| Field | Type | Meaning | Validated by |
|---|---|---|---|
| `schema_version` | string, const "1.0" | Schema version marker | jsonschema |
| `complaint_id` | string | Reference of the analysed complaint | jsonschema (type only) |
| `summary` | string | At most two sentences for the agent | HAL-003, HAL-004, SEC-001; flagged sentences removed |
| `key_facts` | array of string | At most five key facts | HAL-003; flagged items removed |
| `primary_issue` | Issue: label, category, subcategory, evidence_quote | The issue with the greatest impact or risk | SCH-002, CLS-001, CLS-002 |
| `secondary_issues` | array of Issue | Further issues in the same complaint | SCH-002, CLS-003 |
| `issue_category` | string, live enum | Category code, for example `ACC` | SCH-002, CLS-001 |
| `subcategory` | string, live enum | Subcategory code, for example `ACC-UNA` | SCH-002, CLS-002 |
| `sentiment` | enum of 4 | Customer tone, Positive to Strongly Negative | CLS-004 (info, zero weight) |
| `emotion_indicators` | array, enum of 7 | Frustration, Anger, Disappointment, Confusion, Urgency, Anxiety, Satisfaction | jsonschema |
| `urgency` | enum of 4 | Business-risk urgency, Low to Critical | PRI-001, PRI-003, SEC-001 |
| `urgency_rationale` | string | One-sentence reason | HAL-004 |
| `impact` | enum of 3 | Low, Medium, High | PRI-004 |
| `priority` | enum P0 to P3 | Proposed priority | PRI-002, PRI-004 |
| `entities` | array of Entity: type (11 values), value | Values found in the complaint or verified facts | HAL-002, CLS-005 |
| `department` | string, live enum | Primary department code | SCH-003, RTE-001 |
| `supporting_departments` | array of string, live enum | Supporting department codes | SCH-003, RTE-002 |
| `policy_references` | array of PolicyCitation: policy_id (live enum), section, evidence_id, applicability (4 values), reason | Cited policy sections | SCH-004, POL-001 to POL-006 |
| `policy_id` | string or null, live enum | Main policy (SRS sample field) | jsonschema and live enum only |
| `policy_section` | string or null | Main section (SRS sample field) | jsonschema |
| `resolution_steps` | array of ResolutionStep: action_code (live enum), description, policy_ref | Ordered resolution steps | SCH-006, RES-001 to RES-004, HAL-004 |
| `refund_eligibility` | Eligibility: status (4 values), reason, policy_ref | Proposed refund eligibility | ELG-001, RES-004, SEC-001 |
| `replacement_eligibility` | Eligibility | Proposed replacement eligibility | ELG-002, RES-004 |
| `compensation_eligibility` | CompensationEligibility: status, type (5 values or null), amount_usd, reason, policy_ref | Proposed compensation | ELG-003, RES-004, SEC-001 |
| `escalation_required` | boolean | Escalation proposed | SCH-005, ESC-001, ESC-003, SEC-001 |
| `escalation_level` | enum of 6 | Proposed escalation level | SCH-005, ESC-002, ESC-003 |
| `escalation_reason` | string or null | Short reason | jsonschema |
| `escalation_notes` | EscalationNotes or null: summary, key_facts, reason, actions_taken, relevant_policy, required_next_action | Internal escalation notes (SRS Step 38) | SCH-005, ESC-004 |
| `response_type` | string | Kind of reply needed (SRS sample field) | jsonschema |
| `follow_up_required` | boolean | Follow-up proposed | FUP-001 |
| `follow_up_type` | enum of 6 or null, live enum | Proposed follow-up type | FUP-002 |
| `missing_information` | array of MissingInfo: field, reason | Information needed to resolve safely | MIS-001 |
| `clarification_questions` | array of string | Focused questions for the customer | MIS-001, MIS-002 |
| `agent_guidance` | array of string | At most four internal instructions | HAL-004, SEC-001 |
| `claims` | array of Claim: statement, source_type (5 values), source_ref | Factual statements and their sources | HAL-001 |
| `manipulation_detected` | boolean | The model noticed manipulation | reported in the SEC-001 message and in evaluation results |
| `manipulation_notes` | string or null | What the model noticed | jsonschema |

Six fields are validated structurally only: `complaint_id`, `emotion_indicators`, `policy_section`, `escalation_reason`, `response_type` and `manipulation_notes`, and `policy_id` additionally by its live enum. None of them drives a decision; the policy citations that matter are checked entry by entry in `policy_references`, and the complaint reference comes from the complaint record, not from the model.

### 8.12.2 customer_communication.v1

**Table 8.11 — Fields of customer_communication.v1**

| Field | Type | Meaning | Validated by |
|---|---|---|---|
| `schema_version` | string, const "1.0" | Schema version marker | jsonschema |
| `complaint_id` | string | Reference of the complaint | jsonschema (type only) |
| `tone` | enum of 4 | Tone the model used | recorded; RSP-005 checks the text against the requested tone |
| `subject` | string | Subject line of the reply | stored (first 240 characters) |
| `customer_response` | string | The reply to the customer | RSP-001 to RSP-006, SEC-002 |
| `follow_up_message` | string or null | Message for the scheduled follow-up | RSP-007; stored with the follow-up |
| `claims` | array of Claim | Statements made and their sources | jsonschema |

### 8.12.3 Example of Stored Output

The following JSON is the analysis stored for complaint CMP-00616 (fictional data; abridged with "…"; the complete object and the communication output are in Appendix D). It shows the model's proposal before validation; Section 7.10 describes how Pipeline 2 corrected it.

```json
{
  "schema_version": "1.0",
  "complaint_id": "CMP-00616",
  "summary": "Customer reports an unexplained remote unlock event on their Lumora Keystone Smart Lock, causing safety and security concerns.",
  "primary_issue": {"label": "Unexplained Smart Lock Unlock Event", "category": "ACC", "subcategory": "ACC-UNA", "evidence_quote": "Unexplained lock or unlock events are critical security incidents. …"},
  "secondary_issues": [],
  "issue_category": "ACC",
  "subcategory": "ACC-UNA",
  "sentiment": "Negative",
  "emotion_indicators": ["Anxiety", "Urgency", "Frustration"],
  "urgency": "Critical",
  "impact": "High",
  "priority": "P0",
  "department": "DEPT-SEC",
  "supporting_departments": ["DEPT-MGT"],
  "policy_references": [
    {"policy_id": "SEC-POL-09", "section": "5.1", "evidence_id": "E1", "applicability": "Applicable", "reason": "Defines unexplained lock events as critical security incidents requiring investigation."},
    {"policy_id": "ESC-SOP-12", "section": "4.2", "evidence_id": "E4", "applicability": "Applicable", "reason": "Mandates critical management escalation for unexplained smart-lock unlock events."},
    "…"
  ],
  "policy_id": "SEC-POL-09",
  "policy_section": "5.1",
  "resolution_steps": [
    {"action_code": "VERIFY_IDENTITY", "description": "Verify customer identity to ensure secure handling of the account.", "policy_ref": "SEC-POL-09:5.1"},
    {"action_code": "ESCALATE_CRITICAL_MANAGEMENT", "description": "Escalate the case to Critical Management due to the high risk of security breach.", "policy_ref": "ESC-SOP-12:4.2"},
    "…"
  ],
  "refund_eligibility": {"status": "not_applicable", "reason": "No refund requested or applicable for security incident.", "policy_ref": null},
  "escalation_required": true,
  "escalation_level": "Critical Management Escalation",
  "escalation_notes": {"summary": "…", "key_facts": ["Remote unlock event at 4:40am recorded in lock log.", "…"], "reason": "…", "actions_taken": ["…"], "relevant_policy": ["SEC-POL-09:5.1", "ESC-SOP-12:4.2"], "required_next_action": "Account Security team to conduct detailed investigation and coordinate with management."},
  "response_type": "Apology and Resolution Update",
  "follow_up_required": true,
  "follow_up_type": "Resolution confirmation",
  "missing_information": [{"field": "order reference", "reason": "Order reference is needed to verify product warranty and purchase details."}],
  "clarification_questions": ["Please provide the order reference or purchase details for the Lumora Keystone Smart Lock.", "…"],
  "agent_guidance": ["Verify the customer's identity and account before proceeding.", "…"],
  "claims": [{"statement": "The smart lock log shows a remote unlock event at 4:40am.", "source_type": "complaint", "source_ref": "complaint"}, "…"],
  "manipulation_detected": false,
  "manipulation_notes": null,
  "…": "…"
}
```

## 8.13 Measured Behaviour

All recorded runs used OpenAI gpt-4.1-mini with prompts `complaint_analysis` 1.2.0 and `customer_communication` 1.0.0; the demo database holds 780 completed analyses and 1,591 logged model calls (Table 8.12).

**Table 8.12 — Measured behaviour of the two GenAI stages**

| Measure | Analysis stage | Communication stage |
|---|---|---|
| Model calls logged in `ai_runs` | 789 | 802 |
| Valid structured outputs | 780 | 780 |
| Failed attempts | 9: 4 connection, 4 timeout, 1 invalid output | 22: all connection |
| Analyses that needed a second attempt | 9 | 22 |
| Analyses without a valid output after retries | 0 | 0 |
| Mean latency of valid calls | 16,512 ms | 5,563 ms |
| p50 and p95 latency of valid calls | 15,973 ms and 23,865 ms | 5,203 ms and 8,557 ms |
| Mean input and output tokens per valid call | 9,598 and 1,405 | 1,684 and 322 |
| Total input and output tokens | 7,496,455 and 1,097,603 | 1,313,446 and 251,306 |
| Rendered system prompt | 24,141 characters | 2,549 characters |
| Mean rendered user prompt | 6,520 characters | 3,713 characters |
| Finish reason of valid calls | `stop` in all 780 | `stop` in all 780 |

Of the 1,591 attempts, 1,560 were valid and 31 failed (`reports/genai_pipeline_evidence/attempt_statistics.json`): 26 connection errors (DNS failures, "getaddrinfo failed"), 4 timeouts and 1 invalid output. Every failure was recovered by the second attempt; no stage needed a third attempt and no analysis was left without a valid output. In strict JSON-schema mode, gpt-4.1-mini never returned an invalid structure on its own in these runs: the only invalid-output attempt was the deliberately injected one of Table 8.7. Of the 42 analyses of complaints that the injection screener flagged, the model set `manipulation_detected` in 40, and it flagged one complaint the screener had not.

Valid structure is not the same as correct content. On the 154 unseen holdout cases of evaluation run 1, the model's category matched the expected label in 89.5% of cases and its department in 92.1%, but its urgency in 68.4%, its priority in 62.5% and its policy-reference set in 5.9% (`reports/genai_python_comparison/summary.md`). These are the proposals that Pipeline 2 checks and, where they disagree with the Rule Matrix, overrides; Chapter 12 reports the comparison and its evaluation. Two recorded limits remain: the full pipeline meets the 20-second target for only 32.4% of dataset complaints (Section 7.11, Chapter 35), and gpt-4.1-mini was the only model measured.

## 8.14 Compliance with the SRS GenAI Requirements

**Table 8.13 — Status of the SRS GenAI pipeline requirements**

| Requirement | Status | Evidence |
|---|---|---|
| Integration with an approved GenAI API (1.6 xii) | Implemented, Tested | OpenAI adapter, 780 live analyses; adapter tests |
| Predefined structured JSON output (1.6 xliii) | Implemented, Tested | `schemas/ai/*.schema.json`, strict `json_schema` mode |
| JSON schema validation by Python (Step 46, 1.6 xliv) | Implemented, Tested | `parsing.validate_output`, SCH-001 to SCH-006 |
| Invalid response handling (Step 47) | Implemented, Tested | `runner.run_stage`, Table 8.6, four retry tests |
| Prompts centrally stored and versioned (Step 48) | Implemented | `prompts/`, `prompt_versions` table (Chapter 22) |
| Prompt version, provider, model, timestamp, policy version per analysis (Step 49) | Implemented, Tested | `analyses.prompt_versions`, `provider`, `model`, `created_at`, `policy_versions` |
| Complaint treated as untrusted data (Step 50) | Implemented, Tested | nonce element, flagged spans, SEC-001 (Chapter 21) |
| No fake GenAI responses (1.8, item 17) | Implemented, Tested | no mock provider; `test_no_api_key_means_no_ai_output_and_manual_review` |
| GenAI does not replace Python rules (1.8, item 18) | Implemented, Tested | Rule Matrix decision enforced (Chapter 7) |
| Evidence: provider, model, templates, versions, configuration | Implemented | `reports/genai_pipeline_evidence/*.json` |
| Evidence: sample API requests | Partial | Request metadata and a redacted 1,200-character preview are stored, not the full request body |
| Evidence: invalid responses and retries | Implemented | `invalid_response_and_retry.json`; the only invalid output was deliberately injected |
| Performance: recommendation within 20 s (NFR 1) | Partially met | 32.4% of dataset complaints within 20 s |
