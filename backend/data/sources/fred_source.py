import asyncio
import logging
from datetime import datetime
from typing import List

from fredapi import Fred

from ...core.cache_utils import cached
from ...core.config import settings
from ..normalizer import get_normalizer
from ...models.schemas import MacroSeries, MacroSeriesPoint

logger = logging.getLogger(__name__)

DEFAULT_SERIES_METADATA = {
    "GDP": ("Gross Domestic Product", "Billions of Dollars", "Quarterly"),
    "CPIAUCSL": ("Consumer Price Index for All Urban Consumers", "Index 1982-1984=100", "Monthly"),
    "UNRATE": ("Unemployment Rate", "Percent", "Monthly"),
    "FEDFUNDS": ("Federal Funds Effective Rate", "Percent", "Monthly"),
    "DGS10": ("10-Year Treasury Constant Maturity Rate", "Percent", "Daily"),
    "DGS2": ("2-Year Treasury Constant Maturity Rate", "Percent", "Daily"),
    "T10Y2Y": ("10Y-2Y Treasury Spread", "Percent", "Daily"),
    "VIXCLS": ("CBOE Volatility Index: VIX", "Index", "Daily"),
    "DCOILWTICO": ("Crude Oil Prices: WTI", "Dollars per Barrel", "Daily"),
}


class FredSource:
    """Async wrapper around fredapi for FRED macroeconomic data."""

    def __init__(self) -> None:
        self._client = Fred(api_key=settings.fred_api_key) if settings.fred_api_key else None

    def _enabled(self) -> bool:
        return self._client is not None

    @cached("fred:series", ttl=600, model=MacroSeries)
    async def get_series(self, series_id: str, limit: int = 120) -> MacroSeries:
        if not self._enabled():
            title, units, freq = DEFAULT_SERIES_METADATA.get(
                series_id, (series_id, None, None)
            )
            return MacroSeries(series_id=series_id, title=title, units=units, frequency=freq)
        series = await asyncio.to_thread(self._series_sync, series_id, limit)
        get_normalizer().from_macro_series("fred", series)
        return series

    def _series_sync(self, series_id: str, limit: int) -> MacroSeries:
        assert self._client is not None
        series = self._client.get_series(series_id)
        observations: List[MacroSeriesPoint] = []
        for ts, value in series.dropna().tail(limit).items():
            observations.append(
                MacroSeriesPoint(
                    date=ts.date() if hasattr(ts, "date") else datetime.fromisoformat(str(ts)).date(),
                    value=float(value),
                )
            )
        title, units, freq = DEFAULT_SERIES_METADATA.get(
            series_id, (series_id, None, None)
        )
        try:
            info = self._client.get_series_info(series_id)
            title = info.get("title", title)
            units = info.get("units", units)
            freq = info.get("frequency", freq)
        except Exception as exc:
            logger.debug("FRED metadata lookup failed for %s: %s", series_id, exc)
        return MacroSeries(
            series_id=series_id,
            title=title,
            units=units,
            frequency=freq,
            observations=observations,
        )
