"""Request dependencies: DB session, authenticated user, RBAC permission guards, CSRF protection.

Browsers authenticate with an HttpOnly, SameSite=Lax access cookie; every state-changing request made
with that cookie must echo the CSRF token (double-submit: sn_csrf cookie == X-CSRF-Token header).
API clients may instead send ``Authorization: Bearer <token>`` (not ambient, so no CSRF needed).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from supportnova.core.errors import AuthenticationFailed, PermissionDenied
from supportnova.database.base import get_db
from supportnova.database.models import User
from supportnova.security.auth import (
    ACCESS_COOKIE,
    CSRF_COOKIE,
    CSRF_HEADER,
    csrf_matches,
    decode_access_token,
)

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def db_session() -> Iterator[Session]:
    yield from get_db()


def current_user(request: Request, db: Session = Depends(db_session)) -> User:
    header = request.headers.get("authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    via_cookie = False
    if not token:
        token = request.cookies.get(ACCESS_COOKIE)
        via_cookie = bool(token)
    if not token:
        raise AuthenticationFailed("Please sign in to continue.")
    claims = decode_access_token(token)
    if via_cookie and request.method in UNSAFE and not csrf_matches(request.cookies.get(CSRF_COOKIE),
                                                                    request.headers.get(CSRF_HEADER)):
        raise PermissionDenied("Your session's security token is missing or expired. Reload the page and try again.",
                               code="csrf_failed")
    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise AuthenticationFailed("Your account is not active.")
    request.state.user = user
    return user


def require(*permissions: str) -> Callable[[User], User]:
    """Dependency factory: the user must hold ALL listed permissions (enforced server-side)."""

    def guard(user: User = Depends(current_user)) -> User:
        missing = [p for p in permissions if p not in user.permissions]
        if missing:
            raise PermissionDenied(f"Your role ({user.role_code}) is not allowed to perform this action.",
                                   details={"missing_permissions": missing})
        return user

    return guard


def require_any(*permissions: str) -> Callable[[User], User]:
    def guard(user: User = Depends(current_user)) -> User:
        if not any(p in user.permissions for p in permissions):
            raise PermissionDenied(f"Your role ({user.role_code}) is not allowed to perform this action.")
        return user

    return guard


def client_ip(request: Request) -> str:
    """The peer address. X-Forwarded-For is NOT read here: a client can put anything in it. Behind a reverse
    proxy, uvicorn's --proxy-headers resolves it using only the proxies listed in FORWARDED_ALLOW_IPS."""
    return request.client.host if request.client else "-"
