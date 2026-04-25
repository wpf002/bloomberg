"""Continuous futures + term structure via yfinance.

We carry a small curated set of physical/financial commodity roots:
WTI crude (CL), gold (GC), natural gas (NG), corn (ZC), soybeans (ZS).
Each curve is built by querying:
  - The continuous front-month ticker (`CL=F`) for "spot" + change.
  - A grid of dated contracts (`CLM26.NYM`, `CLN26.NYM`, ...) using the
    standard CME month codes for the next ~12 expirations.

Some contracts in the grid will return empty data (illiquid back months,
holiday dates, exchange suspensions). We filter those out so the curve
panel only renders contracts that actually have a price.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from typing import Iterable

import yfinance as yf

from ...core.cache_utils import cached
from ...models.schemas import FuturesContract, FuturesCurve
from .fred_source import FredSource

logger = logging.getLogger(__name__)

# FRED series for spot/front-month commodity prices — used as a fallback
# whenever yfinance returns nothing (Yahoo periodically blocks the
# scraper-style endpoints, leaving fast_info / history empty).
FRED_SPOT_SERIES: dict[str, str] = {
    "CL": "DCOILWTICO",       # WTI crude, daily
    "GC": "GOLDAMGBD228NLBM", # London PM gold fix, daily
    "NG": "DHHNGSP",          # Henry Hub natural gas spot, daily
    # FRED doesn't carry a daily corn/soybean series at the same cadence;
    # ZC and ZS fall back to whatever yfinance gives us (often nothing —
    # the panel renders "no data" for those rather than fabricating).
}

CME_MONTH_CODES = {
    1: "F", 2: "G", 3: "H", 4: "J", 5: "K", 6: "M",
    7: "N", 8: "Q", 9: "U", 10: "V", 11: "X", 12: "Z",
}

ROOTS: dict[str, dict] = {
    "CL": {"label": "WTI Crude Oil",  "exchange_suffix": ".NYM", "front": "CL=F"},
    "GC": {"label": "Gold",            "exchange_suffix": ".CMX", "front": "GC=F"},
    "NG": {"label": "Natural Gas",    "exchange_suffix": ".NYM", "front": "NG=F"},
    "ZC": {"label": "Corn",            "exchange_suffix": ".CBT", "front": "ZC=F"},
    "ZS": {"label": "Soybeans",       "exchange_suffix": ".CBT", "front": "ZS=F"},
}


def _next_contract_months(count: int = 12) -> list[tuple[int, int]]:
    today = date.today()
    out: list[tuple[int, int]] = []
    y, m = today.year, today.month
    for _ in range(count):
        out.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def _contract_ticker(root: str, year: int, month: int, suffix: str) -> str:
    code = CME_MONTH_CODES[month]
    yy = year % 100
    return f"{root}{code}{yy:02d}{suffix}"


def _fetch_single_sync(ticker: str) -> tuple[float, float, float, int] | None:
    """Pull last + previous close + volume for one ticker via yfinance.

    Tries `fast_info` first (cheap), falls back to `history(period='5d')`
    (more reliable when Yahoo blocks the fast endpoints). Returns
    `(price, change, change_pct, volume)` or None when the ticker has no
    recent data (illiquid back-month, deprecated symbol, Yahoo throttling).
    """
    try:
        tk = yf.Ticker(ticker)
        try:
            fast = tk.fast_info
            price = float(fast.get("last_price") or 0.0)
            prev = float(fast.get("previous_close") or 0.0)
            volume = int(fast.get("last_volume") or 0)
        except Exception:
            price = prev = 0.0
            volume = 0
        if price <= 0 or prev <= 0:
            try:
                hist = tk.history(period="5d", auto_adjust=False)
                if hist is not None and not hist.empty and "Close" in hist.columns:
                    closes = hist["Close"].dropna()
                    if len(closes) >= 1:
                        price = float(closes.iloc[-1]) if price <= 0 else price
                    if len(closes) >= 2:
                        prev = float(closes.iloc[-2]) if prev <= 0 else prev
                    if "Volume" in hist.columns and volume == 0:
                        try:
                            volume = int(hist["Volume"].dropna().iloc[-1])
                        except Exception:
                            volume = 0
            except Exception as exc:
                logger.debug("futures history(%s) failed: %s", ticker, exc)
        if price <= 0:
            return None
        if prev <= 0:
            prev = price
        change = price - prev
        change_pct = (change / prev * 100.0) if prev else 0.0
        return price, change, change_pct, volume
    except Exception as exc:
        logger.debug("futures fetch %s failed: %s", ticker, exc)
        return None


class FuturesSource:
    @cached("futures:curve", ttl=300, model=FuturesCurve)
    async def get_curve(self, root: str) -> FuturesCurve:
        meta = ROOTS.get(root.upper())
        if not meta:
            return FuturesCurve(root=root.upper(), label="(unknown root)", contracts=[])
        # Front-month continuous
        front = await asyncio.to_thread(_fetch_single_sync, meta["front"])
        front_price = front[0] if front else None

        # Build grid of next-12 dated contracts
        targets: list[tuple[str, str]] = []
        for (y, m) in _next_contract_months(12):
            ticker = _contract_ticker(root.upper(), y, m, meta["exchange_suffix"])
            iso = date(y, m, 1).isoformat()
            targets.append((ticker, iso))

        # Run them in parallel — yfinance is thread-bound so wrap each in
        # asyncio.to_thread.
        results = await asyncio.gather(
            *(asyncio.to_thread(_fetch_single_sync, t) for t, _ in targets),
            return_exceptions=False,
        )

        contracts: list[FuturesContract] = []
        for (ticker, iso), data in zip(targets, results):
            if not data:
                continue
            price, change, change_pct, volume = data
            contracts.append(
                FuturesContract(
                    contract_symbol=ticker,
                    expiration=iso,
                    price=price,
                    change=change,
                    change_percent=change_pct,
                    volume=volume,
                )
            )
        return FuturesCurve(
            root=root.upper(),
            label=meta["label"],
            front_month_price=front_price,
            contracts=contracts,
            timestamp=datetime.now(timezone.utc),
        )

    @cached("futures:dashboard", ttl=300, model=FuturesContract)
    async def dashboard(self) -> list[FuturesContract]:
        """Front-month snapshot of every supported root — used by the
        Futures panel as the top-line strip without firing N curve calls.

        Falls back to FRED daily-spot series for CL/GC/NG when yfinance
        returns empty (Yahoo periodically blocks the front-month tickers).
        """
        results = await asyncio.gather(
            *(asyncio.to_thread(_fetch_single_sync, ROOTS[r]["front"]) for r in ROOTS),
            return_exceptions=False,
        )
        out: list[FuturesContract] = []
        missing: list[str] = []
        for root, data in zip(ROOTS.keys(), results):
            if not data:
                missing.append(root)
                continue
            price, change, change_pct, volume = data
            out.append(
                FuturesContract(
                    contract_symbol=ROOTS[root]["front"],
                    expiration=None,
                    price=price,
                    change=change,
                    change_percent=change_pct,
                    volume=volume,
                )
            )

        # FRED fallback for the front-month strip. We treat the most-recent
        # daily observation as "spot" and the prior day as "previous close".
        if missing:
            fred = FredSource()
            for root in list(missing):
                series_id = FRED_SPOT_SERIES.get(root)
                if not series_id:
                    continue
                try:
                    series = await fred.get_series(series_id, limit=5)
                except Exception as exc:
                    logger.debug("futures FRED fallback %s/%s failed: %s", root, series_id, exc)
                    continue
                obs = series.observations or []
                if not obs:
                    continue
                last = obs[-1]
                prev = obs[-2] if len(obs) >= 2 else last
                price = float(last.value)
                prev_price = float(prev.value) or price
                change = price - prev_price
                change_pct = (change / prev_price * 100.0) if prev_price else 0.0
                out.append(
                    FuturesContract(
                        contract_symbol=f"{root}=F (FRED:{series_id})",
                        expiration=None,
                        price=price,
                        change=change,
                        change_percent=change_pct,
                        volume=0,
                    )
                )
        return out
