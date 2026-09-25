"""Password hashing (bcrypt), signed access tokens (JWT, HS256) and CSRF tokens."""

from __future__ import annotations

import hmac
import secrets
from datetime import timedelta
from typing import Any

import bcrypt
import jwt

from supportnova.core.config import get_settings
from supportnova.core.errors import AuthenticationFailed
from supportnova.core.timeutil import utcnow

ALGORITHM = "HS256"
ACCESS_COOKIE = "sn_access"
CSRF_COOKIE = "sn_csrf"
CSRF_HEADER = "x-csrf-token"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8")[:72], bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], password_hash.encode("ascii"))
    except ValueError:
        return False


def create_access_token(user_id: int, role: str, *, minutes: int | None = None) -> str:
    settings = get_settings()
    now = utcnow()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes or settings.access_token_minutes)).timestamp()),
        "jti": secrets.token_hex(8),
        "iss": "supportnova",
    }
    return jwt.encode(payload, settings.secret_key.get_secret_value(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, get_settings().secret_key.get_secret_value(), algorithms=[ALGORITHM],
                          issuer="supportnova", options={"require": ["exp", "sub", "iat"]})
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationFailed("Your session has expired. Please sign in again.", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise AuthenticationFailed("Invalid authentication token.", code="invalid_token") from exc


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


def csrf_matches(cookie_value: str | None, header_value: str | None) -> bool:
    return bool(cookie_value and header_value and hmac.compare_digest(cookie_value, header_value))
