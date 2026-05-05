"""V2.3 — Options flow + sector heatmap endpoints.

Routes:
  GET /api/flow/options    large options orders (size > min_premium)
  GET /api/flow/darkpool   dark-pool block prints (unsupported tier)
  GET /api/flow/sweeps     aggressive multi-exchange sweeps (unsupported)
  GET /api/flow/heatmap    sector-level bullish vs bearish $ flow
  GET /api/flow/unusual    flagged unusual activity (unsupported tier)

All endpoints accept the same filter set: symbol, side, min_premium,
expiry, sector. BullFlow is the sole supported provider — the
darkpool / sweeps / unusual endpoints stay in place but return an
`unsupported_on_tier` flag so the FLOW panel can render a "tier note"
section instead of crashing.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ...data.sources.bullflow_source import BullFlowSource

router = APIRouter()
logger = logging.getLogger(__name__)

_bf = BullFlowSource()


# Sector mapping for the heatmap. Keep tight — full GICS resolution
# requires a fundamentals lookup we don't run on every flow tick.
SECTOR_MAP: dict[str, list[str]] = {
    "Technology":              ["AAPL","MSFT","NVDA","AVGO","GOOGL","GOOG","META","AMD","ORCL","CRM","ADBE","INTC","QCOM","CSCO","IBM","TXN","NOW","INTU"],
    "Communication Services":  ["NFLX","DIS","CMCSA","T","VZ","TMUS","CHTR","WBD","ROKU","PINS","SNAP","SPOT"],
    "Consumer Discretionary":  ["AMZN","TSLA","HD","MCD","NKE","SBUX","BKNG","LOW","TJX","ABNB","CMG","MAR","DPZ","DAL","UAL","AAL","CCL","RCL"],
    "Consumer Staples":        ["WMT","PG","KO","PEP","COST","PM","MO","CL","TGT","KR","ADM","KMB","GIS","STZ"],
    "Financials":              ["JPM","BAC","WFC","C","GS","MS","BLK","SCHW","AXP","V","MA","PYPL","SQ","COIN","HOOD"],
    "Health Care":              ["UNH","JNJ","LLY","PFE","ABBV","MRK","TMO","ABT","DHR","CVS","BMY","AMGN","GILD","MRNA","BIIB","REGN"],
    "Energy":                  ["XOM","CVX","COP","EOG","SLB","PSX","MPC","VLO","OXY","HAL","DVN","FANG","HES"],
    "Industrials":             ["GE","CAT","HON","UNP","BA","RTX","LMT","UPS","FDX","DE","ETN","EMR","NOC","GD","ITW"],
    "Materials":               ["LIN","SHW","FCX","NEM","APD","DD","ECL","DOW","ALB","CTVA"],
    "Real Estate":             ["AMT","PLD","EQIX","CCI","SPG","O","WELL","DLR","PSA","VICI"],
    "Utilities":               ["NEE","DUK","SO","SRE","D","AEP","XEL","PEG","ED","EXC"],
}

# Reverse map: ticker -> sector (lazy build).
_TICKER_TO_SECTOR: dict[str, str] = {}
for _sec, _tickers in SECTOR_MAP.items():
    for _t in _tickers:
        _TICKER_TO_SECTOR[_t] = _sec


def _sector_for(symbol: str) -> str:
    return _TICKER_TO_SECTOR.get(symbol.upper(), "Other")


class FlowItem(BaseModel):
    timestamp: str
    symbol: str
    type: str
    strike: float | None = None
    expiry: str | None = None
    size: int = 0
    premium: float | None = None
    side: str
    sentiment: str | None = None
    source: str


class DarkPoolItem(BaseModel):
    timestamp: str
    symbol: str
    price: float = 0.0
    size: int = 0
    notional: float = 0.0
    venue: str | None = None
    source: str = "bullflow"


class FlowResponse(BaseModel):
    items: list[FlowItem]
    needs_key: bool = False
    unsupported_on_tier: bool = False
    sources_configured: list[str] = Field(default_factory=list)
    filters: dict = Field(default_factory=dict)


class DarkPoolResponse(BaseModel):
    items: list[DarkPoolItem]
    needs_key: bool = False
    unsupported_on_tier: bool = False
    sources_configured: list[str] = Field(default_factory=list)


class SectorBucket(BaseModel):
    sector: str
    bullish_premium: float = 0.0
    bearish_premium: float = 0.0
    net_premium: float = 0.0
    trade_count: int = 0
    bullish_dominance: float = 0.0  # 0..1; 0.5 = balanced


class HeatmapResponse(BaseModel):
    buckets: list[SectorBucket]
    needs_key: bool = False
    sources_configured: list[str] = Field(default_factory=list)


def _sources_configured() -> list[str]:
    out = []
    if _bf.configured:
        out.append("bullflow")
    return out


def _filter_items(items: list[dict], *, side: str, min_premium: float, sector: str | None) -> list[dict]:
    out: list[dict] = []
    for it in items:
        prem = it.get("premium") or 0.0
        if prem < min_premium:
            continue
        if side and side != "all" and (it.get("side") or "").lower() != side:
            continue
        if sector and sector != "all":
            if _sector_for(it.get("symbol") or "") != sector:
                continue
        out.append(it)
    return out


@router.get("/options", response_model=FlowResponse)
async def options_flow(
    symbol: str | None = None,
    side: Literal["bullish", "bearish", "all"] = "all",
    min_premium: float = 100_000.0,
    expiry: Literal["0dte", "weekly", "monthly", "leaps", "all"] = "all",
    sector: str | None = None,
) -> FlowResponse:
    sources = _sources_configured()
    filters = {
        "symbol": symbol, "side": side, "min_premium": min_premium,
        "expiry": expiry, "sector": sector,
    }
    if not _bf.configured:
        return FlowResponse(items=[], needs_key=True, sources_configured=[], filters=filters)
    items = await _bf.options_flow(symbol=symbol, side=side, min_premium=min_premium)
    items = _filter_items(items, side=side, min_premium=min_premium, sector=sector)
    items.sort(key=lambda i: i.get("timestamp") or "", reverse=True)
    return FlowResponse(
        items=[FlowItem(**i) for i in items[:200]],
        needs_key=False,
        sources_configured=sources,
        filters=filters,
    )


@router.get("/darkpool", response_model=DarkPoolResponse)
async def dark_pool_flow(
    symbol: str | None = None,
    min_premium: float = 100_000.0,
) -> DarkPoolResponse:
    """Dark-pool block prints are not available on the free tier.

    The route stays so the frontend keeps a stable contract, but the
    response is always tagged `unsupported_on_tier: true` so the panel
    can show a "tier note" section instead of crashing.
    """
    return DarkPoolResponse(
        items=[],
        needs_key=False,
        unsupported_on_tier=True,
        sources_configured=_sources_configured(),
    )


@router.get("/sweeps", response_model=FlowResponse)
async def sweeps(
    symbol: str | None = None,
    side: Literal["bullish", "bearish", "all"] = "all",
    min_premium: float = 100_000.0,
    sector: str | None = None,
) -> FlowResponse:
    """Sweep detection requires a tick-level options feed we don't carry."""
    return FlowResponse(
        items=[],
        needs_key=False,
        unsupported_on_tier=True,
        sources_configured=_sources_configured(),
        filters={"symbol": symbol, "side": side, "min_premium": min_premium, "sector": sector},
    )


