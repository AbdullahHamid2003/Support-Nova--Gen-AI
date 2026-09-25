"""HTTP middleware: request IDs, security headers, in-memory rate limiting, response timing."""

from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict, deque

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from supportnova.api.deps import client_ip
from supportnova.core.config import get_settings
from supportnova.core.logging import request_id_var

CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
       "font-src 'self' data: https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
       "base-uri 'self'; form-action 'self'; object-src 'none'")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        rid = request.headers.get("x-request-id") or secrets.token_hex(8)
        token = request_id_var.set(rid[:64])
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        response.headers["X-Request-ID"] = rid[:64]
        response.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - started) * 1000:.1f}"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not request.url.path.startswith(("/api/docs", "/api/redoc", "/api/openapi")):
            response.headers.setdefault("Content-Security-Policy", CSP)
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limiter per client IP (stricter for the login endpoint)."""

    def __init__(self, app: object) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()
        if not request.url.path.startswith("/api/") or request.method == "OPTIONS":
            return await call_next(request)
        ip = client_ip(request)  # never the raw X-Forwarded-For header (client-controlled)
        login = request.url.path.endswith("/auth/login")
        limit = settings.login_rate_limit_per_minute if login else settings.rate_limit_per_minute
        key = f"{ip}:{'login' if login else 'api'}"
        now = time.monotonic()
        with self._lock:
            window = self._hits[key]
            while window and now - window[0] > 60:
                window.popleft()
            if len(window) >= limit:
                return JSONResponse(status_code=429, content={"error": {"code": "rate_limited",
                                                                        "message": "Too many requests - please slow down.",
                                                                        "details": None, "request_id": request_id_var.get()}},
                                    headers={"Retry-After": "30"})
            window.append(now)
        return await call_next(request)
