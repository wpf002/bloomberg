"""V2.4 — VEX (Vanna Exposure) endpoint.

Per the spec the VEX profile lives at /api/vex/{symbol}. The math is
shared with the GEX route under services/risk_engine.py.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ...services.risk_engine import compute_vex

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{symbol}")
async def vex_profile(symbol: str) -> dict:
    sym = symbol.upper()
    try:
        return await compute_vex(sym)
    except Exception as exc:
        logger.warning("vex compute failed for %s: %s", sym, exc)
        raise HTTPException(status_code=502, detail=f"VEX compute failed: {exc}")
