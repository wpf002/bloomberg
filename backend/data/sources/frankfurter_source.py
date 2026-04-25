"""Frankfurter — free ECB reference FX rates.

The Finnhub free tier doesn't expose `/forex/rates`, so we use
Frankfurter (https://www.frankfurter.app), an open service that mirrors
the European Central Bank's daily reference rates. No API key required,
no rate limit advertised, ECB-grade reliability.

Trade-off: rates are end-of-day reference values, not intraday. Acceptable
for a retail FX panel; the alternative is paying for a real intraday feed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ...core.cache_utils import cached
from ...models.schemas import FxQuote

logger = logging.getLogger(__name__)

FRANKFURTER_BASE = "https://api.frankfurter.dev/v1"


def _parse_pair(pair: str) -> tuple[str, str] | None:
    s = pair.upper().replace("/", "")
    if len(s) < 6:
        return None
    return s[:3], s[3:6]


class FrankfurterSource:
    @cached("frankfurter:fx", ttl=3600, model=FxQuote)
    async def get_fx_quote(self, pair: str) -> FxQuote | None:
        parsed = _parse_pair(pair)
        if not parsed:
            return None
        base, quote_ccy = parsed
        # Frankfurter rates: /latest?from=USD&to=EUR returns 1 USD in EUR
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{FRANKFURTER_BASE}/latest",
                    params={"from": base, "to": quote_ccy},
                )
        except httpx.HTTPError as exc:
            logger.warning("frankfurter fx fetch failed: %s", exc)
            return None
        if resp.status_code != 200:
            logger.warning("frankfurter fx %s%s -> %s", base, quote_ccy, resp.status_code)
            return None
        data: Any = resp.json() or {}
        rate = (data.get("rates") or {}).get(quote_ccy)
        if rate is None:
            return None
        return FxQuote(
            pair=f"{base}{quote_ccy}",
            base=base,
            quote=quote_ccy,
            price=float(rate),
            change=0.0,
            change_percent=0.0,
            timestamp=datetime.now(timezone.utc),
        )
