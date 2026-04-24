from typing import List

from fastapi import APIRouter, HTTPException

from ...data.sources import get_alpaca_source
from ...models.schemas import Account, Position

router = APIRouter()
_alpaca = get_alpaca_source()


@router.get("/account", response_model=Account | None)
async def get_account() -> Account | None:
    if not _alpaca.credentials_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Alpaca credentials not configured. Add ALPACA_API_KEY and "
                "ALPACA_API_SECRET to .env (free paper account at "
                "https://alpaca.markets/signup) and restart."
            ),
        )
    account = await _alpaca.get_account()
    if account is None:
        raise HTTPException(status_code=502, detail="Alpaca account fetch failed")
    return account


@router.get("/positions", response_model=List[Position])
async def get_positions() -> List[Position]:
    if not _alpaca.credentials_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Alpaca credentials not configured. Add ALPACA_API_KEY and "
                "ALPACA_API_SECRET to .env (free paper account at "
                "https://alpaca.markets/signup) and restart."
            ),
        )
    return await _alpaca.get_positions()
