import logging
from datetime import datetime, timedelta, timezone
from typing import List

import httpx

from ...core.bsm import bsm_greeks, year_fraction
from ...core.cache_utils import cached
from ...core.config import settings
from ..normalizer import get_normalizer
from ...models.schemas import (
    Account,
    NewsItem,
    OptionChain,
    OptionContract,
    Order,
    OrderRequest,
    Position,
    Quote,
    QuoteHistoryPoint,
)

logger = logging.getLogger(__name__)

ALPACA_DATA_BASE = "https://data.alpaca.markets/v2"
ALPACA_NEWS_BASE = "https://data.alpaca.markets/v1beta1/news"
ALPACA_CRYPTO_BASE = "https://data.alpaca.markets/v1beta3/crypto/us"
ALPACA_OPTIONS_BASE = "https://data.alpaca.markets/v1beta1/options"


def _pick_default_expiration(expirations: list[str]) -> str:
    """First expiration ≥ 7 days out. Zero/near-zero DTE chains have no
    meaningful IV (the indicative feed reports 0%) and the smile chart
    flat-lines, which is what the OPT panel was rendering when it
    defaulted to today's expiry. Falls back to the soonest expiration if
    the symbol only carries weeklies that are all close-in."""
    today = datetime.now(timezone.utc).date()
    cutoff = today + timedelta(days=7)
    for exp in expirations:
        try:
            d = datetime.strptime(exp, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d >= cutoff:
            return exp
    return expirations[0]


def _parse_occ_symbol(symbol: str) -> tuple[str, str, float] | None:
    """Decode an OCC-style option symbol like AAPL250117C00150000 into
    (expiration ISO, type, strike). Returns None on malformed input.

    OCC layout (right-aligned): 6 chars YYMMDD, 1 char C|P, 8 chars
    (strike × 1000) zero-padded. Anything before that is the root.
    """
    if not symbol or len(symbol) < 16:
        return None
    body = symbol[-15:]
    yymmdd = body[:6]
    typ = body[6]
    strike_raw = body[7:]
    try:
        year = 2000 + int(yymmdd[0:2])
        month = int(yymmdd[2:4])
        day = int(yymmdd[4:6])
        strike = int(strike_raw) / 1000.0
    except ValueError:
        return None
    if typ not in ("C", "P"):
        return None
    return (f"{year:04d}-{month:02d}-{day:02d}", "call" if typ == "C" else "put", strike)

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
        quote = Quote(
            symbol=symbol.upper(),
            price=mid,
            timestamp=datetime.now(timezone.utc),
        )
        get_normalizer().from_quote("alpaca", quote)
        return quote

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
        get_normalizer().from_bars("alpaca", symbol.upper(), out)
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

        quote = Quote(
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
        get_normalizer().from_quote("alpaca", quote)
        return quote

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

        quote = Quote(
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
        get_normalizer().from_quote("alpaca", quote)
        return quote

    @cached("alpaca:assets_active", ttl=86400, model=None)
    async def list_active_assets(self) -> list[dict]:
        """Snapshot of every active US-equity / ETF asset Alpaca carries.
        ~12k rows; cache for a day. Used by /api/symbols/search to
        autocomplete tickers in the command bar.
        """
        if not self._enabled():
            return []
        url = f"{settings.alpaca_base_url.rstrip('/')}/v2/assets"
        params = {"status": "active", "asset_class": "us_equity"}
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url, headers=self._headers, params=params)
        if resp.status_code != 200:
            logger.warning("Alpaca assets -> %s: %s", resp.status_code, resp.text[:200])
            return []
        items = resp.json() or []
        # Trim to fields the frontend cares about so the cache stays small.
        return [
            {
                "symbol": (it.get("symbol") or "").upper(),
                "name": it.get("name") or "",
                "exchange": it.get("exchange") or "",
                "tradable": bool(it.get("tradable", False)),
            }
            for it in items
            if it.get("symbol")
        ]

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
        legs_raw = data.get("legs") or []
        legs = [self._to_order(leg) for leg in legs_raw if isinstance(leg, dict)]
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
            order_class=data.get("order_class") or None,
            legs=legs,
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

        Supports `simple` (default) plus the bracket/OCO/OTO order classes:
        - bracket: entry + take-profit + stop-loss in one submission
        - oco:     two paired exit legs only (no entry)
        - oto:     entry + one of {take-profit, stop-loss}
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

        order_class = (order.order_class or "simple").lower()
        if order_class != "simple":
            payload["order_class"] = order_class
            tp: dict = {}
            sl: dict = {}
            if order.take_profit_limit_price is not None:
                tp["limit_price"] = str(order.take_profit_limit_price)
            if order.stop_loss_stop_price is not None:
                sl["stop_price"] = str(order.stop_loss_stop_price)
            if order.stop_loss_limit_price is not None:
                sl["limit_price"] = str(order.stop_loss_limit_price)
            if order_class == "bracket":
                payload["take_profit"] = tp
                payload["stop_loss"] = sl
            elif order_class == "oco":
                payload["take_profit"] = tp
                payload["stop_loss"] = sl
            elif order_class == "oto":
                if tp:
                    payload["take_profit"] = tp
                if sl:
                    payload["stop_loss"] = sl

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, headers=self._headers, json=payload)
        if resp.status_code not in (200, 201):
            detail = resp.text[:300]
            logger.warning("Alpaca place_order -> %s: %s", resp.status_code, detail)
            raise RuntimeError(f"alpaca rejected order ({resp.status_code}): {detail}")
        return self._to_order(resp.json())

    # ── options ──────────────────────────────────────────────────────────

    @cached("alpaca:opt_exps", ttl=300, model=None)
    async def list_option_expirations(self, symbol: str) -> list[str]:
        """Active future expiration dates for `symbol`'s options. Returns an
        empty list when Alpaca doesn't carry the underlying (most non-US,
        and any symbol the account isn't entitled to)."""
        if not self._enabled():
            return []
        # /v2/options/contracts lives on the trading host (paper-api.alpaca.markets
        # in dev, api.alpaca.markets in live) — same host as orders/positions.
        url = f"{settings.alpaca_base_url.rstrip('/')}/v2/options/contracts"
        today = datetime.now(timezone.utc).date().isoformat()
        params: dict = {
            "underlying_symbols": symbol.upper(),
            "status": "active",
            "expiration_date_gte": today,
            "limit": 10000,
        }
        seen: set[str] = set()
        page_token: str | None = None
        async with httpx.AsyncClient(timeout=15.0) as client:
            for _ in range(5):  # cap pagination — even AAPL fits in 1-2 pages
                if page_token:
                    params["page_token"] = page_token
                resp = await client.get(url, headers=self._headers, params=params)
                if resp.status_code != 200:
                    logger.warning(
                        "Alpaca options contracts %s -> %s: %s",
                        symbol, resp.status_code, resp.text[:200],
                    )
                    return []
                payload = resp.json() or {}
                for item in payload.get("option_contracts") or []:
                    exp = item.get("expiration_date")
                    if isinstance(exp, str):
                        seen.add(exp)
                page_token = payload.get("next_page_token")
                if not page_token:
                    break
        return sorted(seen)

    @cached("alpaca:opt_chain", ttl=30, model=OptionChain)
    async def get_option_chain(
        self,
        symbol: str,
        expiration: str | None = None,
    ) -> OptionChain:
        """Snapshot the chain for one expiration. We default to the nearest
        future expiration when none is specified. The free `feed=indicative`
        is delayed but covers the same contracts as the paid OPRA feed.

        Returns an empty chain (with `expirations=[]`) when Alpaca returns
        no data — the route layer falls through to yfinance in that case.
        """
        if not self._enabled():
            return OptionChain(symbol=symbol.upper())
        sym = symbol.upper()
        try:
            expirations = await self.list_option_expirations(sym)
        except Exception as exc:
            logger.warning("alpaca expirations failed for %s: %s", sym, exc)
            expirations = []
        if not expirations:
            return OptionChain(symbol=sym)
        target = expiration if expiration in expirations else _pick_default_expiration(expirations)

        # Pull the underlying spot for moneyness/Greeks (fast — already cached
        # by get_stock_quote).
        spot: float | None = None
        try:
            quote = await self.get_stock_quote(sym)
            spot = quote.price if quote else None
        except Exception:
            spot = None

        url = f"{ALPACA_OPTIONS_BASE}/snapshots/{sym}"
        params: dict = {
            "feed": "indicative",
            "expiration_date": target,
            "limit": 1000,
        }
        snapshots: dict = {}
        page_token: str | None = None
        async with httpx.AsyncClient(timeout=15.0) as client:
            for _ in range(3):
                if page_token:
                    params["page_token"] = page_token
                resp = await client.get(url, headers=self._headers, params=params)
                if resp.status_code != 200:
                    logger.warning(
                        "Alpaca options snapshots %s -> %s: %s",
                        sym, resp.status_code, resp.text[:200],
                    )
                    return OptionChain(symbol=sym, expirations=expirations)
                payload = resp.json() or {}
                snapshots.update(payload.get("snapshots") or {})
                page_token = payload.get("next_page_token")
                if not page_token:
                    break

        if not snapshots:
            return OptionChain(symbol=sym, expirations=expirations, selected_expiration=target)

        rate = settings.risk_free_rate
        t_years = year_fraction(target)
        calls: list[OptionContract] = []
        puts: list[OptionContract] = []
        for contract_symbol, snap in snapshots.items():
            decoded = _parse_occ_symbol(contract_symbol)
            if not decoded:
                continue
            _, option_type, strike = decoded
            quote = (snap or {}).get("latestQuote") or {}
            trade = (snap or {}).get("latestTrade") or {}
            iv = _f((snap or {}).get("impliedVolatility")) or 0.0
            greeks = (snap or {}).get("greeks") or {}
            bid = _f(quote.get("bp"))
            ask = _f(quote.get("ap"))
            last = _f(trade.get("p"))
            volume = int(_f(trade.get("s")) or 0)
            # Alpaca's snapshot doesn't include open_interest reliably; some
            # responses do, leave 0 when absent.
            open_interest = int(_f((snap or {}).get("openInterest")) or 0)

            # Greeks: prefer Alpaca's served Greeks; fall back to BSM when the
            # snapshot omits them (common on illiquid contracts).
            delta = _of(greeks.get("delta"))
            gamma = _of(greeks.get("gamma"))
            vega = _of(greeks.get("vega"))
            theta = _of(greeks.get("theta"))
            rho = _of(greeks.get("rho"))
            if (delta is None or gamma is None) and spot and strike and iv > 0:
                bsm = bsm_greeks(spot, strike, t_years, rate, iv, option_type == "call")
                delta = delta if delta is not None else bsm.delta
                gamma = gamma if gamma is not None else bsm.gamma
                vega = vega if vega is not None else bsm.vega
                theta = theta if theta is not None else bsm.theta
                rho = rho if rho is not None else bsm.rho

            moneyness = (spot / strike) if (spot and strike) else None
            in_the_money = bool(
                spot
                and (
                    (option_type == "call" and spot > strike)
                    or (option_type == "put" and spot < strike)
                )
            )
            contract = OptionContract(
                contract_symbol=contract_symbol,
                option_type=option_type,
                strike=strike,
                expiration=target,
                bid=bid or 0.0,
                ask=ask or 0.0,
                last=last or 0.0,
                volume=volume,
                open_interest=open_interest,
                implied_volatility=iv,
                in_the_money=in_the_money,
                delta=delta,
                gamma=gamma,
                vega=vega,
                theta=theta,
                rho=rho,
                moneyness=moneyness,
            )
            (calls if option_type == "call" else puts).append(contract)

        calls.sort(key=lambda c: c.strike)
        puts.sort(key=lambda c: c.strike)
        return OptionChain(
            symbol=sym,
            underlying_price=spot,
            selected_expiration=target,
            expirations=expirations,
            calls=calls,
            puts=puts,
        )

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
