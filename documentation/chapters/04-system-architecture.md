# Chapter 4 — System Architecture

SupportNova is a single web application with three tiers. The presentation tier is a React single-page application. The application tier is one FastAPI process, which hosts the REST API, both pipelines and a background worker pool. The data tier is a PostgreSQL 17 database plus a file store. The React build is served by the same FastAPI process, so the browser talks to one origin only. The GenAI provider is the only external service, and the server alone calls it.

Figure 4.1 gives the overview, and Table 4.1 lists the technology stack with the exact versions used. The sections that follow describe the frontend, backend, data, AI, validation and security layers. Chapter 3 describes the workflow that runs across these layers, and Chapter 40 describes how they are deployed.

![Figure 4.1 — High-level system architecture](diagrams/architecture/fig-04-01-high-level-architecture.svg)
*Figure 4.1 — High-level system architecture*

**Table 4.1 — Technology stack and exact versions**

| Layer | Technology | Version (source) |
|---|---|---|
| Frontend language and build | TypeScript, Vite, @vitejs/plugin-react | ~6.0.2, ^8.3.0, ^6.1.1 (`frontend/package.json`) |
| UI library | React, react-dom | ^19.2.8 |
| Styling | Tailwind CSS, @tailwindcss/vite, tailwind-merge, clsx | ^4.3.3, ^4.3.3, ^3.7.0, ^2.1.1 |
| Components | radix-ui primitives, class-variance-authority, lucide-react icons | ^1.6.7, ^0.7.1, ^1.47.0 |
| Routing | react-router | ^7.18.4 |
| Server state | @tanstack/react-query | ^5.103.2 |
| Forms and validation | react-hook-form, @hookform/resolvers, zod | ^7.88.0, ^5.9.1, ^4.6.5 |
| Charts, motion, toasts, dates | recharts, framer-motion, sonner, date-fns | ^3.10.1, ^13.4.2, ^2.0.8, ^4.4.0 |
| Frontend tests and lint | vitest, @testing-library/react, jsdom, eslint | ^5.0.1, ^16.3.3, ^29.1.1, ^10.10.0 |
| Backend language | Python | 3.14 (3.14.7 on the build machine; `requires-python >=3.12`) |
| Web framework and server | FastAPI, Starlette, uvicorn | 0.141.1, 1.7.0, 0.53.0 (`requirements.txt`) |
| Settings and models | pydantic, pydantic-settings | 2.13.5, 2.15.0 |
| Database access | SQLAlchemy, Alembic, psycopg (binary) | 2.0.54, 1.20.0, 3.3.6 |
| Authentication | PyJWT, bcrypt | 2.14.0, 5.0.0 |
| GenAI access | httpx (OpenAI, Gemini REST), anthropic SDK | 0.28.1, 1.8.0 |
| Validation | jsonschema, PyYAML | 4.26.0, 6.0.3 |
| Documents and reports | pymupdf, python-docx, openpyxl, fpdf2 | 1.28.2, 1.2.0, 3.1.5, 2.8.8 |
| Numerics | numpy | 2.5.3 |
| Quality tools | pytest, pytest-cov, ruff, mypy | 9.1.1, 7.1.0, 0.16.8, 2.3.1 (`requirements-dev.txt`) |
| Database server | PostgreSQL | 17 (17.10 embedded dev cluster; `postgres:17-alpine` in docker-compose) |
| Build runtime for the frontend | Node.js | 22 (v22.20.0 on the build machine; `node:22-alpine` in the Dockerfile) |

## 4.1 Frontend Architecture

The frontend lives in `frontend/src` and has 16,867 lines of TypeScript and TSX. It is a Vite-built React 19 application. `npm run build` runs `tsc -b` and then `vite build`, writing the output to `frontend/dist`. FastAPI serves that folder at `/`, with the hashed assets under `/assets`, and falls back to `index.html` for client-side routes. During development, `npm run dev` starts Vite on port 5173 and proxies `/api` to FastAPI on port 8000 (`frontend/vite.config.ts`). Figure 4.2 shows how the pieces fit together.

![Figure 4.2 — Frontend architecture](diagrams/architecture/fig-04-02-frontend-architecture.svg)
*Figure 4.2 — Frontend architecture*

### 4.1.1 Bootstrap, routing and access control

`main.tsx` creates the TanStack Query client and wraps the application in providers:

- The query client keeps data fresh for 20 seconds, does not refetch on window focus, never retries a 4xx error and retries other errors at most twice.
- `AuthProvider` (`lib/auth.tsx`), the tooltip provider and the Sonner toaster wrap the application.

