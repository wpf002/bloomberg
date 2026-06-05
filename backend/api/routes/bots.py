"""REST CRUD + lifecycle + dry-run for trading bots.

All routes require an authenticated user (bots are user-scoped). The
streaming activity feed lives in streams.py (`/api/ws/bots`). Execution is
paper-only; see core/bots/executor.is_paper.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException

from ...core.auth import User, require_user
from ...core.bots import manager
from ...core.bots.backtest import run_backtest
from ...core.bots.executor import is_paper, place
from ...core.bots.schemas import (
    BacktestResult,
    Bot,
    BotConfig,
    BotCreateRequest,
    BotEvent,
    BotOrder,
    BotStatus,
    BotUpdateRequest,
    PendingAction,
)
from ...core.bots.store import store
from ...core.brokers import resolve_execution_broker
from ...core.brokers.base import BrokerError
from ...core.config import settings
from ...core.streaming import streamer
from ...data.sources.alpaca_source import get_alpaca_source

router = APIRouter()

_VALID_BROKERS = {"alpaca", "robinhood"}
_VALID_MODES = {"paper", "live"}


def _validate_config(config: BotConfig) -> None:
    if not config.symbols:
        raise HTTPException(status_code=400, detail="at least one symbol is required")
    if len(config.symbols) > 25:
        raise HTTPException(status_code=400, detail="too many symbols (max 25)")


def _validate_broker(broker: str, mode: str) -> tuple[str, str]:
    broker, mode = (broker or "alpaca").lower(), (mode or "paper").lower()
    if broker not in _VALID_BROKERS:
        raise HTTPException(status_code=400, detail=f"unknown broker '{broker}'")
    if mode not in _VALID_MODES:
        raise HTTPException(status_code=400, detail=f"unknown mode '{mode}'")
    if broker == "robinhood" and not settings.robinhood_enabled:
        raise HTTPException(status_code=400, detail="Robinhood broker is not enabled on this server")
    return broker, mode


@router.get("/status")
async def bots_status() -> dict:
    """Engine status — paper/live posture + which brokers are available, so
    the UI can gate the Live option and show the PAPER badge."""
    alpaca = get_alpaca_source()
    return {
        "paper": is_paper(),
        "alpaca_configured": alpaca.credentials_configured(),
        "live_enabled": bool(settings.bots_allow_live),
        "robinhood_enabled": bool(settings.robinhood_enabled),
        "mode": "paper",
    }


@router.get("/robinhood/tools")
async def robinhood_tools(user: User = Depends(require_user)) -> dict:
    """Discover the tools Robinhood's MCP server exposes — the safe, read-only
    way to learn the exact tool names before mapping them for execution.
    Requires ROBINHOOD_MCP_ENDPOINT + ROBINHOOD_MCP_TOKEN to be set."""
    if not (settings.robinhood_mcp_endpoint and settings.robinhood_mcp_token):
        raise HTTPException(status_code=503, detail="ROBINHOOD_MCP_ENDPOINT/TOKEN not configured")
    from ...core.brokers.robinhood_mcp import RobinhoodMcpBroker
    broker = RobinhoodMcpBroker()
    try:
        tools = await broker.list_tools()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"robinhood MCP discovery failed: {exc}")
    return {
        "tools": [{"name": t.get("name"), "description": t.get("description")} for t in tools],
        "hint": "Map these to ROBINHOOD_TOOL_ACCOUNT/POSITIONS/PLACE_ORDER/CANCEL_ORDER, then set ROBINHOOD_ENABLED=true.",
    }


@router.get("", response_model=List[Bot])
async def list_bots(user: User = Depends(require_user)) -> List[Bot]:
    return await store.list_bots(user_id=user.id)


@router.post("", response_model=Bot)
async def create_bot(req: BotCreateRequest, user: User = Depends(require_user)) -> Bot:
    _validate_config(req.config)
    broker, mode = _validate_broker(req.broker, req.mode)
    bot = Bot(
        user_id=user.id,
        name=req.name,
        decision_mode=req.decision_mode,
        require_approval=req.require_approval,
        config=req.config,
        guardrails=req.guardrails,
        status=BotStatus.draft,
        broker=broker,
        mode=mode,
    )
    return await store.create_bot(bot)


@router.post("/validate")
async def validate_bot(req: BotCreateRequest, user: User = Depends(require_user)) -> dict:
    """Lint a bot config without persisting it. Returns warnings the builder
    can surface inline."""
    _validate_config(req.config)
    warnings: list[str] = []
    gr = req.guardrails
    if not req.require_approval:
        warnings.append("Autonomous mode: trades execute without your approval (within guardrails).")
    if gr.daily_loss_limit_usd is None:
        warnings.append("No daily-loss kill-switch set — consider adding one.")
    if gr.max_position_usd > 100_000:
        warnings.append("Max position is very large for a paper test.")
    return {"ok": True, "warnings": warnings}


@router.get("/{bot_id}", response_model=Bot)
async def get_bot(bot_id: str, user: User = Depends(require_user)) -> Bot:
    bot = await store.get_bot(bot_id, user_id=user.id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    return bot


@router.put("/{bot_id}", response_model=Bot)
async def update_bot(bot_id: str, req: BotUpdateRequest, user: User = Depends(require_user)) -> Bot:
    bot = await store.get_bot(bot_id, user_id=user.id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    if req.name is not None:
        bot.name = req.name
    if req.decision_mode is not None:
        bot.decision_mode = req.decision_mode
    if req.require_approval is not None:
        bot.require_approval = req.require_approval
    if req.broker is not None or req.mode is not None:
        broker, mode = _validate_broker(req.broker or bot.broker, req.mode or bot.mode)
        bot.broker, bot.mode = broker, mode
    if req.config is not None:
        _validate_config(req.config)
        bot.config = req.config
    if req.guardrails is not None:
        bot.guardrails = req.guardrails
    bot = await store.update_bot(bot)
    await manager.sync_symbols()
    return bot


@router.delete("/{bot_id}")
async def delete_bot(bot_id: str, user: User = Depends(require_user)) -> dict:
    ok = await store.delete_bot(bot_id, user_id=user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="bot not found")
    return {"id": bot_id, "deleted": True}


# ── lifecycle ──────────────────────────────────────────────────────────────


async def _transition(bot_id: str, status: BotStatus, user: User) -> Bot:
    bot = await store.get_bot(bot_id, user_id=user.id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    if status == BotStatus.active:
        # Resolving the broker proves the bot can actually trade: paper falls
        # back to env keys; live requires BOTS_ALLOW_LIVE + per-user live keys;
        # robinhood requires it be enabled. Surface the precise reason.
        try:
            await resolve_execution_broker(user.id, bot.broker, bot.mode)
        except BrokerError as exc:
            raise HTTPException(status_code=403, detail=str(exc))
    bot.status = status
    await store.update_bot(bot)
    await store.record_event(BotEvent(
        bot_id=bot.id, user_id=user.id, kind="lifecycle", detail={"action": status.value},
    ))
    if status == BotStatus.active:
        try:
            await streamer.add_symbols([s.upper() for s in bot.config.symbols])
        except Exception:
            pass
        await manager.sync_symbols()
    return bot


@router.post("/{bot_id}/start", response_model=Bot)
async def start_bot(bot_id: str, user: User = Depends(require_user)) -> Bot:
    return await _transition(bot_id, BotStatus.active, user)


@router.post("/{bot_id}/pause", response_model=Bot)
async def pause_bot(bot_id: str, user: User = Depends(require_user)) -> Bot:
    return await _transition(bot_id, BotStatus.paused, user)


@router.post("/{bot_id}/stop", response_model=Bot)
async def stop_bot(bot_id: str, user: User = Depends(require_user)) -> Bot:
    return await _transition(bot_id, BotStatus.stopped, user)


@router.post("/{bot_id}/kill", response_model=Bot)
async def kill_bot(bot_id: str, user: User = Depends(require_user)) -> Bot:
    return await _transition(bot_id, BotStatus.killed, user)


# ── activity + orders + approvals ──────────────────────────────────────────


@router.get("/{bot_id}/events", response_model=List[BotEvent])
async def bot_events(bot_id: str, limit: int = 100, user: User = Depends(require_user)) -> List[BotEvent]:
    bot = await store.get_bot(bot_id, user_id=user.id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    return await store.list_events(bot_id, limit=limit)


@router.get("/{bot_id}/orders", response_model=List[BotOrder])
async def bot_orders(bot_id: str, limit: int = 100, user: User = Depends(require_user)) -> List[BotOrder]:
    bot = await store.get_bot(bot_id, user_id=user.id)
    if not bot:
        raise HTTPException(status_code=404, detail="bot not found")
    return await store.list_orders(bot_id, limit=limit)


@router.get("/{bot_id}/pending", response_model=List[PendingAction])
async def bot_pending(bot_id: str, user: User = Depends(require_user)) -> List[PendingAction]:
    return await store.list_pending(bot_id=bot_id, user_id=user.id)


@router.post("/{bot_id}/pending/{action_id}/approve")
async def approve_pending(bot_id: str, action_id: str, user: User = Depends(require_user)) -> dict:
    bot = await store.get_bot(bot_id, user_id=user.id)
    action = await store.get_pending(action_id, user_id=user.id)
    if not bot or not action or action.bot_id != bot_id:
        raise HTTPException(status_code=404, detail="pending action not found")
    if action.status != "pending":
        raise HTTPException(status_code=409, detail=f"already {action.status}")
    await store.resolve_pending(action_id, "approved", user_id=user.id)
    result = await place(bot, action.intent)
    return {"approved": True, "result": result}


@router.post("/{bot_id}/pending/{action_id}/reject")
async def reject_pending(bot_id: str, action_id: str, user: User = Depends(require_user)) -> dict:
    action = await store.get_pending(action_id, user_id=user.id)
    if not action or action.bot_id != bot_id:
        raise HTTPException(status_code=404, detail="pending action not found")
    ok = await store.resolve_pending(action_id, "rejected", user_id=user.id)
    if not ok:
        raise HTTPException(status_code=409, detail="could not reject")
    await store.record_event(BotEvent(
        bot_id=bot_id, user_id=user.id, kind="lifecycle",
        detail={"action": "rejected_pending", "pending_id": action_id},
    ))
    return {"rejected": True}


# ── dry-run / backtest ─────────────────────────────────────────────────────


@router.post("/backtest", response_model=BacktestResult)
async def backtest(req: BotCreateRequest, user: User = Depends(require_user)) -> BacktestResult:
    """Replay the strategy over ~6mo of daily bars for the first symbol. No
    orders placed — this is the preview a user runs before arming a bot."""
    _validate_config(req.config)
    symbol = req.config.symbols[0].upper()
    alpaca = get_alpaca_source()
    bars = await alpaca.get_stock_bars(symbol, period="6mo", interval="1d")
    closes = [b.close for b in bars if b.close]
    timestamps = [b.timestamp for b in bars if b.close]
    if len(closes) < 35:
        raise HTTPException(status_code=422, detail=f"not enough history for {symbol} to backtest")
    return run_backtest(req.config, closes, symbol=symbol, timestamps=timestamps)
