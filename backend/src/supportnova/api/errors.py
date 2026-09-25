"""Consistent error responses. Internal details and stack traces are logged, never returned."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from supportnova.core.errors import AppError
from supportnova.core.logging import get_logger, request_id_var

log = get_logger(__name__)


def _body(code: str, message: str, details: object = None) -> dict[str, object]:
    return {"error": {"code": code, "message": message, "details": details, "request_id": request_id_var.get()}}


def _audit_denied(request: Request, message: str) -> None:
    """Unauthorised-access attempts are security events: record them in the immutable audit log."""
    from supportnova.api.deps import client_ip
    from supportnova.audit import service as audit
    from supportnova.database.base import session_scope
    try:
        with session_scope() as db:
            audit.record(db, action="access.denied", entity_type="endpoint",
                         entity_id=f"{request.method} {request.url.path}"[:64], actor=getattr(request.state, "user", None),
                         summary=message, ip_address=client_ip(request))
    except Exception:  # never let auditing failure mask the 403
        log.exception("could not audit denied access")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.status_code >= 500:
            log.warning("application error: %s", exc.message)
        if exc.status_code == 403:
            await run_in_threadpool(_audit_denied, request, exc.message)
        return JSONResponse(status_code=exc.status_code, content=_body(exc.code, exc.message, exc.details))

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [{"field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content=_body("validation_error", "Some fields are invalid.", details))

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed", 401: "authentication_required", 403: "permission_denied"}.get(exc.status_code, "http_error")
        return JSONResponse(status_code=exc.status_code, content=_body(code, str(exc.detail)))

    @app.exception_handler(IntegrityError)
    async def integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
        log.warning("integrity error: %s", str(exc.orig)[:300])
        return JSONResponse(status_code=409, content=_body("conflict", "The change conflicts with existing data."))

    @app.exception_handler(OperationalError)
    async def db_unavailable(_request: Request, exc: OperationalError) -> JSONResponse:
        log.error("database unavailable: %s", str(exc.orig)[:300])
        return JSONResponse(status_code=503, content=_body("database_unavailable", "The database is temporarily unavailable."))

    @app.exception_handler(SQLAlchemyError)
    async def db_error(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
        log.error("database error", exc_info=exc)
        return JSONResponse(status_code=500, content=_body("database_error", "A database error occurred."))

    @app.exception_handler(Exception)
    async def unexpected(_request: Request, exc: Exception) -> JSONResponse:
        log.error("unhandled error", exc_info=exc)
        return JSONResponse(status_code=500, content=_body("internal_error", "An unexpected error occurred. Please try again."))