`AuthProvider` loads the session from `GET /api/v1/auth/me`. It exposes `can(permission)` and `hasRole(...)`, and it clears all cached data of the previous user on login and logout.

`App.tsx` defines the routes with `createBrowserRouter` from react-router 7, and every page is code-split with `React.lazy`:

- `RequireAuth` redirects an anonymous visitor to `/login`, keeping the page they asked for.
- `AppShell` (`components/app/layout.tsx`) draws the navigation. It shows only the entries the user's permissions allow, and it carries the theme toggle and the live AI model chip.
- `Guard` checks each page's permission and shows an access-denied state instead of the page.

These checks exist for usability only. The server enforces the same permissions on every API route (Section 4.6).

### 4.1.2 API client, server state and forms

All HTTP traffic passes through `lib/api.ts`. The client never stores a token in JavaScript:

- It sends same-origin requests with the HttpOnly session cookie.
- For every request other than GET, HEAD or OPTIONS, it copies the readable `sn_csrf` cookie into the `X-CSRF-Token` header.
- It turns error bodies into `ApiError` objects with the HTTP status, error code, message, field errors and request ID.
- Its `download()` helper saves report and export files.

The frontend test `src/test/core.test.tsx` checks two of these behaviours: that the CSRF token is sent on unsafe requests and never on GET, and that error payloads are mapped to field errors.

Server state is handled with TanStack Query: 57 `useQuery` and 34 `useMutation` calls in 28 modules. Pages that show running work poll their data. The complaint page polls every 1.5 seconds until the pipeline reaches `completed` or `failed`; evaluation runs, Lab runs and the dataset seed status are polled in the same way.

Forms use react-hook-form with zod schemas, through `@hookform/resolvers`, in nine modules: the login, complaint submission, administration, evaluation, Lab and prompt pages, and the document-upload, rule-simulator and taxonomy components. The server's 422 responses carry field-level errors, and the forms display them against the matching inputs.

### 4.1.3 Components, charts and pages

The component library in `components/ui` follows the shadcn/ui pattern. Thin wrappers around Radix UI primitives (dialog, dropdown menu, popover, select, tabs, tooltip, scroll area, checkbox, switch, progress, separator, label) are styled with Tailwind CSS 4, and their variants are built with class-variance-authority. Charts use Recharts, through the wrappers in `components/app/charts.tsx`. Framer Motion animates the layout, the pipeline tracker and the login and submission pages. The application has a light and a dark theme, which the screenshots `28-dashboard-dark.png` and `29-complaint-detail-dark.png` show. The layout also works at mobile width (`30-mobile-dashboard.png`).

Table 4.2 lists the 18 pages and Table 4.3 the component groups.

**Table 4.2 — Frontend pages (`frontend/src/pages`)**

| Page | Route | Permission | Purpose | Lines |
|---|---|---|---|---|
| Login | `/login` | public | Sign-in, demo accounts while enabled | 146 |
| Dashboard | `/` | signed in | Role-specific dashboard | 344 |
| Complaints | `/complaints` | signed in | Search and filter; customers see their own | 275 |
| SubmitComplaint | `/complaints/new` | `complaint:create` | Complaint form, pre-check, pipeline progress | 381 |
| ComplaintDetail | `/complaints/:ref` | signed in | Case tabs, actions, response | 434 |
| Reviews | `/reviews` | `review:read` | Manual-review queue | 122 |
| ReviewWorkspace | `/reviews/:id` | `review:read` | Reviewer actions on one case | 304 |
| Knowledge | `/knowledge` | `knowledge:read` | Documents, search, conflicts, upload | 882 |
| DocumentDetail | `/knowledge/:docId` | `knowledge:read` | Versions, sections, impact analysis | 1,086 |
| Rules | `/rules` | `rules:read` | Rule Matrix, parameters, simulator, taxonomy | 986 |
| Prompts | `/prompts` | `prompts:manage` | Prompt versions, AI status, AI runs | 758 |
| Analytics | `/analytics` | `analytics:read` | Distributions, trends, SLA, AI vs rules | 1,097 |
| Reports | `/reports` | `reports:export` | Report catalogue, PDF, Excel and CSV export | 436 |
| Evaluation | `/evaluation` | `evaluation:read` | Start runs, upload a hidden dataset | 449 |
| EvaluationRun | `/evaluation/:runId` | `evaluation:read` | Metrics and per-case results of a run | 711 |
| Lab | `/lab` | `lab:use` | Adversarial scenarios, fault profiles | 885 |
| Audit | `/audit` | `audit:read` or `audit:read_complaint` | Audit log and chain verification | 373 |
| Admin | `/admin` | `users:read` | Users, roles, system information | 607 |

