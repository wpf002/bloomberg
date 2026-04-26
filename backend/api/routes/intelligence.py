"""Intelligence Engine API.

Surfaces regime classification, fragility scoring, capital flow inference,
and sector rotation signals computed by backend/services/intelligence_engine.py.

These endpoints are read-only and stateless from the API's perspective.
Module 5 captures their outputs into intelligence_snapshots so the system
can replay "what did we know at time T."
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from ...services import intelligence_engine

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/regime")
async def get_regime() -> dict:
    """Current macro regime + confidence + contributing factors."""
    try:
        payload = await intelligence_engine.regime_now()
    except Exception as exc:
        logger.exception("intelligence/regime failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    # Best-effort persistence to the intelligence_snapshots hypertable
    # (Module 5). Failure is non-fatal — the live answer still ships.
    try:
        from ...core.audit import persist_intelligence_snapshot
        await persist_intelligence_snapshot("regime", payload.get("raw") or {}, payload)
    except Exception:
        pass
    return payload


@router.get("/fragility")
async def get_fragility() -> dict:
    """Portfolio + per-position fragility scores (0-100)."""
    try:
        payload = await intelligence_engine.fragility_now()
    except Exception as exc:
        logger.exception("intelligence/fragility failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    try:
        from ...core.audit import persist_intelligence_snapshot
        await persist_intelligence_snapshot(
            "fragility", {"regime": payload.get("regime")}, payload
        )
    except Exception:
        pass
    return payload


@router.get("/flows")
async def get_flows() -> dict:
    """Capital flow inference: 13F filer cadence + sector ETF flows."""
    try:
        return await intelligence_engine.capital_flows()
    except Exception as exc:
        logger.exception("intelligence/flows failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/rotation")
async def get_rotation() -> dict:
    """Sector rotation signals + cycle phase classification."""
    try:
        payload = await intelligence_engine.sector_rotation()
    except Exception as exc:
        logger.exception("intelligence/rotation failed")
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    try:
        from ...core.audit import persist_intelligence_snapshot
        await persist_intelligence_snapshot(
            "rotation",
            {"spy_return_30d": payload.get("spy_return_30d")},
            payload,
        )
    except Exception:
        pass
    return payload
