"""Futures: live data via Massive (Polygon futures API) when the plan is
entitled, falling back to FRED daily spot for crude + nat gas.

Massive is a Polygon-compatible client; Polygon offers a Futures API. When
the configured Massive key is entitled to futures, we get live front-month
prices AND a real term-structure curve (multiple contracts per root). When
it isn't (or the call fails), we fall back to FRED daily spot for the two
roots a free public source covers (CL, NG). Every Massive call is wrapped so
a missing entitlement degrades gracefully rather than erroring.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from ...core.cache_utils import cached
from ...models.schemas import FuturesContract, FuturesCurve
from .fred_source import FredSource
from .massive_source import MassiveSource

logger = logging.getLogger(__name__)

# `product` is the Polygon futures product code (Massive path). `series` is the
# FRED fallback series (only crude + nat gas have a free public daily source).
ROOTS: dict[str, dict] = {
    "CL": {"label": "WTI Crude Oil", "product": "CL", "series": "DCOILWTICO"},
    "NG": {"label": "Natural Gas",   "product": "NG", "series": "DHHNGSP"},
    "GC": {"label": "Gold",          "product": "GC"},
    "ES": {"label": "S&P 500 E-mini", "product": "ES"},
    "ZC": {"label": "Corn",          "product": "ZC"},
    "ZS": {"label": "Soybeans",      "product": "ZS"},
}


def _pct(last: float, prev: float) -> tuple[float, float]:
    change = last - prev
    return change, (change / prev * 100.0) if prev else 0.0


async def _fred_quote(root: str) -> tuple[float, float, float] | None:
    """(price, change, change_pct) from FRED daily series, or None."""
    meta = ROOTS.get(root)
    if not meta or "series" not in meta:
        return None
    try:
        series = await FredSource().get_series(meta["series"], limit=5)
    except Exception as exc:
        logger.debug("FRED %s/%s failed: %s", root, meta["series"], exc)
        return None
    obs = series.observations or []
    if not obs:
        return None
    last = float(obs[-1].value)
    prev = float(obs[-2].value) if len(obs) >= 2 else last
    change, change_pct = _pct(last, prev or last)
    return last, change, change_pct


class FuturesSource:
    @cached("futures:dashboard", ttl=300, model=FuturesContract)
    async def dashboard(self) -> list[FuturesContract]:
        """Front-month snapshot per root — Massive (live) first, FRED fallback."""
        massive = MassiveSource()
        out = await asyncio.gather(*(self._dash_one(massive, r) for r in ROOTS))
        return [c for c in out if c is not None]

    async def _dash_one(self, massive: MassiveSource, root: str) -> FuturesContract | None:
        meta = ROOTS[root]
        # 1) Massive / Polygon futures (live front month).
        if massive.configured:
            try:
                contracts = await massive.futures_contracts(meta["product"], limit=1)
                if contracts:
                    front = contracts[0]
                    closes = await massive.futures_recent_closes(front["ticker"], limit=2)
                    if closes:
                        last = closes[0]
                        prev = closes[1] if len(closes) > 1 else last
                        change, change_pct = _pct(last, prev)
                        return FuturesContract(
                            contract_symbol=f"{root} · {front['ticker']}",
                            expiration=front.get("expiration"),
                            price=last, change=change, change_percent=change_pct, volume=0,
                        )
            except Exception as exc:
                logger.debug("massive futures dash %s failed: %s", root, exc)
        # 2) FRED daily spot (CL / NG only).
        fred = await _fred_quote(root)
        if fred:
            price, change, change_pct = fred
            return FuturesContract(
                contract_symbol=f"{root}=F (FRED:{meta['series']})",
                expiration=None, price=price, change=change, change_percent=change_pct, volume=0,
            )
        return None

    @cached("futures:curve", ttl=300, model=FuturesCurve)
    async def get_curve(self, root: str) -> FuturesCurve:
        root = root.upper()
        meta = ROOTS.get(root)
        if not meta:
            return FuturesCurve(root=root, label="(unsupported root)", contracts=[])
        massive = MassiveSource()
        # 1) Massive / Polygon futures — a real term-structure curve.
        if massive.configured:
            try:
                contracts = await massive.futures_contracts(meta["product"], limit=12)
                points: list[FuturesContract] = []
                for c in contracts:
                    closes = await massive.futures_recent_closes(c["ticker"], limit=2)
                    if not closes:
                        continue
                    last = closes[0]
                    prev = closes[1] if len(closes) > 1 else last
                    change, change_pct = _pct(last, prev)
                    points.append(FuturesContract(
                        contract_symbol=c["ticker"], expiration=c.get("expiration"),
                        price=last, change=change, change_percent=change_pct, volume=0,
                    ))
                if points:
                    return FuturesCurve(
                        root=root, label=meta["label"], front_month_price=points[0].price,
                        contracts=points, timestamp=datetime.now(timezone.utc),
                    )
            except Exception as exc:
                logger.debug("massive futures curve %s failed: %s", root, exc)
        # 2) FRED single front-month point (CL / NG only).
        front = await _fred_quote(root)
        contracts: list[FuturesContract] = []
        if front:
            price, change, change_pct = front
            contracts.append(FuturesContract(
                contract_symbol=f"{root}=F (FRED:{meta.get('series')})",
                expiration=None, price=price, change=change, change_percent=change_pct, volume=0,
            ))
        return FuturesCurve(
            root=root, label=meta["label"],
            front_month_price=front[0] if front else None,
            contracts=contracts, timestamp=datetime.now(timezone.utc),
        )
