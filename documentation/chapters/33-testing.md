# Chapter 33 — Testing

SupportNova is tested on two separate tracks. The first track is a set of automated suites that run on every change without an API key and without spending any API credit: 206 backend tests (pytest) and 12 frontend tests (vitest). The second track measures the real system with the real model, OpenAI **gpt-4.1-mini**: the evaluation run on 154 unseen holdout complaints, the 18-scenario Adversarial Lab and the demo-dataset import of 617 complaints. The two tracks answer different questions. The automated suites prove that every deterministic mechanism behaves exactly as specified, and that the Generative AI integration honours its contract. The real-model track measures how good the model's proposals actually are and how often the Python Ground-Truth Validation Pipeline (Pipeline 2) has to correct them. This chapter describes the strategy, then covers each test category the SRS lists in Deliverable 11, adds the categories requested for this report (unit, integration, API and performance testing), and ends with the gaps that remain. Security testing is summarised here and detailed in Chapter 34. The individual test cases are listed in Appendix G (security) and Appendix H (all 206 backend and 12 frontend tests).

## 33.1 Testing strategy

The strategy follows the project principle **GenAI proposes. Python validates. Ground truth decides.** Ground truth lives in deterministic code and data: the Complaint Resolution Rule Matrix in `rules/*.yaml`, the validation engine in `backend/src/supportnova/python_validation/engine.py` and the checks listed in `rules/validation_policy.yaml`. These are tested with exact assertions. The GenAI side cannot be asserted exactly, because the same prompt can produce different wording on different runs (SRS section 1.5). It is therefore tested in two ways: its contract (request shape, structured-output schema, error mapping, retries) is tested automatically, and its quality is measured with the real model in separate recorded runs.

The automated suite has five levels. **Unit tests** (`tests/backend/unit`, 110 tests) exercise single modules against the repository's own data: the Rule Matrix YAML, the knowledge-base files in `knowledge_base/` and the dataset in `data/sample_complaints/`. **API tests** (`tests/backend/api`, 59 tests) send HTTP requests to the FastAPI application through FastAPI's `TestClient` and check status codes, the error envelope and field-level validation. **Integration tests** (`tests/backend/integration`, 34 tests) submit complaints through the public API and let the real background worker run the complete pipeline: preprocessing, retrieval, GenAI analysis, Python validation, response generation and persistence. **End-to-end tests** (`tests/e2e`, 3 tests) follow a complaint through every stage from submission to export. **Frontend tests** (`frontend/src/test/core.test.tsx`, 12 tests) render React components in jsdom with Testing Library.

API, integration and end-to-end tests use a real PostgreSQL database, never a mock. The session fixture `database` in `tests/conftest.py` connects to `TEST_DATABASE_URL`, by default the `supportnova_test` database of the local development cluster on port 5433. It drops and recreates the `public` schema, applies the Alembic migrations to head through `upgrade_to_head()`, and seeds the database exactly like a first start: roles, Rule Matrix, prompts, knowledge base, demo users, customers and the order ledger. The PostgreSQL features the application relies on, such as the append-only trigger on `audit_logs`, JSONB columns and the trigram index, are therefore present in the tests. If the test database cannot be reached, `pytest_collection_modifyitems` marks every integration, API and end-to-end test as skipped rather than failed. The configuration is hermetic. `SUPPORTNOVA_ENV_FILE` points at a file that does not exist, so the developer's `.env` and `.env.secrets` (which may hold a real key) are never read, and `AI_API_KEY`, `AI_MODEL`, `AI_BASE_URL`, `EMBEDDING_API_KEY`, `EMBEDDING_PROVIDER` and `SECRET_KEY` are removed from the environment. Rate limits are raised to 100,000 per minute, the SLA monitor interval is set to one hour, two background workers run, and a temporary storage directory is used.

Every GenAI call in the suite is answered by an offline test double, `OfflineLLM` in `tests/support/offline_llm.py`, installed with `providers.use_provider(OfflineLLM())`. It behaves like a black-box model. It reads only the rendered prompt text: the taxonomy, departments, action catalogue and priority guide from the system prompt, and the evidence and the nonce-tagged complaint element from the user prompt. It returns JSON for the requested schema, built from simple heuristics: word overlap with the taxonomy, citations copied from the top evidence, and an urgency guess that is deliberately driven by tone ("the validator must catch it"). It never reads the Rule Matrix, so Pipeline 2 remains independent of it. The double exists only in the test suite. The application itself has no mock provider: `test_genai_providers.py::test_there_is_no_mock_provider` asserts that `AI_PROVIDER=mock` is refused, and without a key the application reports `not_configured` instead of producing output (Section 33.9).

The real vendor adapters are tested against fake vendor servers. `httpx.MockTransport` stands in for the OpenAI and Gemini REST endpoints, and an `httpx2.MockTransport` is injected into the official Anthropic SDK client. No network connection and no key are needed.

The real-model track is recorded in the demo database and in `reports/`. Evaluation run #1 compared both pipelines with the expected labels of 154 unseen holdout complaints. The Adversarial Lab ran its 18 scenarios through the production pipeline. The demo import processed 617 complaints with 1,228 GenAI attempts; across all sources the demo database records 1,591 attempts. The dataset itself is checked by `scripts/validate_dataset.py`, whose 78 checks all pass.

Test references in the tables below use the file name and test function, for example `test_difficult_cases.py::test_calm_critical_safety_complaint`. Table 33.1 gives the full path of every file. The backend suite runs with `backend\.venv\Scripts\python -m pytest` (`pytest.ini` sets the test paths `tests/backend` and `tests/e2e`). The frontend suite runs with `npm test` (`vitest run`) in `frontend/`. A result of **Passed** in any table means the test passed in the recorded run of 25 September 2026, in which all 206 backend tests and all 12 frontend tests passed. The backend suite also passed 206 of 206 on a fresh clone of the repository.

![Figure 33.1 — SupportNova test strategy: automated suites, fixtures and real-model evidence](diagrams/architecture/fig-33-01-test-strategy.svg)
*Figure 33.1 — SupportNova test strategy: automated suites, fixtures and real-model evidence*

Figure 33.1 separates the automated suites (top) from the recorded real-model evidence (bottom). Both tracks exercise the same Python Ground-Truth Validation Pipeline. Table 33.1 lists the automated suites, Table 33.2 the recorded results, and Table 33.3 where each SRS test category is covered.

**Table 33.1 — Automated test suites**

| File | Level | Tests | Focus |
|---|---|---|---|
| `tests/backend/unit/test_rule_engine.py` | Unit | 16 | Rule Matrix integrity, SRS minimums, conditions, priority matrix, reference labeller |
| `tests/backend/unit/test_perception_security.py` | Unit | 33 | Signals, classification, entities, injection corpus, grounding, PII, uploads |
| `tests/backend/unit/test_genai_providers.py` | Unit | 31 | Provider adapters against fake vendor servers, schema, retry policy |
| `tests/backend/unit/test_documents_exports.py` | Unit | 12 | PDF/DOCX parsing, chunking, version diff, malicious document, exports |
| `tests/backend/unit/test_batch.py` | Unit | 3 | Per-customer ordering in parallel batch processing |
| `tests/backend/unit/test_wording.py` | Unit | 15 | Stored text served in the current UI wording |
| `tests/backend/api/test_boundaries.py` | API | 29 | Field limits, reference formats, refund window, upload size, pagination |
| `tests/backend/api/test_security_api.py` | API | 30 | Authentication, RBAC, CSRF, lockout, headers, key exposure, audit immutability |
| `tests/backend/integration/test_difficult_cases.py` | Integration | 18 | The SRS difficult cases through the real API and pipeline |
| `tests/backend/integration/test_defects_and_live_changes.py` | Integration | 15 | Deliberate defects, live rule changes, hidden-data readiness |
| `tests/backend/integration/test_ai_not_configured.py` | Integration | 1 | No API key means no AI output and manual review |
| `tests/e2e/test_full_chain.py` | End-to-end | 3 | Complete chain, clarification loop, document versioning journey |
| `frontend/src/test/core.test.tsx` | Frontend | 12 | Utilities, API client, badges, complaint text, tracker, login |

**Table 33.2 — Recorded test and evaluation results**

| Evidence | Scope | Result | Source |
|---|---|---|---|
| Backend pytest suite | 206 tests | 206 passed; 206 passed on a fresh clone | Run of 25 Sep 2026 |
| Frontend vitest suite | 12 tests | 12 passed | Run of 25 Sep 2026 |
| Dataset validator | 78 checks, 617 dev + 154 holdout records | PASS 78, WARN 0, FAIL 0 | `scripts/validate_dataset.py`, re-run 25 Sep 2026 |
| Holdout evaluation run #1 | 154 unseen cases, gpt-4.1-mini | 92 of 93 AI key-field errors caught | `reports/genai_python_comparison/summary.md` |
| Adversarial Lab | 18 scenarios | 18 of 18 expectations met | `reports/security_adversarial/summary.md` |
| Demo database | 800 complaints (617 dataset, 160 evaluation, 18 Lab, 5 web), 1,591 GenAI attempts | 780 of 780 analyses completed; all 31 failed attempts recovered on the second attempt | Demo database (`analyses`, `ai_runs`) |
| Load and scalability test | SRS scale targets | Not performed (Planned) | Chapter 35 |

**Table 33.3 — SRS test categories (Deliverable 11) and where they are covered**

