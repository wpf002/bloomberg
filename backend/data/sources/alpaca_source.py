import logging
from datetime import datetime, timedelta, timezone
from typing import List

import httpx

from ...core.config import settings
from ...models.schemas import NewsItem, Quote

logger = logging.getLogger(__name__)

ALPACA_DATA_BASE = "https://data.alpaca.markets/v2"
ALPACA_NEWS_BASE = "https://data.alpaca.markets/v1beta1/news"


class AlpacaSource:
    """HTTP client for Alpaca Market Data + News (v2 / v1beta1)."""

    def __init__(self) -> None:
        self._headers = {
            "APCA-API-KEY-ID": settings.alpaca_api_key or "",
            "APCA-API-SECRET-KEY": settings.alpaca_api_secret or "",
            "Accept": "application/json",
        }

    def _enabled(self) -> bool:
        return bool(settings.alpaca_api_key and settings.alpaca_api_secret)

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
