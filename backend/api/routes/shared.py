"""Public read-only access to shared Launchpad layouts.

Anyone can fetch a layout by slug — that's the whole point. We bump
view_count on each fetch so the owner can see basic engagement, but the
counter is best-effort: a Postgres outage doesn't fail the read.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from ...core.database import database
from .me import SharedLayoutPublic

router = APIRouter()


@router.get("/layouts/{slug}", response_model=SharedLayoutPublic)
async def get_shared_layout(slug: str) -> SharedLayoutPublic:
    if database.pool is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    async with database.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT s.slug, s.name, s.layouts, s.hidden, s.view_count,
                   s.created_at, u.login AS owner_login
            FROM shared_layouts s
            JOIN users u ON u.id = s.owner_user_id
            WHERE s.slug = $1
            """,
            slug,
        )
        if row is None:
            raise HTTPException(status_code=404, detail="shared layout not found")
        # Bump view count async-but-awaited; cheap.
        try:
            await conn.execute(
                "UPDATE shared_layouts SET view_count = view_count + 1 WHERE slug = $1",
                slug,
            )
        except Exception:
            pass
    layouts = row["layouts"] if isinstance(row["layouts"], dict) else json.loads(row["layouts"])
    hidden = row["hidden"] if isinstance(row["hidden"], list) else json.loads(row["hidden"])
    return SharedLayoutPublic(
        slug=row["slug"],
        owner_login=row["owner_login"],
        name=row["name"],
        layouts=layouts,
        hidden=hidden,
        view_count=int(row["view_count"]) + 1,  # reflect the increment we just did
        created_at=row["created_at"].isoformat(),
    )
