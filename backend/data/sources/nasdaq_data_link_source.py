"""Nasdaq Data Link adapter — short interest, insider, institutional.

Only routes used here are the read-only datatable endpoints. Without
NASDAQ_DATA_LINK_API_KEY every method returns an empty payload so
the panels can render a configure-key message instead of crashing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ...core.config import settings
from ..normalizer import get_normalizer

logger = logging.getLogger(__name__)

NDL_BASE = "https://data.nasdaq.com/api/v3"


class NasdaqDataLinkSource:
    def __init__(self) -> None:
        self._key = settings.nasdaq_data_link_api_key
        self._normalizer = get_normalizer()

    @property
    def configured(self) -> bool:
        return bool(self._key)

    async def _get(self, path: str, params: dict | None = None) -> Any | None:
        if not self.configured:
            return None
        url = f"{NDL_BASE}{path}"
        params = dict(params or {})
        params["api_key"] = self._key
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.get(url, params=params)
        except Exception as exc:
            logger.warning("ndl request failed %s: %s", path, exc)
            return None
        if resp.status_code != 200:
            logger.warning("ndl %s -> %s", path, resp.status_code)
            return None
        try:
            return resp.json()
        except Exception:
            return None

    async def short_interest(self, symbol: str) -> list[dict]:
        # FINRA short volume (FINRA/FNYX, FNSQ, etc) — sample dataset id.
        data = await self._get(f"/datasets/FINRA/FNYX_{symbol.upper()}.json", {"rows": 30})
        rows = ((data or {}).get("dataset") or {}).get("data") or []
        cols = ((data or {}).get("dataset") or {}).get("column_names") or []
        out: list[dict] = []
        for r in rows:
            d = dict(zip(cols, r))
            out.append({
                "date": d.get("Date"),
                "short_volume": d.get("ShortVolume"),
                "total_volume": d.get("TotalVolume"),
                "short_pct": (
                    (d.get("ShortVolume") / d.get("TotalVolume") * 100.0)
                    if d.get("ShortVolume") and d.get("TotalVolume")
                    else None
                ),
                "source": "nasdaq_data_link",
            })
        for row in out:
            try:
                self._normalizer.normalize(
                    source="nasdaq_data_link",
                    symbol=symbol.upper(),
                    series_id="short_volume_pct",
                    value=row["short_pct"] or 0.0,
                    timestamp=row["date"] or datetime.now(timezone.utc).isoformat(),
                )
            except Exception:
                pass
        return out

    async def insider_transactions(self, symbol: str) -> list[dict]:
        data = await self._get(f"/datatables/SHARADAR/SF3.json", {"ticker": symbol.upper(), "qopts.export": "false"})
        if not data:
            return []
        rows = (data.get("datatable") or {}).get("data") or []
        cols = [c.get("name") for c in (data.get("datatable") or {}).get("columns") or []]
        return [dict(zip(cols, r)) for r in rows][:50]

    async def institutional_ownership(self, symbol: str) -> list[dict]:
        data = await self._get(f"/datatables/SHARADAR/SF3.json", {"ticker": symbol.upper(), "qopts.columns": "ticker,calendardate,name,units,value,price"})
        if not data:
            return []
        rows = (data.get("datatable") or {}).get("data") or []
        cols = [c.get("name") for c in (data.get("datatable") or {}).get("columns") or []]
        return [dict(zip(cols, r)) for r in rows][:50]