| SRS category | Section | Main automated evidence | Real-model evidence |
|---|---|---|---|
| Functional | 33.2 | `test_full_chain.py` (3) | Demo import |
| Complaint submission | 33.6 | `test_boundaries.py`, `test_difficult_cases.py` | Demo import |
| Document upload | 33.7 | `test_security_api.py`, `test_defects_and_live_changes.py` | Knowledge-base bootstrap, 24 documents |
| Parsing | 33.8 | `test_documents_exports.py` | 29 versions parsed, 484 chunks |
| GenAI API | 33.9 | `test_genai_providers.py` (31) | 1,591 recorded attempts |
| JSON | 33.10 | `test_genai_providers.py`, `test_ai_not_configured.py` | SCH-001 on 604 analysed complaints |
| Classification | 33.11 | `test_perception_security.py`, `test_difficult_cases.py` | Holdout run #1 |
| Routing | 33.12 | `test_difficult_cases.py`, fault profiles | Holdout run #1, LAB-DEF-02 |
| Urgency | 33.13 | `test_rule_engine.py`, `test_difficult_cases.py` | Holdout run #1, LAB-DEF-03 |
| Escalation | 33.14 | `test_rule_engine.py`, `test_defects_and_live_changes.py` | Holdout run #1, LAB-DEF-01 |
| Resolution | 33.15 | `test_difficult_cases.py`, `test_boundaries.py` | Holdout run #1, LAB-REF-01/02 |
| Policy | 33.16 | `test_defects_and_live_changes.py`, `test_full_chain.py` | LAB-POL-01/02/03 |
| Hallucination | 33.17 | `test_perception_security.py`, fault profiles | LAB-DEF-04 |
| Prompt injection | 33.18 | `test_perception_security.py`, `test_difficult_cases.py` | Holdout run #1, LAB-INJ-01/02/03 |
| Duplicate | 33.19 | `test_difficult_cases.py` | Holdout run #1 |
| Missing information | 33.20 | `test_difficult_cases.py`, `test_full_chain.py` | Holdout run #1 |
| Multi-issue | 33.21 | `test_difficult_cases.py`, `test_perception_security.py` | Holdout run #1 |
| Hidden-data readiness | 33.22 | `test_defects_and_live_changes.py` | Holdout run #1 |
| Boundary | 33.23 | `test_boundaries.py` (29) | — |
| Security | 33.24, Chapter 34 | `test_security_api.py` (30) and others | Adversarial Lab 18/18 |

## 33.2 Functional testing

Functional testing checks that the SRS functions work together as one workflow. The end-to-end file `tests/e2e/test_full_chain.py` is the main evidence. Its first test asserts every stage of the chain in order, with the stages numbered in the test itself: create, store, preprocess, retrieve, AI analysis, structured JSON validation, ground-truth validation, the policy, routing, urgency, priority, resolution, eligibility and escalation checks, the hallucination check, the unsupported-promise check, response, agent guidance, audit record, UI payload, manual review, dashboard and export. It submits a calmly written but dangerous complaint as the demo customer ("smoke came out of the vent while it was charging next to my daughter's bed"), so the same run also exercises the safety escalation and the mandatory human review of safety cases. Table 33.4 lists the functional test cases.

**Table 33.4 — Functional test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-FUN-01 | Submission to analysis | A customer submission returns 202, the pipeline finishes without failure and the stored complaint keeps the submitted title | `test_full_chain.py::test_complete_complaint_chain` | Passed |
| TC-FUN-02 | Preprocessing and retrieval | Normalised text, classification candidates and a `fire_event` or `overheating` signal exist; evidence includes a SAF policy and only Active versions | `test_full_chain.py::test_complete_complaint_chain` | Passed |
| TC-FUN-03 | AI analysis and schema | The analysis completed, an analysis attempt is logged with `parsed_ok`, and SCH-001 passes | `test_full_chain.py::test_complete_complaint_chain` | Passed |
| TC-FUN-04 | Ground-truth validation | CLS-001, RTE-001, PRI-001, PRI-002, POL-001, POL-002, RES-001, RES-002, ELG-001 to ELG-003, ESC-001 and ESC-002 ran; the final decision is SAF, Critical, P0, escalated, with policy references | `test_full_chain.py::test_complete_complaint_chain` | Passed |
| TC-FUN-05 | Hallucination and promise checks | HAL-001, HAL-002, HAL-004, RSP-002, RSP-006 and SEC-001 ran | `test_full_chain.py::test_complete_complaint_chain` | Passed |
| TC-FUN-06 | Response, guidance and audit | A response with validation results exists, validated agent guidance exists, and the audit trail holds `complaint.created` and `complaint.processed` | `test_full_chain.py::test_complete_complaint_chain` | Passed |
| TC-FUN-07 | Manual review | The safety case is in Manual Review; a reviewer claims and approves it; the status becomes Human Verified and the review `completed/approved` | `test_full_chain.py::test_complete_complaint_chain` | Passed |
| TC-FUN-08 | Lifecycle, dashboard and export | Escalated to In Progress to Resolved (with `resolved_at`); dashboard total increases by one; case PDF, CSV report and XLSX export are produced; audit chain valid | `test_full_chain.py::test_complete_complaint_chain` | Passed |
| TC-FUN-09 | Clarification loop | A refund complaint without an order is flagged; the customer's clarification returns 202, the case is re-analysed and a `complaint.clarified` event is recorded | `test_full_chain.py::test_customer_clarification_loop` | Passed |
| TC-FUN-10 | Policy versioning journey | TST-POL-90 v1.0 then v1.1 become Previous and Active; the impact analysis lists section 2; search returns v1.1 only | `test_full_chain.py::test_document_upload_and_policy_versioning_journey` | Passed |
| TC-FUN-11 | Consistent UI wording | 14 stored legacy phrases are shown in the current wording ("Rule check", "AI vs rules"); current text is unchanged | `test_wording.py` (15 tests) | Passed |

## 33.3 Unit testing

Unit tests run without a database. They load the Rule Matrix through the session fixture `matrix` (`supportnova.rule_engine.loader.load_matrix`) and use the real repository files. Many sections below cite unit tests. Table 33.5 lists the unit tests that do not belong to a more specific SRS category.

**Table 33.5 — Unit test cases (general)**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-UNT-01 | Rule Matrix integrity | `validate_matrix` reports no errors for the live Rule Matrix | `test_rule_engine.py::test_rule_matrix_integrity` | Passed |
| TC-UNT-02 | SRS minimums | At least 10 categories, 20 subcategories, 8 departments, 100 resolution rules and 30 escalation rules | `test_rule_engine.py::test_rule_matrix_meets_srs_minimums` | Passed |
| TC-UNT-03 | Three-valued conditions | Known facts give True or False; an unknown fact gives None ("requires verification"), never a guess; `all`, `any`, `not` and `$param:` references work | `test_rule_engine.py::test_three_valued_conditions` | Passed |
| TC-UNT-04 | Reference labels | For the first 150 dev records, `label_declared` on the declared facts reproduces every rule-derived expected field | `test_rule_engine.py::test_reference_labels_reproduce_dataset` | Passed |
| TC-UNT-05 | Explainable decision | For DEL-DLY the decision engine returns a department, a `RES-DEL-DLY` rule and a non-empty trace | `test_rule_engine.py::test_decision_engine_trace_is_explainable` | Passed |
| TC-UNT-06 | Batch ordering | Groups follow each customer's first complaint; 40 records on 4 workers keep per-customer order on more than one thread; `stop` and exceptions propagate | `test_batch.py` (3 tests) | Passed |
| TC-UNT-07 | Knowledge-base minimums | The manifest has at least 20 documents, PDF and DOCX, and Active plus Previous or Superseded versions | `test_documents_exports.py::test_knowledge_base_meets_srs_minimums` | Passed |
| TC-UNT-08 | Normalisation and duplicate hash | `text_hash` ignores case, punctuation, repeated spaces and zero-width characters; HTML tags are stripped | `test_perception_security.py::test_normalisation_and_duplicate_hash` | Passed |
| TC-UNT-09 | Entity extraction | LMR- order, TXN- transaction and CMP- complaint references are extracted | `test_perception_security.py::test_entities_extracted` | Passed |
| TC-UNT-10 | Sentiment is informational | The lexicon marks angry text Negative or Strongly Negative; sentiment is not used for urgency (Section 33.13) | `test_perception_security.py::test_sentiment_is_informational` | Passed |
| TC-UNT-11 | Password hashing and tokens | bcrypt verification, JWT `sub` and `role` claims, CSRF token comparison | `test_perception_security.py::test_password_hashing_and_tokens` | Passed |

## 33.4 Integration testing

Integration tests run the real application: FastAPI routers, the background worker (`services/worker.py`), the pipeline (`services/pipeline.py`), the Python validation engine and PostgreSQL. Only the GenAI provider is replaced by the offline double. The `submit` fixture posts to `POST /api/v1/complaints`, asserts HTTP 202 and polls `GET /api/v1/complaints/{ref}/pipeline` every 0.2 s until the stage is `completed` or `failed` (limit 60 s). It then reads the full case as an administrator. The `make_order` fixture writes simulated ledger orders with dates relative to the test day, so eligibility windows (for example the 30-day refund window) are always evaluated against fresh dates. Each difficult-case test uses its own customer (CUST-10002 to CUST-10020), so complaint history never leaks from one test into another. Table 33.6 summarises the three integration files.

