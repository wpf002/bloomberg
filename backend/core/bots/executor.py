"""Turns an approved intent into an order (or a pending approval).

Execution routes through the broker resolver, so the bot's `broker`/`mode`
decide where the order goes: Alpaca paper (default), Alpaca live (gated by
BOTS_ALLOW_LIVE + per-user live keys), or Robinhood (scaffold). Paper is
always allowed; anything requiring missing config is refused with a clear
event rather than silently dropped.

Every action — order, pending, refusal, error — writes a bot_event, an audit
row, and publishes to the bot's per-user WS topic. Order client_order_ids are
deterministic per (bot, symbol, side, cooldown-bucket) so a duplicate eval
after a restart re-uses the id and the broker rejects the dupe — idempotency.
"""

from __future__ import annotations

import logging
import math
import time

from ...models.schemas import OrderRequest
from ..audit import persist_audit
from ..brokers import resolve_execution_broker
from ..brokers.base import BrokerError
from ..config import settings
from ..streaming import hub
from .schemas import Bot, BotEvent, BotOrder, Intent, PendingAction
from .store import store

logger = logging.getLogger(__name__)


def is_paper() -> bool:
    """Whether the default/env Alpaca endpoint is a paper account (used by the
    status route)."""
    return "paper" in (settings.alpaca_base_url or "").lower()


def _client_order_id(bot: Bot, intent: Intent) -> str:
    """Deterministic, coarse-bucketed id → natural idempotency across a
    restart or a double-eval within the same cooldown window."""
    cooldown = max(1, int(bot.guardrails.per_symbol_cooldown_seconds or 60))
    bucket = int(time.time()) // cooldown
    return f"bot-{bot.id}-{intent.symbol}-{intent.side}-{bucket}"


async def _emit(bot: Bot, kind: str, detail: dict) -> None:
    event = BotEvent(bot_id=bot.id, user_id=bot.user_id, kind=kind, detail=detail)
    await store.record_event(event)
    topic = f"bots:user:{bot.user_id}" if bot.user_id is not None else "bots"
    await hub.publish(topic, {"type": "bot_event", **event.model_dump(mode="json")})


async def execute(bot: Bot, intent: Intent, *, broker=None) -> dict:
    """Execute (or queue for approval) a single guardrail-approved intent.

    `broker` may be injected (tests / a manager that already resolved it);
    otherwise it's resolved from the bot's broker/mode.
    """
    intent = intent.normalized()

    # Approval gate — queue without needing a broker.
    if bot.require_approval:
        # Dedupe: if an identical (symbol, side) approval is already pending for
        # this bot, don't stack another — otherwise an away-from-keyboard user
        # returns to a wall of duplicate approvals for the same signal.
        existing = await store.list_pending(bot_id=bot.id, user_id=bot.user_id)
        for p in existing:
            if p.intent.symbol == intent.symbol and p.intent.side == intent.side:
                return {"status": "pending", "pending_id": p.id, "deduped": True}
        action = await store.create_pending(PendingAction(bot_id=bot.id, user_id=bot.user_id, intent=intent))
        await _emit(bot, "signal", {"intent": intent.model_dump(), "pending_id": action.id, "awaiting_approval": True})
        return {"status": "pending", "pending_id": action.id}

    return await place(bot, intent, broker=broker)


async def place(bot: Bot, intent: Intent, *, broker=None) -> dict:
    """Place the order through the bot's resolved broker and record it.
    Assumes the intent already passed guardrails (qty resolved)."""
    intent = intent.normalized()
    if broker is None:
        try:
            broker = await resolve_execution_broker(bot.user_id, bot.broker, bot.mode)
        except BrokerError as exc:
            await _emit(bot, "error", {"reason": str(exc)[:300], "intent": intent.model_dump()})
            return {"status": "refused", "reason": str(exc)[:300]}

    qty = intent.qty
    if qty is None or qty <= 0 or math.isnan(qty):
        await _emit(bot, "reject", {"reason": "no resolved qty", "intent": intent.model_dump()})
        return {"status": "rejected", "reason": "no resolved qty"}

    req = OrderRequest(
        symbol=intent.symbol,
        qty=qty,
        side=intent.side,
        type=intent.type or "market",
        time_in_force="day",
        limit_price=intent.limit_price,
        client_order_id=_client_order_id(bot, intent),
    )
    try:
        order = await broker.place_order(req)
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
        endpoint_called=f"bot:{bot.id}:order:{bot.mode}", user_id=bot.user_id,
    )
    await _emit(bot, "order", {
        "intent": intent.model_dump(), "order_id": order.id, "symbol": order.symbol,
        "side": order.side, "qty": order.qty, "status": order.status,
        "mode": bot.mode, "broker": bot.broker, "reason": intent.reason,
    })
    return {"status": "placed", "order_id": order.id, "bot_order_id": bot_order.id}
