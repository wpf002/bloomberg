"""Fixed income — Treasury auctions (free, public) + FINRA TRACE corp
bond prints (free, requires registration at developer.finra.org)."""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources.finra_source import FinraSource
from ...data.sources.treasury_source import TreasurySource
from ...models.schemas import TraceAggregate, TreasuryAuction

logger = logging.getLogger(__name__)
router = APIRouter()

_treasury = TreasurySource()
_finra = FinraSource()


@router.get("/treasury/auctions", response_model=List[TreasuryAuction])
async def treasury_auctions(
    kind: str = Query("announced", description="announced (upcoming) | auctioned (recent results)"),
    limit: int = Query(20, ge=1, le=100),
) -> List[TreasuryAuction]:
    if kind == "announced":
        return await _treasury.announced(limit=limit)
    if kind == "auctioned":
        return await _treasury.auctioned(limit=limit)
    raise HTTPException(status_code=400, detail="kind must be 'announced' or 'auctioned'")


@router.get("/trace", response_model=List[TraceAggregate])
async def trace_aggregates(
    limit: int = Query(50, ge=1, le=500),
) -> List[TraceAggregate]:
    """FINRA Treasury aggregates (monthly first, weekly fallback).

    The free developer tier doesn't entitle accounts to corporate-bond
    TRACE prints — those need a paid subscription. The data we expose
    here are the public Treasury aggregates, which round out the
    Treasury-auction calendar above with actual trading activity.
    """
    if not _finra.credentials_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "FINRA not configured. Register a free developer "
                "account at https://developer.finra.org/ then set "
                "FINRA_API_KEY + FINRA_API_SECRET in .env."
            ),
        )
    return await _finra.treasury_aggregates(limit=limit)


@router.get("/status")
async def fixed_income_status() -> dict:
    """Cheap probe so the panel can say 'TRACE not configured' without a
    503 round-trip."""
    return {
        "treasury": True,  # public, always available
        "trace_configured": _finra.credentials_configured(),
    }