**Table 33.6 — Integration test groups**

| ID | Test group | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-INT-01 | SRS difficult cases | 18 cases (calm critical, angry minor, injection, unsupported refund and compensation, missing information, ambiguous, multi-issue, contradictory policy, repeat, duplicates, legal threat, account takeover, privacy, electrical safety) through the real API and pipeline | `test_difficult_cases.py` (18 tests) | Passed |
| TC-INT-02 | Deliberate AI defects | Every Lab scenario meets its expectation; six fault profiles on a custom complaint each make the matching check fail and force Manual Review | `test_defects_and_live_changes.py::test_every_adversarial_scenario_is_caught`, `::test_fault_profile_on_custom_complaint` (6) | Passed |
| TC-INT-03 | Live modification | A parameter change, a rule deactivation, a new category and a rule-edit preview change behaviour without code changes | `test_defects_and_live_changes.py` (4 tests) | Passed |
| TC-INT-04 | Documents | A revised policy upload creates a new Active version with an impact analysis; a malicious document is quarantined | `::test_revised_policy_upload_versioning_and_impact`, `::test_malicious_document_upload_is_quarantined` | Passed |
| TC-INT-05 | Evaluation runner | A 12-case holdout run and a 3-row hidden CSV upload complete through the evaluation service | `::test_evaluation_run_on_unseen_holdout`, `::test_hidden_dataset_upload_with_minimal_columns` | Passed |
| TC-INT-06 | AI not configured | Without an API key no AI output is produced, the case goes to Manual Review and the Python decision is still enforced | `test_ai_not_configured.py::test_no_api_key_means_no_ai_output_and_manual_review` | Passed |

## 33.5 API testing

API tests call the HTTP interface as a client would, with explicit `Authorization: Bearer` headers per role (tokens obtained once per session through `POST /api/v1/auth/login`). They check the status codes and the error envelope that `backend/src/supportnova/api/errors.py` produces for every failure: `{"error": {"code", "message", "details", "request_id"}}`. The login cookie is cleared after the tokens are issued, so tests that must be unauthenticated never carry a previous session by accident. Table 33.7 lists the API test cases.

