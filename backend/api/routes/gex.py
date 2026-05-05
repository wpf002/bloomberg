"""V2.4 — GEX (Gamma Exposure) and VEX (Vanna Exposure) endpoints.

GEX/VEX are computed from the options chain Alpaca already exposes —
no new data source needed. The math lives in
backend/services/risk_engine.py; this module is just the route layer.

Routes:
  GET /api/gex/{symbol}        full per-strike GEX profile
  GET /api/vex/{symbol}        full per-strike VEX profile
  GET /api/gex/{symbol}/levels trimmed payload — flip / max-gamma / walls
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ...services.risk_engine import compute_gex, compute_gex_levels, compute_vex

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{symbol}")
async def gex_profile(symbol: str) -> dict:
    sym = symbol.upper()
    try:
        return await compute_gex(sym)
    except Exception as exc:
        logger.warning("gex compute failed for %s: %s", sym, exc)
        raise HTTPException(status_code=502, detail=f"GEX compute failed: {exc}")


@router.get("/{symbol}/levels")
async def gex_levels(symbol: str) -> dict:
    sym = symbol.upper()
    try:
        return await compute_gex_levels(sym)
    except Exception as exc:
        logger.warning("gex levels compute failed for %s: %s", sym, exc)
        raise HTTPException(status_code=502, detail=f"GEX levels compute failed: {exc}")
