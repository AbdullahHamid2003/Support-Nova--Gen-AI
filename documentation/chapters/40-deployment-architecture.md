# Chapter 40 — Deployment Architecture

SupportNova is deployed as one application process and one PostgreSQL database. The process serves the REST API, runs both pipelines and the background worker, and also serves the built React frontend. The repository describes three ways to run this pair: a local deployment on Windows, a container image with Docker Compose, and a Render blueprint. They have been exercised to different degrees, so this chapter labels each one with its real status (Table 40.1). Chapter 41 gives the step-by-step installation commands for the local deployment.

**Table 40.1 — Deployment options and their status**

| Option | Defined in | Database | Status | Evidence |
|---|---|---|---|---|
| Local deployment (Windows) | `README.md` section 1, `scripts/devdb.py` | Embedded PostgreSQL 17.10 on `127.0.0.1:5433` | Tested (actual) | Demo dataset processed with the real model (780 analyses); 31 screenshots captured from the running app with no console errors; 206 backend tests passed |
| Container image | `Dockerfile` | External | Implemented, not tested | Docker was not available on the build machine; the image has never been built |
| Docker Compose stack | `docker-compose.yml` | `postgres:17-alpine` container | Implemented, not tested | Never started, for the same reason |
| Render blueprint | `render.yaml` | Render managed PostgreSQL | Implemented, not deployed | No Render service has been created |
| Public application URL | — | — | Planned | No public deployment exists; the SRS deliverable "Public application URL" is open |

## 40.1 Deployment topology

Figure 40.1 shows the three options side by side. They share one topology:

- **One origin.** A single uvicorn process runs the FastAPI application, `supportnova.main:app`. Because `SERVE_FRONTEND` is true and `frontend/dist/index.html` exists, the same process serves the React build at `/` and its assets at `/assets`. Unknown client routes fall back to `index.html`, and unknown `/api/` paths return a JSON 404. The browser therefore talks to one origin. The HttpOnly session cookie and the double-submit CSRF token work without cross-origin requests, and the GenAI key never has to leave the server.
- **One relational database.** PostgreSQL holds all 35 tables. The application creates and upgrades the schema itself at startup.
- **One file store.** Uploaded documents and attachments are kept under `STORAGE_DIR` (default `storage/` in the repository, `/app/storage` in the image).
- **One external service.** The GenAI provider is called over HTTPS by the server only. In the recorded runs this was the OpenAI API with `gpt-4.1-mini`.

![Figure 40.1 — Deployment architecture: local deployment, container stack and Render blueprint](diagrams/architecture/fig-40-01-deployment-architecture.svg)
*Figure 40.1 — Deployment architecture: local deployment, container stack and Render blueprint*

## 40.2 Local deployment (tested)

The only deployment that has actually run is local, on the Windows 10 build machine. It used Python 3.14.7, Node.js 22.20.0 and the embedded PostgreSQL 17.10 cluster from `scripts/devdb.py`:

- **The application.** It is started with `backend\.venv\Scripts\python -m uvicorn supportnova.main:app --app-dir backend/src --host 127.0.0.1 --port 8000` and serves both the API and the built frontend at `http://127.0.0.1:8000`.
- **The database.** It is a private PostgreSQL 17 cluster in user space. The binaries come from the npm package `@embedded-postgres/windows-x64` 17.10.0-beta.17 and are installed under `tools/devdb`. The cluster lives in `tools/devdb/pgdata` and listens only on `127.0.0.1:5433`, and no system service is installed. It holds two databases: `supportnova` for the application and `supportnova_test` for the test suite.
- **Configuration.** Settings are read from `.env`, and secrets from `.env.secrets` in the repository root (Section 40.6).
- **Evidence.** This deployment processed the 617-complaint demo dataset, 154 holdout evaluation cases and 18 Lab scenarios with the real model. The screenshots in `screenshots/` were captured from it.

