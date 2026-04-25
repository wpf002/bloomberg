"""Per-user state: watchlist + Launchpad layout.

Both endpoints are read-your-writes — the frontend persists in real time
as the user reorders panels or adds symbols, and falls back to localStorage
when the request fails. Empty bodies are valid (a freshly-onboarded user
has no rows yet); we 200 with default state in that case.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...core.auth import User, require_user
from ...core.database import database

router = APIRouter()


class WatchlistPayload(BaseModel):
    symbols: list[str] = Field(default_factory=list, max_length=200)


class LayoutPayload(BaseModel):
    layouts: dict[str, Any] = Field(default_factory=dict)
    hidden: list[str] = Field(default_factory=list)


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
    body: LayoutPayload, user: User = Depends(require_user)
) -> LayoutPayload:
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
