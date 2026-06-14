from typing import List

import httpx
from fastapi import APIRouter, HTTPException, Query

from ...core import settings
from ...data.sources import FredSource
from ...data.sources.fred_source import DEFAULT_SERIES_METADATA
from ...models.schemas import MacroForecast, MacroForecastPoint, MacroSeries

router = APIRouter()
_fred = FredSource()


@router.get("/series", response_model=List[str])
async def list_series() -> List[str]:
    return list(DEFAULT_SERIES_METADATA.keys())


@router.get("/series/{series_id}", response_model=MacroSeries)
async def get_series(series_id: str, limit: int = Query(120, ge=1, le=5000)) -> MacroSeries:
    try:
        return await _fred.get_series(series_id.upper(), limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"fred error: {exc}") from exc


@router.get("/forecast/{series_id}", response_model=MacroForecast)
async def forecast_series(
    series_id: str,
    horizon: int = Query(12, ge=1, le=12),
    level: int = Query(80, ge=1, le=99),
) -> MacroForecast:
    """Project a macro series forward via the Prophet forecasting service.

    Read-only: calls Prophet's ``POST /forecast`` (model ``macro``) and maps the
    response into ``MacroForecast``. Only the forecastable FRED series Prophet
    serves (``settings.prophet_macro_series``) are supported.
    """
    sid = series_id.upper()
    if sid not in settings.prophet_macro_series:
        raise HTTPException(
            status_code=404,
            detail=(
                f"'{sid}' is not forecastable by Prophet. "
                f"Available: {', '.join(settings.prophet_macro_series)}."
            ),
        )

    payload = {"model": "macro", "series_id": sid, "horizon": horizon, "level": [level]}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(f"{settings.prophet_url}/forecast", json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"prophet error: {exc}") from exc

    lvl = str(level)
    points = [
        MacroForecastPoint(
            date=row["ds"][:10],
            value=row["y_hat"],
            lo=(row.get("lo") or {}).get(lvl),
            hi=(row.get("hi") or {}).get(lvl),
        )
        for row in data.get("forecasts", [])
    ]
    return MacroForecast(
        series_id=sid,
        model=data.get("model", "macro"),
        horizon=horizon,
        generated_at=data.get("generated_at"),
        points=points,
    )
