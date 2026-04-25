"""Futures dashboard + per-root term-structure curve."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, HTTPException

from ...data.sources.futures_source import FuturesSource, ROOTS
from ...models.schemas import FuturesContract, FuturesCurve

router = APIRouter()
_source = FuturesSource()


@router.get("/dashboard", response_model=List[FuturesContract])
async def dashboard() -> List[FuturesContract]:
    return await _source.dashboard()


@router.get("/curve/{root}", response_model=FuturesCurve)
async def curve(root: str) -> FuturesCurve:
    if root.upper() not in ROOTS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown root '{root}'. Supported: {sorted(ROOTS.keys())}",
        )
    return await _source.get_curve(root.upper())
