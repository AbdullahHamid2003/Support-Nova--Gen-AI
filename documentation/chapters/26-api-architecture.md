# Chapter 26 — API Architecture

## 26.1 Overview

SupportNova's backend is a FastAPI 0.141.1 application built by `create_app()` in `backend/src/supportnova/main.py`. Eight router modules in `backend/src/supportnova/api/v1/` are mounted under the prefix `/api/v1` (setting `api_prefix`) and together define 95 routes. `main.py` adds two routes of its own: `GET /api/health`, a liveness alias, and `GET /api/v1/system/seed-status`, which reports the progress of the background import of the demo dataset. The OpenAPI description is served at `/api/docs`, `/api/redoc` and `/api/openapi.json`. The built React application is served from the same origin (`SERVE_FRONTEND`), so the browser talks to the API without cross-origin requests, and the AI provider key never leaves the server.

All 95 routes were extracted from the source code for this chapter and compared with the verified route list in `documentation/_work/facts.md`; method, path, handler and permission matched for every route. Appendix L lists all of them. Of the 95 routes, 59 use GET, 33 POST and 3 PUT. There is no DELETE route: complaints, analyses, documents, users and audit entries are never deleted through the API, which matches the database design in Chapter 25. Table 26.1 shows how the routes are distributed over the modules.

**Table 26.1 — API router modules**

| Module (api/v1) | OpenAPI tag | Routes | Scope |
|---|---|---|---|
| auth.py | auth | 11 | sign-in, session, public form configuration, users, roles, staff and customer lookup |
| complaints.py | complaints | 18 | submission, search, case detail, pipeline progress, lifecycle, responses, follow-ups, case report, export |
| reviews.py | reviews | 4 | manual review queue and reviewer actions |
| knowledge.py | knowledge | 11 | documents, versions, retrieval playground, policy conflicts, statistics |
| rules.py | rules | 19 | Rule Matrix, parameters, validation, simulator, taxonomy, prompts, AI status and AI runs |
| insights.py | analytics | 12 | role dashboards, analytics, reports |
| quality.py | quality | 14 | evaluation runs and the Adversarial Lab |
| system.py | system | 6 | health, audit log, audit verification and export, system information |

## 26.2 Request processing layers

Every request passes through the same layers, shown in Figure 26.1. The design keeps each concern in one place: middleware handles transport concerns, dependencies decide who the caller is and what the caller may do, Pydantic models check the shape of the request, route handlers stay thin, and the service layer holds the business logic and writes the audit trail.

![Figure 26.1 — Layers of an API request, from the client to PostgreSQL and the background pipelines](diagrams/architecture/fig-26-01-api-request-layering.svg)
*Figure 26.1 — Layers of an API request, from the client to PostgreSQL and the background pipelines*

