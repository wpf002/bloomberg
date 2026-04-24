import asyncio
import logging
from typing import List

from fastapi import APIRouter, HTTPException

from ...data.sources import YFinanceSource, get_alpaca_source
from ...models.schemas import MarketOverview, OverviewTile

logger = logging.getLogger(__name__)
router = APIRouter()
_yf = YFinanceSource()
_alpaca = get_alpaca_source()

# (symbol, label, asset_class). We use Alpaca-covered ETF proxies for indices
# and commodities so tiles populate in real time without depending on
# yfinance (which hits Yahoo and gets rate-limited under load). Crypto falls
# back to yfinance for now; the tile tolerates a 0 if yfinance is throttled.
TILES: List[tuple[str, str, str]] = [
    ("SPY",     "S&P 500 (SPY)",    "equity_etf"),
    ("QQQ",     "Nasdaq 100 (QQQ)", "equity_etf"),
    ("DIA",     "Dow 30 (DIA)",     "equity_etf"),
    ("IWM",     "Russell 2k (IWM)", "equity_etf"),
    ("VIXY",    "VIX (VIXY)",       "volatility_etf"),
    ("TLT",     "Long Tsy (TLT)",   "bond_etf"),
    ("UUP",     "Dollar (UUP)",     "fx_etf"),
    ("USO",     "Crude (USO)",      "commodity_etf"),
    ("GLD",     "Gold (GLD)",       "commodity_etf"),
    ("BTC-USD", "Bitcoin",          "crypto"),
    ("ETH-USD", "Ethereum",         "crypto"),
]


async def _tile_quote(symbol: str, asset_class: str):
    """Route by asset class: crypto goes to Alpaca's crypto endpoint
    (separate URL from equities); everything else tries Alpaca stock
    snapshot then yfinance. Swallow failures per tile so one bad symbol
    doesn't kill the whole grid."""
    if asset_class == "crypto":
        try:
            q = await _alpaca.get_crypto_quote(symbol)
            if q is not None and q.price > 0:
                return q
        except Exception as exc:
            logger.debug("alpaca crypto %s failed: %s", symbol, exc)
    else:
        try:
            q = await _alpaca.get_stock_quote(symbol)
            if q is not None and q.price > 0:
                return q
        except Exception as exc:
            logger.debug("alpaca overview %s failed: %s", symbol, exc)
    try:
        return await _yf.get_quote(symbol)
    except Exception as exc:
        logger.debug("yfinance overview %s failed: %s", symbol, exc)
    return None


@router.get("", response_model=MarketOverview)
async def get_overview() -> MarketOverview:
    async def _tile(sym: str, label: str, asset_class: str) -> OverviewTile | None:
        q = await _tile_quote(sym, asset_class)
        if q is None or q.price <= 0:
            return None
        return OverviewTile(
            symbol=sym,
            label=label,
            asset_class=asset_class,
            price=q.price,
            change=q.change,
            change_percent=q.change_percent,
            timestamp=q.timestamp,
        )

    results = await asyncio.gather(*(_tile(*t) for t in TILES))
    tiles = [t for t in results if t is not None]
    if not tiles:
        raise HTTPException(status_code=502, detail="overview provider unavailable")
    return MarketOverview(tiles=tiles)
