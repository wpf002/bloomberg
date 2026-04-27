"""GitHub OAuth login.

Flow:
  1. Browser → GET /api/auth/github/login
     → 302 redirect to GitHub's authorize URL with our client_id + a CSRF
       state cookie.
  2. GitHub → GET /api/auth/github/callback?code=…&state=…
     → we verify the state cookie, exchange the code for an access_token,
       fetch the GitHub user profile, upsert into Postgres, set our session
       cookie, then 302 to the frontend URL.
  3. Browser → GET /api/auth/me
     → returns the current user (or 200 with `null` when unauthenticated).
"""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from ...core.auth import current_user, issue_session, upsert_github_user
from ...core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
GITHUB_EMAILS_URL = "https://api.github.com/user/emails"

OAUTH_STATE_COOKIE = "bt_oauth_state"


def _oauth_configured() -> bool:
    return bool(settings.github_client_id and settings.github_client_secret)


def _cookie_security() -> tuple[str, bool]:
    """Pick (samesite, secure) for our auth cookies.

    Local dev (frontend on http://localhost:5173) needs `lax + insecure`
    so cookies get set without HTTPS. Production (frontend on a different
    Railway subdomain than the backend) needs `none + secure` so the
    browser sends the session cookie on cross-origin XHRs from the SPA.
    Heuristic: if FRONTEND_URL is HTTPS, assume cross-origin production.
    """
    if settings.frontend_url.startswith("https://"):
        return "none", True
    return "lax", False


@router.get("/github/login")
async def github_login(request: Request) -> Response:
    if not _oauth_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "GitHub OAuth not configured. Set GITHUB_CLIENT_ID + "
                "GITHUB_CLIENT_SECRET in .env (https://github.com/settings/developers)."
            ),
        )
    state = secrets.token_urlsafe(24)
    callback_url = str(request.url_for("github_callback"))
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": callback_url,
        "scope": "read:user user:email",
        "state": state,
        "allow_signup": "true",
    }
    target = f"{GITHUB_AUTHORIZE_URL}?{urlencode(params)}"
    response = RedirectResponse(target, status_code=302)
    samesite, secure = _cookie_security()
    response.set_cookie(
        OAUTH_STATE_COOKIE,
        state,
        max_age=600,
        httponly=True,
        samesite=samesite,
        secure=secure,
    )
    return response


@router.get("/github/callback", name="github_callback")
async def github_callback(request: Request, code: str | None = None, state: str | None = None) -> Response:
    if not _oauth_configured():
        raise HTTPException(status_code=503, detail="GitHub OAuth not configured")
    if not code:
        raise HTTPException(status_code=400, detail="missing ?code")
    expected_state = request.cookies.get(OAUTH_STATE_COOKIE)
    if not expected_state or expected_state != state:
        raise HTTPException(status_code=400, detail="invalid oauth state")

    callback_url = str(request.url_for("github_callback"))
    async with httpx.AsyncClient(timeout=10.0) as client:
        token_resp = await client.post(
            GITHUB_TOKEN_URL,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": callback_url,
            },
        )
        if token_resp.status_code != 200:
            logger.warning("github token exchange %s: %s", token_resp.status_code, token_resp.text[:200])
            raise HTTPException(status_code=502, detail="github token exchange failed")
        token_payload = token_resp.json()
        access_token = token_payload.get("access_token")
        if not access_token:
            raise HTTPException(status_code=502, detail=f"github oauth error: {token_payload}")

        auth_headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "bloomberg-terminal",
        }
        user_resp = await client.get(GITHUB_USER_URL, headers=auth_headers)
        if user_resp.status_code != 200:
            raise HTTPException(status_code=502, detail="github /user failed")
        profile = user_resp.json()
        # /user.email may be null when the user keeps it private; pull the
        # primary verified address from /user/emails as a fallback.
        if not profile.get("email"):
            email_resp = await client.get(GITHUB_EMAILS_URL, headers=auth_headers)
            if email_resp.status_code == 200:
                emails = email_resp.json() or []
                primary = next(
                    (e for e in emails if e.get("primary") and e.get("verified")),
                    None,
                )
                if primary:
                    profile["email"] = primary.get("email")

    user = await upsert_github_user(profile)
    session = issue_session(user.id)
    redirect = RedirectResponse(settings.frontend_url, status_code=302)
    samesite, secure = _cookie_security()
    redirect.set_cookie(
        settings.session_cookie_name,
        session,
        max_age=settings.jwt_ttl_hours * 3600,
        httponly=True,
        samesite=samesite,
        secure=secure,
        path="/",
    )
    redirect.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    return redirect


@router.get("/me")
async def me(request: Request) -> dict | None:
    user = await current_user(request)
    return user.public() if user else None


@router.post("/logout")
async def logout() -> Response:
    response = JSONResponse({"ok": True})
    response.delete_cookie(settings.session_cookie_name, path="/")
    return response


@router.get("/status")
async def status() -> dict:
    """Cheap unauthenticated probe so the frontend can hide the login button
    when OAuth isn't configured (instead of letting the user click into a
    503)."""
    return {"github_configured": _oauth_configured()}
