"""Application error hierarchy with stable machine-readable codes.

All API errors are rendered as ``{"error": {"code", "message", "details", "request_id"}}``.
Stack traces are logged server-side only and never returned to clients.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, details: Any = None, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details
        if code:
            self.code = code


class ValidationFailed(AppError):
    status_code = 422
    code = "validation_error"


class AuthenticationFailed(AppError):
    status_code = 401
    code = "authentication_required"


class PermissionDenied(AppError):
    status_code = 403
    code = "permission_denied"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class DocumentProcessingError(AppError):
    status_code = 422
    code = "document_processing_error"


class RetrievalError(AppError):
    status_code = 503
    code = "retrieval_error"


class AIProviderError(AppError):
    """Raised by GenAI providers. ``retryable`` drives the controlled retry policy."""

    status_code = 502
    code = "ai_provider_error"

    def __init__(self, message: str, *, retryable: bool = True, details: Any = None, kind: str = "provider") -> None:
        super().__init__(message, details=details)
        self.retryable = retryable
        self.kind = kind


class AITimeout(AIProviderError):
    status_code = 504
    code = "ai_timeout"

    def __init__(self, message: str = "The AI provider did not respond in time.") -> None:
        super().__init__(message, retryable=True, kind="timeout")

