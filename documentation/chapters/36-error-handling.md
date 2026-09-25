# Chapter 36 — Error Handling

The SRS requires that API, parsing, validation and database errors are handled (section 1.6, item lxxiv). For invalid GenAI output it also prescribes the behaviour exactly: detect the error, retry with a controlled strategy, log the failure, prevent infinite retries and route unresolved failures to manual review (Step 47). SupportNova's error handling follows three rules. A request never fails with an unexplained crash: every error becomes a documented HTTP status with a stable machine-readable code. A GenAI failure never produces invented output and never removes the Python decision: the case is still validated against the Rule Matrix and goes to a person. And a complaint is never left stuck in processing. This chapter describes the error model, then each error condition with its detection, response and recovery.

## 36.1 Error model and response format

All application errors derive from `AppError` in `backend/src/supportnova/core/errors.py`. Each subclass carries an HTTP status and a stable code. `backend/src/supportnova/api/errors.py` installs handlers that turn every exception into the same JSON envelope, `{"error": {"code", "message", "details", "request_id"}}`. The `request_id` is also returned in the `X-Request-ID` response header (`api/middleware.py`) and written into every log line, so a message a user reports can be matched to the server log. Stack traces are logged server-side only, in the structured JSON log of `core/logging.py`, and are never returned to the client: an unexpected exception reaches the client only as "An unexpected error occurred. Please try again."

**Table 36.1 — Error classes and their HTTP responses**

| Error | HTTP | Code | Raised when |
|---|---|---|---|
| `ValidationFailed` | 422 | `validation_error` | Field errors, an invalid status transition, an invalid rule edit, an unsupported export format |
| FastAPI `RequestValidationError` | 422 | `validation_error` | Wrong parameter or body types, for example `page_size=201` |
| `AuthenticationFailed` | 401 | `authentication_required`, `invalid_credentials`, `account_locked` | No or invalid session, wrong password, locked account |
| `PermissionDenied` | 403 | `permission_denied`, `csrf_failed` | Missing permission or CSRF token; every case is audited as `access.denied` |
| `NotFound` | 404 | `not_found` | Unknown complaint, document, report or review, and another customer's complaint |
| `Conflict` | 409 | `conflict`, `duplicate_complaint` | Duplicate submission or document, existing document version, evaluation run already running |
| SQLAlchemy `IntegrityError` | 409 | `conflict` | A database constraint rejects the change |
| `DocumentProcessingError` | 422 | `document_processing_error` | Corrupted, encrypted, image-only or empty document, unsupported format |
| Rate limit (middleware) | 429 | `rate_limited` | More than 240 requests (20 for login) per minute from one peer address; `Retry-After: 30` |
| `RetrievalError` | 503 | `retrieval_error` | An external embedding provider fails (only when `EMBEDDING_PROVIDER` is not `local`) |
| SQLAlchemy `OperationalError` | 503 | `database_unavailable` | The database cannot be reached |
| Other `SQLAlchemyError` | 500 | `database_error` | Any other database error |
| `AIProviderError`, `AITimeout` | 502, 504 | `ai_provider_error`, `ai_timeout` | GenAI errors; inside the pipeline they are caught by the retry runner and recorded, not returned |
| Any other exception | 500 | `internal_error` | Anything unexpected; logged with its stack trace |

The frontend turns the envelope into an `ApiError` with the status, the code and a map of field errors (`frontend/src/lib/api.ts`). Forms show the field messages next to the fields, and pages show an error panel with a "Try again" button (`ErrorState` in `components/app/common.tsx`). Both behaviours are covered by the frontend tests (Chapter 33, TC-FE-04 and TC-FE-09).

## 36.2 Handling of each error condition

Table 36.2 lists the error conditions and how SupportNova detects them, responds and recovers. The HTTP column applies to the request that caused the error. Errors inside the background pipeline never produce an HTTP error, because the submission has already returned 202; they are recorded on the complaint, and the complaint's status and review state show them.

**Table 36.2 — Error conditions, detection, response and recovery**

