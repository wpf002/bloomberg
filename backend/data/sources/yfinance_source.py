import asyncio
import logging
from datetime import datetime, timezone
from typing import List

import yfinance as yf

from ...core.bsm import bsm_greeks, year_fraction
from ...core.cache_utils import cached
from ...core.config import settings
from ...models.schemas import (
    CryptoQuote,
    EarningsEvent,
    Fundamentals,
    FxQuote,
    OptionChain,
    OptionContract,
    Quote,
    QuoteHistoryPoint,
)

logger = logging.getLogger(__name__)


def _safe_float(value) -> float | None:
    if value is None:
        return None
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return None
    if fv != fv or fv in (float("inf"), float("-inf")):
        return None
    return fv


class YFinanceSource:
    """Thin async wrapper around the synchronous yfinance SDK."""

    @cached("yf:quote", ttl=20, model=Quote)
    async def get_quote(self, symbol: str) -> Quote:
        return await asyncio.to_thread(self._quote_sync, symbol)

    async def get_quotes(self, symbols: List[str]) -> List[Quote]:
        return await asyncio.gather(*(self.get_quote(sym) for sym in symbols))

    @cached("yf:history", ttl=300, model=QuoteHistoryPoint)
    async def get_history(
        self,
        symbol: str,
        period: str = "1mo",
        interval: str = "1d",
    ) -> List[QuoteHistoryPoint]:
        return await asyncio.to_thread(self._history_sync, symbol, period, interval)

    @cached("yf:crypto", ttl=20, model=CryptoQuote)
    async def get_crypto_quote(self, symbol: str) -> CryptoQuote:
        return await asyncio.to_thread(self._crypto_sync, symbol)

    @cached("yf:fx", ttl=20, model=FxQuote)
    async def get_fx_quote(self, pair: str) -> FxQuote:
        return await asyncio.to_thread(self._fx_sync, pair)

    @cached("yf:options", ttl=120, model=OptionChain)
    async def get_option_chain(self, symbol: str, expiration: str | None = None) -> OptionChain:
        return await asyncio.to_thread(self._option_chain_sync, symbol, expiration)

    @cached("yf:fundamentals", ttl=3600, model=Fundamentals)
    async def get_fundamentals(self, symbol: str) -> Fundamentals:
        return await asyncio.to_thread(self._fundamentals_sync, symbol)

    @cached("yf:earnings", ttl=3600, model=EarningsEvent)
    async def get_upcoming_earnings(self, symbol: str, limit: int = 8) -> List[EarningsEvent]:
        return await asyncio.to_thread(self._earnings_sync, symbol, limit)

    def _quote_sync(self, symbol: str) -> Quote:
        ticker = yf.Ticker(symbol)
        fast = ticker.fast_info
        price = float(fast.get("last_price") or fast.get("regular_market_price") or 0.0)
        prev = float(fast.get("previous_close") or price)
        change = price - prev
        change_pct = (change / prev * 100.0) if prev else 0.0
        return Quote(
            symbol=symbol.upper(),
            price=price,
            change=change,
            change_percent=change_pct,
            volume=int(fast.get("last_volume") or 0),
            day_high=float(fast.get("day_high") or 0.0) or None,
            day_low=float(fast.get("day_low") or 0.0) or None,
            previous_close=prev,
            market_cap=float(fast.get("market_cap") or 0.0) or None,
            timestamp=datetime.now(timezone.utc),
        )

    def _history_sync(
        self, symbol: str, period: str, interval: str
    ) -> List[QuoteHistoryPoint]:
        frame = yf.Ticker(symbol).history(period=period, interval=interval)
        points: List[QuoteHistoryPoint] = []
        for ts, row in frame.iterrows():
            points.append(
                QuoteHistoryPoint(
                    timestamp=ts.to_pydatetime(),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                )
            )
        return points

    def _fundamentals_sync(self, symbol: str) -> Fundamentals:
        ticker = yf.Ticker(symbol)
        info: dict = {}
        try:
            info = ticker.get_info() or {}
        except Exception as exc:
            logger.debug("yfinance get_info(%s) failed: %s", symbol, exc)

        def _f(key: str) -> float | None:
            value = info.get(key)
            if value in (None, "Infinity", "-Infinity"):
                return None
            try:
                fv = float(value)
                if fv != fv or fv in (float("inf"), float("-inf")):
                    return None
                return fv
            except (TypeError, ValueError):
                return None

        def _i(key: str) -> int | None:
            value = info.get(key)
            try:
                return int(value) if value is not None else None
            except (TypeError, ValueError):
                return None

        return Fundamentals(
            symbol=symbol.upper(),
            name=info.get("longName") or info.get("shortName"),
            sector=info.get("sector"),
            industry=info.get("industry"),
            description=info.get("longBusinessSummary"),
            country=info.get("country"),
            employees=_i("fullTimeEmployees"),
            website=info.get("website"),
            market_cap=_f("marketCap"),
            enterprise_value=_f("enterpriseValue"),
            shares_outstanding=_f("sharesOutstanding"),
            float_shares=_f("floatShares"),
            pe_ratio=_f("trailingPE"),
            forward_pe=_f("forwardPE"),
            peg_ratio=_f("pegRatio"),
            price_to_book=_f("priceToBook"),
            price_to_sales=_f("priceToSalesTrailing12Months"),
            ev_to_ebitda=_f("enterpriseToEbitda"),
            dividend_yield=_f("dividendYield"),
            payout_ratio=_f("payoutRatio"),
            beta=_f("beta"),
            fifty_two_week_high=_f("fiftyTwoWeekHigh"),
            fifty_two_week_low=_f("fiftyTwoWeekLow"),
            revenue_ttm=_f("totalRevenue"),
            revenue_growth_yoy=_f("revenueGrowth"),
            gross_margin=_f("grossMargins"),
            operating_margin=_f("operatingMargins"),
            profit_margin=_f("profitMargins"),
            net_income_ttm=_f("netIncomeToCommon"),
            earnings_growth_yoy=_f("earningsGrowth"),
            eps_ttm=_f("trailingEps"),
            free_cash_flow_ttm=_f("freeCashflow"),
            debt_to_equity=_f("debtToEquity"),
            return_on_equity=_f("returnOnEquity"),
            return_on_assets=_f("returnOnAssets"),
            analyst_target=_f("targetMeanPrice"),
            analyst_recommendation=info.get("recommendationKey"),
            currency=info.get("currency"),
            exchange=info.get("exchange"),
            timestamp=datetime.now(timezone.utc),
        )

    def _earnings_sync(self, symbol: str, limit: int) -> List[EarningsEvent]:
        ticker = yf.Ticker(symbol)
        events: List[EarningsEvent] = []
        try:
            frame = ticker.get_earnings_dates(limit=limit)
        except Exception as exc:
            logger.debug("yfinance get_earnings_dates(%s) failed: %s", symbol, exc)
            return events
        if frame is None or frame.empty:
            return events
        name = None
        try:
            info = ticker.fast_info
            name = None  # fast_info is a dict-like without longName
        except Exception:
            pass
        for ts, row in frame.iterrows():
            try:
                event_date = ts.date() if hasattr(ts, "date") else datetime.fromisoformat(str(ts)).date()
            except Exception:
                continue
            events.append(
                EarningsEvent(
                    symbol=symbol.upper(),
                    name=name,
                    event_date=event_date,
                    when=str(row.get("Event Type") or "").strip() or None,
                    eps_estimate=_safe_float(row.get("EPS Estimate")),
                    eps_actual=_safe_float(row.get("Reported EPS")),
                    eps_surprise_percent=_safe_float(row.get("Surprise(%)")),
                )
            )
        events.sort(key=lambda e: e.event_date)
        return events

    def _fx_sync(self, pair: str) -> FxQuote:
        yf_symbol = pair if pair.endswith("=X") else f"{pair.replace('/', '')}=X"
        ticker = yf.Ticker(yf_symbol)
        fast = ticker.fast_info
        price = float(fast.get("last_price") or 0.0)
        prev = float(fast.get("previous_close") or price)
        change = price - prev
        change_pct = (change / prev * 100.0) if prev else 0.0
        base, quote = (pair[:3], pair[3:6]) if len(pair.replace("/", "")) >= 6 else (pair, "USD")
        return FxQuote(
            pair=pair.upper(),
            base=base.upper(),
            quote=quote.upper() or "USD",
            price=price,
            change=change,
            change_percent=change_pct,
            timestamp=datetime.now(timezone.utc),
        )

    def _option_chain_sync(self, symbol: str, expiration: str | None) -> OptionChain:
        ticker = yf.Ticker(symbol)
        expirations: List[str] = list(ticker.options) if ticker.options else []
        if not expirations:
            return OptionChain(symbol=symbol.upper(), expirations=[], calls=[], puts=[])
        target = expiration if expiration in expirations else expirations[0]
        chain = ticker.option_chain(target)
        underlying_price = float(ticker.fast_info.get("last_price") or 0.0)
        t_years = year_fraction(target)
        rate = settings.risk_free_rate

        def _rows(frame, option_type: str) -> List[OptionContract]:
            is_call = option_type == "call"
            contracts: List[OptionContract] = []
            for _, row in frame.iterrows():
                strike = float(row.get("strike", 0.0) or 0.0)
                iv = float(row.get("impliedVolatility", 0.0) or 0.0)
                greeks = bsm_greeks(underlying_price, strike, t_years, rate, iv, is_call) \
                    if underlying_price and strike and iv > 0 else None
                moneyness = (underlying_price / strike) if (underlying_price and strike) else None
                contracts.append(
                    OptionContract(
                        contract_symbol=str(row.get("contractSymbol", "")),
                        option_type=option_type,
                        strike=strike,
                        expiration=target,
                        bid=float(row.get("bid", 0.0) or 0.0),
                        ask=float(row.get("ask", 0.0) or 0.0),
                        last=float(row.get("lastPrice", 0.0) or 0.0),
                        volume=int(row.get("volume", 0) or 0),
                        open_interest=int(row.get("openInterest", 0) or 0),
                        implied_volatility=iv,
                        in_the_money=bool(row.get("inTheMoney", False)),
                        delta=greeks.delta if greeks else None,
                        gamma=greeks.gamma if greeks else None,
                        vega=greeks.vega if greeks else None,
                        theta=greeks.theta if greeks else None,
                        rho=greeks.rho if greeks else None,
                        moneyness=moneyness,
                    )
                )
            return contracts

        return OptionChain(
            symbol=symbol.upper(),
            underlying_price=underlying_price,
            selected_expiration=target,
            expirations=expirations,
            calls=_rows(chain.calls, "call"),
            puts=_rows(chain.puts, "put"),
        )

    def _crypto_sync(self, symbol: str) -> CryptoQuote:
        yf_symbol = symbol if "-" in symbol else f"{symbol}-USD"
        ticker = yf.Ticker(yf_symbol)
        fast = ticker.fast_info
        price = float(fast.get("last_price") or 0.0)
        prev = float(fast.get("previous_close") or price)
        change = price - prev
        change_pct = (change / prev * 100.0) if prev else 0.0
        return CryptoQuote(
            symbol=yf_symbol.upper(),
            price=price,
            change_24h=change,
            change_percent_24h=change_pct,
            volume_24h=float(fast.get("last_volume") or 0.0),
            market_cap=float(fast.get("market_cap") or 0.0) or None,
            timestamp=datetime.now(timezone.utc),
        )
