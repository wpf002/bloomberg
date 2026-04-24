import asyncio
from typing import List

from fastapi import APIRouter, HTTPException

from ...data.sources import YFinanceSource
from ...models.schemas import MarketOverview, OverviewTile

router = APIRouter()
_yf = YFinanceSource()

TILES: List[tuple[str, str, str]] = [
    ("^GSPC", "S&P 500", "equity_index"),
    ("^NDX", "Nasdaq 100", "equity_index"),
    ("^DJI", "Dow Jones", "equity_index"),
    ("^RUT", "Russell 2000", "equity_index"),
    ("^VIX", "VIX", "volatility"),
    ("^TNX", "US 10Y", "rate"),
    ("DX-Y.NYB", "DXY", "fx"),
    ("CL=F", "WTI Crude", "commodity"),
    ("GC=F", "Gold", "commodity"),
    ("BTC-USD", "Bitcoin", "crypto"),
    ("ETH-USD", "Ethereum", "crypto"),
]


@router.get("", response_model=MarketOverview)
async def get_overview() -> MarketOverview:
    async def _tile(sym: str, label: str, asset_class: str) -> OverviewTile | None:
        try:
            q = await _yf.get_quote(sym)
            return OverviewTile(
                symbol=sym,
                label=label,
                asset_class=asset_class,
                price=q.price,
                change=q.change,
                change_percent=q.change_percent,
                timestamp=q.timestamp,
            )
        except Exception:
            return None

    results = await asyncio.gather(*(_tile(*t) for t in TILES))
    tiles = [t for t in results if t is not None]
    if not tiles:
        raise HTTPException(status_code=502, detail="overview provider unavailable")
    return MarketOverview(tiles=tiles)
