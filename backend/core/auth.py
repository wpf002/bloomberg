"""Session auth: GitHub OAuth + signed JWT cookies.

Why JWT cookies instead of a server-side session table?
  - The same FastAPI process serves the WebSocket endpoints, and we want the
    WS upgrade handshake to authenticate from the same cookie without a DB
    hit. A signed token is read in pure Python.
  - We don't have a logout-everywhere requirement; a 30-day TTL is fine and
    we treat client-side cookie deletion as logout.

We sign with a stable secret (`settings.jwt_secret`); when unset we generate
one in-process so dev still works (tokens then invalidate on restart).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status

from .config import settings
from .database import database

logger = logging.getLogger(__name__)


# ── token signing ───────────────────────────────────────────────────────────

_dev_secret: str | None = None


def _signing_secret() -> str:
    global _dev_secret
    # Accept either SECRET_KEY (Railway-friendly name) or JWT_SECRET. The
    # `signing_secret` property folds both into one value.
    configured = settings.signing_secret
    if configured:
        return configured
    if _dev_secret is None:
        _dev_secret = secrets.token_urlsafe(48)
        logger.warning(
            "SECRET_KEY/JWT_SECRET unset — generated an ephemeral signing key. "
            "Sessions will invalidate on backend restart. Set SECRET_KEY in env."
        )
    return _dev_secret


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(token: str) -> bytes:
    pad = "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode(token + pad)


def encode_token(payload: dict[str, Any]) -> str:
    """Compact HS256 JWT. We hand-roll instead of pulling pyjwt because the
    surface area is tiny and we already control both encode and decode."""
    header = {"alg": "HS256", "typ": "JWT"}
    seg_h = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    seg_p = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{seg_h}.{seg_p}".encode("ascii")
    sig = hmac.new(_signing_secret().encode(), signing_input, hashlib.sha256).digest()
    return f"{seg_h}.{seg_p}.{_b64url_encode(sig)}"


def decode_token(token: str) -> dict[str, Any] | None:
    try:
        seg_h, seg_p, seg_s = token.split(".")
    except ValueError:
        return None
    signing_input = f"{seg_h}.{seg_p}".encode("ascii")
    expected = hmac.new(_signing_secret().encode(), signing_input, hashlib.sha256).digest()
    try:
        actual = _b64url_decode(seg_s)
    except Exception:
        return None
    if not hmac.compare_digest(expected, actual):
        return None
    try:
        payload = json.loads(_b64url_decode(seg_p))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and exp < time.time():
        return None
    return payload


def issue_session(user_id: int) -> str:
    now = int(time.time())
    return encode_token(
        {
            "sub": str(user_id),
            "iat": now,
            "exp": now + settings.jwt_ttl_hours * 3600,
        }
    )


# ── user dataclass + DB helpers ─────────────────────────────────────────────


@dataclass
class User:
    id: int
    github_id: str
    login: str
    name: str | None
    email: str | None
    avatar_url: str | None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "login": self.login,
            "name": self.name,
            "email": self.email,
            "avatar_url": self.avatar_url,
        }


async def upsert_github_user(profile: dict[str, Any]) -> User:
    """Insert-or-update a user from the GitHub /user response."""
    if database.pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    github_id = str(profile.get("id"))
    login = profile.get("login") or "unknown"
    async with database.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO users (github_id, login, name, email, avatar_url, last_login_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (github_id) DO UPDATE SET
                login = EXCLUDED.login,
                name = EXCLUDED.name,
                email = EXCLUDED.email,
                avatar_url = EXCLUDED.avatar_url,
                last_login_at = NOW()
            RETURNING id, github_id, login, name, email, avatar_url
            """,
            github_id,
            login,
            profile.get("name"),
            profile.get("email"),
            profile.get("avatar_url"),
        )
    return User(**dict(row))


async def get_user_by_id(user_id: int) -> User | None:
    if database.pool is None:
        return None
    async with database.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, github_id, login, name, email, avatar_url FROM users WHERE id = $1",
            user_id,
        )
    return User(**dict(row)) if row else None


# ── FastAPI dependencies ───────────────────────────────────────────────────


def _read_token(request: Request) -> str | None:
    cookie = request.cookies.get(settings.session_cookie_name)
    if cookie:
        return cookie
    auth = request.headers.get("Authorization") or request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip() or None
    return None


async def current_user(request: Request) -> User | None:
    token = _read_token(request)
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
    return await get_user_by_id(user_id)


async def require_user(request: Request) -> User:
    user = await current_user(request)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")
    return user


def user_from_token(token: str | None) -> int | None:
    """Sync token decode for WS handshake. Returns user id or None."""
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    try:
        return int(payload.get("sub"))
    except (TypeError, ValueError):
        return None
