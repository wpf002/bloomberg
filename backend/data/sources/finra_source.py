"""FINRA fixed-income data — Treasury monthly/weekly aggregates.

Plumbing only when `FINRA_API_KEY` + `FINRA_API_SECRET` are set; otherwise
every method returns empty + a flag so the route layer can 503 with a
clear setup hint.

Auth: OAuth2 client-credentials grant against FINRA's IDP, then a Bearer
token on every data call. Tokens last ~1h — we cache them in-process.

Free FINRA dev-account entitlements: `treasuryMonthlyAggregates` and
`treasuryWeeklyAggregates`. Corporate-bond TRACE prints require a paid
subscription that retail dev accounts don't get; we 404 cleanly when
those datasets are out of reach.
"""

from __future__ import annotations

import base64
import csv
import io
import logging
import time
from typing import Any

import httpx

from ...core.config import settings
from ...models.schemas import TraceAggregate

logger = logging.getLogger(__name__)

FINRA_TOKEN_URL = "https://ews.fip.finra.org/fip/rest/ews/oauth2/access_token?grant_type=client_credentials"
FINRA_API_BASE = "https://api.finra.org/data/group/fixedIncomeMarket/name"

# Datasets entitled by default on a free developer account, in order of
# preference. The first one we successfully fetch wins.
DEFAULT_DATASETS = ["treasuryMonthlyAggregates", "treasuryWeeklyAggregates"]


def _f(value: Any) -> float | None:
    if value in (None, "", "null"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _row_to_aggregate(row: dict[str, Any]) -> TraceAggregate:
    """Map a FINRA `treasuryMonthlyAggregates` row into our generic shape.

    Real schema (CSV header):
      beginningOfTheMonthDate, productCategory, yearsToMaturity, benchmark,
      atsInterdealerCount,   atsInterdealerVolume,
      dealerCustomerCount,   dealerCustomerVolume
    """
    period = row.get("beginningOfTheMonthDate") or row.get("monthEndingDate") or row.get("weekEndingDate")
    product = row.get("productCategory") or row.get("benchmark") or row.get("securityType")
    term = row.get("yearsToMaturity") or row.get("benchmark") or row.get("treasuryTerm")
    d2c_count = _f(row.get("dealerCustomerCount") or row.get("totalTradeCount"))
    d2d_count = _f(row.get("atsInterdealerCount"))
    d2c_vol = _f(row.get("dealerCustomerVolume") or row.get("totalParAmount"))
    d2d_vol = _f(row.get("atsInterdealerVolume"))
    total_count = (d2c_count or 0) + (d2d_count or 0) or None
    total_vol = ((d2c_vol or 0) + (d2d_vol or 0)) or None
    # Volume in the dataset is reported in $ billions ("1308.30" = $1.3T).
    # Multiply through so the panel's $-formatter renders sensibly.
    if total_vol is not None:
        total_vol *= 1_000_000_000
    return TraceAggregate(
        period=str(period) if period else None,
        security_type=product,
        benchmark_term=str(term) if term else None,
        trade_date=str(period) if period else None,
        total_par_volume=total_vol,
        total_trade_count=int(total_count) if total_count else None,
        avg_trade_size=(total_vol / total_count) if total_vol and total_count else None,
        pct_dealer_to_customer=(d2c_count / total_count * 100.0) if d2c_count and total_count else None,
        pct_dealer_to_dealer=(d2d_count / total_count * 100.0) if d2d_count and total_count else None,
        raw=row,
    )


def _parse_csv(text: str) -> list[dict[str, Any]]:
    """Parse a CSV body where every cell is a quoted string. Empty cells
    become None instead of empty-string for cleaner downstream handling."""
    reader = csv.DictReader(io.StringIO(text))
    out: list[dict[str, Any]] = []
    for row in reader:
        out.append({k: (v if v != "" else None) for k, v in row.items()})
    return out


class FinraSource:
    def __init__(self) -> None:
        self._token: str | None = None
        self._token_expires_at: float = 0.0

    def credentials_configured(self) -> bool:
        return bool(settings.finra_api_key and settings.finra_api_secret)

    async def _get_token(self) -> str | None:
        if not self.credentials_configured():
            return None
        if self._token and time.time() < self._token_expires_at - 30:
            return self._token
        creds = f"{settings.finra_api_key}:{settings.finra_api_secret}".encode()
        basic = base64.b64encode(creds).decode("ascii")
        headers = {
            "Authorization": f"Basic {basic}",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(FINRA_TOKEN_URL, headers=headers)
        except Exception as exc:
            logger.warning("FINRA token fetch failed: %s", exc)
            return None
        if resp.status_code != 200:
            logger.warning("FINRA token %s: %s", resp.status_code, resp.text[:200])
            return None
        payload = resp.json() or {}
        self._token = payload.get("access_token")
        ttl = int(payload.get("expires_in") or 3600)
        self._token_expires_at = time.time() + ttl
        return self._token

    async def fetch_dataset(
        self,
        dataset: str,
        limit: int = 50,
    ) -> list[TraceAggregate]:
        token = await self._get_token()
        if not token:
            return []
        url = f"{FINRA_API_BASE}/{dataset}"
        body: dict[str, Any] = {"limit": max(1, min(limit, 500))}
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                    json=body,
                )
        except Exception as exc:
            logger.warning("FINRA %s fetch failed: %s", dataset, exc)
            return []
        if resp.status_code == 204:  # no content
            return []
        if resp.status_code != 200:
            logger.warning("FINRA %s -> %s: %s", dataset, resp.status_code, resp.text[:200])
            return []
        # FINRA defaults to CSV even when Accept: application/json is sent,
        # so we sniff: if the body parses as JSON, use it; otherwise treat
        # it as CSV.
        body = resp.text or ""
        rows: list[dict[str, Any]] = []
        try:
            import json as _json
            parsed = _json.loads(body)
            if isinstance(parsed, list):
                rows = parsed
            elif isinstance(parsed, dict):
                rows = parsed.get("data") or []
        except Exception:
            try:
                rows = _parse_csv(body)
            except Exception as exc:
                logger.warning("FINRA %s parse failed: %s", dataset, exc)
                rows = []
        out: list[TraceAggregate] = []
        for row in rows[:limit]:
            try:
                out.append(_row_to_aggregate(row))
            except Exception:
                continue
        return out

    async def treasury_aggregates(self, limit: int = 50) -> list[TraceAggregate]:
        """Pull whichever entitled treasury aggregates dataset returns rows
        first. Lets the same panel work whether the account has monthly
        only, weekly only, or both."""
        for ds in DEFAULT_DATASETS:
            rows = await self.fetch_dataset(ds, limit=limit)
            if rows:
                return rows
        return []
