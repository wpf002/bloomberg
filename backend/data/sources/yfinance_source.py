import asyncio
import logging
from datetime import datetime, timezone
from typing import List

import yfinance as yf

from ...models.schemas import CryptoQuote, Quote, QuoteHistoryPoint

logger = logging.getLogger(__name__)


class YFinanceSource:
    """Thin async wrapper around the synchronous yfinance SDK."""

    async def get_quote(self, symbol: str) -> Quote:
        return await asyncio.to_thread(self._quote_sync, symbol)

    async def get_quotes(self, symbols: List[str]) -> List[Quote]:
        return await asyncio.gather(*(self.get_quote(sym) for sym in symbols))

    async def get_history(
        self,
        symbol: str,
        period: str = "1mo",
        interval: str = "1d",
    ) -> List[QuoteHistoryPoint]:
        return await asyncio.to_thread(self._history_sync, symbol, period, interval)

    async def get_crypto_quote(self, symbol: str) -> CryptoQuote:
        return await asyncio.to_thread(self._crypto_sync, symbol)

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
