"""Financial Modeling Prep data source.

Primary fundamentals provider; yfinance is the fallback. Uses FMP's
`/stable/...` endpoints (the `/api/v3/...` ones became "Legacy" on
Aug 31 2025 and are paid-only now).

Free tier: 250 req/day, statement endpoints capped at limit=5. Each
fundamentals call makes 8 sub-requests, so we cache the outer result for
6h — that supports ~187 distinct ticker loads per day before we'd touch
the FMP quota cap.

Endpoints used:
- /stable/profile?symbol=...                    name, sector, industry, beta, exchange, range
- /stable/key-metrics-ttm?symbol=...            EV, ROE, ROA, working capital, etc.
- /stable/ratios-ttm?symbol=...                 P/E, P/B, P/S, EV/EBITDA, margins, debt ratios
- /stable/income-statement?symbol=…&period=quarter&limit=4   TTM revenue / net income / EPS
- /stable/income-statement?symbol=…&period=annual&limit=2    YoY growth
- /stable/cash-flow-statement?symbol=…&period=quarter&limit=4  TTM free cash flow
- /stable/price-target-consensus?symbol=...     analyst target
- /stable/grades-consensus?symbol=...           buy/hold/sell consensus label
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Iterable

import httpx

from ...core.cache_utils import cached
from ...core.config import settings
from ...models.schemas import Fundamentals

logger = logging.getLogger(__name__)

FMP_BASE = "https://financialmodelingprep.com/stable"


def _safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        fv = float(value)
    except (TypeError, ValueError):
        return None
    if fv != fv or fv in (float("inf"), float("-inf")):
        return None
    return fv


def _safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _sum_field(rows: Iterable[dict], key: str) -> float | None:
    total = 0.0
    found = False
    for row in rows:
        v = _safe_float(row.get(key))
        if v is None:
            continue
        total += v
        found = True
    return total if found else None


def _yoy_growth_annual(annual_rows: list[dict], key: str) -> float | None:
    """Compute YoY growth from two consecutive annual statements."""
    if len(annual_rows) < 2:
        return None
    current = _safe_float(annual_rows[0].get(key))
    prior = _safe_float(annual_rows[1].get(key))
    if current is None or prior is None or prior == 0:
        return None
    return (current - prior) / abs(prior)


class FmpSource:
    """Async wrapper around Financial Modeling Prep stable REST endpoints."""

    def __init__(self) -> None:
        self._api_key = settings.fmp_api_key

    def enabled(self) -> bool:
        return bool(self._api_key)

    async def _get(self, client: httpx.AsyncClient, path: str, **params: Any) -> Any:
        params = {**params, "apikey": self._api_key}
        try:
            resp = await client.get(f"{FMP_BASE}/{path.lstrip('/')}", params=params)
        except httpx.HTTPError as exc:
            logger.warning("FMP %s failed: %s", path, type(exc).__name__)
            return None
        if resp.status_code != 200:
            logger.warning("FMP %s -> %s: %s", path, resp.status_code, resp.text[:200])
            return None
        try:
            return resp.json()
        except ValueError:
            logger.warning("FMP %s returned non-JSON", path)
            return None

    # 6h cache: fundamentals don't move intraday, and each call fans into 8
    # FMP sub-requests. With FMP's 250/day free tier this lets ~187 distinct
    # tickers be loaded per day (vs ~31 if cached for only 1h).
    @cached("fmp:fundamentals", ttl=21600, model=Fundamentals)
    async def get_fundamentals(self, symbol: str) -> Fundamentals:
        symbol = symbol.upper()
        if not self.enabled():
            return Fundamentals(symbol=symbol)

        async with httpx.AsyncClient(timeout=20.0) as client:
            (
                profile,
                key_metrics,
                ratios,
                income_q,
                income_y,
                cashflow_q,
                target,
                grades,
            ) = await asyncio.gather(
                self._get(client, "profile", symbol=symbol),
                self._get(client, "key-metrics-ttm", symbol=symbol),
                self._get(client, "ratios-ttm", symbol=symbol),
                self._get(client, "income-statement", symbol=symbol, period="quarter", limit=4),
                self._get(client, "income-statement", symbol=symbol, period="annual", limit=2),
                self._get(client, "cash-flow-statement", symbol=symbol, period="quarter", limit=4),
                self._get(client, "price-target-consensus", symbol=symbol),
                self._get(client, "grades-consensus", symbol=symbol),
            )

        prof = profile[0] if isinstance(profile, list) and profile else {}
        km = key_metrics[0] if isinstance(key_metrics, list) and key_metrics else {}
        rt = ratios[0] if isinstance(ratios, list) and ratios else {}
        target_row = target[0] if isinstance(target, list) and target else {}
        grades_row = grades[0] if isinstance(grades, list) and grades else {}
        income_q_rows = income_q if isinstance(income_q, list) else []
        income_y_rows = income_y if isinstance(income_y, list) else []
        cashflow_q_rows = cashflow_q if isinstance(cashflow_q, list) else []

        revenue_ttm = _sum_field(income_q_rows, "revenue")
        net_income_ttm = _sum_field(income_q_rows, "netIncome")
        eps_ttm = _sum_field(income_q_rows, "eps")
        fcf_ttm = _sum_field(cashflow_q_rows, "freeCashFlow")
        revenue_growth = _yoy_growth_annual(income_y_rows, "revenue")
        earnings_growth = _yoy_growth_annual(income_y_rows, "netIncome")

        # `grades-consensus.consensus` is already the label we want.
        recommendation = (grades_row.get("consensus") or "").lower() or None

        price = _safe_float(prof.get("price"))
        market_cap = _safe_float(prof.get("marketCap"))
        last_dividend = _safe_float(prof.get("lastDividend"))
        dividend_yield = (last_dividend / price) if (last_dividend and price) else None

        return Fundamentals(
            symbol=symbol,
            name=prof.get("companyName"),
            sector=prof.get("sector"),
            industry=prof.get("industry"),
            description=prof.get("description"),
            country=prof.get("country"),
            employees=_safe_int(prof.get("fullTimeEmployees")),
            website=prof.get("website"),
            market_cap=market_cap,
            enterprise_value=_safe_float(km.get("enterpriseValueTTM")),
            shares_outstanding=(market_cap / price) if (market_cap and price) else None,
            float_shares=None,
            pe_ratio=_safe_float(rt.get("priceToEarningsRatioTTM")),
            forward_pe=None,  # forward EPS lives behind the paid tier
            peg_ratio=_safe_float(rt.get("priceToEarningsGrowthRatioTTM")),
            price_to_book=_safe_float(rt.get("priceToBookRatioTTM")),
            price_to_sales=_safe_float(rt.get("priceToSalesRatioTTM")),
            ev_to_ebitda=_safe_float(km.get("evToEBITDATTM")),
            dividend_yield=dividend_yield,
            payout_ratio=None,
            beta=_safe_float(prof.get("beta")),
            fifty_two_week_high=_parse_range_high(prof.get("range")),
            fifty_two_week_low=_parse_range_low(prof.get("range")),
            revenue_ttm=revenue_ttm,
            revenue_growth_yoy=revenue_growth,
            gross_margin=_safe_float(rt.get("grossProfitMarginTTM")),
            operating_margin=_safe_float(rt.get("operatingProfitMarginTTM")),
            profit_margin=_safe_float(rt.get("netProfitMarginTTM")),
            net_income_ttm=net_income_ttm,
            earnings_growth_yoy=earnings_growth,
            eps_ttm=eps_ttm,
            free_cash_flow_ttm=fcf_ttm,
            debt_to_equity=_safe_float(rt.get("debtToEquityRatioTTM")),
            return_on_equity=_safe_float(km.get("returnOnEquityTTM")),
            return_on_assets=_safe_float(km.get("returnOnAssetsTTM")),
            analyst_target=_safe_float(target_row.get("targetConsensus")),
            analyst_recommendation=recommendation,
            currency=prof.get("currency"),
            exchange=prof.get("exchange") or prof.get("exchangeFullName"),
            timestamp=datetime.now(timezone.utc),
        )


def _parse_range_high(range_str: str | None) -> float | None:
    if not range_str or "-" not in range_str:
        return None
    try:
        return float(range_str.split("-")[1].strip())
    except (ValueError, IndexError):
        return None


def _parse_range_low(range_str: str | None) -> float | None:
    if not range_str or "-" not in range_str:
        return None
    try:
        return float(range_str.split("-")[0].strip())
    except (ValueError, IndexError):
        return None
