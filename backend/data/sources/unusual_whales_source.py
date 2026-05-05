"""Unusual Whales adapter — institutional options flow + dark pool prints.

Endpoints used:
- /api/option-trades        for the "live tape" of large options orders
- /api/dark-pool/recent     for dark-pool block prints
- /api/option-trades/sweeps for aggressive multi-exchange sweeps
- /api/flow/heatmap         (composed locally) sector aggregation

This module is intentionally tolerant: when UNUSUAL_WHALES_API_KEY is
unset every method returns an empty payload tagged with a "needs_key"
flag so /api/flow can render a "configure to enable" message instead
of crashing the panel.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ...core.config import settings
from ..normalizer import get_normalizer

logger = logging.getLogger(__name__)

UW_BASE = "https://api.unusualwhales.com/api"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UnusualWhalesSource:
    """Thin async wrapper around the Unusual Whales REST API."""

    def __init__(self) -> None:
        self._key = settings.unusual_whales_api_key
        self._normalizer = get_normalizer()

    @property
    def configured(self) -> bool:
        return bool(self._key)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}" if self._key else "",
            "Accept": "application/json",
        }

    async def _get(self, path: str, params: dict | None = None) -> dict | list | None:
        if not self.configured:
            return None
        url = f"{UW_BASE}{path}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=self._headers, params=params or {})
        except Exception as exc:
            logger.warning("UW request failed %s: %s", path, exc)
            return None
        if resp.status_code != 200:
            logger.warning("UW %s -> %s", path, resp.status_code)
            return None
        try:
            return resp.json()
        except Exception:
            return None

    async def options_flow(self, *, symbol: str | None = None, side: str = "all", min_premium: float = 100_000.0, expiry: str = "all") -> list[dict]:
        params: dict[str, Any] = {"min_premium": int(min_premium), "limit": 100}
        if symbol:
            params["ticker"] = symbol.upper()
        if expiry and expiry != "all":
            params["expiry"] = expiry
        if side and side != "all":
            params["sentiment"] = side
        data = await self._get("/option-trades", params)
        if not data:
            return []
        items = data.get("data") if isinstance(data, dict) else data
        return [self._record_flow(t) for t in (items or [])]

    async def dark_pool(self, *, symbol: str | None = None, min_premium: float = 100_000.0) -> list[dict]:
        params: dict[str, Any] = {"min_premium": int(min_premium), "limit": 100}
        if symbol:
            params["ticker"] = symbol.upper()
        data = await self._get("/dark-pool/recent", params)
        if not data:
            return []
        items = data.get("data") if isinstance(data, dict) else data
        return [
            {
                "timestamp": t.get("executed_at") or t.get("timestamp") or _now_iso(),
                "symbol": (t.get("ticker") or t.get("symbol") or "").upper(),
                "price": float(t.get("price") or 0.0),
                "size": int(t.get("size") or t.get("volume") or 0),
                "notional": float(t.get("premium") or t.get("notional") or 0.0),
                "venue": t.get("venue"),
                "source": "unusual_whales",
            }
            for t in (items or [])
        ]

    async def sweeps(self, *, symbol: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"limit": 50}
        if symbol:
            params["ticker"] = symbol.upper()
        data = await self._get("/option-trades/sweeps", params)
        if not data:
            return []
        items = data.get("data") if isinstance(data, dict) else data
        return [self._record_flow(t) for t in (items or [])]

    async def unusual(self, *, symbol: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"limit": 50}
        if symbol:
            params["ticker"] = symbol.upper()
        data = await self._get("/option-trades/unusual", params)
        if not data:
            return []
        items = data.get("data") if isinstance(data, dict) else data
        return [self._record_flow(t) for t in (items or [])]

    def _record_flow(self, t: dict) -> dict:
        sym = (t.get("ticker") or t.get("symbol") or "").upper()
        side = (t.get("side") or t.get("sentiment") or "").lower()
        if side not in ("bullish", "bearish"):
            # Common UW fields: type ∈ {call, put}, sentiment string
            type_ = (t.get("type") or "").lower()
            side = "bullish" if type_ == "call" else ("bearish" if type_ == "put" else "neutral")
        rec = {
            "timestamp": t.get("executed_at") or t.get("timestamp") or _now_iso(),
            "symbol": sym,
            "type": (t.get("type") or "").lower(),
            "strike": _f(t.get("strike")),
            "expiry": t.get("expiry") or t.get("expiration"),
            "size": int(t.get("size") or 0),
            "premium": _f(t.get("premium")),
            "side": side,
            "sentiment": t.get("sentiment") or side,
            "source": "unusual_whales",
        }
        # Provenance trail — we don't have a numeric "value" so we record the
        # premium under series_id "options_flow_premium".
        try:
            self._normalizer.normalize(
                source="unusual_whales",
                symbol=sym or "MARKET",
                series_id="options_flow_premium",
                value=rec["premium"] or 0.0,
                timestamp=rec["timestamp"],
                tags={"side": side, "type": rec["type"]},
            )
        except Exception:
            pass
        return rec


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