The embedded cluster is a development tool. Its password (`DEVDB_PASSWORD`, default `postgres`) is a development credential, and `scripts/devdb.py` itself states that deployments use a managed PostgreSQL instead.

## 40.3 Container image (Dockerfile)

The `Dockerfile` builds one image in two stages:

1. **Frontend build stage** (`node:22-alpine`). It copies `package.json` and `package-lock.json`, runs `npm ci --no-audit --no-fund`, copies the frontend sources and runs `npm run build`.
2. **Runtime stage** (`python:3.14-slim`). It sets:
   - `PYTHONDONTWRITEBYTECODE`, `PYTHONUNBUFFERED` and the pip options
   - `STORAGE_DIR=/app/storage`
   - `FORWARDED_ALLOW_IPS=127.0.0.1`

   It installs only the runtime pins from `requirements.txt`, without the development tools. It then copies `backend/` and the version-controlled ground truth the application reads at runtime (`config/`, `rules/`, `prompts/`, `schemas/`, `knowledge_base/`, `data/`), plus `frontend/dist` from stage 1.

The runtime stage also hardens and prepares the container:

- **User.** It creates the unprivileged user `supportnova` (UID 10001) and runs as that user. Only `/app/storage` is writable.
- **Port and health.** It exposes port 8000. A `HEALTHCHECK` calls `/api/health` every 30 seconds, with a 5-second timeout, a 60-second start period and three retries.
- **Command.** `sh -c "exec python -m uvicorn supportnova.main:app --app-dir backend/src --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"`. `--proxy-headers` makes uvicorn take the client address from `X-Forwarded-For` only when the direct peer is listed in `FORWARDED_ALLOW_IPS`.
- **Build context.** `.dockerignore` keeps these out of the image: `.git`, every `.env` file except `.env.example`, virtual environments, `node_modules`, `frontend/dist` (it is rebuilt in stage 1), `tools/devdb`, `storage`, `reports`, `screenshots`, `docs` and `tests`. No secret or local database can therefore enter the image.

Status: Implemented, not tested. Docker was not available on the build machine, so the image has never been built. For example, it has not been checked that every pinned wheel installs on `python:3.14-slim`.

## 40.4 Docker Compose stack

`docker-compose.yml` describes a two-container local stack, started with `docker compose up --build`:

- **`db`** runs `postgres:17-alpine`, with the user and database `supportnova` and the password `${POSTGRES_PASSWORD:-supportnova-local-only}`. It keeps its data in the named volume `pgdata`, and a `pg_isready` health check runs every 5 seconds, with up to 20 retries.
- **`app`** is built from the `Dockerfile`. It starts only after `db` is healthy and publishes port `8000:8000`. Uploads are kept in the named volume `storage`. Its environment is:
  - `DATABASE_URL`, pointing at `db:5432`
  - `APP_ENV` (default `development`), `SECRET_KEY` (default empty) and `COOKIE_SECURE` (default `false`)
  - `CORS_ORIGINS=http://localhost:8000`
  - `AI_PROVIDER` (default `openai`), `AI_API_KEY` and `AI_MODEL`
  - `SEED_DEMO_USERS` (default `true`) and `DEMO_PASSWORD`

The variables are taken from the shell, or from a `.env` file next to the compose file, which is never committed. With the defaults, the stack runs in development mode: an empty `SECRET_KEY` falls back to the development key, and the session cookie is not marked Secure. That is suitable only for a local demonstration.

Status: Implemented, not tested, for the same reason as the image.

## 40.5 Render blueprint

`render.yaml` is a Render blueprint for a hosted demonstration. It declares two resources:

- **A managed PostgreSQL database**, `supportnova-db` (database and user `supportnova`, free plan).
- **A Docker web service**, `supportnova`, built from the `Dockerfile` (free plan). Render checks its health at `/api/health`. The service receives the following environment:

