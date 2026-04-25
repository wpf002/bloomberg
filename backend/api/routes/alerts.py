"""REST CRUD around the alert engine. The streaming side is in `streams.py`."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...core.alerts import engine
from ...core.auth import current_user
from ...core.streaming import streamer
from ...models.schemas import AlertCondition, AlertEvent, AlertRule

router = APIRouter()


class AlertRuleRequest(BaseModel):
    symbol: str
    name: str | None = None
    conditions: List[AlertCondition] = Field(default_factory=list)
    cooldown_seconds: int = 300


@router.get("/rules", response_model=List[AlertRule])
async def list_rules(request: Request) -> List[AlertRule]:
    user = await current_user(request)
    return await engine.list_rules(user_id=user.id if user else None)


@router.post("/rules", response_model=AlertRule)
async def create_rule(req: AlertRuleRequest, request: Request) -> AlertRule:
    if not req.conditions:
        raise HTTPException(status_code=400, detail="at least one condition is required")
    user = await current_user(request)
    rule = await engine.add_rule(
        symbol=req.symbol,
        conditions=req.conditions,
        name=req.name,
        cooldown_seconds=req.cooldown_seconds,
        user_id=user.id if user else None,
    )
    # Make sure the streamer is watching this symbol so the engine sees ticks.
    await streamer.add_symbols([rule.symbol])
    return rule


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str, request: Request) -> dict:
    user = await current_user(request)
    ok = await engine.delete_rule(rule_id, user_id=user.id if user else None)
    if not ok:
        raise HTTPException(status_code=404, detail="rule not found")
    return {"id": rule_id, "deleted": True}


@router.get("/events", response_model=List[AlertEvent])
async def recent_events(request: Request, limit: int = 50) -> List[AlertEvent]:
    user = await current_user(request)
    return await engine.recent_events(limit=limit, user_id=user.id if user else None)
