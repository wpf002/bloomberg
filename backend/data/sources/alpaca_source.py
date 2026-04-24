import logging
from datetime import datetime, timedelta, timezone
from typing import List

import httpx

from ...core.cache_utils import cached
from ...core.config import settings
from ...models.schemas import Account, NewsItem, Position, Quote

logger = logging.getLogger(__name__)

ALPACA_DATA_BASE = "https://data.alpaca.markets/v2"
ALPACA_NEWS_BASE = "https://data.alpaca.markets/v1beta1/news"


def _f(value) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _of(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class AlpacaSource:
    """HTTP client for Alpaca Market Data + News + Trading (v2 / v1beta1)."""

    def __init__(self) -> None:
        self._headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key or "",
            "APCA-API-SECRET-KEY": settings.alpaca_api_secret or "",
            "Accept": "application/json",
        }

    def _enabled(self) -> bool:
        return bool(settings.alpaca_api_key and settings.alpaca_api_secret)

    def credentials_configured(self) -> bool:
        return self._enabled()

    async def latest_quote(self, symbol: str) -> Quote | None:
        if not self._enabled():
            return None
        url = f"{ALPACA_DATA_BASE}/stocks/{symbol}/quotes/latest"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self._headers)
        if resp.status_code != 200:
            logger.warning("Alpaca latest_quote %s -> %s", symbol, resp.status_code)
            return None
        payload = resp.json().get("quote", {})
        bid = float(payload.get("bp") or 0.0)
        ask = float(payload.get("ap") or 0.0)
        mid = (bid + ask) / 2 if bid and ask else bid or ask
        return Quote(
            symbol=symbol.upper(),
            price=mid,
            timestamp=datetime.now(timezone.utc),
        )

    async def news(self, symbols: List[str] | None = None, limit: int = 25) -> List[NewsItem]:
        if not self._enabled():
            return []
        params: dict[str, str | int] = {"limit": limit, "sort": "desc"}
        if symbols:
            params["symbols"] = ",".join(sym.upper() for sym in symbols)
        params["start"] = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(ALPACA_NEWS_BASE, headers=self._headers, params=params)
        if resp.status_code != 200:
            logger.warning("Alpaca news -> %s: %s", resp.status_code, resp.text[:200])
            return []
        items = resp.json().get("news", [])
        out: List[NewsItem] = []
        for item in items:
            out.append(
                NewsItem(
                    id=str(item.get("id")),
                    headline=item.get("headline", ""),
                    summary=item.get("summary"),
                    source=item.get("source", "alpaca"),
                    url=item.get("url", ""),
                    symbols=item.get("symbols", []) or [],
                    published_at=datetime.fromisoformat(
                        item["created_at"].replace("Z", "+00:00")
                    ),
                )
            )
        return out

    @cached("alpaca:quote", ttl=10, model=Quote)
    async def get_stock_quote(self, symbol: str) -> Quote | None:
        """Full Quote from Alpaca's /v2/stocks/{symbol}/snapshot endpoint.

        Returns None for symbols Alpaca doesn't carry (indices like ^VIX,
        futures with =F, FX pairs, most non-US tickers) so callers can fall
        back to another provider.
        """
        if not self._enabled():
            return None
        url = f"{ALPACA_DATA_BASE}/stocks/{symbol}/snapshot"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self._headers)
        if resp.status_code != 200:
            logger.warning(
                "Alpaca snapshot %s -> %s: %s", symbol, resp.status_code, resp.text[:200]
            )
            return None
        data = resp.json()
        latest_trade = data.get("latestTrade") or {}
        daily_bar = data.get("dailyBar") or {}
        prev_daily = data.get("prevDailyBar") or {}

        price = _f(latest_trade.get("p")) or _f(daily_bar.get("c"))
        if price <= 0:
            return None
        prev_close = _f(prev_daily.get("c"))
        change = price - prev_close if prev_close else 0.0
        change_pct = (change / prev_close * 100.0) if prev_close else 0.0

        return Quote(
            symbol=symbol.upper(),
            price=price,
            change=change,
            change_percent=change_pct,
            volume=int(_f(daily_bar.get("v"))),
            day_high=_of(daily_bar.get("h")),
            day_low=_of(daily_bar.get("l")),
            previous_close=prev_close if prev_close else None,
            timestamp=datetime.now(timezone.utc),
        )

    @cached("alpaca:account", ttl=10, model=Account)
    async def get_account(self) -> Account | None:
        if not self._enabled():
            return None
        url = f"{settings.alpaca_base_url.rstrip('/')}/v2/account"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self._headers)
        if resp.status_code != 200:
            logger.warning("Alpaca account -> %s: %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        return Account(
            account_number=data.get("account_number"),
            status=data.get("status"),
            currency=data.get("currency") or "USD",
            cash=_f(data.get("cash")),
            buying_power=_f(data.get("buying_power")),
            portfolio_value=_f(data.get("portfolio_value")),
            equity=_f(data.get("equity")),
            last_equity=_f(data.get("last_equity")),
            long_market_value=_f(data.get("long_market_value")),
            short_market_value=_f(data.get("short_market_value")),
            daytrade_count=int(data.get("daytrade_count") or 0),
            pattern_day_trader=bool(data.get("pattern_day_trader", False)),
            timestamp=datetime.now(timezone.utc),
        )

    @cached("alpaca:positions", ttl=10, model=Position)
    async def get_positions(self) -> List[Position]:
        if not self._enabled():
            return []
        url = f"{settings.alpaca_base_url.rstrip('/')}/v2/positions"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self._headers)
        if resp.status_code != 200:
            logger.warning("Alpaca positions -> %s: %s", resp.status_code, resp.text[:200])
            return []
        items = resp.json()
        out: List[Position] = []
        for item in items:
            pct = _of(item.get("unrealized_plpc"))
            intraday_pct = _of(item.get("unrealized_intraday_plpc"))
            change_today = _of(item.get("change_today"))
            out.append(
                Position(
                    symbol=(item.get("symbol") or "").upper(),
                    asset_class=item.get("asset_class"),
                    exchange=item.get("exchange"),
                    qty=_f(item.get("qty")),
                    side=item.get("side") or "long",
                    avg_entry_price=_f(item.get("avg_entry_price")),
                    current_price=_of(item.get("current_price")),
                    market_value=_of(item.get("market_value")),
                    cost_basis=_of(item.get("cost_basis")),
                    unrealized_pl=_of(item.get("unrealized_pl")),
                    unrealized_pl_percent=(pct * 100.0) if pct is not None else None,
                    unrealized_intraday_pl=_of(item.get("unrealized_intraday_pl")),
                    unrealized_intraday_pl_percent=(
                        intraday_pct * 100.0 if intraday_pct is not None else None
                    ),
                    change_today_percent=(
                        change_today * 100.0 if change_today is not None else None
                    ),
                )
            )
        return out


_alpaca_singleton: AlpacaSource | None = None


def get_alpaca_source() -> AlpacaSource:
    """Shared process-wide AlpacaSource; routes should import this rather
    than constructing their own instance."""
    global _alpaca_singleton
    if _alpaca_singleton is None:
        _alpaca_singleton = AlpacaSource()
    return _alpaca_singleton