**Middleware.** `create_app()` registers three middlewares in `api/middleware.py` and FastAPI's `CORSMiddleware`, in the order RateLimitMiddleware, CORSMiddleware, RequestContextMiddleware. Starlette inserts each new middleware at the front of its list (`starlette/applications.py`, `add_middleware`), so the last one registered runs first. `RequestContextMiddleware` therefore wraps every response, including rate-limit rejections: it takes the caller's `X-Request-ID` or generates a 16-character hexadecimal ID, makes it available to logging and to the error envelope, and adds the response headers `X-Request-ID`, `Server-Timing`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy` and a restrictive `Content-Security-Policy` (not sent on the API documentation pages). `CORSMiddleware` allows only the origins in `CORS_ORIGINS`, with credentials, and exposes `X-Request-ID` and `Content-Disposition`. `RateLimitMiddleware` applies the limits described in Section 26.3.7.

**Dependencies.** `api/deps.py` provides `db_session` (one SQLAlchemy session per request), `current_user` (authentication and the CSRF check) and the permission factories `require()` and `require_any()`. FastAPI resolves a route's dependencies before it reports validation errors in the route's own parameters (`fastapi/dependencies/utils.py`, `solve_dependencies`), so a request without a valid session is rejected with 401 before its query or body is examined, and a caller without the permission receives 403 even if the body is malformed.

**Handlers and services.** Route handlers parse the request, call a service in `services/`, commit and serialise the result. Serialisation is role-aware (`api/serializers.py`): the same `GET /complaints/{ref}` returns customer-safe fields to a customer and the full case, including the AI output and every validation check, to staff. Services record audit entries with `audit.record()`, which are chained and written when the transaction commits (Section 25.6).

**Background work.** Seven routes return 202 Accepted and hand the work to the in-process worker (`services/worker.py`, a `ThreadPoolExecutor` with `BACKGROUND_WORKERS` threads, 2 by default): complaint submission, reprocessing, clarification, the two evaluation-run starts and the two lab-run starts. The worker runs the GenAI Complaint Intelligence Pipeline (Pipeline 1) and the Python Ground-Truth Validation Pipeline (Pipeline 2) and stores the results; the client follows progress by polling (Section 26.3.8).

**Error handlers.** `api/errors.py` converts every exception into one JSON envelope (Section 26.3.5). Application errors keep their status and code; request-validation errors become 422 with a field list; database integrity errors become 409, an unavailable database 503, and any unexpected exception a generic 500. Stack traces are logged on the server and never returned.

## 26.3 Conventions

### 26.3.1 Paths, formats and status codes

All application routes live under `/api/v1`; the tables in Section 26.4 give paths relative to that prefix. Request and response bodies are JSON, except file uploads, which use `multipart/form-data` (complaint attachments in the field `attachments`, policy documents and evaluation datasets in the field `file`), and file downloads, which are returned with a `Content-Disposition: attachment` header: CSV, Excel (`.xlsx`), PDF, JSON and, for the Rule Matrix only, YAML. Successful calls return 200, except the six routes that create a resource (a user, a document version, a category, a subcategory, a department or a prompt version), which return 201, and the seven background routes, which return 202.

### 26.3.2 Authentication

`POST /auth/login` checks the e-mail and bcrypt password hash and, on success, sets two cookies. `sn_access` holds a signed access token and is HttpOnly, `SameSite=Lax`, `Secure` when `COOKIE_SECURE` is set, and valid for `ACCESS_TOKEN_MINUTES` (480 by default). `sn_csrf` holds the CSRF token and is readable by the page's script. The response body also contains `csrf_token` and `access_token`, so non-browser clients can use `Authorization: Bearer <token>` instead of cookies; when both are present, the Bearer header is used.

The access token is a JWT signed with HS256 (`security/auth.py`). It carries `sub` (user ID), `role`, `iat`, `exp`, a random `jti` and the issuer `supportnova`, and decoding requires `exp`, `sub`, `iat` and the issuer. An expired token yields 401 `token_expired`, any other invalid token 401 `invalid_token`, and a token of a deactivated user 401. Five consecutive failed sign-ins lock an account for five minutes (401 `account_locked`), and every failed sign-in is audited. In production mode the application refuses to start with the development signing key or a key shorter than 32 characters (`core/config.py`). Chapter 24 describes the roles and permissions in detail.

### 26.3.3 CSRF protection

Because the browser sends the `sn_access` cookie automatically, every cookie-authenticated POST, PUT, PATCH or DELETE request must echo the CSRF token: the `X-CSRF-Token` header must equal the `sn_csrf` cookie, compared in constant time. Otherwise `current_user` rejects the request with 403 `csrf_failed`. Requests authenticated with a Bearer header are exempt, because a browser never adds that header on its own. The frontend client (`frontend/src/lib/api.ts`) adds the header to every non-GET request. Both sides are tested: `tests/backend/api/test_security_api.py::test_cookie_session_requires_csrf_header` and the frontend test "sends the CSRF token on unsafe requests and never on GET" in `frontend/src/test/core.test.tsx`.

### 26.3.4 Authorisation per route

Every route declares its access rule through a dependency, and the rule is enforced on the server whatever the user interface shows. The 95 routes use four kinds of rule.

**Table 26.2 — Kinds of access rule**

| Rule | Routes | Meaning |
|---|---|---|
| public | 3 | no session needed: POST /auth/login, GET /auth/demo-accounts, GET /health |
| current_user | 10 | any signed-in user; the handler applies role logic (for example customers see only their own complaints) |
| require(permission) | 79 | the user's role must hold the named permission |
| require_any(...) | 3 | the role must hold at least one of the listed permissions (GET /staff, GET /audit, GET /complaints/{ref}/audit) |

Some handlers add checks that a single permission cannot express. A customer who requests another customer's complaint, or a lab or evaluation case, receives 404 rather than 403, so the API does not reveal that the case exists (`services/complaints.py`, `ensure_can_view`; tested by `test_customer_sees_only_own_complaints`). A customer may change a status only to Reopened. Reprocessing with a fault-injection profile additionally needs `lab:use`. `GET /system/info` requires `settings:manage`, which only administrators hold. Holders of `audit:read_complaint` (reviewers and managers) see only complaint, review, report and evaluation-run entries in `GET /audit`. Every 403 response is itself written to the audit trail as `access.denied` (`test_denied_access_is_audited`), and `test_role_permission_matrix_enforced_server_side` checks eleven protected endpoints against all five roles. The agent role holds `analytics:read_own`, but no route requires it: agents obtain their own statistics from `GET /dashboard`, whose content depends on the caller's role.

### 26.3.5 Error envelope and status codes

Every error response has the same JSON shape, produced by `_body()` in `api/errors.py`:

```json
{"error": {"code": "validation_error", "message": "Some fields are invalid.",
           "details": [{"field": "…", "message": "…"}], "request_id": "…"}}
