"""REST CRUD around the alert engine. The streaming side is in `streams.py`."""

from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.alerts import engine
from ...core.streaming import streamer
from ...models.schemas import AlertCondition, AlertEvent, AlertRule

router = APIRouter()


class AlertRuleRequest(BaseModel):
    symbol: str
    name: str | None = None
    conditions: List[AlertCondition] = Field(default_factory=list)
    cooldown_seconds: int = 300


@router.get("/rules", response_model=List[AlertRule])
async def list_rules() -> List[AlertRule]:
    return await engine.list_rules()


@router.post("/rules", response_model=AlertRule)
async def create_rule(req: AlertRuleRequest) -> AlertRule:
    if not req.conditions:
        raise HTTPException(status_code=400, detail="at least one condition is required")
    rule = await engine.add_rule(
        symbol=req.symbol,
        conditions=req.conditions,
        name=req.name,
        cooldown_seconds=req.cooldown_seconds,
    )
    # Make sure the streamer is watching this symbol so the engine sees ticks.
    await streamer.add_symbols([rule.symbol])
    return rule


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str) -> dict:
    ok = await engine.delete_rule(rule_id)
    if not ok:
        raise HTTPException(status_code=404, detail="rule not found")
    return {"id": rule_id, "deleted": True}


@router.get("/events", response_model=List[AlertEvent])
async def recent_events(limit: int = 50) -> List[AlertEvent]:
    return await engine.recent_events(limit=limit)
