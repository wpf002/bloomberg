"""Per-user state: watchlist + Launchpad layout + shared layouts.

Watchlist and layout endpoints are read-your-writes — the frontend persists
in real time as the user reorders panels or adds symbols, and falls back to
localStorage when the request fails.

Shared layouts (Phase 7) let a signed-in user publish their current
Launchpad as a public URL. The slug is stable + URL-safe; anyone can
fetch by slug, only the owner can delete.
"""

from __future__ import annotations

import json
import re
import secrets
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.auth import User, current_user, require_user
from ...core.database import database

router = APIRouter()


class WatchlistPayload(BaseModel):
    symbols: list[str] = Field(default_factory=list, max_length=200)


class LayoutPayload(BaseModel):
    layouts: dict[str, Any] = Field(default_factory=dict)
    hidden: list[str] = Field(default_factory=list)


class ShareLayoutRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class SharedLayoutSummary(BaseModel):
    slug: str
    name: str
    view_count: int
    created_at: str


class SharedLayoutPublic(BaseModel):
    slug: str
    owner_login: str
    name: str
    layouts: dict[str, Any]
    hidden: list[str]
    view_count: int
    created_at: str


_SLUG_RE = re.compile(r"[^a-z0-9-]")


def _slugify(name: str, login: str) -> str:
    base = _SLUG_RE.sub("-", name.lower()).strip("-")
    base = re.sub(r"-+", "-", base) or "layout"
    return f"{login.lower()}-{base[:32]}-{secrets.token_urlsafe(4).lower().replace('_', '').replace('-', '')[:6]}"


def _ensure_db() -> None:
    if database.pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")


@router.get("/watchlist", response_model=WatchlistPayload)
async def get_watchlist(user: User = Depends(require_user)) -> WatchlistPayload:
    _ensure_db()
    async with database.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT symbols FROM user_watchlists WHERE user_id = $1", user.id
        )
    if row is None:
        return WatchlistPayload(symbols=[])
    raw = row["symbols"]
    symbols = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return WatchlistPayload(symbols=[s for s in symbols if isinstance(s, str)])


@router.put("/watchlist", response_model=WatchlistPayload)
async def put_watchlist(
    body: WatchlistPayload, user: User = Depends(require_user)
) -> WatchlistPayload:
    _ensure_db()
    cleaned = [s.strip().upper() for s in body.symbols if s and s.strip()]
    async with database.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_watchlists (user_id, symbols, updated_at)
            VALUES ($1, $2::jsonb, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                symbols = EXCLUDED.symbols,
                updated_at = NOW()
            """,
            user.id,
            json.dumps(cleaned),
        )
    return WatchlistPayload(symbols=cleaned)


@router.get("/layout", response_model=LayoutPayload)
async def get_layout(user: User = Depends(require_user)) -> LayoutPayload:
    _ensure_db()
    async with database.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT layouts, hidden FROM user_layouts WHERE user_id = $1", user.id
        )
    if row is None:
        return LayoutPayload(layouts={}, hidden=[])
    layouts_raw = row["layouts"]
    hidden_raw = row["hidden"]
    layouts = json.loads(layouts_raw) if isinstance(layouts_raw, str) else (layouts_raw or {})
    hidden = json.loads(hidden_raw) if isinstance(hidden_raw, str) else (hidden_raw or [])
    return LayoutPayload(
        layouts=layouts if isinstance(layouts, dict) else {},
        hidden=[h for h in hidden if isinstance(h, str)],
    )


@router.put("/layout", response_model=LayoutPayload)
async def put_layout(
    body: LayoutPayload, request: Request
) -> LayoutPayload:
    user = await require_user(request)
    _ensure_db()
    async with database.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO user_layouts (user_id, layouts, hidden, updated_at)
            VALUES ($1, $2::jsonb, $3::jsonb, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                layouts = EXCLUDED.layouts,
                hidden  = EXCLUDED.hidden,
                updated_at = NOW()
            """,
            user.id,
            json.dumps(body.layouts),
            json.dumps(body.hidden),
        )
    return body


# ── shared layouts (Phase 7) ───────────────────────────────────────────────


@router.post("/layout/share", response_model=SharedLayoutPublic)
async def share_layout(req: ShareLayoutRequest, request: Request) -> SharedLayoutPublic:
    """Snapshot the user's current Launchpad layout under a public slug."""
    user = await require_user(request)
    _ensure_db()
    async with database.acquire() as conn:
        layout_row = await conn.fetchrow(
            "SELECT layouts, hidden FROM user_layouts WHERE user_id = $1", user.id
        )
        if layout_row is None or not layout_row["layouts"]:
            raise HTTPException(
                status_code=400,
                detail="no saved layout to share — drag a panel first so we have something to capture",
            )
        slug = _slugify(req.name, user.login)
        # Best-effort uniqueness — collisions are extremely unlikely with the
        # 6-char suffix, but a re-roll is cheap.
        for _ in range(3):
            existing = await conn.fetchval("SELECT 1 FROM shared_layouts WHERE slug = $1", slug)
            if existing is None:
                break
            slug = _slugify(req.name, user.login)
        layouts_raw = layout_row["layouts"]
        hidden_raw = layout_row["hidden"]
        layouts_json = layouts_raw if isinstance(layouts_raw, str) else json.dumps(layouts_raw)
        hidden_json = hidden_raw if isinstance(hidden_raw, str) else json.dumps(hidden_raw)
        row = await conn.fetchrow(
            """
            INSERT INTO shared_layouts (slug, owner_user_id, name, layouts, hidden)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
            RETURNING slug, name, layouts, hidden, view_count, created_at
            """,
            slug,
            user.id,
            req.name.strip(),
            layouts_json,
            hidden_json,
        )
    return SharedLayoutPublic(
        slug=row["slug"],
        owner_login=user.login,
        name=row["name"],
        layouts=row["layouts"] if isinstance(row["layouts"], dict) else json.loads(row["layouts"]),
        hidden=row["hidden"] if isinstance(row["hidden"], list) else json.loads(row["hidden"]),
        view_count=int(row["view_count"]),
        created_at=row["created_at"].isoformat(),
    )


@router.get("/layout/shares", response_model=list[SharedLayoutSummary])
async def list_my_shares(request: Request) -> list[SharedLayoutSummary]:
    user = await require_user(request)
    _ensure_db()
    async with database.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT slug, name, view_count, created_at
            FROM shared_layouts
            WHERE owner_user_id = $1
            ORDER BY created_at DESC
            """,
            user.id,
        )
    return [
        SharedLayoutSummary(
            slug=r["slug"],
            name=r["name"],
            view_count=int(r["view_count"]),
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]


@router.delete("/layout/shares/{slug}")
async def delete_my_share(slug: str, request: Request) -> dict:
    user = await require_user(request)
    _ensure_db()
    async with database.acquire() as conn:
        out = await conn.execute(
            "DELETE FROM shared_layouts WHERE slug = $1 AND owner_user_id = $2",
            slug,
            user.id,
        )
    if not out or not out.endswith(" 1"):
        raise HTTPException(status_code=404, detail="share not found")
    return {"slug": slug, "deleted": True}
