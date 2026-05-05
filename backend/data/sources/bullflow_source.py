"""BullFlow adapter — institutional order flow.

This is the secondary feed for the V2.3 FLOW panel. It mirrors the
shape of UnusualWhalesSource so the route handlers can merge results
without per-source branching. Without BULLFLOW_API_KEY all methods
return [] — the route handler swaps that for a "needs_key" indicator
in the response payload.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ...core.config import settings
from ..normalizer import get_normalizer

logger = logging.getLogger(__name__)

BF_BASE = "https://api.bullflow.io/v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BullFlowSource:
    def __init__(self) -> None:
        self._key = settings.bullflow_api_key
        self._normalizer = get_normalizer()

    @property
    def configured(self) -> bool:
        return bool(self._key)

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-API-KEY": self._key or "",
            "Accept": "application/json",
        }

    async def _get(self, path: str, params: dict | None = None) -> Any | None:
        if not self.configured:
            return None
        url = f"{BF_BASE}{path}"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, headers=self._headers, params=params or {})
        except Exception as exc:
            logger.warning("BullFlow request failed %s: %s", path, exc)
            return None
        if resp.status_code != 200:
            logger.warning("BullFlow %s -> %s", path, resp.status_code)
            return None
        try:
            return resp.json()
        except Exception:
            return None

    async def options_flow(self, *, symbol: str | None = None, side: str = "all", min_premium: float = 100_000.0) -> list[dict]:
        params: dict[str, Any] = {"min_premium": int(min_premium), "limit": 100}
        if symbol:
            params["symbol"] = symbol.upper()
        if side and side != "all":
            params["side"] = side
        data = await self._get("/options/flow", params)
        if not data:
            return []
        items = data.get("results") if isinstance(data, dict) else data
        out: list[dict] = []
        for t in items or []:
            sym = (t.get("symbol") or "").upper()
            side_v = (t.get("side") or t.get("sentiment") or "").lower()
            if side_v not in ("bullish", "bearish"):
                type_ = (t.get("contract_type") or t.get("type") or "").lower()
                side_v = "bullish" if type_ == "call" else ("bearish" if type_ == "put" else "neutral")
            rec = {
                "timestamp": t.get("ts") or t.get("timestamp") or _now_iso(),
                "symbol": sym,
                "type": (t.get("contract_type") or t.get("type") or "").lower(),
                "strike": _f(t.get("strike")),
                "expiry": t.get("expiry"),
                "size": int(t.get("size") or 0),
                "premium": _f(t.get("premium") or t.get("notional")),
                "side": side_v,
                "sentiment": t.get("sentiment") or side_v,
                "source": "bullflow",
            }
            try:
                self._normalizer.normalize(
                    source="bullflow",
                    symbol=sym or "MARKET",
                    series_id="options_flow_premium",
                    value=rec["premium"] or 0.0,
                    timestamp=rec["timestamp"],
                    tags={"side": side_v, "type": rec["type"]},
                )
            except Exception:
                pass
            out.append(rec)
        return out


def _f(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