| Condition | Detection | Response | Recovery | Source files |
|---|---|---|---|---|
| Invalid complaint | `validate_submission`: title 5 to 180 characters, description at least 20 characters and 4 words and at most 8,000, supported option values, reference formats, previous complaint exists and belongs to the customer; Pydantic hard caps of 200 and 10,000 characters | `POST /complaints/validate` returns 200 with an `errors` list (live form check); `POST /complaints` returns 422 with `details` per field | The user corrects the fields; nothing is stored. Bulk imports use lenient mode: unsupported values fall back to defaults with a `complaint.intake_warnings` event, and malformed references are kept so REV-014 flags them | `services/complaints.py`, `api/v1/complaints.py` |
| Missing mandatory fields | Empty title or description (whitespace counts as empty); missing customer type or channel | 422 with the missing fields | For customers the customer type comes from their profile, so the form never asks for it | `services/complaints.py` |
| Missing case information | Missing-information rules find facts the subcategory needs (for example the order reference) | Not an error: the complaint is processed; MIS-001 and MIS-002 check the AI's questions | The validated decision carries clarification questions; after the response is sent the case moves to Awaiting Customer; the customer's answer (`POST /complaints/{ref}/clarify`, 202) triggers re-analysis | `python_validation/engine.py`, `api/v1/complaints.py` |
| Duplicate submission | Same customer, same normalised text hash within 24 hours | 409 `duplicate_complaint` with `details.duplicate_of` | The user is pointed to the existing case; a reworded near-duplicate is linked and closed instead of opening a second case | `services/complaints.py`, `services/pipeline.py` |
| Invalid document | `validate_upload`: empty file, size above `MAX_UPLOAD_MB` (15), executable extension or header, extension and magic bytes disagree, DOCX with macros, too many entries or an unsafe expanded size; metadata errors; a newer Active version exists | 422 with a message and the file name; an identical file (same SHA-256) or an existing version returns 409 | The administrator fixes and re-uploads; nothing is stored for a rejected file | `security/files.py`, `document_processing/validation.py`, `services/documents.py` |
| Parsing failure | PyMuPDF or python-docx cannot open the file; the PDF is encrypted or has no extractable text; no readable content | 422 `document_processing_error` | The upload is rejected before any version is stored; the Lab document scan uses the same parser for a dry run | `document_processing/parsers.py` |
| AI API failure | The adapter maps the vendor response: 429 `rate_limited`, 5xx `server_error`, network error `connection` (retryable); 401/403 `authentication`, other 4xx `bad_request` (not retryable) | No HTTP error; each attempt is stored in `ai_runs` with `error_type` and message, and a warning is logged | Retry with back-off (Section 36.3); after the last attempt the stage fails: SCH-001 fails, REV-009 `invalid_ai_output`, Manual Review with the rules decision | `genai_pipeline/providers/http_providers.py`, `anthropic_provider.py`, `runner.py` |
| Timeout | `httpx` timeout of `AI_TIMEOUT_SECONDS` (60 s) raises `AITimeout` (kind `timeout`, retryable) | Recorded on the attempt | Back-off, then retry; all 4 timeouts in the demo database succeeded on the second attempt | `http_providers.py`, `runner.py` |
| Invalid JSON | `extract_json` accepts plain or fenced JSON, then tries the outermost braces; otherwise "The response is not valid JSON (… at position n)" | Attempt stored with `error_type = invalid_output` | The next attempt carries a correction with the errors; LAB-00018 was rejected at position 1760 and accepted on retry | `genai_pipeline/parsing.py`, `runner.py` |
| Schema mismatch | jsonschema (Draft 2020-12) against `schemas/ai/*.schema.json`, then Pydantic; up to 25 errors as "path: message"; vendor-side strict JSON schema restricted to catalogue codes | Attempt stored as `invalid_output` | Retry with the errors, bounded by `AI_MAX_RETRIES`; after that SCH-001 fails and the case goes to Manual Review | `genai_pipeline/parsing.py`, `schemas.py` |
| AI refusal | OpenAI `refusal`, Anthropic `stop_reason: refusal`, Gemini `SAFETY` | Kind `refusal`, not retryable | The stage fails at once; SCH-001 and Manual Review as above | Provider adapters |
| AI not configured | No `AI_API_KEY`: `UnconfiguredProvider` raises `not_configured` (not retryable) | One attempt per stage, both recorded; the header shows "AI not configured"; `/api/v1/health` reports `ai_mode: not_configured` | No output and no response draft are produced; SCH-001 fails with "not configured"; Manual Review; the rules decision, including a required safety escalation, still applies | `genai_pipeline/providers/__init__.py`, `api/v1/system.py` |
| Retrieval failure | No eligible evidence for the complaint; or an external embedding provider fails (`RetrievalError`) | Empty evidence is not an error; an embedding error is 503 on a search request | Empty evidence triggers REV-004 `missing_policy_support` and Manual Review; an exception during the pipeline follows the pipeline-failure path below. The default local embedder has no network dependency | `knowledge_base/retriever.py`, `knowledge_base/embeddings.py`, `python_validation/engine.py` |
| Database failure | `OperationalError` or other `SQLAlchemyError`; constraint violations as `IntegrityError` | 503 `database_unavailable`, 500 `database_error` or 409 `conflict`; `/api/v1/health` reports `degraded` | Each request and background job runs in its own session, rolled back on error (`session_scope`); audit entries of a rolled-back transaction are discarded with it; the pool uses `pool_pre_ping`; interrupted complaints are resubmitted on start-up (`requeue_stuck`) | `api/errors.py`, `database/base.py`, `audit/service.py`, `services/worker.py` |
| Validation mismatch | One of the 52 checks fails because the AI disagrees with the Rule Matrix | Not an error: the check is stored with expected and actual values | The validated decision uses the rules value; review reasons (for example REV-001, REV-002, REV-006) send the case to Manual Review; the "AI vs rules" tab shows each difference | `python_validation/engine.py`, `services/pipeline.py` |
| Unauthorised action | No or expired session; missing permission; missing CSRF token on a cookie request; customer opens another customer's case; too many requests | 401, 403 (audited as `access.denied`), 404, 429 | The user signs in, or the action is refused; failed logins increment a counter and lock the account for 5 minutes after 5 failures | `api/deps.py`, `api/errors.py`, `api/v1/auth.py`, `api/middleware.py` |
| Prompt injection | `injection.scan` finds instruction-like or manipulative text | Not an error: the complaint is accepted and processed as data | Flagged spans are annotated for the model; REV-010 sends the case to Manual Review; SEC-001 fails if the AI obeyed; flagged sentences are removed from the validated summary | `security/injection.py`, `python_validation/engine.py` |
| Unsupported resolution | AI steps outside the rule's required or recommended actions, prohibited actions (RES-002), unsupported promises or timelines (RSP-002, RSP-003), prohibited statements (RSP-006) | The steps are listed under "AI proposals rejected" with the reason; the response draft is marked `requires_review` | Sending is refused with 422 until a reviewer approves or an edit passes the same checks (`validate_edited_response`) | `python_validation/engine.py`, `hallucination_checks/promises.py`, `api/v1/complaints.py`, `services/reviews.py` |
| Unexpected pipeline exception | Any exception escaping `_process` | The complaint's stage becomes `failed`, `needs_review` is set, a `pipeline.failed` history event and a `complaint.processing_failed` audit entry are written | A review with reason `pipeline_error` is queued (except for evaluation cases); the status returns from Processing to New so the case can be reprocessed | `services/pipeline.py` |
| Invalid state change or rule edit | `transition` checks the allowed status graph; rule edits are rebuilt as a candidate matrix and integrity-checked before saving | 422 with the allowed statuses, or with the integrity issues | Nothing is changed; the rule-edit preview (`POST /rules/validate`) shows the issues without saving | `services/complaints.py`, `services/rules.py` |

