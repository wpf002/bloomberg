"""Finnhub data source.

Used as the primary feed for:
- Earnings calendar (`/calendar/earnings`) — already wired
- Real-time quotes for indices and any non-US ticker Alpaca doesn't carry
- Spot FX (`/forex/rates`)
- Per-symbol company news (`/company-news`)

Finnhub's free tier also exposes `/stock/candle` historical bars but is
restrictive on coverage; we don't rely on it. Index charts use the
Alpaca-tradable ETF proxy (^GSPC → SPY etc.) so the chart endpoint
stays Alpaca-only.

Free tier: 60 req/min, no daily cap. Cached aggressively.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, List

import httpx

from ...core.cache_utils import cached
from ...core.config import settings
from ...models.schemas import EarningsEvent, FxQuote, NewsItem, Quote

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


def _stable_news_id(url: str, headline: str) -> str:
    return hashlib.sha1(f"{url}|{headline}".encode("utf-8")).hexdigest()[:20]


class FinnhubSource:
    """Async wrapper around Finnhub's REST API."""

    def __init__(self) -> None:
        self._api_key = settings.finnhub_api_key

    def enabled(self) -> bool:
        return bool(self._api_key)

    async def _get(self, client: httpx.AsyncClient, path: str, **params: Any) -> Any:
        params = {**params, "token": self._api_key}
        try:
            resp = await client.get(f"{FINNHUB_BASE}/{path.lstrip('/')}", params=params)
        except httpx.HTTPError as exc:
            logger.warning("Finnhub %s failed: %s", path, type(exc).__name__)
            return None
        if resp.status_code != 200:
            logger.warning("Finnhub %s -> %s: %s", path, resp.status_code, resp.text[:200])
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    # ── earnings calendar (existing) ─────────────────────────────────────

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
        params: dict = {
            "from": from_date.isoformat(),
            "to": to_date.isoformat(),
        }
        if symbol:
            params["symbol"] = symbol.upper()
        async with httpx.AsyncClient(timeout=20.0) as client:
            payload = await self._get(client, "calendar/earnings", **params)
        rows = (payload or {}).get("earningsCalendar", []) or []
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

    # ── quote (indices + non-US tickers) ─────────────────────────────────

    @cached("finnhub:quote", ttl=20, model=Quote)
    async def get_quote(self, symbol: str) -> Quote | None:
        """Real-time quote via `/quote`. Works for US equities, indices
        (^GSPC, ^IXIC, ^DJI, ^VIX), and most non-US tickers on the free
        tier. Returns None when Finnhub doesn't carry the symbol."""
        if not self.enabled():
            return None
        async with httpx.AsyncClient(timeout=10.0) as client:
            data = await self._get(client, "quote", symbol=symbol.upper())
        if not data or not isinstance(data, dict):
            return None
        price = _safe_float(data.get("c")) or 0.0
        if price <= 0:
            return None
        prev = _safe_float(data.get("pc")) or price
        change = _safe_float(data.get("d")) or (price - prev)
        change_pct = _safe_float(data.get("dp")) or ((change / prev * 100.0) if prev else 0.0)
        return Quote(
            symbol=symbol.upper(),
            price=price,
            change=change,
            change_percent=change_pct,
            volume=0,
            day_high=_safe_float(data.get("h")),
            day_low=_safe_float(data.get("l")),
            previous_close=prev,
            timestamp=datetime.now(timezone.utc),
        )

    # ── spot FX ──────────────────────────────────────────────────────────

    @cached("finnhub:fx", ttl=60, model=FxQuote)
    async def get_fx_quote(self, pair: str) -> FxQuote | None:
        """Spot FX via `/forex/rates`. We compute a quote relative to USD
        when possible: pair "EURUSD" → fetch base=EUR rates, take the USD
        leg. The change vs. previous close is best-effort (Finnhub's free
        rates endpoint doesn't return prev close, so we report 0)."""
        if not self.enabled():
            return None
        sym = pair.upper().replace("/", "")
        if len(sym) < 6:
            return None
        base, quote_ccy = sym[:3], sym[3:6]
        async with httpx.AsyncClient(timeout=10.0) as client:
            data = await self._get(client, "forex/rates", base=base)
        if not data or not isinstance(data, dict):
            return None
        rates = data.get("quote") or {}
        rate = _safe_float(rates.get(quote_ccy))
        if rate is None or rate <= 0:
            return None
        return FxQuote(
            pair=sym,
            base=base,
            quote=quote_ccy,
            price=rate,
            change=0.0,
            change_percent=0.0,
            timestamp=datetime.now(timezone.utc),
        )

    # ── per-symbol news ──────────────────────────────────────────────────

    @cached("finnhub:news", ttl=300, model=NewsItem)
    async def get_company_news(self, symbol: str, days_back: int = 7, limit: int = 30) -> List[NewsItem]:
        if not self.enabled():
            return []
        today = date.today()
        params = {
            "symbol": symbol.upper(),
            "from": (today - timedelta(days=days_back)).isoformat(),
            "to": today.isoformat(),
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            data = await self._get(client, "company-news", **params)
        if not data or not isinstance(data, list):
            return []
        out: List[NewsItem] = []
        for row in data[:limit]:
            url = row.get("url") or ""
            headline = (row.get("headline") or "").strip()
            if not url or not headline:
                continue
            ts = row.get("datetime")
            try:
                published = datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else datetime.now(timezone.utc)
            except (TypeError, ValueError):
                published = datetime.now(timezone.utc)
            out.append(
                NewsItem(
                    id=_stable_news_id(url, headline),
                    headline=headline,
                    summary=(row.get("summary") or "").strip() or None,
                    source=row.get("source") or "Finnhub",
                    url=url,
                    symbols=[symbol.upper()],
                    published_at=published,
                )
            )
        return out
