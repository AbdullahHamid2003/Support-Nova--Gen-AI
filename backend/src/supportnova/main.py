"""FastAPI application factory.

Startup: apply migrations, seed reference data (roles, Rule Matrix, prompts, knowledge base, demo
users), start the background pipeline worker and SLA monitor, recover interrupted complaints and -
on an empty database - import the demo dataset in the background. The built React app is served
from the same origin, so the AI key and all validation stay server-side.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.staticfiles import StaticFiles

from supportnova import __version__
from supportnova.api.errors import install_error_handlers
from supportnova.api.middleware import RateLimitMiddleware, RequestContextMiddleware
from supportnova.api.v1 import auth, complaints, insights, knowledge, quality, reviews, rules, system
from supportnova.core.config import get_settings
from supportnova.core.logging import configure_logging, get_logger
from supportnova.core.paths import FRONTEND_DIST_DIR

log = get_logger(__name__)


def run_migrations() -> None:
    from supportnova.database.migrate import upgrade_to_head
    upgrade_to_head()


def bootstrap() -> dict[str, Any]:
    """Idempotent first-run setup (also used by scripts/seed.py)."""
    from supportnova.database.base import session_scope
    from supportnova.services import seed
    settings = get_settings()
    if settings.auto_migrate:
        run_migrations()
    summary: dict[str, Any] = {}
    if settings.auto_seed:
        with session_scope() as db:
            summary = seed.seed_reference(db)
    return summary


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    from supportnova.database.base import session_scope
    from supportnova.services import seed
    from supportnova.services.worker import worker
    settings = get_settings()
    summary = bootstrap()
    log.info("startup seed summary", extra={"summary": summary})
    worker.start()
    recovered = worker.requeue_stuck()
    if recovered:
        log.info("requeued %s interrupted complaints", recovered)
    if settings.auto_seed and settings.seed_dataset_on_startup:
        with session_scope() as db:
            empty = seed.dataset_loaded(db) == 0
        if empty and seed.datasets.BUILTIN["dev"].exists():
            seed.start_background_import()
    log.info("SupportNova %s ready (AI provider: %s / %s)", __version__, settings.resolved_provider, settings.resolved_model)
    yield
    worker.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    app = FastAPI(title="SupportNova API", version=__version__, lifespan=lifespan,
                  description="GenAI complaint intelligence with an independent Python ground-truth validation pipeline. "
                              "AI proposes. Python validates. Ground truth decides.",
                  docs_url="/api/docs", redoc_url="/api/redoc", openapi_url="/api/openapi.json")
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], allow_headers=["*"],
                       expose_headers=["X-Request-ID", "Content-Disposition"])
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    for module in (system, auth, complaints, reviews, knowledge, rules, insights, quality):
        app.include_router(module.router, prefix=settings.api_prefix)

    @app.get("/api/health", include_in_schema=False)
    def health_alias() -> JSONResponse:
        return JSONResponse({"status": "ok", "version": __version__})

    @app.get(f"{settings.api_prefix}/system/seed-status", tags=["system"])
    def seed_status() -> dict[str, Any]:
        from supportnova.services.seed import progress
        return dict(progress)

    if settings.serve_frontend and (FRONTEND_DIST_DIR / "index.html").exists():
        assets = FRONTEND_DIST_DIR / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> Any:
            if path.startswith("api/"):
                return JSONResponse({"error": {"code": "not_found", "message": "Not found."}}, status_code=404)
            candidate = (FRONTEND_DIST_DIR / path).resolve()
            if path and FRONTEND_DIST_DIR.resolve() in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(FRONTEND_DIST_DIR / "index.html")
    return app


app = create_app()
