"""Turns an approved intent into a paper order (or a pending approval).

Hard safety invariant: this build is **paper only**. `is_paper()` checks the
configured Alpaca base URL and the executor refuses to place an order against
a live endpoint. Every action — order, pending, or error — writes a
bot_event, an audit row, and publishes to the bot's per-user WS topic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ...models.schemas import OrderRequest
from ..audit import persist_audit
from ..config import settings
from ..streaming import hub
from .schemas import Bot, BotEvent, BotOrder, Intent, PendingAction
from .store import store

logger = logging.getLogger(__name__)


def is_paper() -> bool:
    """True when the configured Alpaca endpoint is a paper account. The bot
    executor only ever runs against paper in this build."""
    return "paper" in (settings.alpaca_base_url or "").lower()


async def _emit(bot: Bot, kind: str, detail: dict) -> None:
    event = BotEvent(bot_id=bot.id, user_id=bot.user_id, kind=kind, detail=detail)
    await store.record_event(event)
    topic = f"bots:user:{bot.user_id}" if bot.user_id is not None else "bots"
    await hub.publish(topic, {"type": "bot_event", **event.model_dump(mode="json")})


async def execute(bot: Bot, intent: Intent, *, alpaca=None) -> dict:
    """Execute (or queue for approval) a single guardrail-approved intent.

    `alpaca` is injected for tests; defaults to the shared singleton.
    Returns a small dict describing what happened.
    """
    intent = intent.normalized()

    if not is_paper():
        await _emit(bot, "error", {"reason": "executor refused: not a paper account", "intent": intent.model_dump()})
        return {"status": "refused", "reason": "live trading is disabled in this build"}

    # Approval gate — queue instead of placing.
    if bot.require_approval:
        action = await store.create_pending(PendingAction(bot_id=bot.id, user_id=bot.user_id, intent=intent))
        await _emit(bot, "signal", {"intent": intent.model_dump(), "pending_id": action.id, "awaiting_approval": True})
        return {"status": "pending", "pending_id": action.id}

    return await place(bot, intent, alpaca=alpaca)


async def place(bot: Bot, intent: Intent, *, alpaca=None) -> dict:
    """Place the order on Alpaca paper and record it. Assumes the intent has
    already passed guardrails (qty resolved)."""
    if alpaca is None:
        from ...data.sources.alpaca_source import get_alpaca_source
        alpaca = get_alpaca_source()

    qty = intent.qty
    if qty is None or qty <= 0:
        await _emit(bot, "reject", {"reason": "no resolved qty", "intent": intent.model_dump()})
        return {"status": "rejected", "reason": "no resolved qty"}

    req = OrderRequest(
        symbol=intent.symbol,
        qty=qty,
        side=intent.side,
        type=intent.type or "market",
        time_in_force="day",
        limit_price=intent.limit_price,
        client_order_id=f"bot-{bot.id}-{int(datetime.now(timezone.utc).timestamp())}",
    )
    try:
        order = await alpaca.place_order(req)
    except Exception as exc:
        await _emit(bot, "error", {"reason": str(exc)[:300], "intent": intent.model_dump()})
        return {"status": "error", "reason": str(exc)[:300]}

    bot_order = BotOrder(
        bot_id=bot.id, user_id=bot.user_id, alpaca_order_id=order.id,
        client_order_id=order.client_order_id, symbol=order.symbol, side=order.side,
        qty=order.qty, intent=intent.model_dump(), status=order.status,
    )
    await store.record_order(bot_order)
    await persist_audit(
        record_id=order.id, source="bot", symbol=order.symbol,
        endpoint_called=f"bot:{bot.id}:order", user_id=bot.user_id,
    )
    await _emit(bot, "order", {
        "intent": intent.model_dump(), "order_id": order.id, "symbol": order.symbol,
        "side": order.side, "qty": order.qty, "status": order.status, "reason": intent.reason,
    })
    return {"status": "placed", "order_id": order.id, "bot_order_id": bot_order.id}
