"""Risk Engine API — sector exposure, correlation, drawdown, VaR/CVaR, stress.

All routes pull the current Alpaca paper-account positions and return a
JSON-serializable analytics payload. Heavy computation (90-day correlation
matrices, multi-decade SPY paths for stress tests) is delegated to
backend/services/risk_engine.py.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ...data.sources import get_alpaca_source
from ...services import risk_engine

logger = logging.getLogger(__name__)
router = APIRouter()


def _alpaca_or_503() -> None:
    if not get_alpaca_source().credentials_configured():
        raise HTTPException(
            status_code=503,
            detail="Alpaca credentials not configured — set ALPACA_API_KEY/SECRET.",
        )


@router.get("/exposure")
async def get_exposure() -> dict:
    """Sector exposure breakdown weighted by market value."""
    _alpaca_or_503()
    try:
        return await risk_engine.compute_exposure()
    except Exception as exc:
        logger.exception("risk/exposure failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/correlation")
async def get_correlation() -> dict:
    """Correlation matrix across current holdings (90-day daily returns)."""
    _alpaca_or_503()
    try:
        return await risk_engine.compute_correlation()
    except Exception as exc:
        logger.exception("risk/correlation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/drawdown")
async def get_drawdown() -> dict:
    """Per-position + portfolio drawdown stats with NAV curve."""
    _alpaca_or_503()
    try:
        return await risk_engine.compute_drawdown()
    except Exception as exc:
        logger.exception("risk/drawdown failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/var")
async def get_var() -> dict:
    """Historical-simulation VaR + CVaR at 95% and 99%."""
    _alpaca_or_503()
    try:
        return await risk_engine.compute_var()
    except Exception as exc:
        logger.exception("risk/var failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/stress")
async def get_stress() -> dict:
    """Stress-test results vs 2008 GFC / 2020 COVID / 2022 rate shock."""
    _alpaca_or_503()
    try:
        return await risk_engine.compute_stress()
    except Exception as exc:
        logger.exception("risk/stress failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