| Variable | Value in `render.yaml` | Effect |
|---|---|---|
| `DATABASE_URL` | the database's connection string | the application rewrites `postgres://` to the psycopg driver URL |
| `APP_ENV` | `production` | turns on the production guard |
| `SECRET_KEY` | `generateValue: true` | generated by Render |
| `COOKIE_SECURE` | `"true"` | the session cookie is sent only over HTTPS |
| `AI_PROVIDER` | `openai` | vendor selection |
| `AI_API_KEY` | `sync: false` | entered by hand in the Render dashboard |
| `SEED_DEMO_USERS` | `"true"` | commented "public demo only" |
| `DEMO_PASSWORD` | `sync: false` | entered in the dashboard |
| `FORWARDED_ALLOW_IPS` | `10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` | Render's private proxy ranges |
| `BACKGROUND_WORKERS` | `"2"` | worker pool size |

Status: Implemented, not deployed. No Render service has been created, and the public application URL required by the SRS is Planned.

Reading the blueprint against the code shows three points that must be settled before a real deployment:

- **No persistent disk.** The blueprint declares no disk for `/app/storage`. Uploaded documents and attachments would therefore not survive a redeploy, although their database rows would. The chunks that retrieval uses would stay available, but downloading the original file would fail.
- **Paid first start.** `SEED_DATASET_ON_STARTUP` is not set, so it keeps its default `true`. With a key present, the first start would process the 617-complaint demo dataset with the real model, which took about 58 minutes and cost roughly US$4-5 locally (Chapter 41).
- **No HSTS header.** TLS would be terminated by the platform, and the application itself does not send an HSTS header.

## 40.6 Environment variables and the .env / .env.secrets split

All settings are defined in `backend/src/supportnova/core/config.py` (a pydantic-settings `Settings` class) and documented in `.env.example`, with comments. Every setting has a working development default, so the application also starts with no `.env` at all. The settings are resolved in this order:

1. Process environment variables. Docker Compose and Render set these, and they take precedence over both files.
2. `.env.secrets`, which is read after `.env` and overrides it (tested by `test_secrets_file_overrides_the_settings_file`).
3. `.env`, which holds the ordinary settings.
4. The built-in defaults.

The test suite sets `SUPPORTNOVA_ENV_FILE` to a path that does not exist, so it never reads a developer's key. Both files are git-ignored (`.env` and `.env.*`, except `.env.example`), and both are excluded from the Docker build context.

**Table 40.2 — Configuration groups (`.env.example`)**

| Group | Settings | Where they belong |
|---|---|---|
| Application | `APP_ENV`, `SECRET_KEY`, `ACCESS_TOKEN_MINUTES`, `COOKIE_SECURE`, `CORS_ORIGINS`, `SERVE_FRONTEND` | `.env`; `SECRET_KEY` in `.env.secrets` |
| Database | `DATABASE_URL`, `DB_ECHO` | `.env` (credentials may go to `.env.secrets`) |
| GenAI (Pipeline 1) | `AI_PROVIDER`, `AI_MODEL`, `AI_BASE_URL`, `AI_TIMEOUT_SECONDS`, `AI_MAX_RETRIES`, `AI_TEMPERATURE`, `AI_MAX_OUTPUT_TOKENS`, `AI_EFFORT`, `AI_REFUSAL_FALLBACK` | `.env` |
| GenAI secret | `AI_API_KEY` | `.env.secrets` only |
| Retrieval | `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_API_KEY`, `VECTOR_DATABASE_URL`, `RETRIEVAL_TOP_K` | `.env`; `EMBEDDING_API_KEY` in `.env.secrets` |
| Background work | `REDIS_URL`, `BACKGROUND_WORKERS`, `BATCH_WORKERS`, `SLA_MONITOR_INTERVAL_SECONDS` | `.env` |
| Limits | `RATE_LIMIT_PER_MINUTE`, `LOGIN_RATE_LIMIT_PER_MINUTE`, `MAX_UPLOAD_MB`, `MAX_ATTACHMENT_MB` | `.env` |
| Complaint processing | `DUPLICATE_WINDOW_HOURS`, `REJECT_EXACT_DUPLICATES`, `NEAR_DUPLICATE_THRESHOLD`, `REPEAT_SIMILARITY_THRESHOLD` | `.env` |
| First-run setup | `AUTO_MIGRATE`, `AUTO_SEED`, `SEED_DATASET_ON_STARTUP`, `SEED_DEMO_USERS`, `SEED_SIMULATE_LIFECYCLE`, `DEMO_PASSWORD` | `.env`; `DEMO_PASSWORD` in `.env.secrets` |

