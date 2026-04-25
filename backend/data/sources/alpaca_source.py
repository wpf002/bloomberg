import logging
from datetime import datetime, timedelta, timezone
from typing import List

import httpx

from ...core.cache_utils import cached
from ...core.config import settings
from ...models.schemas import Account, NewsItem, Order, OrderRequest, Position, Quote, QuoteHistoryPoint

logger = logging.getLogger(__name__)

ALPACA_DATA_BASE = "https://data.alpaca.markets/v2"
ALPACA_NEWS_BASE = "https://data.alpaca.markets/v1beta1/news"
ALPACA_CRYPTO_BASE = "https://data.alpaca.markets/v1beta3/crypto/us"

# yfinance-style → Alpaca bar timeframe enum
_INTERVAL_TO_TIMEFRAME = {
    "1m": "1Min",  "2m": "5Min",  "5m": "5Min",  "15m": "15Min",
    "30m": "30Min","60m": "1Hour","90m": "1Hour","1h": "1Hour",
    "1d": "1Day",  "5d": "1Day",  "1wk": "1Week","1mo": "1Month",
}
_PERIOD_TO_DAYS = {
    "1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
    "1y": 365, "2y": 730, "5y": 1825, "10y": 3650, "max": 5475,
}


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

    @cached("alpaca:bars", ttl=60, model=QuoteHistoryPoint)
    async def get_stock_bars(
        self,
        symbol: str,
        period: str = "1mo",
        interval: str = "1d",
    ) -> List[QuoteHistoryPoint]:
        """OHLCV bars from Alpaca's /v2/stocks/{symbol}/bars. Maps the
        yfinance-style period/interval strings (e.g. '1mo' / '1d') onto
        Alpaca's timeframe enum and a start/end window. Free-tier IEX feed."""
        if not self._enabled():
            return []
        tf = _INTERVAL_TO_TIMEFRAME.get(interval, "1Day")
        now = datetime.now(timezone.utc)
        if period == "ytd":
            start = datetime(now.year, 1, 1, tzinfo=timezone.utc)
        else:
            days = _PERIOD_TO_DAYS.get(period, 30)
            start = now - timedelta(days=days)
        url = f"{ALPACA_DATA_BASE}/stocks/{symbol}/bars"
        params = {
            "timeframe": tf,
            "start": start.isoformat().replace("+00:00", "Z"),
            "limit": 10000,
            "feed": "iex",
            "adjustment": "raw",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=self._headers, params=params)
        if resp.status_code != 200:
            logger.warning(
                "Alpaca bars %s (%s/%s) -> %s: %s",
                symbol, period, interval, resp.status_code, resp.text[:200],
            )
            return []
        bars = (resp.json() or {}).get("bars") or []
        out: List[QuoteHistoryPoint] = []
        for b in bars:
            try:
                out.append(
                    QuoteHistoryPoint(
                        timestamp=datetime.fromisoformat(b["t"].replace("Z", "+00:00")),
                        open=_f(b.get("o")),
                        high=_f(b.get("h")),
                        low=_f(b.get("l")),
                        close=_f(b.get("c")),
                        volume=int(_f(b.get("v"))),
                    )
                )
            except Exception as exc:
                logger.debug("skipping malformed bar for %s: %s", symbol, exc)
        return out

    @cached("alpaca:crypto", ttl=15, model=Quote)
    async def get_crypto_quote(self, symbol: str) -> Quote | None:
        """Alpaca crypto snapshot. Accepts 'BTC-USD' or 'BTC/USD'; normalises
        internally to the 'BTC/USD' form Alpaca expects. Returns None when
        credentials are missing or the symbol isn't carried."""
        if not self._enabled():
            return None
        alp_sym = symbol.replace("-", "/").upper()
        url = f"{ALPACA_CRYPTO_BASE}/snapshots"
        params = {"symbols": alp_sym}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self._headers, params=params)
        if resp.status_code != 200:
            logger.warning(
                "Alpaca crypto snapshot %s -> %s: %s",
                symbol,
                resp.status_code,
                resp.text[:200],
            )
            return None
        snaps = (resp.json() or {}).get("snapshots") or {}
        data = snaps.get(alp_sym) or {}
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


    def _parse_dt(self, raw: str | None) -> datetime | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None

    def _to_order(self, data: dict) -> Order:
        return Order(
            id=str(data.get("id") or ""),
            client_order_id=data.get("client_order_id"),
            symbol=(data.get("symbol") or "").upper(),
            asset_class=data.get("asset_class"),
            side=data.get("side") or "buy",
            type=data.get("type") or data.get("order_type") or "market",
            time_in_force=data.get("time_in_force") or "day",
            qty=_f(data.get("qty")),
            filled_qty=_f(data.get("filled_qty")),
            limit_price=_of(data.get("limit_price")),
            stop_price=_of(data.get("stop_price")),
            filled_avg_price=_of(data.get("filled_avg_price")),
            status=data.get("status") or "unknown",
            submitted_at=self._parse_dt(data.get("submitted_at")),
            filled_at=self._parse_dt(data.get("filled_at")),
            canceled_at=self._parse_dt(data.get("canceled_at")),
            extended_hours=bool(data.get("extended_hours", False)),
        )

    async def list_orders(self, status: str = "all", limit: int = 50) -> List[Order]:
        if not self._enabled():
            return []
        url = f"{settings.alpaca_base_url.rstrip('/')}/v2/orders"
        params = {"status": status, "limit": limit, "direction": "desc"}
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, headers=self._headers, params=params)
        if resp.status_code != 200:
            logger.warning("Alpaca list_orders -> %s: %s", resp.status_code, resp.text[:200])
            return []
        return [self._to_order(item) for item in (resp.json() or [])]

    async def place_order(self, order: OrderRequest) -> Order:
        """POST /v2/orders. Lets Alpaca enforce validation (insufficient
        buying power, halted symbol, etc.) and propagates its error message
        back to the route layer.
        """
        if not self._enabled():
            raise RuntimeError("alpaca credentials not configured")
        url = f"{settings.alpaca_base_url.rstrip('/')}/v2/orders"
        payload: dict = {
            "symbol": order.symbol.upper(),
            "qty": str(order.qty),
            "side": order.side.lower(),
            "type": order.type.lower(),
            "time_in_force": order.time_in_force.lower(),
            "extended_hours": bool(order.extended_hours),
        }
        if order.limit_price is not None:
            payload["limit_price"] = str(order.limit_price)
        if order.stop_price is not None:
            payload["stop_price"] = str(order.stop_price)
        if order.client_order_id:
            payload["client_order_id"] = order.client_order_id
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=self._headers, json=payload)
        if resp.status_code not in (200, 201):
            detail = resp.text[:300]
            logger.warning("Alpaca place_order -> %s: %s", resp.status_code, detail)
            raise RuntimeError(f"alpaca rejected order ({resp.status_code}): {detail}")
        return self._to_order(resp.json())

    async def cancel_order(self, order_id: str) -> bool:
        if not self._enabled():
            return False
        url = f"{settings.alpaca_base_url.rstrip('/')}/v2/orders/{order_id}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(url, headers=self._headers)
        # 204 = canceled, 207 = multi-status (filled/canceled before delete).
        if resp.status_code in (204, 207, 200):
            return True
        logger.warning("Alpaca cancel_order %s -> %s: %s", order_id, resp.status_code, resp.text[:200])
        return False


_alpaca_singleton: AlpacaSource | None = None


def get_alpaca_source() -> AlpacaSource:
    """Shared process-wide AlpacaSource; routes should import this rather
    than constructing their own instance."""
    global _alpaca_singleton
    if _alpaca_singleton is None:
        _alpaca_singleton = AlpacaSource()
    return _alpaca_singleton