**Table 4.3 — Frontend component groups (`frontend/src`)**

| Folder | Main modules | Role | Lines |
|---|---|---|---|
| `components/ui` | `button`, `primitives`, `overlays` | Radix-based design primitives | 451 |
| `components/app` | `layout`, `charts`, `common`, `status` | Shell, charts, shared states and status badges | 777 |
| `components/complaint` | `FinalIntelligence`, `ComparisonPanel`, `PipelineTracker`, `CasePanels`, `ComplaintText` | Complaint page panels; flagged injection spans shown as text, never HTML | 943 |
| `components/rules` | `RuleEditorDialog`, `RuleSimulator`, `TaxonomyManager` | Rule editing, what-if simulation, taxonomy changes | 1,805 |
| `components/knowledge` | `UploadDocumentDialog`, `doc-ui` | Upload with metadata preview, document views | 965 |
| `components/insights` | `access-matrix`, `fault-profiles`, `common` | Lab and analytics helpers | 612 |
| `lib`, `hooks` | `api`, `auth`, `types`, `format`, `reviews`, `time` | API client, session, shared types | 663 |

## 4.2 Backend Architecture

The backend is the Python package `supportnova` in `backend/src`, with 15,744 lines of Python. It is organised in layers. The API layer handles HTTP. The service layer orchestrates the work. The domain packages hold the two pipelines and their building blocks. The shared packages provide configuration, persistence, security and auditing. Figure 4.3 shows the principal dependencies between the packages, which were taken from the actual import statements. Table 4.4 lists each package's responsibility and size.

![Figure 4.3 — Backend packages and their principal dependencies](diagrams/architecture/fig-04-03-backend-packages.svg)
*Figure 4.3 — Backend packages and their principal dependencies*

The import graph confirms the independence of the two pipelines. `python_validation` imports only the two output models, `ComplaintAnalysis` and `CustomerCommunication`, from `genai_pipeline/schemas.py`. It never imports a provider, so it has no way to call a model. Only `services/pipeline.py` calls the GenAI runner, and it does so for the two stages, analysis and communication.

**Table 4.4 — Backend packages, responsibilities and lines of code**

| Package | Responsibility | Lines |
|---|---|---|
| `services` | Pipeline orchestration, worker pool, complaints, reviews, SLA, analytics, evaluation, Lab, seeding, Rule Matrix service, batch runner | 3,415 |
| `api` | FastAPI routers (`api/v1`), dependencies (session, RBAC, CSRF), middleware, error handlers, serializers | 2,355 |
| `database` | SQLAlchemy models (5 modules, 35 tables), engine and sessions, Alembic migrations | 1,789 |
| `rule_engine` | Rule Matrix loader and typed model, condition language, decision engine, integrity checks, dataset reference labeler | 1,426 |
| `genai_pipeline` | Pipeline 1: provider abstraction and adapters, prompt management, context building, schemas, parsing, controlled retries, fault injection | 1,185 |
| `python_validation` | Pipeline 2: Phase A and Phase B checks, Comparison Engine, validated decision, verification score | 1,000 |
| `reporting` | Report builders and CSV, Excel and PDF rendering | 992 |
| `complaint_processing` | Deterministic perception: signals, entities, classification, sentiment, order and eligibility facts | 709 |
| `security` | Password hashing, JWT and CSRF, RBAC, upload validation, sanitisation, injection screening, PII redaction | 669 |
| `knowledge_base` | Knowledge snapshot, BM25 and vector index, embeddings, rule-guided retrieval, conflict detection | 631 |
| `document_processing` | PDF, DOCX, Markdown, TXT and CSV parsers, section-aware chunking, metadata validation, policy facts | 612 |
| `core` | Settings (`core/config.py`), paths, errors, logging, time helpers | 388 |
| `hallucination_checks` | Claim grounding and unsupported-promise detection | 317 |
| `audit` | Append-only, hash-chained audit trail | 137 |
| `main.py`, `__init__.py` | Application factory, lifespan, SPA route; package version | 119 |

### 4.2.1 API layer

`main.py` builds the application in `create_app()` and registers the eight router modules under `/api/v1`. Table 4.5 lists them. They expose 95 routes. In addition there are `GET /api/health`, `GET /api/v1/system/seed-status` and the OpenAPI documentation at `/api/docs`.