Two settings in the table have no effect today. `REDIS_URL` and `VECTOR_DATABASE_URL` are accepted, but no code path reads them: the in-process worker pool and the in-process retrieval index are always used.

## 40.7 AI provider configuration

The GenAI provider is selected by configuration only (Chapter 4, Section 4.4):

- **`AI_PROVIDER`** accepts `openai` (the default), `anthropic`, `gemini` or `real`. With `real`, the vendor is inferred from the key prefix or the model name. Any other value stops the application at startup.
- **`AI_MODEL`**, when empty, selects the provider's default: `gpt-4.1-mini` for OpenAI, `claude-opus-5` for Anthropic and `gemini-2.5-flash` for Gemini. All recorded runs used OpenAI `gpt-4.1-mini`. The Anthropic and Gemini adapters have been tested only against fake vendor servers.
- **`AI_BASE_URL`** optionally routes OpenAI-format requests through a compatible gateway.
- **Call limits.** `AI_TIMEOUT_SECONDS` (60) and `AI_MAX_RETRIES` (2) bound every call. The prompt versions supply their own temperature and output limit; `AI_TEMPERATURE` and `AI_MAX_OUTPUT_TOKENS` apply only when a prompt does not.
- **Anthropic-only settings.** `AI_EFFORT` and `AI_REFUSAL_FALLBACK` apply to the Anthropic adapter only.

Staff can see whether the AI is configured. The header chip shows the live model name, and the **Administration → System** page reads `GET /api/v1/system/info`. That endpoint reports the provider, the model, whether a key is configured, the timeout and the retry limit, but never the key itself.

Without a key, the GenAI step reports `not_configured`. No AI output is produced, every complaint goes to manual review, and the Python Rule Matrix decision is still enforced (Chapter 42).

## 40.8 Secrets handling

Three values are secrets: the GenAI key (`AI_API_KEY`), the session signing key (`SECRET_KEY`) and, for a public demo, `DEMO_PASSWORD`. The embedding key and the database credentials are treated the same way when they are used. They are handled as follows:

- **Location.** Locally the secrets live only in `.env.secrets` on the server machine. In the planned hosted form they would be environment variables: in Render, `SECRET_KEY` is generated and the other two are entered in the dashboard (`sync: false`). The repository contains no secret. `.env.example` keeps `AI_API_KEY` and `SECRET_KEY` empty, and `.gitignore` and `.dockerignore` exclude every other `.env` file.
- **Typing.** In code, the secrets are `SecretStr` values, so they are not printed by accident. The AI key is sent only in the vendor's request header. For Gemini this is `x-goog-api-key`, so the key never appears in a URL.
- **Browser.** The key is never returned to the browser. `test_ai_key_never_exposed` checks `/config/public`, `/ai/status` and `/system/info` for it.
- **Logs.** Prompt previews written to `ai_runs` are PII-redacted, and the key is not part of any logged request.
- **Demo password.** It is published on the login page only while `SEED_DEMO_USERS` is on (`GET /api/v1/auth/demo-accounts`, tested by `test_demo_accounts_are_public_only_while_enabled`). It must be switched off for any deployment that holds real data.

## 40.9 HTTPS, cookies and CORS

