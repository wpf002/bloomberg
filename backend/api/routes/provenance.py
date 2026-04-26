"""Data provenance endpoints — lineage of every value the panels render.

`GET /api/provenance?symbol=X&limit=N` returns the most-recent N normalized
records the system has ingested for that symbol. Each record carries the
source it came from, when the source produced the timestamp, and when we
ingested it. Module 5 adds the durable audit-log read-back; this endpoint
is the "what did the system see lately" view that always works.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ...data.normalizer import NormalizedRecord, get_normalizer

logger = logging.getLogger(__name__)
router = APIRouter()


class ProvenanceResponse(BaseModel):
    symbol: str
    series_id: Optional[str] = None
    count: int
    records: List[NormalizedRecord]
    sources: dict[str, int]
    oldest_ingested_at: Optional[datetime] = None
    newest_ingested_at: Optional[datetime] = None


@router.get("", response_model=ProvenanceResponse)
async def get_provenance(
    symbol: str = Query(..., min_length=1, max_length=32),
    limit: int = Query(100, ge=1, le=500),
    series_id: Optional[str] = Query(None, max_length=64),
) -> ProvenanceResponse:
    """Recent normalized records for `symbol`, newest first."""
    norm = get_normalizer()
    records = norm.recent(symbol=symbol, limit=limit, series_id=series_id)
    sources: dict[str, int] = {}
    for r in records:
        sources[r.source] = sources.get(r.source, 0) + 1
    oldest = records[-1].ingested_at if records else None
    newest = records[0].ingested_at if records else None
    return ProvenanceResponse(
        symbol=symbol.upper(),
        series_id=series_id,
        count=len(records),
        records=records,
        sources=sources,
        oldest_ingested_at=oldest,
        newest_ingested_at=newest,
    )