Each route declares its permission in one of two ways:

- `require(...)`, where the user must hold every listed permission
- `require_any(...)`, where one of the listed permissions is enough

Both depend on `current_user` (`api/deps.py`), which decodes the session token and enforces CSRF on cookie-authenticated writes.

**Table 4.5 — REST API router modules (`backend/src/supportnova/api/v1`)**

| Module | Routes | Examples | Lines |
|---|---|---|---|
| `auth.py` | 11 | login, logout, me, demo accounts, public config, users, roles, customers | 236 |
| `complaints.py` | 18 | submit, validate, list, detail, pipeline, reprocess, status, assign, escalate, responses, clarify, PDF report, export | 495 |
| `reviews.py` | 4 | queue, detail, claim, actions | 79 |
| `knowledge.py` | 11 | documents, preview, upload, versions, status, download, impact, search, conflicts, stats | 174 |
| `rules.py` | 19 | rules, parameters, validate, simulate, export, taxonomy, prompts, AI status, AI runs, reset to baseline | 431 |
| `insights.py` | 12 | dashboard, analytics (overview, distributions, trends, alerts, validation, SLA, departments, policy usage, resolution times), reports | 103 |
| `quality.py` | 14 | evaluation datasets and runs, hidden-dataset upload, results, reports, Lab scenarios and runs, document scan, access matrix | 170 |
| `system.py` | 6 | health, audit log, audit verification, audit export, complaint audit, system information | 125 |

### 4.2.2 Middleware and error handling

Three middlewares wrap every request. The outermost is described first.

- **`RequestContextMiddleware`** assigns or propagates the `X-Request-ID` header and adds a `Server-Timing` header. It also sets the security headers `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy` and `Permissions-Policy`, and a strict Content-Security-Policy on every path except the API documentation.
- **`CORSMiddleware`** allows only the origins in `CORS_ORIGINS`, with credentials.
- **`RateLimitMiddleware`** keeps an in-memory sliding window per client IP for `/api/` paths. The limit is 240 requests per minute (`RATE_LIMIT_PER_MINUTE`), or 20 per minute for the login endpoint (`LOGIN_RATE_LIMIT_PER_MINUTE`). A request over the limit gets HTTP 429 with `Retry-After`.

The error handlers in `api/errors.py` turn every failure into the same body shape, `{"error": {code, message, details, request_id}}`:

| Failure | Response |
|---|---|
| Invalid request fields | 422, with a field list |
| Integrity violation | 409 |
| Database unavailable | 503 |
| Any other error | 500 |

Stack traces are logged and never returned. Every 403 response is written to the audit log as `access.denied`.

### 4.2.3 Service layer and background processing

The routers are thin: validation and orchestration live in `services/`. The API never runs a pipeline inside the request. `POST /api/v1/complaints` stores the complaint and hands its ID to the `Worker` in `services/worker.py`. The worker uses a `ThreadPoolExecutor` sized by `BACKGROUND_WORKERS` (default 2) and ignores a second submission while the first is still in flight.

The same worker runs an SLA monitor thread. Every `SLA_MONITOR_INTERVAL_SECONDS` (default 60, at least 10), it recomputes the SLA states (On Track, At Risk, Breached, Met). On startup, `requeue_stuck()` resubmits complaints that a previous process left queued or half-processed.

Dataset imports and evaluation runs use `services/batch.py`. It processes customers in parallel (`BATCH_WORKERS`, default 4) and each customer's complaints in date order, so that repeat and duplicate detection sees the same history as live traffic.

No Redis, Celery or other queue is used. `REDIS_URL` is present in the settings, but no code path reads it; a shared queue for several instances is a Future Enhancement.

The application lifespan (`main.py`) performs the startup steps in this order:

1. Apply the Alembic migrations (`AUTO_MIGRATE`).
2. Seed the reference data (`AUTO_SEED`): the roles, the Rule Matrix, the prompts, the Knowledge Base from `knowledge_base/manifest.yaml`, the customers, the order ledger and the demo users.
3. Start the worker and the SLA monitor, and requeue interrupted complaints.
4. When the database holds no dataset complaints and `SEED_DATASET_ON_STARTUP` is true, import the 617-complaint demo dataset in a background thread.

### 4.2.4 Rule Matrix service

The Rule Matrix has two forms that can be exchanged:

