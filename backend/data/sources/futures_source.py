"""Continuous futures via FRED.

We carry front-month spot prices for WTI crude (CL) and natural gas (NG)
via FRED daily series. Gold, corn, and soybeans need a paid futures
data feed we don't carry; the panel renders only the contracts we can
prove from a reliable public source.

Term-structure curves (back-month contracts) require a paid futures data
feed (CME, Refinitiv, etc.). The previous yfinance-based curve was
unreliable and is gone with the rest of the Yahoo deps; the curve
endpoint now returns the front-month price as a single point so the
panel still renders without error.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Iterable

from ...core.cache_utils import cached
from ...models.schemas import FuturesContract, FuturesCurve
from .fred_source import FredSource

logger = logging.getLogger(__name__)

# FRED series for front-month spot prices.
ROOTS: dict[str, dict] = {
    "CL": {"label": "WTI Crude Oil",  "series": "DCOILWTICO",       "front": "CL=F"},
    "NG": {"label": "Natural Gas",    "series": "DHHNGSP",          "front": "NG=F"},
    # GC / ZC / ZS need a paid feed; see module docstring.
}


async def _fred_quote(root: str) -> tuple[float, float, float] | None:
    """Pull last + previous daily close from FRED. Returns
    (price, change, change_pct) or None when the series is empty."""
    meta = ROOTS.get(root)
    if not meta:
        return None
    fred = FredSource()
    try:
        series = await fred.get_series(meta["series"], limit=5)
    except Exception as exc:
        logger.debug("FRED %s/%s failed: %s", root, meta["series"], exc)
        return None
    obs = series.observations or []
    if not obs:
        return None
    last = obs[-1]
    prev = obs[-2] if len(obs) >= 2 else last
    price = float(last.value)
    prev_price = float(prev.value) or price
    change = price - prev_price
    change_pct = (change / prev_price * 100.0) if prev_price else 0.0
    return price, change, change_pct


class FuturesSource:
    @cached("futures:dashboard", ttl=300, model=FuturesContract)
    async def dashboard(self) -> list[FuturesContract]:
        """Front-month snapshot of every supported root via FRED."""
        results = await asyncio.gather(
            *(_fred_quote(root) for root in ROOTS),
            return_exceptions=False,
        )
        out: list[FuturesContract] = []
        for root, data in zip(ROOTS.keys(), results):
            if not data:
                continue
            price, change, change_pct = data
            out.append(
                FuturesContract(
                    contract_symbol=f"{root}=F (FRED:{ROOTS[root]['series']})",
                    expiration=None,
                    price=price,
                    change=change,
                    change_percent=change_pct,
                    volume=0,
                )
            )
        return out

    @cached("futures:curve", ttl=300, model=FuturesCurve)
    async def get_curve(self, root: str) -> FuturesCurve:
        """Single front-month point per root — back-month curve requires a
        paid futures data feed we don't carry. The panel renders this
        gracefully (empty curve message) rather than fabricating data."""
        meta = ROOTS.get(root.upper())
        if not meta:
            return FuturesCurve(root=root.upper(), label="(unsupported root — no public feed)", contracts=[])
        front = await _fred_quote(root.upper())
        front_price = front[0] if front else None
        contracts: list[FuturesContract] = []
        if front:
            price, change, change_pct = front
            contracts.append(
                FuturesContract(
                    contract_symbol=f"{root.upper()}=F (FRED:{meta['series']})",
                    expiration=None,
                    price=price,
                    change=change,
                    change_percent=change_pct,
                    volume=0,
                )
            )
        return FuturesCurve(
            root=root.upper(),
            label=meta["label"],
            front_month_price=front_price,
            contracts=contracts,
            timestamp=datetime.now(timezone.utc),
        )
