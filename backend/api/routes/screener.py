"""Technical stock screener — the EQS mnemonic.

Filters run over the DuckDB `bars` table, so every metric is OHLCV-derived and
the whole universe screens without a fundamentals feed. See `core.screener` for
the field list and the metric SQL.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field as PField

from ...core.screener import FIELDS, build_query
from ...core.sql_engine import engine

logger = logging.getLogger(__name__)
router = APIRouter()


class ScreenFilter(BaseModel):
    field: str
    op: str
    value: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None


class ScreenRequest(BaseModel):
    filters: list[ScreenFilter] = PField(default_factory=list)
    sort: str = "dollar_volume"
    desc: bool = True
    limit: int = PField(default=100, ge=1, le=500)


class ScreenResponse(BaseModel):
    rows: list[dict[str, Any]]
    count: int
    universe: int


@router.get("/fields")
async def list_fields() -> list[dict[str, str]]:
    """Field catalogue for the filter builder UI."""
    return [
        {"key": f.key, "label": f.label, "unit": f.unit, "help": f.help}
        for f in FIELDS
    ]


@router.post("", response_model=ScreenResponse)
async def run_screen(req: ScreenRequest) -> ScreenResponse:
    universe = engine.universe_size()
    if universe == 0:
        raise HTTPException(
            status_code=503,
            detail="Screener universe is empty. Run POST /api/screener/refresh first.",
        )
    try:
        sql, params = build_query(
            [f.model_dump() for f in req.filters],
            sort=req.sort,
            desc=req.desc,
            limit=req.limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        rows = await engine.run_screen(sql, params)
    except Exception as exc:
        logger.exception("screen failed")
        raise HTTPException(status_code=500, detail=f"screen failed: {exc}") from exc

    return ScreenResponse(rows=rows, count=len(rows), universe=universe)


@router.post("/refresh")
async def refresh_universe(
    limit: int | None = Query(None, ge=1, le=20000, description="Cap symbols, for a quick test run"),
) -> dict[str, int]:
    """Re-ingest daily bars for the equity universe. Minutes for a full pass."""
    try:
        written = await engine.refresh_universe(limit=limit)
    except Exception as exc:
        logger.exception("universe refresh failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"rows": written, "symbols": engine.universe_size()}