@router.get("/unusual", response_model=FlowResponse)
async def unusual_activity(
    symbol: str | None = None,
    min_premium: float = 100_000.0,
) -> FlowResponse:
    return FlowResponse(
        items=[],
        needs_key=False,
        unsupported_on_tier=True,
        sources_configured=_sources_configured(),
        filters={"symbol": symbol, "min_premium": min_premium},
    )


@router.get("/heatmap", response_model=HeatmapResponse)
async def sector_heatmap(
    side: Literal["bullish", "bearish", "all"] = "all",
    min_premium: float = 100_000.0,
) -> HeatmapResponse:
    sources = _sources_configured()
    if not _bf.configured:
        return HeatmapResponse(buckets=[], needs_key=True, sources_configured=[])
    items = await _bf.options_flow(symbol=None, side="all", min_premium=min_premium)
    if side != "all":
        items = [i for i in items if (i.get("side") or "").lower() == side]
    return HeatmapResponse(
        buckets=_aggregate_sectors(items),
        needs_key=False,
        sources_configured=sources,
    )


def _aggregate_sectors(items: list[dict]) -> list[SectorBucket]:
    """Aggregate raw flow records into per-sector net premium buckets."""
    by_sector: dict[str, dict[str, float]] = defaultdict(
        lambda: {"bullish": 0.0, "bearish": 0.0, "count": 0}
    )
    for it in items:
        sec = _sector_for(it.get("symbol") or "")
        side = (it.get("side") or "").lower()
        prem = float(it.get("premium") or 0.0)
        if side == "bullish":
            by_sector[sec]["bullish"] += prem
        elif side == "bearish":
            by_sector[sec]["bearish"] += prem
        by_sector[sec]["count"] += 1
    out: list[SectorBucket] = []
    for sec in list(SECTOR_MAP.keys()) + ["Other"]:
        b = by_sector.get(sec, {"bullish": 0.0, "bearish": 0.0, "count": 0})
        bull = float(b["bullish"])
        bear = float(b["bearish"])
        total = bull + bear
        dom = (bull / total) if total > 0 else 0.5
        out.append(
            SectorBucket(
                sector=sec,
                bullish_premium=bull,
                bearish_premium=bear,
                net_premium=bull - bear,
                trade_count=int(b["count"]),
                bullish_dominance=dom,
            )
        )
    return out
