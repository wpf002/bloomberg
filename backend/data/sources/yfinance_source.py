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
    FxQuote,
    OptionChain,
    OptionContract,
    Quote,
    QuoteHistoryPoint,
)

logger = logging.getLogger(__name__)


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
