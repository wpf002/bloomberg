"""Alpaca paper-trading order entry.

Phase 5 EMS panel. Thin wrappers over Alpaca's /v2/orders. We intentionally
do *not* sanity-check the order payload locally: Alpaca already enforces
buying-power, fractional-share, halted-symbol, and option-not-supported
rules and returns a JSON error body. Letting the broker be the source of
truth keeps us honest if/when their rules change.
"""

from typing import List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import get_alpaca_source
from ...models.schemas import Order, OrderRequest

router = APIRouter()
_alpaca = get_alpaca_source()


def _ensure_creds() -> None:
    if not _alpaca.credentials_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Alpaca credentials not configured. Add ALPACA_API_KEY and "
                "ALPACA_API_SECRET to .env (free paper account at "
                "https://alpaca.markets/signup) and restart."
            ),
        )


@router.get("", response_model=List[Order])
async def list_orders(
    status: str = Query("all", description="open | closed | all"),
    limit: int = Query(50, ge=1, le=500),
) -> List[Order]:
    _ensure_creds()
    return await _alpaca.list_orders(status=status, limit=limit)


@router.post("", response_model=Order)
async def place_order(order: OrderRequest) -> Order:
    _ensure_creds()
    if order.side.lower() not in {"buy", "sell"}:
        raise HTTPException(status_code=400, detail="side must be 'buy' or 'sell'")
    if order.type.lower() in {"limit", "stop_limit"} and order.limit_price is None:
        raise HTTPException(status_code=400, detail=f"{order.type} requires limit_price")
    if order.type.lower() in {"stop", "stop_limit"} and order.stop_price is None:
        raise HTTPException(status_code=400, detail=f"{order.type} requires stop_price")

    klass = (order.order_class or "simple").lower()
    if klass not in {"simple", "bracket", "oco", "oto"}:
        raise HTTPException(status_code=400, detail=f"unknown order_class: {klass}")
    if klass == "bracket":
        if order.take_profit_limit_price is None or order.stop_loss_stop_price is None:
            raise HTTPException(
                status_code=400,
                detail="bracket requires take_profit_limit_price + stop_loss_stop_price",
            )
        # Alpaca requires bracket entries to be limit/market — explicitly reject
        # combos that won't get through to the broker.
        if order.time_in_force.lower() not in {"day", "gtc"}:
            raise HTTPException(
                status_code=400,
                detail="bracket orders only support day/gtc time-in-force",
            )
    elif klass == "oco":
        if order.take_profit_limit_price is None or order.stop_loss_stop_price is None:
            raise HTTPException(
                status_code=400,
                detail="oco requires take_profit_limit_price + stop_loss_stop_price",
            )
    elif klass == "oto":
        if order.take_profit_limit_price is None and order.stop_loss_stop_price is None:
            raise HTTPException(
                status_code=400,
                detail="oto requires take_profit_limit_price OR stop_loss_stop_price",
            )

    try:
        return await _alpaca.place_order(order)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{order_id}")
async def cancel_order(order_id: str) -> dict:
    _ensure_creds()
    ok = await _alpaca.cancel_order(order_id)
    if not ok:
        raise HTTPException(status_code=400, detail=f"could not cancel {order_id}")
    return {"id": order_id, "status": "canceled"}
