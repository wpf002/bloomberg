"""Finnhub data source.

Used as the primary earnings calendar provider. Finnhub exposes a real
market-wide `/calendar/earnings?from=…&to=…` endpoint with consensus EPS
and revenue, which is what Yahoo's per-ticker endpoint gives us only
unreliably.

Free tier: 60 req/min, no per-day cap. We cache aggressively because the
calendar changes only when new estimates land.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import List

import httpx

from ...core.cache_utils import cached
from ...core.config import settings
from ...models.schemas import EarningsEvent

logger = logging.getLogger(__name__)

FINNHUB_BASE = "https://finnhub.io/api/v1"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None


def _safe_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return None
    if fv != fv:  # NaN
        return None
    return fv


class FinnhubSource:
    """Async wrapper around Finnhub's REST API."""

    def __init__(self) -> None:
        self._api_key = settings.finnhub_api_key

    def enabled(self) -> bool:
        return bool(self._api_key)

    # 1h cache: earnings dates / consensus estimates change at most a few
    # times per day. The frontend polls at the same cadence so a refresh
    # doesn't burn requests on stale data. Finnhub free tier is 60 req/min
    # with no daily cap, so the binding constraint is "don't be wasteful."
    @cached("finnhub:calendar", ttl=3600, model=EarningsEvent)
    async def get_earnings_calendar(
        self,
        symbol: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
    ) -> List[EarningsEvent]:
        if not self.enabled():
            return []
        from_date = from_date or date.today()
        to_date = to_date or (from_date + timedelta(days=90))
        params = {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
            "token": self._api_key,
        }
        if symbol:
            params["symbol"] = symbol.upper()
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.get(f"{FINNHUB_BASE}/calendar/earnings", params=params)
        except httpx.HTTPError as exc:
            logger.warning("Finnhub calendar request failed: %s", type(exc).__name__)
            return []
        if resp.status_code != 200:
            logger.warning(
                "Finnhub calendar returned %s: %s",
                resp.status_code,
                resp.text[:200],
            )
            return []
        rows = (resp.json() or {}).get("earningsCalendar", []) or []
        events: List[EarningsEvent] = []
        for row in rows:
            event_date = _parse_date(row.get("date"))
            if event_date is None:
                continue
            events.append(
                EarningsEvent(
                    symbol=str(row.get("symbol") or "").upper(),
                    event_date=event_date,
                    when=row.get("hour") or None,
                    eps_estimate=_safe_float(row.get("epsEstimate")),
                    eps_actual=_safe_float(row.get("epsActual")),
                    eps_surprise_percent=_safe_float(row.get("surprisePercent")),
                    revenue_estimate=_safe_float(row.get("revenueEstimate")),
                    revenue_actual=_safe_float(row.get("revenueActual")),
                    source="finnhub",
                )
            )
        events.sort(key=lambda e: e.event_date)
        return events