- **The YAML baseline** in `rules/` and `config/`, loaded by `rule_engine/loader.py`.
- **The live copy** in the `rules` table, 276 rule rows and 14 configuration rows, managed by `services/rules.py`.

`RuleService.matrix()` caches a typed, immutable `RuleMatrix` and rebuilds it when the `rules_revision` counter in `system_settings` changes. While the counter is 0 the matrix is built from YAML; after the first edit it is built from the database.

Every edit follows the same path. A candidate matrix is built first and passed through `validate_matrix()` (`rule_engine/integrity.py`). Only a valid edit is saved; the rule's version is increased, the revision is bumped and the change is audited. `POST /api/v1/rules/validate` previews an edit without saving it, and `POST /api/v1/rules/reset-to-baseline` restores the YAML baseline.

## 4.3 Data Layer

The data layer uses PostgreSQL 17 through SQLAlchemy 2. The schema consists of 35 tables in five model modules (Table 4.6), created by two Alembic migrations: `0001_initial` and `0002_drop_mock_flags`. Uploaded files are kept in a file store outside the database. Figure 4.4 shows how the process, the database, the file store and the version-controlled repository files relate.

![Figure 4.4 — Data storage architecture](diagrams/architecture/fig-04-04-data-storage-architecture.svg)
*Figure 4.4 — Data storage architecture*

**Table 4.6 — Database tables by model module (`database/models`)**

| Module | Tables | Count |
|---|---|---|
| `identity.py` | roles, departments, categories, subcategories, products, customers, users | 7 |
| `complaints.py` | orders, complaints, complaint_attachments, complaint_history, sla_records | 5 |
| `intelligence.py` | rules, system_settings, prompts, prompt_versions, analyses, ai_runs, policy_references, validation_results, validation_checks | 9 |
| `knowledge.py` | documents, document_versions, document_sections, document_chunks | 4 |
| `workflow.py` | resolutions, customer_responses, escalations, follow_ups, reviews, review_actions, audit_logs, evaluation_cases, evaluation_runs, evaluation_results | 10 |

The schema has these notable features:

- **JSON columns.** Structured content is stored in JSON columns, which become JSONB on PostgreSQL (`database/base.py`). Examples are the AI output, the validated decision, the comparison rows, the rule bodies, the retrieval results and the before and after snapshots of reviews.
- **Embeddings.** Similarity vectors are stored as float32 bytes in `complaints.embedding` and `document_chunks.embedding`. Each chunk vector also records the embedder name (`embedding_model`), so that a change of model triggers re-embedding.
- **Indexes.** The `complaints` table has 17 indexes covering status, priority, department, category, SLA state, verification status and dates. The initial migration adds a trigram GIN index on `lower(title)` for fast complaint search, when the `pg_trgm` extension is available.
- **Audit immutability.** The trigger function `supportnova_audit_immutable` is installed by two triggers on `audit_logs`, `audit_logs_immutable` and `audit_logs_no_truncate`. Together they reject UPDATE, DELETE and TRUNCATE. The test `test_audit_log_is_append_only_in_the_database` checks this against the database.
- **Migrations.** `database/migrate.py` upgrades to the head revision on every start. It stamps the baseline revision first when an older database already has tables but no migration history. Migration `0002_drop_mock_flags` removed the five mock-flag columns (`is_mock`, and `is_mock_analysis` on `complaints`) left over from the removed development mock provider (Chapter 42).
- **Connections.** The engine uses a pool of 10 connections with 20 overflow, pre-ping and 30-minute recycling.

The version-controlled files remain the baseline. They are the Rule Matrix YAML, the prompt templates, the JSON schemas (which are read at runtime), the knowledge-base sources and the complaint dataset. Figure 4.4 shows them seeded into an empty database on the first start.

Uploaded documents and complaint attachments are stored under `storage_dir()`, which is `STORAGE_DIR` or `storage/` in the repository. Documents go to `documents/<DOC_ID>/<version>/<file>` and attachments to `attachments/<complaint ref>/<file>`. Each file's SHA-256 is recorded in the database.

The demo database contains 800 complaints: 617 from the dataset, 160 from evaluation runs, 18 from the Lab and 5 submitted on the web. The NFR 2 targets of the SRS (10,000 complaints, 100 categories and subcategories, 1,000 documents) are supported by the indexed schema, but they have not been load-tested.

## 4.4 AI Layer