```

`code` is a stable machine-readable string, `message` is a sentence that the user interface can show as it is, `details` carries field errors or context (for example `{"duplicate_of": "…"}` or `{"missing_permissions": [...]}`), and `request_id` matches the `X-Request-ID` header, so a user-reported error can be found in the server log. The frontend turns the envelope into an `ApiError` whose `fieldErrors` are shown next to the form fields. Table 26.3 lists the status codes the API returns.

**Table 26.3 — HTTP status codes and error codes**

| Status | Codes | When |
|---|---|---|
| 401 | authentication_required, invalid_credentials, account_locked, token_expired, invalid_token | no or invalid session, failed sign-in, locked account, inactive user |
| 403 | permission_denied, csrf_failed | role lacks the permission, or cookie request without a valid CSRF header; always audited |
| 404 | not_found | unknown complaint, review, document, version, rule, report key or run; also another customer's complaint |
| 405 | method_not_allowed | wrong HTTP method on an existing path |
| 409 | conflict, duplicate_complaint | exact duplicate complaint, duplicate document file or version, existing e-mail, evaluation run already in progress, database integrity error |
| 422 | validation_error, document_processing_error | invalid fields, business-rule violations, invalid state transitions, unreadable or corrupt documents |
| 429 | rate_limited | request limit exceeded, with header Retry-After: 30 |
| 500 | internal_error, database_error | unexpected server or database error (details are logged, not returned) |
| 503 | database_unavailable | the database cannot be reached |

`core/errors.py` also defines `AIProviderError` (502), `AITimeout` (504) and `RetrievalError` (503). AI provider failures occur inside the background pipeline, where they are handled by the retry policy and recorded in `ai_runs` (Chapter 8), so API clients see them only as the outcome of the analysis; `RetrievalError` is defined but not raised by the current code. Chapter 36 describes error handling across the whole system.

### 26.3.6 Pagination, filtering and sorting

List endpoints that can grow without bound are paginated with `page` (from 1) and `page_size` and return `{"items", "total", "page", "page_size"}`. Out-of-range values are rejected with 422; a page beyond the last one returns an empty list. This behaviour is tested by `tests/backend/api/test_boundaries.py::test_list_pagination_limits`. Smaller lists (documents, rules, prompts, users) are returned whole with a `total`.

**Table 26.4 — Pagination and filter parameters**

| Endpoint | Paging | Main filters and options |
|---|---|---|
| GET /complaints | page ≥ 1, page_size 1–200 (default 25) | q, status, category, subcategory, department, priority, urgency, sentiment, verification, escalated, sla, channel, customer_ref, date_from, date_to, needs_review, assigned_to_me, repeat, duplicate, injection, source; sort (created_at, priority, status, verification_score, complaint_ref, updated_at, urgency) and order |
| GET /reviews | page, page_size 1–200 (default 25) | status, reason, mine, include_lab |
| GET /audit | page, page_size 1–500 (default 50) | action (prefix), entity_type, entity_id, actor, date_from, date_to |
| GET /evaluation/runs/{run_id}/results | page, page_size 1–500 (default 50) | difficulty, mismatches_only |
| GET /ai/runs | limit ≤ 500 (default 50) | failed_only, stage |
| GET /analytics/trends | — | days 7–730 (default 120), granularity day or week, dimension |
| GET /analytics/alerts | — | window_days 3–90 (default 14) |

Multi-valued filters are repeated query parameters (`status=Escalated&status=Assigned`). Unless a `source` is requested explicitly, staff lists show only operational complaints (web, API and dataset sources), so Adversarial Lab and evaluation cases never mix with customer cases.

### 26.3.7 Rate limiting

`RateLimitMiddleware` counts requests per client IP address in a sliding 60-second window, for paths under `/api/` (OPTIONS requests are exempt). The limit is `RATE_LIMIT_PER_MINUTE` (240) for the API in general and `LOGIN_RATE_LIMIT_PER_MINUTE` (20) for the login path. A request over the limit receives 429 `rate_limited` with `Retry-After: 30`. The client address is the socket peer; the `X-Forwarded-For` header is ignored because a client can set it freely, and behind a reverse proxy uvicorn's `--proxy-headers` option resolves it only for trusted proxies. This is tested by `test_spoofed_forwarded_for_does_not_bypass_login_rate_limit`. The counters are held in memory, so each server process counts on its own; a shared limiter would be needed for a multi-process deployment (Chapter 43).

### 26.3.8 Asynchronous processing and polling

Submitting a complaint returns 202 with the complaint reference, status and processing stage as soon as the complaint has been validated and stored. Analysis continues in the background, and the client polls `GET /complaints/{ref}/pipeline`, which reports each pipeline stage as done, active or pending. The submission page polls it every 600 ms and the complaint page reloads the case every 1.5 seconds until processing has finished. For customers the progress response omits the verification status, score, timings and model, so validation internals never reach a customer. Evaluation and lab runs follow the same pattern and are polled through their own list endpoints.

## 26.4 Endpoints by group

The tables below cover the important endpoints of each group, with the request and response shapes taken from the Pydantic models and handlers. "Errors" lists the codes specific to the endpoint; 401 applies to every non-public endpoint and 403 to every endpoint with a permission. Appendix L lists all 95 routes with their handlers.

### 26.4.1 Authentication and users

**Table 26.5 — Authentication and user endpoints**

| Method | Endpoint | Purpose | Permission | Request | Response | Errors |
|---|---|---|---|---|---|---|
| POST | /auth/login | sign in | public (20/min) | email, password | user, permissions, csrf_token, access_token; sets cookies | 401 invalid_credentials, account_locked; 422 |
| POST | /auth/logout | sign out | current_user | — | status signed_out; clears cookies | 403 csrf_failed |
| GET | /auth/me | current session | current_user | — | user, permissions, csrf_token | 401 token_expired |
| GET | /auth/demo-accounts | demo sign-ins for the login page | public | — | enabled, password, accounts (email, role) | — |
| GET | /config/public | form options and taxonomy names | current_user | — | channels, customer types, tones, categories, departments, products, statuses, ai status, limits | — |
| GET | /users | list accounts | users:read | — | items, total | — |
| POST | /users | create account | users:manage | email, full_name, role, password (10+), department, customer_ref, is_active | 201 user | 409 e-mail exists; 422 |
| PUT | /users/{user_id} | update or deactivate | users:manage | same as create, password optional | user | 404; 422 |
| GET | /roles | roles and permissions | users:read | — | items (code, name, description, permissions) | — |
| GET | /staff | staff picker | review:act or complaint:update | role, department | items (id, full_name, role, department) | — |
| GET | /customers | customer search | complaint:read_all | q | up to 25 items | — |

`GET /auth/demo-accounts` returns accounts only while `SEED_DEMO_USERS` is on and only for demo accounts that still exist and are active (`test_demo_accounts_are_public_only_while_enabled`); the demo password is demonstration data for the fictional Lumora accounts.

### 26.4.2 Complaints

**Table 26.6 — Complaint endpoints**

| Method | Endpoint | Purpose | Permission | Request | Response | Errors |
|---|---|---|---|---|---|---|
| POST | /complaints | submit a complaint | complaint:create | JSON or multipart: title, description, channel, product_text, order_ref, transaction_ref, previous_complaint_ref, preferred_contact, requested_resolution, requested_tone, supporting_info, complaint_date, customer_ref (staff only), attachments (up to 5) | 202 complaint_ref, status, processing_stage | 409 duplicate_complaint; 422 field errors |
| POST | /complaints/validate | live pre-check, creates nothing | complaint:create | same as submit | valid, errors, duplicate_of | 422 |
| GET | /complaints | search and filter | current_user | Table 26.4 | items, total, page, page_size | 403 without complaint:read_all; 422 |
| GET | /complaints/{ref} | case detail (role-aware) | current_user | — | complaint, analysis, validation, resolution, responses, escalations, follow_ups, sla, review, related | 404 |
| GET | /complaints/{ref}/pipeline | processing progress | current_user | — | stage, status, done, failed, stages; staff also score and timings | 404 |
| GET | /complaints/{ref}/timeline | case history and audit entries | complaint:read_all | — | events, audit | 404 |
| GET | /complaints/{ref}/analyses | analysis versions | complaint:read_all | — | items (version_no, trigger, status, provider, model, prompt_versions) | 404 |
| POST | /complaints/{ref}/reprocess | re-run both pipelines | complaint:reprocess | tone, fault_profile (lab:use) | 202 complaint_ref, processing_stage | 403; 422 closed complaint |
| POST | /complaints/{ref}/status | lifecycle transition | current_user (customers: Reopened only; staff: complaint:update) | status, note (up to 1,000) | complaint_ref, status | 403; 422 transition not allowed |
| POST | /complaints/{ref}/assign | assign to staff | complaint:update | agent_id (default: caller) | complaint_ref, assigned_agent, status | 422 invalid staff member |
| POST | /complaints/{ref}/clarify | add requested information | current_user (own complaint, or complaint:update) | information (3–4,000), order_ref, product_text | 202 complaint_ref, processing_stage | 422 invalid order reference |
| GET | /complaints/{ref}/report.pdf | case report | complaint:read_all | — | PDF file | 404 |
| GET | /complaints-export | export the filtered list | reports:export | list filters, format csv, xlsx, pdf or json | file | 422 unknown format |

Submission is validated in two layers. The Pydantic model `ComplaintIn` enforces types and hard caps (title 200, description 10,000 and supporting information 6,000 characters) and returns them as 422 field errors rather than server errors (`test_title_over_the_hard_cap_is_a_field_error_not_a_crash`, `test_malformed_body_is_a_field_error_not_a_crash`). `validate_submission()` in `services/complaints.py` then applies the business rules: a title of 5 to 180 characters, a description of at least 20 characters and four words and at most 8,000 characters, supported values for channel, customer type, contact method, resolution and tone, the reference formats of the organisation configuration (for example LMR-123456 for orders), and a previous-complaint reference that exists and belongs to the same customer. Attachments are checked by type and content (`security/files.py`) and limited to five files of `MAX_ATTACHMENT_MB` each. Their boundary cases are among the 29 tests in `tests/backend/api/test_boundaries.py`, for example `test_title_length_edges`, `test_description_length_edges` and `test_order_reference_format`.

### 26.4.3 Validation and comparison

The results of the Python Ground-Truth Validation Pipeline and of the Comparison Engine have no endpoints of their own. They are part of the staff view of `GET /complaints/{ref}`, which returns the latest analysis and its validation result together, so that the AI proposal and the rule decision always arrive as one consistent pair. Table 26.7 lists the relevant fields; Chapters 11 and 12 describe how they are computed.

**Table 26.7 — Validation and comparison data in GET /complaints/{ref} (staff view)**

| Field | Content |
|---|---|
| analysis.output | the AI's structured answer (complaint_analysis.v1) |
| analysis.provider, model, prompt_versions, policy_versions, ruleset_hash | what produced the analysis |
| validation.score, decision, overall_status | verification score (0–100), Verified or Manual Review, pass, warn or fail |
| validation.dimension_scores | scores of the twelve validation dimensions |
| validation.checks | all 52 checks: code, name, dimension, severity, status, message, expected, actual, rule_refs, policy_refs |
| validation.comparison | rows (field, ai, python, match, explanation) and agreement |
| validation.python_expected | the rules' own decision |
| validation.validated_decision | the final decision shown to agents |
| validation.review_reasons | why the case needs manual review |
| resolution | AI steps, validated steps and eligibility |

Three further endpoints expose the same logic in other forms. `POST /rules/simulate` runs only the deterministic Python side on any text, without an AI call, and returns the signals, classification, sentiment, entities, facts and full rule decision (Section 26.4.7). `GET /evaluation/runs/{run_id}/results` returns the AI values, the rules' values and the expected labels of every evaluated case side by side (Section 26.4.11). `GET /reports/genai-python-comparison` exports the comparison as a report (Section 26.4.10). Because the comparison is data rather than a separate call, the check wording is normalised when it is served: `api/serializers.py` passes stored check messages, comparison explanations and review reasons through `current_wording()` (`api/wording.py`), so records written before the plain-language update read the same as new ones without the stored text being changed (`tests/backend/unit/test_wording.py`).

### 26.4.4 Escalation, responses and follow-ups

**Table 26.8 — Escalation, response and follow-up endpoints**

| Method | Endpoint | Purpose | Permission | Request | Response | Errors |
|---|---|---|---|---|---|---|
| POST | /complaints/{ref}/escalate | manual escalation | escalation:create | level (not No Escalation), reason (5–1,000) | complaint_ref, escalation_level, status | 404; 422 invalid level |
| POST | /complaints/{ref}/responses/{response_id}/edit | edit a draft as a new version | complaint:respond | body (20–6,000), tone | response_id, status (ready or requires_review), validation | 404; 422 |
| POST | /complaints/{ref}/responses/{response_id}/send | record the response as sent | complaint:respond | — | response_id, status, complaint_status | 404; 422 not validated or approved |
| POST | /complaints/{ref}/follow-ups/{follow_up_id}/complete | complete a follow-up | complaint:update | — | id, status | 404 |

Escalations required by the Rule Matrix are created by the pipeline, not by an API call; the endpoint above adds a manual escalation, which can only raise the level. A response can be sent only when its status is `ready` or `approved`, so no reply that failed its checks reaches a customer without a reviewer's approval. Sending sets the SLA first-response time, moves the complaint to In Progress, or to Awaiting Customer when information is missing, and records the delivery as simulated, because there is no live e-mail or SMS integration. An edited response is checked again for unsupported promises, prohibited statements and unsupported timelines before it can become `ready`. No endpoint acknowledges or closes an escalation; this is Planned (Section 25.4.6).

### 26.4.5 Manual review

**Table 26.9 — Review endpoints**

| Method | Endpoint | Purpose | Permission | Request | Response | Errors |
|---|---|---|---|---|---|---|
| GET | /reviews | review queue | review:read | Table 26.4 | items, total, page, page_size, reason_counts | 422 |
| GET | /reviews/{review_id} | one review | review:read | — | status, reasons, priority, complaint summary, actions | 404 |
| POST | /reviews/{review_id}/claim | claim a review | review:act | — | review (status in_review) | 404; 422 already completed |
| POST | /reviews/{review_id}/actions | reviewer decision | review:act | action, comment (up to 2,000), payload | review, followup | 404; 422 unknown action, comment missing, invalid value, completed |

The action is one of approve, reject, modify, reclassify, reassign, escalate, regenerate or comment. Reject, modify, reclassify and reassign require a comment. The payload carries the action's parameters: changed fields and an optional edited response for modify, a subcategory for reclassify, a department or agent for reassign, a level for escalate and a tone for regenerate. Reclassify and regenerate return a `followup.reprocess` instruction, after which the route queues a new pipeline run with the reviewer's classification or tone. Every action stores before and after snapshots and an audit entry (Section 25.4.6).

### 26.4.6 Knowledge Base

**Table 26.10 — Knowledge Base endpoints**

| Method | Endpoint | Purpose | Permission | Request | Response | Errors |
|---|---|---|---|---|---|---|
| GET | /documents | documents with versions | knowledge:read | — | items (doc_id, title, doc_type, active_version, versions), total | — |
| POST | /documents/preview | parse without saving | knowledge:manage | multipart file | detected metadata and section outline | 422 type, size, empty or corrupt file |
| POST | /documents | upload a version | knowledge:manage | multipart file with doc_id, title, doc_type, version, status, effective_date, expiry_date, owner_department, topics | 201 version | 409 duplicate file or version; 422 |
| GET | /documents/{doc_id} | one document | knowledge:read | — | document and versions | 404 |
| GET | /documents/{doc_id}/versions/{version} | sections, chunks, facts | knowledge:read | — | version with sections, chunks and facts | 404 |
| POST | /documents/{doc_id}/versions/{version}/status | change status | knowledge:manage | status (Active, Previous, Superseded, Draft) | version | 404; 422 |
| GET | /documents/{doc_id}/versions/{version}/download | original file | knowledge:read | — | file | 404 |
| GET | /documents/{doc_id}/impact | revision impact | knowledge:read | — | impacts per version | 404 |
| GET | /knowledge/search | retrieval playground | knowledge:read | q, subcategory, top_k (1–20) | evidence and candidate subcategories | 422 |
| GET | /knowledge/conflicts | precedence-resolved conflicts | knowledge:read | — | items, precedence rules, document-type rank | — |
| GET | /knowledge/stats | counts | knowledge:read | — | documents, versions by status and format, chunks, quarantined chunks, revision | — |

Upload validation checks the file type against the file content, the size limit (`MAX_UPLOAD_MB`, 15), empty files, duplicate files, and the document ID, version, dates and category (Chapter 5). The version response includes `effective_state` (Active, Pending, Expired or the stored status) and `primary_eligible`, the flag that decides whether the version can be used as evidence.

### 26.4.7 Rules and taxonomy

**Table 26.11 — Rule Matrix and taxonomy endpoints**

| Method | Endpoint | Purpose | Permission | Request | Response | Errors |
|---|---|---|---|---|---|---|
| GET | /rules | list rules | rules:read | type, subcategory, q, active | items, total, counts per type, ruleset_hash | — |
| GET | /rules/meta | editor reference data | rules:read | — | actions, prohibited actions, signals, levels, priority matrix, parameters, SLA rules | — |
| GET | /rules/{rule_type}/{rule_id} | one rule | rules:read | — | rule with body, version and readable condition | 404 |
| PUT | /rules/{rule_type}/{rule_id} | create or update | rules:manage | body, is_active | rule (new version) | 422 matrix would be invalid |
| POST | /rules/{rule_type}/{rule_id}/active | enable or disable | rules:manage | active | rule | 404; 422 |
| PUT | /rule-parameters/{key} | change a parameter | rules:manage | value, reason | parameter | 404 |
| POST | /rules/validate | integrity check, or preview of an unsaved edit | rules:read | optional rule_type, rule_id, body, is_active | valid, issues, warnings, counts | — |
| POST | /rules/simulate | deterministic decision for a text | rules:read | title, description, product_text, order_ref, customer_type, requested_resolution, subcategory_override | signals, classification, sentiment, entities, facts, decision, ruleset_hash | 422 |
| GET | /rules/export | Rule Matrix deliverable | rules:read | format csv, xlsx, yaml or pdf | file | 422 |
| POST | /rules/reset-to-baseline | reload the YAML baseline | rules:manage | confirm=true | rules, ruleset_hash, previous_hash, integrity | 422 without confirm |
| GET | /taxonomy | categories, subcategories, departments | rules:read | — | categories with subcategories, departments | — |
| POST | /taxonomy/categories | add a category | taxonomy:manage | code (3–4 capital letters), name, description | 201 | 422 exists |
| POST | /taxonomy/subcategories | add a subcategory with its rules | taxonomy:manage | code (e.g. ABC-DEF), category, name, department, actions, policy_refs, follow-up, keywords | 201 code, rule IDs, warnings | 422 invalid matrix |
| POST | /taxonomy/departments | add a department | taxonomy:manage | code (DEPT-XXX), name, description | 201 | 422 exists |

Every write is validated before it is saved: the service builds a candidate Rule Matrix with the change and runs the integrity validator, and rejects the change with 422 and the list of issues if the candidate is invalid. `POST /rules/validate` with a body runs the same check without writing anything, not even an audit entry (`test_rule_edit_preview_validates_without_saving`). `POST /taxonomy/subcategories` creates the subcategory together with its routing, default resolution and classification rules in one transaction, which is how a new complaint category is added without a code change (`test_new_category_without_code_changes`).

### 26.4.8 AI analysis status, AI runs and prompts

**Table 26.12 — AI status, AI run and prompt endpoints**

| Method | Endpoint | Purpose | Permission | Request | Response | Errors |
|---|---|---|---|---|---|---|
| GET | /ai/status | provider configuration | rules:read | — | configured and resolved provider, active provider, api_key_configured, timeout, max_attempts, embedding provider, fault profiles, notice | — |
| GET | /ai/runs | recent AI attempts | evaluation:read | failed_only, stage, limit | items (stage, attempt, provider, model, prompt, parsed_ok, error, latency), stats (valid, invalid) | 422 |
| GET | /complaints/{ref}/ai-runs | attempts of one case | complaint:read_all | — | items including request metadata and raw response text | 404 |
| GET | /prompts | prompt registry | rules:read | — | items (key, description, versions with templates, schema, params, changelog, sha256) | — |
| POST | /prompts/{key}/versions | new prompt version | prompts:manage | version (x.y.z), system_template (50+), user_template (20+), output_schema, params, changelog, activate | 201 key, version, status, sha256 | 404; 422 duplicate version or missing $complaint or $nonce |
| POST | /prompts/{key}/versions/{version}/activate | activate a version | prompts:manage | — | key, version, status | 404 |

No endpoint calls the AI model synchronously. The analysis itself is started by submission, reprocessing, clarification, reviewer actions, evaluation runs and lab runs, and its result is read through `GET /complaints/{ref}`. `GET /ai/status` never returns the API key; it reports only whether one is configured, and without a key it returns a notice that every complaint is still checked by the rules and sent to manual review (`test_ai_key_never_exposed`, `test_no_api_key_means_no_ai_output_and_manual_review`).

### 26.4.9 Analytics

**Table 26.13 — Dashboard and analytics endpoints**

| Method | Endpoint | Purpose | Permission | Request | Response |
|---|---|---|---|---|---|
| GET | /dashboard | role dashboard | current_user | — | customer: own complaints; agent: my_queue; reviewer, manager, admin: overview, distributions, validation, review queue, plus SLA, departments and alerts for manager and admin |
| GET | /analytics/overview | headline figures and distributions | analytics:read | — | kpis, distributions over 13 dimensions |
| GET | /analytics/distribution/{dimension} | one distribution | analytics:read | category, subcategory, department, priority, urgency, sentiment, channel, status, verification, escalation, customer_type, product or sla | items (422 for an unknown dimension) |
| GET | /analytics/trends | volume over time | analytics:read | days, granularity, dimension | series and keys |
| GET | /analytics/alerts | rising categories, products, departments, escalation spikes | analytics:read | window_days | items |
| GET | /analytics/validation | rule-check statistics | analytics:read | — | decisions, field agreement, review reasons, check outcomes |
| GET | /analytics/sla | SLA states | analytics:read | — | states by priority |
| GET | /analytics/departments | department performance | analytics:read | — | volume, open, escalated, breach rate, average score |
| GET | /analytics/policy-usage | policy citations | analytics:read | — | most-used sections |
| GET | /analytics/resolution-times | time to resolution | analytics:read | — | items |

### 26.4.10 Reports and exports

`GET /reports` lists the ten report keys: complaint-analysis, department-performance, escalations, sla-status, policy-usage, resolution-compliance, genai-python-comparison, manual-reviews, complaint-intelligence and security. `GET /reports/{key}` builds one report, filtered by `date_from`, `date_to`, `department` and `category` (and `run_id` for the comparison report), and renders it as JSON for the on-screen preview or as CSV, Excel or PDF for download. Both require `reports:export`; an unknown key returns 404 and an unknown format 422. Report files, the complaint-list export, the case report PDF and the audit-log export are themselves audited as `report.exported`; the Rule Matrix export (`GET /rules/export`) and the evaluation-run report are not audited. The export writers neutralise spreadsheet formula injection in CSV cells and never write formulas into Excel files (`tests/backend/unit/test_documents_exports.py::test_csv_neutralises_formula_injection`, `test_xlsx_never_contains_formulas`).

### 26.4.11 Evaluation

**Table 26.14 — Evaluation endpoints**

| Method | Endpoint | Purpose | Permission | Request | Response | Errors |
|---|---|---|---|---|---|---|
| GET | /evaluation/datasets | available datasets | evaluation:read | — | items (holdout, dev, dropped files), fault profiles | — |
| POST | /evaluation/runs | start a run | evaluation:run | dataset (default holdout), label, limit (1–5,000), fault_profile | 202 run | 409 run in progress; 422 |
| POST | /evaluation/runs/upload | evaluate an uploaded dataset | evaluation:run | multipart file (JSON, JSONL or CSV), label, fault_profile | 202 run | 422 too large, wrong format, no descriptions |
| GET | /evaluation/runs | latest 50 runs | evaluation:read | — | items | — |
| GET | /evaluation/runs/{run_id} | one run | evaluation:read | — | status, progress, metrics | 404 |
| POST | /evaluation/runs/{run_id}/cancel | stop a run | evaluation:run | — | id, cancelling | 404 |
| GET | /evaluation/runs/{run_id}/results | per-case results | evaluation:read | difficulty, mismatches_only, page, page_size | expected, ai, python, comparison, verification, explanation | 404 |
| GET | /evaluation/runs/{run_id}/report | comparison report | reports:export | format (default pdf) | file | 404 |

The upload route is how an unseen dataset, such as the hidden evaluation pack of the SRS, is processed without code changes: only `title` and `description` are mandatory, unknown columns are ignored and expected labels are used only for scoring (`test_hidden_dataset_upload_with_minimal_columns`).

### 26.4.12 Adversarial Lab

**Table 26.15 — Adversarial Lab endpoints**

| Method | Endpoint | Purpose | Permission | Request | Response |
|---|---|---|---|---|---|
| GET | /lab/scenarios | attack scenarios | lab:use | — | items, fault profiles, security samples |
| POST | /lab/runs | run one scenario or a custom attack | lab:use | scenario_id, or title and description; fault_profile, order_ref, requested_resolution | 202 complaint_ref, scenario_id, fault_profile |
| POST | /lab/runs/all | run all scenarios | lab:use | — | 202 items |
| GET | /lab/runs | recent lab runs with outcome | lab:use | — | items, met, not_met |
| POST | /lab/document-scan | malicious-document test | lab:use | multipart file or sample name | parse and injection-screening result, nothing stored |
| GET | /lab/access-matrix | server-side RBAC matrix | lab:use | — | roles, permissions, matrix |

An unknown fault profile, or a custom attack without a title and description, returns 422. Lab runs are ordinary complaints with source `lab` and a LAB-##### reference, so they pass through exactly the same pipeline as customer complaints (Chapter 34).

### 26.4.13 Audit and system

**Table 26.16 — Audit and system endpoints**

| Method | Endpoint | Purpose | Permission | Request | Response |
|---|---|---|---|---|---|
| GET | /health | liveness and readiness | public | — | status (ok or degraded), version, database, ai_provider, ai_mode |
| GET | /audit | audit log | audit:read or audit:read_complaint | Table 26.4 | items with hash and prev_hash, total, page, page_size, action counts |
| GET | /audit/verify | verify the hash chain | audit:read | — | valid, checked, broken_at_id, message; the check is itself audited |
| GET | /audit/export | export the audit log | audit:read | format and filters | CSV, Excel or PDF (up to 20,000 rows) |
| GET | /complaints/{ref}/audit | audit entries of one case | audit:read, audit:read_complaint or complaint:read_all (not customers) | — | items |
| GET | /system/info | runtime configuration | current_user with settings:manage | — | version, environment, database, AI settings, retrieval, workers, rate limits, upload and duplicate settings |

`GET /health` reports whether the database answers and whether the AI key is configured (`ai_mode` live or not_configured) without exposing any configuration value. `GET /system/info` shows operational settings, such as timeouts, worker counts and limits, but no secret.

## 26.5 Example exchange

A complaint submission shows the conventions together. The request below uses the field names of `ComplaintIn`; the values are fictional.

```http
POST /api/v1/complaints
Cookie: sn_access=…; sn_csrf=…
X-CSRF-Token: …
Content-Type: application/json

