"""TreasuryDirect — upcoming and recent US Treasury auctions.

Public, key-free. The `/TA_WS/securities/announced` endpoint lists
auctions whose announcement date is in the past 30 days; for upcoming
auctions specifically, filter on `auctionDate >= today`. We also fetch
`/TA_WS/securities/auctioned` for recent results so the panel shows both
"upcoming" and "just-cleared" auctions side by side.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from ...core.cache_utils import cached
from ...models.schemas import TreasuryAuction

logger = logging.getLogger(__name__)

ANNOUNCED_URL = "https://www.treasurydirect.gov/TA_WS/securities/announced"
AUCTIONED_URL = "https://www.treasurydirect.gov/TA_WS/securities/auctioned"


def _f(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_to_model(row: dict[str, Any]) -> TreasuryAuction:
    return TreasuryAuction(
        cusip=row.get("cusip"),
        security_type=row.get("securityType"),
        security_term=row.get("securityTerm"),
        auction_date=row.get("auctionDate"),
        issue_date=row.get("issueDate"),
        maturity_date=row.get("maturityDate"),
        offering_amount=_f(row.get("offeringAmt")) or _f(row.get("totalAccepted")),
        high_yield=_f(row.get("highYield")) or _f(row.get("highInvestmentRate")),
        interest_rate=_f(row.get("interestRate")) or _f(row.get("intRateAnnual")),
    )


class TreasurySource:
    @cached("treasury:announced", ttl=1800, model=TreasuryAuction)
    async def announced(self, limit: int = 30) -> list[TreasuryAuction]:
        return await self._fetch(ANNOUNCED_URL, limit=limit)

    @cached("treasury:auctioned", ttl=1800, model=TreasuryAuction)
    async def auctioned(self, limit: int = 30) -> list[TreasuryAuction]:
        return await self._fetch(AUCTIONED_URL, limit=limit)

    async def _fetch(self, url: str, limit: int) -> list[TreasuryAuction]:
        params = {"format": "json"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    url, params=params,
                    headers={"User-Agent": "bloomberg-terminal", "Accept": "application/json"},
                )
        except Exception as exc:
            logger.warning("treasury fetch %s failed: %s", url, exc)
            return []
        if resp.status_code != 200:
            logger.warning("treasury %s -> %s", url, resp.status_code)
            return []
        try:
            data = resp.json() or []
        except Exception as exc:
            logger.warning("treasury parse failed: %s", exc)
            return []
        if not isinstance(data, list):
            return []
        out: list[TreasuryAuction] = []
        for row in data[:limit]:
            try:
                out.append(_row_to_model(row))
            except Exception:
                continue
        return out