The GenAI Complaint Intelligence Pipeline (Pipeline 1) lives in `genai_pipeline/`. Figure 4.5 shows its parts. The pipeline code depends only on the abstract `AIProvider` interface (`providers/base.py`): `generate(AIRequest) -> AIResponse`. An `AIRequest` carries the stage, the system and user prompts, the schema name, the provider-adapted JSON Schema, the temperature, the output-token limit and the timeout; on a retry it also carries the validation feedback.

![Figure 4.5 — GenAI provider layer (Pipeline 1)](diagrams/architecture/fig-04-05-genai-provider-layer.svg)
*Figure 4.5 — GenAI provider layer (Pipeline 1)*

`providers/__init__.py` chooses the adapter from configuration only, using `AI_PROVIDER`, `AI_MODEL` and `AI_API_KEY`. Changing vendor therefore needs no code change. The provider instance is cached until the provider, the model or the presence of a key changes.

`AI_PROVIDER=real` infers the vendor from the key prefix or the model name. Any other value, such as `mock`, is refused when the settings are loaded; the test `test_there_is_no_mock_provider` checks this. Table 4.7 compares the adapters.

**Table 4.7 — GenAI provider adapters**

| Adapter | Default model | Structured output | Evidence | Status |
|---|---|---|---|---|
| `OpenAIProvider` (`http_providers.py`, REST) | `gpt-4.1-mini` | `response_format` JSON Schema with `strict`; `AI_BASE_URL` for OpenAI-compatible gateways | Fake-server unit tests; all recorded runs (780 completed analyses) | Implemented, Tested |
| `AnthropicProvider` (`anthropic_provider.py`, SDK) | `claude-opus-5` | `output_config.format`; SDK retries off; optional refusal fallback | Fake-server unit tests only | Implemented, Tested (offline) |
| `GeminiProvider` (`http_providers.py`, REST) | `gemini-2.5-flash` | `responseMimeType` JSON + `responseJsonSchema`; key in a header, never the URL | Fake-server unit tests only | Implemented, Tested (offline) |
| `UnconfiguredProvider` | (configured vendor) | None; every call fails with `not_configured`, not retried | `test_a_missing_key_fails_honestly_and_is_not_retried` | Implemented, Tested |

The AI layer has five further parts:

- **Prompts.** `prompts.py` loads the versioned templates from `prompts/<key>/<version>.yaml` into the `prompts` and `prompt_versions` tables and fingerprints each one with SHA-256. An administrator can add and activate versions on the **Prompts & AI** page. The active versions are `complaint_analysis` 1.2.0 (temperature 0.1, at most 6,000 output tokens) and `customer_communication` 1.0.0 (temperature 0.3, at most 2,500 tokens).
- **Context.** `context.py` builds the trust-separated context described in Chapter 3. It also wraps each complaint in a fresh random nonce tag.
- **Schemas.** `schemas.py` holds the Pydantic output contracts, from which the committed files in `schemas/ai/` are generated. `provider_schema` removes JSON Schema keywords that a vendor's strict mode rejects, and inlines references for Gemini. `constrain_codes` adds the live catalogue codes as enums on each request, so a category or policy added at runtime is accepted at once.
- **Parsing and retries.** `parsing.py` extracts the JSON and validates it with jsonschema (Draft 2020-12) and then Pydantic. `runner.py` applies the controlled retry policy (Figure 4.5).
- **Fault injection.** `fault_injection.py` holds 13 fault profiles, which deliberately corrupt a real answer to test Pipeline 2. A profile is applied only when it is requested explicitly: in a Lab run, in an evaluation run, or in a reprocess request, and the reprocess API refuses a profile from anyone without the `lab:use` permission. Every use is recorded on the analysis, on the AI run and in the audit log.

The runner's retry policy works as follows:

- There are at most `1 + AI_MAX_RETRIES` attempts, three by default, each with a timeout of `AI_TIMEOUT_SECONDS` (60).
- An invalid answer is retried after a short pause, and the model receives the validation errors.
- Rate-limit and connection errors are retried with an exponential back-off capped at 8 seconds.
- Authentication errors, bad requests, refusals and a missing key end the stage at once.
- When the attempts are exhausted, the stage returns no output. The case goes to manual review with check SCH-001 failed; no output is invented.

In the recorded runs, 31 attempts failed (26 connection errors, 4 timeouts, 1 invalid output), and the retries recovered them. The demo database holds 780 completed analyses, all by OpenAI `gpt-4.1-mini`.

