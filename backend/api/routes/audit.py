"""Audit-log + intelligence-snapshot read API.

Both endpoints degrade gracefully when TimescaleDB is unavailable:
they return an empty result set with a `note` describing the situation
rather than 5xx-ing.

- GET /api/audit?symbol=X&from=ISO&to=ISO&limit=N
- GET /api/audit/snapshots?kind=regime&limit=N
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query

from ...core.audit import fetch_audit, fetch_intelligence_snapshots
from ...core.database import database

logger = logging.getLogger(__name__)
router = APIRouter()


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


@router.get("")
async def get_audit(
    symbol: str = Query(..., min_length=1, max_length=32),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> dict[str, Any]:
    """Paginated audit-log entries for `symbol`."""
    if database.pool is None:
        return {
            "rows": [],
            "note": "Postgres unavailable — audit log not yet readable.",
        }
    rows = await fetch_audit(symbol, _parse_iso(from_), _parse_iso(to), limit)
    return {"rows": rows, "count": len(rows), "note": None}


@router.get("/snapshots")
async def get_snapshots(
    kind: str = Query(..., min_length=1, max_length=64),
    limit: int = Query(50, ge=1, le=500),
) -> dict[str, Any]:
    """Most-recent N intelligence snapshots for the given `kind`
    (regime / fragility / rotation)."""
    if database.pool is None:
        return {
            "rows": [],
            "note": "Postgres unavailable — snapshot history not yet readable.",
        }
    rows = await fetch_intelligence_snapshots(kind, limit)
    return {"rows": rows, "count": len(rows), "note": None}