{"title": "Parcel late", "description": "My order LMR-123456 was due on 3 June and has not arrived yet.",
 "order_ref": "LMR-123456", "requested_resolution": "explanation", "requested_tone": "professional"}
```

A valid request is stored and queued and answered at once with `202 {"complaint_ref": "CMP-…", "status": "New", "processing_stage": "queued"}`. If the same customer had already submitted the same text within 24 hours, the answer would instead be `409` with the code `duplicate_complaint` and `details.duplicate_of` naming the earlier complaint, which the submission page offers to open. A cookie request without the CSRF header would be rejected with `403 csrf_failed` before the body was read, and a reviewer or manager, whose roles do not hold `complaint:create`, would receive `403 permission_denied` with `details.missing_permissions`.

## 26.6 Limitations

- The rate limiter keeps its counters in the memory of each server process, so limits are per process rather than per deployment.
- There is no endpoint to acknowledge or resolve escalations (Planned), and no DELETE endpoint for any resource; deactivation and status changes are used instead.
- The OpenAPI description at `/api/docs` is served without authentication. It reveals the shape of the API, but every operation it describes still enforces its own permission.
- The permission `analytics:read_own` is granted to agents but not required by any route, and `RetrievalError` is defined but not raised.
- When the frontend is served by the backend, an unknown GET path under `/api/` is answered by the single-page-application fallback with a shorter error body (`code` and `message` only, without `details` and `request_id`).