Retrieval belongs to the knowledge layer (`knowledge_base/`). It is deterministic and runs in-process. By default the embedder is a local feature-hashing model with 768 dimensions, so retrieval needs no key and gives identical results on every machine. `EMBEDDING_PROVIDER=openai` or `gemini` switches to vendor embeddings; this option is Implemented but was not used in the recorded runs. `VECTOR_DATABASE_URL` exists as a setting but, like `REDIS_URL`, no code reads it.

## 4.5 Validation Layer

The Python Ground-Truth Validation Pipeline (Pipeline 2) runs in-process in milliseconds and has no network dependency. Figure 4.6 shows its inputs and phases.

![Figure 4.6 — Validation layer (Pipeline 2)](diagrams/architecture/fig-04-06-validation-layer.svg)
*Figure 4.6 — Validation layer (Pipeline 2)*

Pipeline 2 is built from five packages:

- **`complaint_processing/`** derives Python's own view of the complaint: signals, entities, rule-based classification, lexicon sentiment, and the order and eligibility facts from the simulated ledger. All of it is driven by the Rule Matrix configuration (`signals.yaml`, `category_rules.yaml`, `config/products.yaml`).
- **`rule_engine/`** holds the Rule Matrix model and the decision engine.
  - Conditions are written in a safe declarative language (`conditions.py`), with no `eval` and no code in the data. They combine signals, subcategories, text patterns, escalation levels and facts, using the operators `eq`, `gt`, `between` and others. A value may reference a parameter as `$param:key`.
  - The logic has three values. When a required fact is unknown, a condition evaluates to "unknown", and the engine answers "requires verification" instead of guessing.
  - `DecisionEngine` (`decision.py`) selects the resolution rule by precedence and applies the routing, conditional routing, urgency floors, priority matrix, escalation rules, eligibility, follow-up, missing-information and SLA rules. Each result carries the IDs of the rules that produced it, which forms the decision trace.
- **`hallucination_checks/`** tests whether the model's claims and extracted details can be traced to the complaint, the approved policies or the rules (`grounding.py`). It also detects unsupported refund, compensation, timeline and exception promises against the Python decision (`promises.py`).
- **`python_validation/engine.py`** runs the checks:
  - Phase A: 44 checks on the analysis
  - the Comparison Engine (`build_comparison`, 18 fields)
  - the validated decision (`build_validated_decision`)
  - Phase B: 8 checks on the customer response
  - `finalize()`, which computes the verification score and the decision
- **`rules/validation_policy.yaml`** sets the check catalogue, the dimensions, the severity weights and the Verified threshold of 80. These are configuration, not code.

The Comparison Engine therefore lives inside `python_validation/`, not in a separate `comparison_engine/` package.

**Table 4.8 — Validation checks by dimension (`rules/validation_policy.yaml`)**

| Dimension | Checks | Codes |
|---|---|---|
| schema | 6 | SCH-001 to SCH-006 |
| classification | 5 | CLS-001 to CLS-005 |
| routing | 2 | RTE-001, RTE-002 |
| priority | 4 | PRI-001 to PRI-004 |
| policy | 6 | POL-001 to POL-006 |
| resolution | 4 | RES-001 to RES-004 |
| eligibility | 3 | ELG-001 to ELG-003 |
| escalation | 4 | ESC-001 to ESC-004 |
| follow_up | 4 | FUP-001, FUP-002, MIS-001, MIS-002 |
| communication | 7 | RSP-001 to RSP-007 |
| grounding | 4 | HAL-001 to HAL-004 |
| security | 3 | SEC-001 to SEC-003 |

The catalogue sets a default severity for each check. The engine raises the severity in high-risk contexts; for example, a missing safety or security action makes RES-001 critical. This is why, in the example of Chapter 3, RES-001 appears as critical although its catalogue default is major.

## 4.6 Security Layer

Security is enforced on the server and in layers. Figure 4.7 shows the path of a request through the edge, identity and access controls. Figure 4.8 shows how complaint text and uploaded documents are treated as untrusted data. Table 4.9 lists each control with its evidence.

![Figure 4.7 — Security architecture: request path](diagrams/security/fig-04-07-security-request-path.svg)
*Figure 4.7 — Security architecture: request path*

The request path uses these controls:

