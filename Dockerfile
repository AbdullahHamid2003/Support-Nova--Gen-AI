# SupportNova - one image: the React build served by FastAPI (same origin, so the session cookie and CSRF
# protection work without CORS). PostgreSQL runs separately (docker-compose.yml, render.yaml).

# ---- 1. frontend build ----------------------------------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. runtime ----------------------------------------------------------------------------------------
FROM python:3.14-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STORAGE_DIR=/app/storage \
    FORWARDED_ALLOW_IPS=127.0.0.1
WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

# application code and the version-controlled ground truth it reads at runtime
COPY backend/ backend/
COPY config/ config/
COPY rules/ rules/
COPY prompts/ prompts/
COPY schemas/ schemas/
COPY knowledge_base/ knowledge_base/
COPY data/ data/
COPY --from=web /app/frontend/dist frontend/dist

RUN useradd --create-home --uid 10001 supportnova && mkdir -p /app/storage && chown supportnova /app/storage
USER supportnova

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"

# migrations and first-run seeding happen on startup (AUTO_MIGRATE / AUTO_SEED)
# --proxy-headers takes the client address from X-Forwarded-For ONLY when the peer is a trusted proxy
# (FORWARDED_ALLOW_IPS, read by uvicorn; render.yaml sets the platform's private proxy ranges)
CMD ["sh", "-c", "exec python -m uvicorn supportnova.main:app --app-dir backend/src --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