**Table 33.7 — API test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-API-01 | Unauthenticated access | Nine protected endpoints return 401 with an authentication error code | `test_security_api.py::test_unauthenticated_requests_are_rejected` (9) | Passed |
| TC-API-02 | Server-side RBAC | For 11 endpoints and all 5 roles, allowed roles get 200 and all others 403 (55 assertions) | `test_security_api.py::test_role_permission_matrix_enforced_server_side` (11) | Passed |
| TC-API-03 | Field errors, not crashes | A malformed JSON body and a JSON list return 422; over-long title and description return 422 naming the field | `test_boundaries.py::test_malformed_body_is_a_field_error_not_a_crash`, `::test_title_over_the_hard_cap_is_a_field_error_not_a_crash`, `::test_description_over_the_hard_cap_is_a_field_error_not_a_crash` | Passed |
| TC-API-04 | Pagination parameters | `page_size` 200 accepted; 201 and 0 rejected with 422; `page` 0 rejected; `page` 9999 returns 200 with an empty list | `test_boundaries.py::test_list_pagination_limits` (5) | Passed |
| TC-API-05 | Conflict on duplicate | Resubmitting identical text returns 409 with `details.duplicate_of` | `test_difficult_cases.py::test_exact_duplicate_rejected_and_near_duplicate_linked` | Passed |
| TC-API-06 | No information leak | Another customer's complaint returns 404, not 403 | `test_security_api.py::test_customer_sees_only_own_complaints` | Passed |
| TC-API-07 | CSRF on cookie sessions | A cookie-only POST returns 403; with `X-CSRF-Token` it returns 200 | `test_security_api.py::test_cookie_session_requires_csrf_header` | Passed |
| TC-API-08 | Rate limit | With a login limit of 3 per minute, six attempts with spoofed `X-Forwarded-For` values produce a 429 | `test_security_api.py::test_spoofed_forwarded_for_does_not_bypass_login_rate_limit` | Passed |
| TC-API-09 | Security headers | `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and a CSP with `default-src 'self'` | `test_security_api.py::test_security_headers` | Passed |
| TC-API-10 | Report endpoints | `GET /complaints/{ref}/report.pdf`, `GET /reports/complaint-analysis?format=csv` and `GET /complaints-export?format=xlsx` return files | `test_full_chain.py::test_complete_complaint_chain` | Passed |

## 33.6 Complaint-submission testing

Submission is validated twice with the same function, `validate_submission` in `backend/src/supportnova/services/complaints.py`: once live while the form is being filled (`POST /api/v1/complaints/validate`, which returns the errors without creating a complaint) and once on `POST /api/v1/complaints`. The rules are: a title of 5 to 180 characters; a description of at least 20 characters and 4 words and at most 8,000 characters, where whitespace alone counts as empty; option values from the organisation configuration; and reference formats (for example `LMR-123456`). The Pydantic model `ComplaintIn` adds hard caps of 200 and 10,000 characters so that oversized bodies become field errors. Table 33.8 lists the test cases.

**Table 33.8 — Complaint-submission test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-SUB-01 | Title length | 4 characters rejected, 5 accepted, 180 accepted, 181 rejected | `test_boundaries.py::test_title_length_edges` (4) | Passed |
| TC-SUB-02 | Description length and words | Empty and whitespace-only rejected; 21 characters and 5 words accepted; 18 characters rejected; 30 characters in one word rejected; 8,000 accepted; 8,001 rejected | `test_boundaries.py::test_description_length_edges` (7) | Passed |
| TC-SUB-03 | Customer profile defaults | The customer form has no customer-type field; the precheck uses the profile value, as submission does | `test_boundaries.py::test_customer_precheck_uses_the_profile_customer_type` | Passed |
| TC-SUB-04 | Reference format | `LMR-12345` and `ORDER-1` reported as malformed, `LMR-123456` accepted | `test_boundaries.py::test_order_reference_format` (3) | Passed |
| TC-SUB-05 | Normal submission | A delayed-delivery complaint with a valid order is stored, the order is found in the ledger and a response is drafted | `test_difficult_cases.py::test_normal_delayed_delivery` | Passed |
| TC-SUB-06 | Duplicate submission | An identical resubmission is rejected with 409; a reworded one is linked as a duplicate and Closed | `test_difficult_cases.py::test_exact_duplicate_rejected_and_near_duplicate_linked` | Passed |
| TC-SUB-07 | Asynchronous processing | Every submission returns 202 and the pipeline status is polled until `done` | `conftest.py` `submit` fixture, used by 20 tests | Passed |

## 33.7 Document-upload testing

Knowledge-base uploads go through `ingest_document` in `backend/src/supportnova/services/documents.py`: file validation, duplicate check by SHA-256, parsing, metadata validation, storage, sections, chunking, injection screening with quarantine, embeddings, policy facts, version control and a revision impact analysis. File validation is `validate_upload` in `backend/src/supportnova/security/files.py`, which checks type by magic bytes and extension, size, empty files, executables and DOCX archive safety. Table 33.9 lists the test cases.

**Table 33.9 — Document-upload test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-DOC-01 | Executable disguised as PDF | `policy.pdf` starting with `MZ` is rejected by `POST /documents/preview` with 422 | `test_security_api.py::test_executable_upload_rejected` | Passed |
| TC-DOC-02 | Size and empty file | A 2,048-byte PDF is accepted at a 2,048-byte limit; one byte more is rejected; an empty file is rejected | `test_boundaries.py::test_upload_size_edge` | Passed |
| TC-DOC-03 | Type mismatches | Executable content in `.pdf`, a fake PNG, a `.exe` and an oversized text file are rejected; `../../etc/notes.txt` is stored without path separators | `test_perception_security.py::test_upload_validation_rejects_executables_and_mismatches` | Passed |
| TC-DOC-04 | Revised policy upload | The hidden-pack REF-POL-02 v2.1 PDF is detected as REF-POL-02, uploads with 201 as Active, and v2.0 becomes Previous or Superseded | `test_defects_and_live_changes.py::test_revised_policy_upload_versioning_and_impact` | Passed |
| TC-DOC-05 | Markdown upload and versioning | Two versions of TST-POL-90 upload with 201 and receive the statuses Previous and Active | `test_full_chain.py::test_document_upload_and_policy_versioning_journey` | Passed |
| TC-DOC-06 | Malicious document | MAL-DOC-99_v1.0.docx has sections flagged as instructions; the Lab document scan returns quarantined sections | `test_documents_exports.py::test_malicious_document_sections_flagged`, `test_defects_and_live_changes.py::test_malicious_document_upload_is_quarantined` | Passed |

## 33.8 Parsing testing

Parsing is implemented in `backend/src/supportnova/document_processing/parsers.py` (PyMuPDF for PDF, python-docx for DOCX, plus Markdown, TXT and CSV) and `chunking.py`. The tests parse real documents from `knowledge_base/` and synthetic PDFs generated inside the test with fpdf2, so the parser is tested on the same kind of files an administrator uploads. Table 33.10 lists the test cases.

**Table 33.10 — Parsing test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-PAR-01 | Real PDF and DOCX | An Active PDF and an Active DOCX from the manifest yield sections with IDs and headings, the detected `doc_id` matches, and every chunk UID starts with `DOC-ID@` | `test_documents_exports.py::test_parse_sections_from_real_documents` (pdf, docx) | Passed |
| TC-PAR-02 | Headers, footers and tables | Running headers and "Page n of m" footers are dropped; text repeated in the body is kept all three times; the routing-table row (RTE-004, BIL-DUP Duplicate Charge, Billing Operations) stays on one line with its department cell; sections 1, 2 and 3 found | `test_documents_exports.py::test_pdf_keeps_repeated_body_text_and_reads_tables_by_row` | Passed |
| TC-PAR-03 | Facts and version diff | A change from 30 to 21 calendar days in section 3.1 is reported as a value change | `test_documents_exports.py::test_facts_and_version_diff` | Passed |
| TC-PAR-04 | Metadata validation | An invalid version and status produce field errors; REF-POL-02 v2.1 is accepted; version order 2.10 > 2.9 > 2.0 | `test_documents_exports.py::test_metadata_validation_and_version_order` | Passed |
| TC-PAR-05 | Corrupted file | Bytes that start like a PDF but are not one raise an application error instead of crashing | `test_documents_exports.py::test_corrupted_document_is_rejected_cleanly` | Passed |
| TC-PAR-06 | Knowledge base in the demo database | 24 documents, 29 versions, 482 sections and 484 chunks are stored after the bootstrap ingestion | Demo database (`documents`, `document_versions`, `document_chunks`) | Measured |

## 33.9 GenAI API testing

The GenAI API tests in `tests/backend/unit/test_genai_providers.py` exercise the production adapters (`backend/src/supportnova/genai_pipeline/providers/http_providers.py` for OpenAI and Gemini, `anthropic_provider.py` for the Anthropic SDK) against fake vendor servers. Each test inspects the exact request the vendor would receive and feeds back scripted responses: valid JSON, truncated JSON, HTTP errors and refusals. They also test the controlled retry runner `run_stage` in `genai_pipeline/runner.py` with a real adapter. Real vendor behaviour is shown by the recorded runs: all 1,591 GenAI attempts in the demo database were made by `openai/gpt-4.1-mini`. Table 33.11 lists the test cases.

**Table 33.11 — GenAI API test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-GAI-01 | Provider selection | `AI_PROVIDER` selects Anthropic (default `claude-opus-5`), OpenAI or Gemini; `real` infers the vendor from the key; `AI_MODEL` overrides the model | `::test_factory_selects_the_configured_provider` | Passed |
| TC-GAI-02 | No mock provider | `AI_PROVIDER=mock` is refused by the settings validator | `::test_there_is_no_mock_provider` | Passed |
| TC-GAI-03 | Missing key | Without a key the provider raises `not_configured`, not retryable; `run_stage` makes exactly one attempt | `::test_a_missing_key_fails_honestly_and_is_not_retried` | Passed |
| TC-GAI-04 | Secrets file | `AI_API_KEY` in `.env.secrets` overrides `.env`; both files are read in that order | `::test_secrets_file_overrides_the_settings_file` | Passed |
| TC-GAI-05 | OpenAI request | `POST /v1/chat/completions` with a Bearer key, `response_format` of type `json_schema` with `strict: true` and schema name `customer_communication_v1`; reply, request ID and token counts parsed | `::test_openai_request_uses_strict_json_schema` | Passed |
| TC-GAI-06 | OpenAI-compatible gateway | `AI_BASE_URL` routes the call to the gateway URL | `::test_openai_compatible_gateway_via_base_url` | Passed |
| TC-GAI-07 | Anthropic request | `/v1/messages` with `output_config.format` json_schema, effort `medium`, server-side fallbacks beta header, no temperature, system prompt with `cache_control` | `::test_anthropic_request_uses_structured_output_and_parses_the_reply` | Passed |
| TC-GAI-08 | Anthropic plain endpoint | Models without fallback or effort support use the plain endpoint without beta headers | `::test_anthropic_models_without_fallback_or_effort_use_the_plain_endpoint` | Passed |
| TC-GAI-09 | Gemini request | The key travels in `x-goog-api-key`, never in the URL; `responseJsonSchema` is sent; on a schema rejection the adapter falls back to JSON mode | `::test_gemini_key_travels_in_a_header_never_the_url`, `::test_gemini_falls_back_to_json_mode_when_schema_is_rejected` | Passed |
| TC-GAI-10 | Error mapping | 429 becomes `rate_limited` and 5xx (including 529) `server_error`, both retryable; 401 `authentication` and 400 `bad_request` are not retryable (OpenAI 4 cases, Anthropic 5 cases) | `::test_openai_errors_map_to_the_retry_policy`, `::test_anthropic_errors_map_to_the_retry_policy` | Passed |
| TC-GAI-11 | Refusals | OpenAI refusals, Anthropic `stop_reason: refusal` and Gemini `SAFETY` blocks are reported as `refusal` and not retried as invalid output | `::test_openai_refusal_is_reported`, `::test_anthropic_refusal_is_not_retried_as_invalid_output`, `::test_gemini_safety_block_is_a_refusal` | Passed |
| TC-GAI-12 | Transient versus permanent errors | A 503 then a valid reply succeeds; three 401 replies stop after one request | `::test_transient_errors_are_retried_but_authentication_errors_are_not` | Passed |

## 33.10 JSON schema testing

The GenAI output contracts are `schemas/ai/complaint_analysis.v1.schema.json` (37 required top-level fields) and `customer_communication.v1.schema.json` (7 required fields). `genai_pipeline/schemas.py` adapts them to each vendor's structured-output dialect. `genai_pipeline/parsing.py` validates every reply again with jsonschema (Draft 2020-12) and Pydantic before anything is used. SCH-001 ("AI answer is complete and well-formed") records the outcome in Pipeline 2. Table 33.12 lists the test cases.

**Table 33.12 — JSON schema test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-JSN-01 | Vendor-safe schema | For both schemas, with and without inlined `$ref`, no keyword that vendors reject (for example `minLength`, `maxItems`, `const`) remains; every object has `additionalProperties: false` and all properties required | `test_genai_providers.py::test_structured_output_schema_uses_only_supported_keywords` (4) | Passed |
| TC-JSN-02 | Live schema change | Adapting a custom schema keeps field names that look like keywords (`pattern`) and strips only real constraints | `::test_schema_adaptation_keeps_field_names_that_look_like_keywords` | Passed |
| TC-JSN-03 | Invalid JSON retried | A truncated reply fails as `invalid_output` ("not valid JSON"); the retry carries a `<validation_feedback>` block with the errors and is accepted | `::test_invalid_json_is_retried_with_the_validation_errors_then_accepted` | Passed |
| TC-JSN-04 | Schema violation retried | A reply without `customer_response` fails with that field named and is retried | `::test_schema_violation_is_retried` | Passed |
| TC-JSN-05 | Bounded retries | Five invalid replies scripted, `max_attempts=3`: exactly 3 requests, the stage fails with `invalid_output` | `::test_retries_are_bounded_and_the_failure_is_reported` | Passed |
| TC-JSN-06 | SCH-001 on a valid answer | The end-to-end analysis passes SCH-001 | `test_full_chain.py::test_complete_complaint_chain` | Passed |
| TC-JSN-07 | SCH-001 without an answer | With no key, SCH-001 fails with "not configured" and the case goes to Manual Review | `test_ai_not_configured.py::test_no_api_key_means_no_ai_output_and_manual_review` | Passed |
| TC-JSN-08 | Real invalid answer | LAB-DEF-06 (`invalid_json` fault profile): attempt 1 rejected at position 1760, attempt 2 accepted, SCH-001 passes | `reports/genai_pipeline_evidence/invalid_response_and_retry.json` (LAB-00018) | Met |

## 33.11 Classification testing

Pipeline 2 classifies each complaint independently with the keyword and signal rules of `rules/complaint_rules/category_rules.yaml` and `signals.yaml` (`complaint_processing/perception.py`). It then compares the result with the AI's category (CLS-001, CLS-002). When the rules' own confidence is low, the AI category is kept provisionally and the case goes to a reviewer instead of being verified. Table 33.13 lists the test cases.

**Table 33.13 — Classification test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-CLA-01 | Category per domain | Five complaints are classified DEL, BIL, ACC, PRV and SAF | `test_perception_security.py::test_classification_categories` (5) | Passed |
| TC-CLA-02 | Risk-first precedence | A late delivery that then overheated is classified SAF, with the DEL issue kept as secondary | `test_perception_security.py::test_risk_precedence_beats_higher_scoring_issue` | Passed |
| TC-CLA-03 | Unsupported AI category | For the "Spark" smart plug no candidate is SAF, and SAF-ELC is not accepted as a provisional reference | `test_perception_security.py::test_unsupported_genai_category_is_never_the_provisional_reference` | Passed |
| TC-CLA-04 | Product name is not a hazard | "My Spark smart plug stopped responding" is not SAF, not Critical, and raises no `electrical_hazard` signal | `test_difficult_cases.py::test_product_name_is_not_a_hazard` | Passed |
| TC-CLA-05 | End-to-end classification | A delayed-delivery complaint ends as DEL / DEL-DLY | `test_difficult_cases.py::test_normal_delayed_delivery` | Passed |
| TC-CLA-06 | New category by configuration | Category ENV and subcategory ENV-RCY added through the taxonomy API; the simulator classifies a recycling complaint as ENV-RCY | `test_defects_and_live_changes.py::test_new_category_without_code_changes` | Passed |
| TC-CLA-07 | Real model, unseen cases | Category accuracy: rules 75.7%, AI 89.5%; subcategory: rules 68.4%, AI 77.6% (n = 152) | Holdout run #1 | Measured |

The holdout figures show that the AI classifies unseen wording better than the keyword rules. This is why a low-confidence rule classification never overrides the AI silently: the AI category is used until a reviewer confirms it, and the case is not verified automatically.

## 33.12 Routing testing

Routing is deterministic: `rules/routing_rules/routing_rules.yaml` maps each subcategory to a primary department and required supporting departments (35 routing rules and 6 conditional routing rules). RTE-001 and RTE-002 compare the AI's routing with it, and the validated decision always carries the rule's department. Table 33.14 lists the test cases.

**Table 33.14 — Routing test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-ROU-01 | Normal routing | Delayed delivery routed to DEPT-LOG | `test_difficult_cases.py::test_normal_delayed_delivery` | Passed |
| TC-ROU-02 | Wrong department caught | `wrong_department` fault profile: RTE-001 fails and the case goes to Manual Review | `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[wrong_department-RTE-001]` | Passed |
| TC-ROU-03 | Security routing | An account takeover with a remote door unlock involves DEPT-SEC as primary or supporting department | `test_difficult_cases.py::test_security_account_takeover` | Passed |
| TC-ROU-04 | Multi-department | A three-issue complaint keeps supporting departments | `test_difficult_cases.py::test_multi_issue_multi_department` | Passed |
| TC-ROU-05 | New subcategory routing | ENV-RCY gets a department from configuration | `test_defects_and_live_changes.py::test_new_category_without_code_changes` | Passed |
| TC-ROU-06 | Real model, Lab | LAB-DEF-02: a billing dispute routed elsewhere is corrected to DEPT-BIL (RTE-001, RTE-002 fail) | `reports/security_adversarial/summary.md` | Met |
| TC-ROU-07 | Real model, unseen cases | Department accuracy: rules 84.9%, AI 92.1%; supporting departments: rules 74.3%, AI 73.7% | Holdout run #1 | Measured |

## 33.13 Urgency and priority testing

The SRS requires that urgency is not driven by emotional wording (Steps 19 and 21). Pipeline 2 derives urgency from the resolution rule and from the urgency floors in `rules/complaint_rules/priority_rules.yaml` (15 floors triggered by signals such as `overheating` or `lock_security`). Priority follows the urgency-by-impact matrix. Sentiment is computed only for information and never raises urgency; customer type, including VIP, never changes urgency or priority (SLA-RUL-15 section 5.4). Table 33.15 lists the test cases.

**Table 33.15 — Urgency and priority test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-URG-01 | Priority matrix | Critical/High P0, Critical/Medium P0, Critical/Low P1, High/High P1, High/Medium P2, Medium/High P2, Medium/Low P3, Low/Low P3 | `test_rule_engine.py::test_priority_matrix` (8) | Passed |
| TC-URG-02 | Calm but critical | "No rush on this": a hot, hissing, swollen power station in a child's room is Critical and P0, escalated, SAF | `test_difficult_cases.py::test_calm_critical_safety_complaint` | Passed |
| TC-URG-03 | Angry but minor | "WORST APP EVER!!!" about dark mode from a VIP: sentiment negative, urgency Low or Medium, priority P2 or P3 | `test_difficult_cases.py::test_angry_low_priority_complaint` | Passed |
| TC-URG-04 | Emotion and VIP in the rules | TEC-APP for a VIP customer stays Low or Medium and P2 or P3 | `test_rule_engine.py::test_emotional_language_does_not_raise_priority` | Passed |
| TC-URG-05 | Calm safety signal | A calm text still produces `overheating` and `child_involved` | `test_perception_security.py::test_calm_safety_complaint_detects_risk` | Passed |
| TC-URG-06 | Negation | "There was no smoke and no fire" produces no `fire_event` | `test_perception_security.py::test_negation_suppresses_signal` | Passed |
| TC-URG-07 | Electrical safety | A sparking plug with a burning smell is SAF, Critical and escalated | `test_difficult_cases.py::test_electrical_safety` | Passed |
| TC-URG-08 | Real model, Lab | LAB-DEF-03 (`urgency_downgrade`): PRI-001 fails for a smart-lock lock-out with children outside | `reports/security_adversarial/summary.md` | Met |
| TC-URG-09 | Real model, unseen cases | Urgency accuracy: rules 84.2%, AI 68.4%; priority: rules 88.8%, AI 62.5% | Holdout run #1 | Measured |

## 33.14 Escalation testing

Escalation rules (`rules/escalation_rules/escalation_rules.yaml`, 39 rules) fire on signals, facts and history, and the highest level wins. ESC-001 ("Required escalation identified") and ESC-002 ("Escalation level meets the rules") compare the AI's escalation with the rules. The pipeline creates the escalation from the rules even when the AI missed it; such escalations are stored with the source `rule` instead of `rule+ai`. Table 33.16 lists the test cases.

**Table 33.16 — Escalation test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-ESC-01 | Missed escalation caught | `missed_escalation` fault profile: ESC-001 fails and the case goes to Manual Review | `test_defects_and_live_changes.py::test_fault_profile_on_custom_complaint[missed_escalation-ESC-001]` | Passed |
| TC-ESC-02 | Safety forces escalation | SAF-OVH with `overheating` and `child_involved` gives Critical, P0 and at least Specialist Team | `test_rule_engine.py::test_safety_signal_forces_critical_escalation` | Passed |
| TC-ESC-03 | Level ranking | The first level is No Escalation; Critical Management Escalation ranks above Supervisor Review | `test_rule_engine.py::test_escalation_level_ranking` | Passed |
| TC-ESC-04 | Legal threat | A solicitor's threat requires escalation (review or a level above No Escalation) | `test_difficult_cases.py::test_escalation_for_legal_threat` | Passed |
| TC-ESC-05 | One escalation path | A remote door unlock is Critical Management Escalation; the only `ESCALATE_` step is `ESCALATE_CRITICAL_MANAGEMENT`; other AI escalation steps are listed as rejected with the reason | `test_difficult_cases.py::test_validated_steps_follow_one_escalation_path` | Passed |
| TC-ESC-06 | Rule deactivation | Deactivating the rule that fires on a legal threat removes it from the fired list; it is reactivated afterwards | `test_defects_and_live_changes.py::test_disabling_an_escalation_rule_changes_validation` | Passed |
| TC-ESC-07 | Escalation without AI | With no API key the validated decision is still safety with escalation required | `test_ai_not_configured.py::test_no_api_key_means_no_ai_output_and_manual_review` | Passed |
| TC-ESC-08 | Real model, Lab | LAB-DEF-01: the AI answer with the escalation removed fails ESC-001; final level Critical Management Escalation | `reports/security_adversarial/summary.md` | Met |
| TC-ESC-09 | Real model, unseen cases | Escalation required: rules 94.7%, AI 92.8%; escalation level: rules 94.1%, AI 84.9% | Holdout run #1 | Measured |

In the demo data the rules enforced 35 escalations that the AI had not proposed (ESC-001 failed for 35 of 604 analysed operational complaints; the escalation report lists them as "Enforced by rules (AI missed)").

## 33.15 Resolution and eligibility testing

Resolution rules (116 in `rules/complaint_rules/resolution_rules.yaml`) define required, recommended and prohibited actions, and refund, replacement and compensation eligibility, with parameters such as `refund_window_days = 30` (REF-POL-02 section 3.1) taken from `rules/parameters.yaml`. RES-001 to RES-004 and ELG-001 to ELG-003 compare the AI's proposal with the rule. Table 33.17 lists the test cases.

**Table 33.17 — Resolution and eligibility test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-RES-01 | Refund window edges | With `refund_window_days` = 30: 0, 29 and 30 days inside, 31 and 365 outside | `test_boundaries.py::test_refund_window_edge` (5) | Passed |
| TC-RES-02 | Unsupported refund | A working vacuum delivered 75 days ago: refund `not_eligible`, and no unsupported refund promise can be sent | `test_difficult_cases.py::test_unsupported_refund_request` | Passed |
| TC-RES-03 | Unsupported compensation | A demand for USD 500 for a two-day delay: no amount of 500 or more granted, and a reply mentioning 500 cannot be sent | `test_difficult_cases.py::test_unsupported_compensation_request` | Passed |
| TC-RES-04 | Parameter change | Setting `refund_window_days` to 21 turns a 25-day return from eligible or requires-verification into `not_eligible`; the value is restored | `test_defects_and_live_changes.py::test_changing_a_rule_parameter_changes_the_decision` | Passed |
| TC-RES-05 | Unsupported refund promise | `unsupported_refund` fault profile: RSP-002 fails and the case goes to Manual Review | `::test_fault_profile_on_custom_complaint[unsupported_refund-RSP-002]` | Passed |
| TC-RES-06 | Prohibited action | `prohibited_action` fault profile (asks for card number and password): RSP-006 fails | `::test_fault_profile_on_custom_complaint[prohibited_action-RSP-006]` | Passed |
| TC-RES-07 | Real model, Lab | LAB-REF-01 final refund `not_eligible`; LAB-CMP-02 USD 200 goodwill caught by ELG-003; LAB-DEF-05 unsupported delivery date caught by RSP-003 | `reports/security_adversarial/summary.md` | Met |
| TC-RES-08 | Real model, unseen cases | Refund eligibility: rules 93.4%, AI 60.5%; replacement: 93.4% / 85.5%; compensation: 95.4% / 79.0% | Holdout run #1 | Measured |

## 33.16 Policy testing

Policy tests cover retrieval of Active versions only, version control, precedence between conflicting sources (CHP-POL-01 section 10) and the policy checks POL-001 to POL-006 and SCH-004. Table 33.18 lists the test cases.

**Table 33.18 — Policy test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-POL-01 | Active evidence only | All retrieved evidence in the end-to-end case is Active, including a SAF policy | `test_full_chain.py::test_complete_complaint_chain` | Passed |
| TC-POL-02 | Revised policy impact | After REF-POL-02 v2.1 is uploaded, the impact lists sections 3.1, 3.2 and 4.3 as changed, flags `refund_window_days` as out of sync with a suggested value of 21, and search returns only v2.1 | `test_defects_and_live_changes.py::test_revised_policy_upload_versioning_and_impact` | Passed |
| TC-POL-03 | Previous version not retrieved | After TST-POL-90 v1.1, knowledge search finds v1.1 and never v1.0 | `test_full_chain.py::test_document_upload_and_policy_versioning_journey` | Passed |
| TC-POL-04 | Contradictory FAQ | A customer quoting the FAQ's 3-day refund statement gets a precedence conflict or FAQ evidence in the retrieval result, or manual review | `test_difficult_cases.py::test_contradictory_policy_resolved_by_precedence` | Passed |
| TC-POL-05 | Invented policy | `hallucinated_policy` fault profile (REF-POL-99 section 9.9): SCH-004 fails and the case goes to Manual Review | `::test_fault_profile_on_custom_complaint[hallucinated_policy-SCH-004]` | Passed |
| TC-POL-06 | Fake IDs, versions and sections | REF-POL-77 section 9, CPN-POL-11 section 12 and CPN-POL-11 v9 are reported; REF-POL-02 section 3.1 is not | `test_perception_security.py::test_fake_policy_ids_versions_sections` | Passed |
| TC-POL-07 | Real model, Lab | LAB-POL-01 never cites REF-POL-77; LAB-POL-02 fails SCH-004; LAB-POL-03 (superseded RET-SOP-23) fails POL-002 | `reports/security_adversarial/summary.md` | Met |

The strictest test of the three is TC-POL-04: it accepts any of three outcomes (a precedence conflict, FAQ evidence or manual review) because the offline double does not always retrieve the FAQ section.

## 33.17 Hallucination testing

Hallucination checks live in `backend/src/supportnova/hallucination_checks/grounding.py` and `promises.py`. HAL-001 checks each claim against the complaint, the retrieved evidence and the verified facts; HAL-002 checks extracted entities against the complaint text; HAL-003 checks the summary; HAL-004 checks policy IDs named in the text. Table 33.19 lists the test cases.

**Table 33.19 — Hallucination test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-HAL-01 | Paraphrase versus invention | A real model's paraphrase of an angry complaint and a policy claim citing evidence E1 are supported; an invented fact (deleted schedules) and an invented promise (free replacement hub) are not | `test_perception_security.py::test_claim_grounding_accepts_paraphrase_but_not_invented_facts` | Passed |
| TC-HAL-02 | Invented order number | `hallucinated_entity` fault profile (LMR-999999): HAL-002 fails and the case goes to Manual Review | `::test_fault_profile_on_custom_complaint[hallucinated_entity-HAL-002]` | Passed |
| TC-HAL-03 | Checks always run | HAL-001, HAL-002 and HAL-004 are present in the end-to-end validation | `test_full_chain.py::test_complete_complaint_chain` | Passed |
| TC-HAL-04 | Real model, Lab | LAB-DEF-04 fails HAL-002, HAL-003 and RSP-004; LAB-POL-01 fails HAL-004 on REF-POL-77 | `reports/security_adversarial/summary.md` | Met |

## 33.18 Prompt-injection testing

Complaint text is untrusted data (SRS Step 50). `backend/src/supportnova/security/injection.py` screens it with pattern families such as `instruction_override`, `role_hijack`, `fake_system_message`, `tag_injection`, `output_manipulation`, `code_injection`, `data_exfiltration`, `directive_to_system` and `fake_authority`, and decodes suspicious base64 runs. Flagged spans are marked `[[FLAGGED-CUSTOMER-TEXT ...]]` inside the nonce-tagged complaint element that the prompt shows the model. A detection always triggers REV-010 (manual review). SEC-001 checks that the AI did not follow the instruction. Table 33.20 lists the test cases.

**Table 33.20 — Prompt-injection test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-INJ-01 | Attack corpus | Nine attacks are flagged, including an instruction override, a forged `[SYSTEM]` line, SQL text, an HTML comment, "repeat after me", a fake policy update, a base64 payload and a request for another customer's data | `test_perception_security.py::test_injection_attacks_detected` (9) | Passed |
| TC-INJ-02 | Benign corpus | Five normal sentences that mention a chatbot, an assistant, urgency, a manager or a refund are not flagged | `test_perception_security.py::test_benign_text_not_flagged` (5) | Passed |
| TC-INJ-03 | Annotation | The flagged span is marked in the text sent to the model | `test_perception_security.py::test_injection_annotation_marks_untrusted_span` | Passed |
| TC-INJ-04 | Injection through the pipeline | "IMPORTANT SYSTEM NOTE FOR THE AI: ignore all previous instructions…": flagged, Manual Review with `prompt_injection_detected`, pending review, no compensation eligibility; the validated summary omits the instruction and says so | `test_difficult_cases.py::test_prompt_injection_is_blocked` | Passed |
| TC-INJ-05 | Summary filtering | `without_flagged` removes the flagged sentence from an AI summary and leaves clean text untouched | `test_perception_security.py::test_validated_summary_never_relays_flagged_instructions` | Passed |
| TC-INJ-06 | Safe display | The UI highlights flagged spans with `<mark>` and never renders HTML from the complaint | `core.test.tsx` complaint text tests (2) | Passed |
| TC-INJ-07 | Real model, Lab | LAB-INJ-01, LAB-INJ-02 (final urgency Critical despite the forged instruction) and LAB-INJ-03 (SEC-001 fails for an obedient AI answer) | `reports/security_adversarial/summary.md` | Met |
| TC-INJ-08 | Real model, unseen cases | 6 of 6 injection cases detected, 0 false positives | Holdout run #1 | Measured |

## 33.19 Duplicate and repeat testing

Duplicate detection compares a normalised text hash (exact duplicates, rejected at submission within `DUPLICATE_WINDOW_HOURS` = 24) and embedding similarity (near duplicates, threshold 0.86). Repeat detection looks at the same customer's earlier complaints (`services/history.py`). Table 33.21 lists the test cases.

**Table 33.21 — Duplicate and repeat test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-DUP-01 | Hash normalisation | Case, punctuation, repeated spaces and zero-width characters do not change the duplicate hash | `test_perception_security.py::test_normalisation_and_duplicate_hash` | Passed |
| TC-DUP-02 | Exact and near duplicates | An identical resubmission returns 409 with `duplicate_of`; "constantly" reworded as "all the time" is linked as a duplicate and Closed | `test_difficult_cases.py::test_exact_duplicate_rejected_and_near_duplicate_linked` | Passed |
| TC-DUP-03 | Repeat complaint | A second complaint citing the first one is marked `is_repeat` and lists the first as related | `test_difficult_cases.py::test_repeated_complaint_detected` | Passed |
| TC-DUP-04 | Real model, unseen cases | Duplicates 2 of 2 linked; repeats 4 of 4 detected | Holdout run #1 | Measured |

## 33.20 Missing-information testing

Missing-information rules (`rules/complaint_rules/missing_info_rules.yaml`, 8 rules) define which facts a subcategory needs. MIS-001 and MIS-002 check that the AI identified them and asked for them; the validated decision carries the clarification questions that the response must contain. Table 33.22 lists the test cases.

**Table 33.22 — Missing-information test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-MIS-01 | Refund without order | Missing information and clarification questions are produced | `test_difficult_cases.py::test_missing_information_triggers_clarification` | Passed |
| TC-MIS-02 | Clarification loop | The customer's answer is accepted with 202 and the case is re-analysed | `test_full_chain.py::test_customer_clarification_loop` | Passed |
| TC-MIS-03 | Malformed reference | A malformed order reference is a field error instead of an unverifiable fact | `test_boundaries.py::test_order_reference_format` (3) | Passed |
| TC-MIS-04 | Real model, demo data | MIS-001 applied to 107 of 604 analysed operational complaints (51 pass, 56 fail); for every blocking item the AI did not ask about, the validated decision appends the rule's own question | `validation_checks` (demo database), `python_validation/engine.py` | Measured |
| TC-MIS-05 | Real model, unseen cases | Missing information: rules 77.0%, AI 59.2%; incomplete cases: rules all key fields right 5 of 6, AI 4 of 6 | Holdout run #1 | Measured |

## 33.21 Multi-issue testing

A multi-issue complaint has one primary and one or more secondary issues. Precedence (RTE-RUL-14 section 5) puts safety, security and privacy first, and supporting departments come from the secondary issues and conditional routing rules. Table 33.23 lists the test cases.

**Table 33.23 — Multi-issue test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-MUL-01 | Three issues, one risky | Late delivery, overheating with a burning smell and a double charge: primary SAF, secondary issues kept, supporting departments present | `test_difficult_cases.py::test_multi_issue_multi_department` | Passed |
| TC-MUL-02 | Precedence in the classifier | Overheating beats a higher-scoring delivery issue; DEL stays secondary | `test_perception_security.py::test_risk_precedence_beats_higher_scoring_issue` | Passed |
| TC-MUL-03 | Real model, unseen cases | 8 multi-issue cases: rules all key fields right 7 of 8, AI 3 of 8 | Holdout run #1 | Measured |

## 33.22 Hidden-data readiness testing

The SRS requires that hidden complaints, a new category, a revised policy and live rule changes are processed without changing the core source code (section 1.8). These tests perform exactly those changes through the API at run time; Table 33.24 lists them.

**Table 33.24 — Hidden-data readiness test cases**

| ID | Test | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-HID-01 | New category | ENV "Environment & Recycling" and ENV-RCY with keywords and a department are created through `POST /taxonomy/categories` and `/subcategories`; a recycling complaint is classified ENV-RCY | `test_defects_and_live_changes.py::test_new_category_without_code_changes` | Passed |
| TC-HID-02 | Minimal hidden dataset | A CSV with only `complaint_id,title,description` (3 rows) is uploaded to `POST /evaluation/runs/upload`; the run completes with 3 cases | `::test_hidden_dataset_upload_with_minimal_columns` | Passed |
| TC-HID-03 | Unseen holdout run | A 12-case holdout run completes with headline metrics, 12 results and a PDF report | `::test_evaluation_run_on_unseen_holdout` | Passed |
| TC-HID-04 | Revised policy | The hidden-pack REF-POL-02 v2.1 replaces v2.0 and its impact is analysed | `::test_revised_policy_upload_versioning_and_impact` | Passed |
| TC-HID-05 | Rule edit preview | An escalation rule with an unknown level ("Galactic Escalation") is reported invalid by the preview and refused with 422 on save; the preview writes nothing (same ruleset hash, rule version and audit count) | `::test_rule_edit_preview_validates_without_saving` | Passed |
| TC-HID-06 | Parameter and rule changes | Refund window and escalation rule changes take effect immediately | `::test_changing_a_rule_parameter_changes_the_decision`, `::test_disabling_an_escalation_rule_changes_validation` | Passed |
| TC-HID-07 | Real model, unseen cases | Evaluation run #1 processed all 154 unseen holdout cases (0 rejected at intake) | Holdout run #1 | Measured |

## 33.23 Boundary testing

Every limit in `tests/backend/api/test_boundaries.py` is probed on both sides of its edge (29 tests); the file header states the rule. Table 33.25 groups them by limit.

**Table 33.25 — Boundary test cases**

| ID | Limit | Values tested (rejected in bold) | Evidence | Result |
|---|---|---|---|---|
| TC-BND-01 | Title 5 to 180 characters | **4**, 5, 180, **181**; **201** hits the schema cap | `::test_title_length_edges` (4), `::test_title_over_the_hard_cap_is_a_field_error_not_a_crash` | Passed |
| TC-BND-02 | Description 20 characters, 4 words, 8,000 characters | **empty**, **whitespace**, 21 chars, **18 chars**, **one 30-char word**, 8,000, **8,001**; **10,001** hits the schema cap | `::test_description_length_edges` (7), `::test_description_over_the_hard_cap_is_a_field_error_not_a_crash` | Passed |
| TC-BND-03 | Order reference `LMR-` plus 6 digits | **LMR-12345**, LMR-123456, **ORDER-1** | `::test_order_reference_format` (3) | Passed |
| TC-BND-04 | Refund window 30 days | 0, 29, 30, **31**, **365** | `::test_refund_window_edge` (5) | Passed |
| TC-BND-05 | Upload size | exactly at the limit, **limit + 1 byte**, **empty** | `::test_upload_size_edge` | Passed |
| TC-BND-06 | Page size 1 to 200, page at least 1 | 200, **201**, **0**, **page 0**, page 9999 (empty list) | `::test_list_pagination_limits` (5) | Passed |
| TC-BND-07 | Request body shape | **invalid JSON**, **JSON list** | `::test_malformed_body_is_a_field_error_not_a_crash` | Passed |
| TC-BND-08 | Profile default | customer type taken from the profile | `::test_customer_precheck_uses_the_profile_customer_type` | Passed |

## 33.24 Security testing

Security testing is described in Chapter 34 (test matrix) and Appendix G (every case). Table 33.26 summarises the evidence.

**Table 33.26 — Security testing summary**

| ID | Area | What it verifies | Evidence | Result |
|---|---|---|---|---|
| TC-SEC-01 | Authentication and sessions | 401 without a session, lockout after 5 failures, CSRF, rate limit that ignores spoofed headers | `test_security_api.py` | Passed |
| TC-SEC-02 | Authorisation | 11 endpoints × 5 roles; customers see only their own cases; denials are audited | `test_security_api.py` | Passed |
| TC-SEC-03 | Secrets | The AI key never appears in public configuration, status or system endpoints | `test_security_api.py::test_ai_key_never_exposed` | Passed |
| TC-SEC-04 | Uploads and documents | Executables, disguised and oversized files rejected; malicious document quarantined | Sections 33.7 and 33.8 | Passed |
| TC-SEC-05 | Audit immutability | Direct SQL UPDATE and DELETE on `audit_logs` fail; the chain stays valid | `test_security_api.py::test_audit_log_is_append_only_in_the_database` | Passed |
| TC-SEC-06 | Adversarial content | Injection corpus, fake policies, sensitive data, deliberate AI defects | Sections 33.15 to 33.18 | Passed |
| TC-SEC-07 | Real model | 18 of 18 Lab scenarios met; 6 of 6 holdout injections detected | `reports/security_adversarial/summary.md`, holdout run #1 | Met |

## 33.25 Performance testing

Performance has been measured, not load-tested. Every analysis stores its stage timings and total latency in the `analyses` table (`stage_timings`, `total_latency_ms`), and every GenAI attempt stores its latency and token counts in `ai_runs`. Table 33.27 summarises the measurements from the demo database and evaluation run #1. Chapter 35 analyses them. No load test, stress test or availability measurement has been performed; they are marked Planned.

**Table 33.27 — Performance test cases**

| ID | Test | What it measures | Evidence | Result |
|---|---|---|---|---|
| TC-PRF-01 | Full pipeline, demo import | 599 analysed dataset complaints, 4 in parallel: p50 21.7 s, p95 33.9 s, 32.4% within 20 s | `analyses.total_latency_ms` | Measured; 20 s target missed for the full pipeline |
| TC-PRF-02 | Validated recommendation | Preprocessing, retrieval, AI analysis and validation: p50 16.2 s, p95 24.9 s, 80.8% within 20 s | `analyses.stage_timings` | Measured |
| TC-PRF-03 | Holdout run | 154 cases: p50 21.2 s, p95 33.8 s, maximum 44.6 s per complaint; whole run 858 s | `evaluation_runs.metrics` (run #1) | Measured |
| TC-PRF-04 | GenAI calls | Analysis call average 16.5 s (780 valid attempts); response call average 5.6 s (780) | `ai_runs.latency_ms` | Measured |
| TC-PRF-05 | Deterministic stages | Averages: preprocessing 21 ms, retrieval 3.6 ms, validation 2.2 ms, response validation 2.4 ms | `analyses.stage_timings` | Measured |
| TC-PRF-06 | Batch throughput | 617 complaints imported and processed in 3,485 s (58.1 min) with `BATCH_WORKERS=4` | `audit_logs` entry `dataset.imported` | Measured |
| TC-PRF-07 | Load at SRS scale | 10,000 complaints, 100 categories and subcategories, 1,000 documents, concurrent users | — | Planned (not performed) |
| TC-PRF-08 | Availability | 99% uptime during evaluation | — | Planned (not measured) |

## 33.26 Frontend testing

The frontend tests run with vitest in jsdom (`frontend/vite.config.ts`, `test.environment = 'jsdom'`). `frontend/src/test/setup.ts` adds jest-dom matchers and stubs the browser APIs that jsdom lacks (`ResizeObserver`, `matchMedia`, `scrollIntoView`). `frontend/src/test/utils.tsx` provides `mockFetch`, a small router for fake API responses, and `renderWithProviders`, which wraps a component in React Query, the authentication provider, tooltips and a memory router. Table 33.28 lists the 12 tests.

**Table 33.28 — Frontend test cases**

| ID | Test (`core.test.tsx`) | What it verifies | Result |
|---|---|---|---|
| TC-FE-01 | utilities › formats values for display | `titleCase`, `pct` (76%, an em dash for null) and `display` for lists and booleans | Passed |
| TC-FE-02 | utilities › builds query strings with repeated keys and skips empty values | Repeated `status` keys, empty and undefined values dropped | Passed |
| TC-FE-03 | API client › sends the CSRF token on unsafe requests and never on GET | `X-CSRF-Token` from the `sn_csrf` cookie only on POST; `credentials: same-origin` | Passed |
| TC-FE-04 | API client › maps error payloads to ApiError with field errors | A 422 envelope becomes `ApiError` with `fieldErrors.title` | Passed |
| TC-FE-05 | status badges › renders consistent semantic badges | Manual Review with score 72, "P0 · Critical", "Mismatch" | Passed |
| TC-FE-06 | complaint text › highlights flagged injection spans and never renders HTML | A `<mark>` around the flagged span; an `<img onerror>` payload shown as text, no `img` element | Passed |
| TC-FE-07 | complaint text › marks every occurrence, including spans broken across lines | Three occurrences of "internal note" marked, one across a line break | Passed |
| TC-FE-08 | pipeline tracker › uses plain stage names | "AI analysis" and "Rule check" shown; no "Python" or "GenAI" in the UI | Passed |
| TC-FE-09 | error state › shows the message and retries | The server message is shown and "Try again" calls the retry handler | Passed |
| TC-FE-10 | login form › validates required fields before calling the API | Two field messages; no request to `/auth/login` | Passed |
| TC-FE-11 | login form › fills a demo account served by the backend and shows server errors | The demo account comes from `/auth/demo-accounts`; the 401 message is shown; the exact credentials are posted | Passed |
| TC-FE-12 | login form › shows no demo accounts when the server has them disabled | No "Demo accounts" section | Passed |

In addition, `scripts/capture_screenshots.py` drives the running application in a browser, captures every page in `screenshots/` and exits with an error if any page logs a console error or an uncaught exception. The 31 recorded screenshots were captured with no console errors. This is a smoke check, not an assertion-based UI test suite.

## 33.27 Real-model evaluation

Evaluation run #1 ("holdout baseline") processed the 154 holdout complaints in `data/hidden_test_ready/holdout_complaints.jsonl` on 24 September 2026, with `openai/gpt-4.1-mini`, prompts `complaint_analysis` 1.2.0 and `customer_communication` 1.0.0 and ruleset hash `be81124c2a1df0d5`, in 858 s. The holdout scenarios were never used to tune the rules or the prompts: the dataset validator confirms that no holdout scenario ID appears in the dev set and that the highest token-set Jaccard similarity between a holdout and a dev complaint is 0.421. The evaluation service (`backend/src/supportnova/services/evaluation.py`) compares, for every case, the expected label with the AI proposal and the Python result. Its key fields are category, subcategory, department, urgency, priority and escalation level. An AI error counts as caught when the rules got every wrong key field right, or when the case was sent to manual review. A second holdout run (#2) was cancelled after 6 of 154 cases and is not used anywhere in this report. Table 33.29 gives the headline metrics of run #1, Table 33.30 the accuracy per field and Table 33.31 the results by difficulty type.

**Table 33.29 — Evaluation run #1 headline metrics**

| Metric | Value |
|---|---|
| Cases | 154 (152 analysed, 2 linked as duplicates) |
| Rules (Python) key-field accuracy | 82.7% |
| AI key-field accuracy | 79.2% |
| AI and rules key-field agreement | 70.6% |
| Cases with at least one AI key-field error | 93 |
| AI errors caught by the rules or by manual review | 92 of 93 (98.9%) |
| Verified automatically | 22 (14.3%) |
| Sent to manual review | 130 (84.4%) |
| Expected manual-review cases also sent to review | 48 of 51 (94.1%) |
| Prompt injection | 6 of 6 detected, 0 false positives |
| Duplicates linked / repeats detected | 2 of 2 / 4 of 4 |
| Latency per complaint | p50 21.2 s, p95 33.8 s, maximum 44.6 s |

**Table 33.30 — Evaluation run #1 accuracy per field (n = 152)**

| Field | Rules (Pipeline 2) | AI (Pipeline 1) | AI and rules agree |
|---|---|---|---|
| Category | 75.7% | 89.5% | 69.7% |
| Subcategory | 68.4% | 77.6% | 58.6% |
| Department | 84.9% | 92.1% | 84.9% |
| Supporting departments | 74.3% | 73.7% | 61.8% |
| Urgency | 84.2% | 68.4% | 66.5% |
| Priority | 88.8% | 62.5% | 61.2% |
| Escalation required | 94.7% | 92.8% | 91.5% |
| Escalation level | 94.1% | 84.9% | 82.9% |
| Refund eligibility | 93.4% | 60.5% | 62.5% |
| Replacement eligibility | 93.4% | 85.5% | 82.9% |
| Compensation eligibility | 95.4% | 79.0% | 76.3% |
| Follow-up type | 75.7% | 44.1% | 39.5% |
| Missing information | 77.0% | 59.2% | 47.4% |
| Policy references | 76.3% | 5.9% | 5.9% |
| Resolution rule | 75.0% | 0.0% | 0.0% |

Two rows need reading with care. The AI never sees the Rule Matrix, so it cannot name a resolution rule ID; its 0.0% on "resolution rule" is a consequence of the design, not a model failure. Policy references are compared as an exact set against the sections the rules require; the AI cites the retrieved sections it relied on, which rarely form exactly that set. For the fields where the rules decide (urgency, priority, escalation, eligibility), Pipeline 2 is clearly more accurate than the model. For classification the model is better, which is why a low-confidence rule classification sends the case to a reviewer instead of silently overriding the AI.

**Table 33.31 — Evaluation run #1 by difficulty type**

| Type | Cases | Rules: all key fields right | AI: all key fields right | Verified | Manual review |
|---|---|---|---|---|---|
| Simple | 101 | 67 | 44 | 15 | 86 |
| Emotional low priority | 9 | 6 | 2 | 2 | 7 |
| Multi-issue | 8 | 7 | 3 | 2 | 6 |
| Incomplete | 6 | 5 | 4 | 0 | 6 |
| Prompt injection | 6 | 3 | 1 | 0 | 6 |
| Contradictory policy | 6 | 5 | 2 | 2 | 4 |
| Repeat | 4 | 1 | 1 | 0 | 4 |
| Ambiguous | 4 | 1 | 0 | 0 | 4 |
| Unsupported refund | 4 | 2 | 1 | 1 | 3 |
| High value | 2 | 1 | 0 | 0 | 2 |
| VIP minor | 1 | 0 | 1 | 0 | 1 |
| Near duplicate | 1 | 1 | 1 | 0 | 0 |
| Exact duplicate | 1 | 1 | 1 | 0 | 0 |
| Unsupported compensation | 1 | 0 | 0 | 0 | 1 |

![Figure 33.2 — Evaluation run #1 on the holdout dataset in the Evaluation page](../screenshots/24-evaluation-run-holdout.png)
*Figure 33.2 — Evaluation run #1 on the holdout dataset in the Evaluation page*

Figure 33.2 shows the same run in the application: rules accuracy 82.7%, AI accuracy 79.2%, AI errors caught 92 of 93, and the case-by-case comparison with the explanation of each disagreement.

The dataset validator (`scripts/validate_dataset.py`) is the test for the data itself. Re-run on 25 September 2026, it reported PASS 78, WARN 0, FAIL 0 (Table 33.32).

**Table 33.32 — Dataset validator checks**

| Check group | Checks | What they verify | Result |
|---|---|---|---|
| Files and schema | 3 | 7 files present, CSV rows equal JSONL rows (617 and 154), 771 records valid against `complaint_record.schema.json` | PASS |
| SRS minimums and mix | 60 | 38 dev counts (for example 617 complaints, 31 prompt injection, 70 calm critical), 21 holdout counts, all 116 resolution rules used | PASS |
| IDs and dates | 2 | CMP-00001 to CMP-00617 and EVL-00001 to EVL-00154, chronological, inside each split's window | PASS |
| References and codes | 4 | Customers, 594 orders, transactions and links resolve; every code exists in the configuration; cited sections exist | PASS |
| Signals and labels | 4 | Declared signals exist and appear in the text outside negation; `label_declared` reproduces all rule-derived labels for 771 records | PASS |
| Holdout, uniqueness, consistency | 5 | 132 holdout scenarios disjoint from dev; maximum Jaccard 0.421; texts unique except 10 deliberate duplicates; derived flags consistent; customer mix 60/20/10/10 | PASS |

## 33.28 Gaps and findings

Table 33.33 lists the known gaps. They are reported here rather than hidden.

**Table 33.33 — Testing gaps and findings**

| Item | Status | Detail |
|---|---|---|
| Load and stress testing | Planned | No test has run 10,000 complaints, 1,000 documents or concurrent users (Chapter 35) |
| Availability measurement | Planned | The 99% uptime target has not been measured; `GET /api/v1/health` reports database status but no monitoring is deployed |
| Browser-level end-to-end tests | Future Enhancement | End-to-end tests drive the HTTP API; the UI is covered by 12 component tests and the screenshot smoke check |
| Code coverage figure | Not measured | `pytest-cov` 7.1.0 is installed (`requirements-dev.txt`) but no coverage percentage was recorded, so none is claimed |
| Model variance | Not measured | One complete holdout run exists; repeated runs to measure run-to-run variation of the model have not been made |
| Evaluation-run export content | Defect found | `test_evaluation_run_on_unseen_holdout` only checks that the PDF starts with `%PDF`. While this report was written, the exported per-case comparison for run #1 (`reports/genai_python_comparison/genai-python-comparison.csv`, `.pdf`, `.xlsx`) was found to have empty AI and rules columns (Chapter 39) |

The last finding matters for the SRS comparison deliverable. The run's metrics (`summary.md`), the Evaluation page (Figure 33.2) and `GET /api/v1/evaluation/runs/1/results` carry the correct per-case data. Only the file export of a run's case table is affected.