- **Session.** A successful login issues an HS256 JWT signed with `SECRET_KEY`. The token expires after `ACCESS_TOKEN_MINUTES` (480) and carries the subject, role, issuer, issued-at time and a unique ID. It is stored in the HttpOnly, SameSite=Lax cookie `sn_access`; with `COOKIE_SECURE=true` the cookie is also marked Secure.
- **CSRF.** A second, readable cookie `sn_csrf` implements double-submit CSRF protection. Every unsafe request made with the cookie must echo that value in `X-CSRF-Token`, and the two are compared in constant time. API clients may send `Authorization: Bearer` instead; this is not ambient, so it needs no CSRF token.
- **Passwords and lockout.** Passwords are hashed with bcrypt at cost 12. After five failed logins, an account is locked for five minutes.
- **Access control.** RBAC is checked on every route with the 27 permissions of the five roles. Customers additionally see only their own complaints.
- **Client IP.** The client address used for rate limiting and auditing is the socket peer. `X-Forwarded-For` is honoured only through uvicorn's `--proxy-headers` for the proxies listed in `FORWARDED_ALLOW_IPS`, so a spoofed header cannot bypass the login limit.

![Figure 4.8 — Security architecture: untrusted content](diagrams/security/fig-04-08-security-untrusted-content.svg)
*Figure 4.8 — Security architecture: untrusted content*

Complaint text and documents are treated as data, never as instructions:

- **Normalisation** removes the characters and markup that are used to hide text from people.
- **The injection screen** marks suspicious spans. A marked span is shown to the model as inert quoted customer text and forces review trigger REV-010.
- **PII redaction** replaces card numbers (Luhn-checked), CVV codes, passwords, one-time codes, email addresses and phone numbers before any text leaves the server for a GenAI provider or is written to the AI-run log.
- **The nonce tag** prevents customer text from closing the complaint element of the prompt.
- **After generation**, SEC-001 checks that the AI did not follow the embedded instructions. SEC-002 and RSP-006 keep sensitive data and prohibited statements out of the response.
- **Uploaded documents** go through file validation, and chunks that carry instructions are quarantined.

The GenAI key is used only by the server. It is read from `.env.secrets`, which is git-ignored and overrides `.env`, and it is never logged or sent to the browser. The test `test_ai_key_never_exposed` checks that `/config/public`, `/ai/status` and `/system/info` never contain it.

The audit trail (`audit/service.py`) seals each entry at commit time. Each entry holds the SHA-256 of the previous entry's hash plus its own canonical record, and the sealing runs under a process lock and a PostgreSQL advisory lock. `GET /api/v1/audit/verify` recomputes the chain, so any edited or deleted row breaks it.

**Table 4.9 — Security controls and evidence**

| Control | Mechanism | Evidence | Status |
|---|---|---|---|
| Authentication | bcrypt passwords, HS256 JWT in HttpOnly cookie | `test_password_hashing_and_tokens` | Tested |
| CSRF protection | Double-submit cookie and `X-CSRF-Token` header | `test_cookie_session_requires_csrf_header` | Tested |
| Account lockout | 5 failures lock the account for 5 minutes | `test_account_lockout_after_failed_logins` | Tested |
| RBAC | `require` / `require_any` on every route | `test_role_permission_matrix_enforced_server_side`, `test_customer_sees_only_own_complaints` | Tested |
| Rate limiting | Per-IP sliding window, stricter for login | `test_spoofed_forwarded_for_does_not_bypass_login_rate_limit` | Tested |
| Security headers | CSP, nosniff, frame denial, referrer and permissions policy | `test_security_headers` | Tested |
| Upload validation | Magic bytes, size, executables, macros, zip bombs | `test_executable_upload_rejected`, `test_upload_validation_rejects_executables_and_mismatches` | Tested |
| Prompt-injection screening | Pattern families, base64, fake policy IDs, nonce tag | `test_injection_attacks_detected`, `test_prompt_injection_is_blocked` | Tested |
| PII redaction | Cards, CVV, passwords, codes, emails, phones | `test_pii_redaction` | Tested |
| Malicious documents | Chunk quarantine | `test_malicious_document_upload_is_quarantined` | Tested |
| Secret handling | Key only in `.env.secrets`, server-side | `test_ai_key_never_exposed`, `test_secrets_file_overrides_the_settings_file` | Tested |
| Audit integrity | Hash chain, append-only trigger, audited 403s | `test_audit_log_is_append_only_in_the_database`, `test_denied_access_is_audited` | Tested |
| Transport security | TLS terminated by the hosting platform, Secure cookie flag | `render.yaml` sets `COOKIE_SECURE=true`; not deployed | Planned |

Three limitations follow from this design:

- The application does not send an HSTS header, and it relies on the hosting platform for TLS.
- The rate-limit counters are kept in memory for each process, so they are not shared between several instances.
- Both points matter only for the planned hosted deployment described in Chapter 40.