## 36.3 Controlled retries for GenAI output

`run_stage` in `backend/src/supportnova/genai_pipeline/runner.py` implements Step 47 for both GenAI calls, the complaint analysis and the customer response. The maximum number of attempts per stage is `1 + AI_MAX_RETRIES`, which is 3 by default, so the loop can never run indefinitely. Every attempt, successful or not, is passed to a callback that writes an `ai_runs` row with the attempt number, provider, model, prompt key and version, request metadata (including the prompt's SHA-256 and a redacted preview of the user prompt), the raw response text, the parse result, the error type and message, the latency and the token counts. Figure 36.1 shows the control flow.

![Figure 36.1 — Controlled retry flow of a GenAI stage](diagrams/pipelines/fig-36-01-genai-retry-flow.svg)
*Figure 36.1 — Controlled retry flow of a GenAI stage*

Two kinds of failure are handled differently. A provider error is retried only when it is marked retryable, after a wait that doubles with each attempt: 2 s and then 4 s after a rate limit or a connection error, which need a few seconds to clear, and 0.5 s and then 1 s after a timeout or a server error, never more than 8 s. An answer that arrives but fails validation is retried with feedback: the next request carries a correction message, "Your previous response failed validation: … Return only one JSON object that matches the schema exactly.", with up to six of the validation errors, after a short wait of 0.25 s times the attempt number. Table 36.3 summarises the policy.

**Table 36.3 — Retry policy by error kind**

| Error kind | Typical cause | Retried | Wait before the next attempt |
|---|---|---|---|
| `rate_limited` | HTTP 429 | Yes | 2 s, then 4 s (at most 8 s) |
| `connection` | DNS or network failure | Yes | 2 s, then 4 s (at most 8 s) |
| `server_error` | HTTP 5xx, Anthropic 529 | Yes | 0.5 s, then 1 s |
| `timeout` | No answer within 60 s | Yes | 0.5 s, then 1 s |
| `invalid_output` | Not JSON, schema or Pydantic violation | Yes, with the errors sent back | 0.25 s × attempt |
| `authentication` | HTTP 401 or 403 | No | — |
| `bad_request` | Other HTTP 4xx | No | — |
| `refusal` | The model declined | No | — |
| `not_configured` | No API key | No | — |

These paths are tested with the real adapters against fake vendor servers (`tests/backend/unit/test_genai_providers.py`): a truncated answer is retried with a `<validation_feedback>` block and accepted, a missing field is retried, five invalid answers stop after exactly three requests with an `invalid_output` failure, a 503 followed by a valid reply succeeds, and three 401 replies stop after a single request.

The live runs show the policy at work. Of the 1,591 GenAI attempts in the demo database, 31 failed: 26 `connection`, 4 `timeout` and 1 `invalid_output` (the deliberate `invalid_json` fault of Lab scenario LAB-DEF-06). All 31 succeeded on the second attempt, so all 780 analyses completed; 9 analysis stages and 22 response stages needed a second attempt, and none needed a third. `reports/genai_pipeline_evidence/invalid_response_and_retry.json` contains three complete examples with every attempt: an invalid answer (LAB-00018), a connection failure (CMP-00589) and a timeout (CMP-00344).

## 36.4 Recovery through manual review

Every error that affects the content of a decision ends in the same place: the manual review queue, with the reasons attached. When the GenAI analysis is unusable after its retries, Pipeline 2 still runs. SCH-001 fails with the cause ("No usable AI answer after retries (…)" or, without a key, "the AI provider is not configured on the server"), REV-009 `invalid_ai_output` is recorded, and the validated decision is built from the Rule Matrix alone. A required escalation is therefore still created, which `test_no_api_key_means_no_ai_output_and_manual_review` asserts for a smoking power station. No customer response is drafted without a model: nothing is invented to fill the gap. When the pipeline itself fails with an unexpected exception, `process_complaint` catches it, marks the complaint `failed` and queues a review with reason `pipeline_error` and the tail of the stack trace in `original_snapshot`, visible only to staff. The complaint returns from Processing to New so that it can be reprocessed (`POST /complaints/{ref}/reprocess`) once the cause is fixed.

Two background mechanisms guard against a process that stops. On start-up, `worker.requeue_stuck()` resubmits every non-evaluation complaint whose stage is neither `completed` nor `failed` and whose status is New or Processing, which covers a crash or a database outage in the middle of a run. The SLA monitor thread catches and logs any exception in an iteration, waits one second and continues ("monitor must never die"), so SLA states keep being refreshed after a transient error.

## 36.5 Evidence

The error paths are covered by automated tests (Chapter 33) and by recorded runs. Table 36.4 maps the main conditions to their evidence.

**Table 36.4 — Evidence for the error-handling paths**

| Condition | Automated test | Recorded evidence |
|---|---|---|
| Invalid complaint and field limits | `test_boundaries.py` (29 tests) | — |
| Malformed request body | `test_boundaries.py::test_malformed_body_is_a_field_error_not_a_crash` | — |
| Invalid and corrupted documents | `test_security_api.py::test_executable_upload_rejected`, `test_documents_exports.py::test_corrupted_document_is_rejected_cleanly` | — |
| AI errors, timeouts, refusals | `test_genai_providers.py` (error mapping and refusal tests) | 26 connection errors and 4 timeouts recovered (`ai_runs`) |
| Invalid JSON and schema mismatch | `test_genai_providers.py::test_invalid_json_is_retried_with_the_validation_errors_then_accepted`, `::test_schema_violation_is_retried` | LAB-00018 (`invalid_response_and_retry.json`) |
| Bounded retries | `test_genai_providers.py::test_retries_are_bounded_and_the_failure_is_reported` | No stage in the demo database used more than 2 attempts |
| AI not configured | `test_ai_not_configured.py`, `test_genai_providers.py::test_a_missing_key_fails_honestly_and_is_not_retried` | — |
| Unauthorised actions | `test_security_api.py` (30 tests) | — |
| Unsupported resolutions and promises | `test_difficult_cases.py`, fault-profile tests | Lab scenarios LAB-REF-02, LAB-CMP-02, LAB-DEF-05 |
| Frontend error display | `core.test.tsx` (error state, API error mapping) | — |

No automated test simulates a database outage or a crash of the process during a pipeline run. These recovery paths (`OperationalError` handling, `requeue_stuck`) are implemented and visible in the code, but they have not been exercised by a test (**Planned**).