The application speaks HTTP and relies on the hosting layer for TLS. Its cookie and cross-origin settings are:

- **Session cookie.** It is set as `HttpOnly`, `SameSite=Lax` and `path=/`, and as `Secure` when `COOKIE_SECURE=true`. The local deployment runs on plain `http://127.0.0.1:8000` with `COOKIE_SECURE=false`. `render.yaml` sets it to `true`, because Render would terminate HTTPS in front of the container. Behind any other HTTPS proxy, the operator must set it to `true`.
- **CORS.** CORS is needed only when the browser loads the frontend from a different origin. In every documented deployment the frontend is served by FastAPI itself, so requests are same-origin. The default `CORS_ORIGINS` (`http://localhost:5173`, `http://127.0.0.1:5173`) covers the Vite development server. That server proxies `/api` to port 8000, so even it makes same-origin calls. The compose file sets `CORS_ORIGINS=http://localhost:8000`.
- **Client addresses.** Behind a proxy, the client address used for rate limiting and auditing comes from `X-Forwarded-For` only through uvicorn `--proxy-headers`, and only for the proxies listed in `FORWARDED_ALLOW_IPS`.

## 40.10 Production configuration

`APP_ENV=production` turns on a guard in `Settings._production_guard`. The application refuses to start if `SECRET_KEY` is the development placeholder or is shorter than 32 characters. The error message tells the operator how to generate a key: `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Table 40.3 lists what a production deployment has to set. The values come from the code and the comments in `.env.example` and `render.yaml`; none of them has been exercised in a real production environment.

**Table 40.3 — Production configuration checklist**

| Setting | Production value | Reason |
|---|---|---|
| `APP_ENV` | `production` | Enables the `SECRET_KEY` guard |
| `SECRET_KEY` | Random, 32 or more characters | Signs session tokens; the development key is refused |
| `COOKIE_SECURE` | `true` | Session cookie only over HTTPS |
| `AI_API_KEY` | Vendor key, as a platform secret | Without it, the GenAI step reports `not_configured` |
| `SEED_DEMO_USERS` | `false` for real data | Removes the public demo sign-ins |
| `SEED_SIMULATE_LIFECYCLE` | `false` for real data | No labelled "simulated history" for old demo complaints |
| `SEED_DATASET_ON_STARTUP` | `false` unless a demo is intended | Avoids about 1,230 paid model calls on the first start |
| `FORWARDED_ALLOW_IPS` | The platform's proxy ranges | Correct client IPs for rate limiting and auditing |
| `STORAGE_DIR` | A persistent volume | Keeps uploaded documents and attachments |
| `DATABASE_URL` | Managed PostgreSQL 17 | `postgres://` URLs are normalised automatically |

## 40.11 Startup, health and operation

Every deployment form starts in the same way. The FastAPI lifespan:

1. applies the migrations (`AUTO_MIGRATE`)
2. seeds the roles, the Rule Matrix, the prompts, the Knowledge Base, the customers, the order ledger and the demo users (`AUTO_SEED`)
3. starts the worker pool and the SLA monitor, and requeues interrupted complaints
4. imports the demo dataset, when the database holds no dataset complaints and `SEED_DATASET_ON_STARTUP` is true

`GET /api/health` returns `{"status": "ok", "version": ...}` and is used by the Docker `HEALTHCHECK` and by the Render health check. `GET /api/v1/system/seed-status` reports the progress of the dataset import.

The current design assumes one application instance:

- The rate limiter keeps its counters in memory for each process.
- Background work runs in the process's own thread pool.
- The Rule Matrix and the knowledge snapshot are cached in memory. Their revision counters are stored in the database, so several instances would still see edits. The rate limiter and the worker queue, however, would not be shared, and a shared queue is a Future Enhancement.

The availability target of the SRS (NFR 5, 99% uptime during evaluation) cannot be demonstrated without a hosted deployment. Its status is Planned, together with the public URL.
