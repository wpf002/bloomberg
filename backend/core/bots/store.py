"""Persistence for bots, orders, events, and pending actions.

Postgres-backed when a pool is available, with an in-memory fallback that
mirrors the AlertEngine pattern — so the engine and its unit tests run
without a database. All payloads round-trip through the Pydantic models in
schemas.py.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from ..database import database
from .schemas import (
    Bot,
    BotEvent,
    BotOrder,
    BotStatus,
    PendingAction,
)

logger = logging.getLogger(__name__)


def _today_start() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


class BotStore:
    def __init__(self) -> None:
        # in-memory fallbacks (used when database.pool is None)
        self._bots: dict[str, Bot] = {}
        self._orders: list[BotOrder] = []
        self._events: list[BotEvent] = []
        self._pending: dict[str, PendingAction] = {}

    @property
    def _pg(self) -> bool:
        return database.pool is not None

    # ── bots ──────────────────────────────────────────────────────────────

    async def create_bot(self, bot: Bot) -> Bot:
        if self._pg and bot.user_id is not None:
            try:
                async with database.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO bots (id, user_id, name, status, broker, mode, decision_mode,
                                          require_approval, config, guardrails)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10::jsonb)
                        """,
                        bot.id, bot.user_id, bot.name, bot.status.value, bot.broker, bot.mode,
                        bot.decision_mode.value, bot.require_approval,
                        bot.config.model_dump_json(), bot.guardrails.model_dump_json(),
                    )
                return bot
            except Exception as exc:
                logger.warning("bot create pg failed, falling back: %s", exc)
        self._bots[bot.id] = bot
        return bot

    async def get_bot(self, bot_id: str, user_id: int | None = None) -> Bot | None:
        if self._pg and user_id is not None:
            try:
                async with database.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT * FROM bots WHERE id=$1 AND user_id=$2", bot_id, user_id
                    )
                return _row_to_bot(row) if row else None
            except Exception as exc:
                logger.debug("bot get pg failed: %s", exc)
        bot = self._bots.get(bot_id)
        if bot and user_id is not None and bot.user_id != user_id:
            return None
        return bot

    async def list_bots(self, user_id: int | None = None) -> list[Bot]:
        if self._pg and user_id is not None:
            try:
                async with database.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT * FROM bots WHERE user_id=$1 ORDER BY created_at DESC", user_id
                    )
                return [_row_to_bot(r) for r in rows]
            except Exception as exc:
                logger.debug("bot list pg failed: %s", exc)
        out = [b for b in self._bots.values() if user_id is None or b.user_id == user_id]
        return sorted(out, key=lambda b: b.created_at, reverse=True)

    async def list_active_bots(self) -> list[Bot]:
        """All bots in `active` status across every user — drives the eval loop."""
        if self._pg:
            try:
                async with database.acquire() as conn:
                    rows = await conn.fetch("SELECT * FROM bots WHERE status='active'")
                return [_row_to_bot(r) for r in rows]
            except Exception as exc:
                logger.debug("bot list_active pg failed: %s", exc)
        return [b for b in self._bots.values() if b.status == BotStatus.active]

    async def update_bot(self, bot: Bot) -> Bot:
        bot.updated_at = datetime.utcnow()
        if self._pg and bot.user_id is not None:
            try:
                async with database.acquire() as conn:
                    await conn.execute(
                        """
                        UPDATE bots SET name=$3, status=$4, decision_mode=$5,
                            require_approval=$6, config=$7::jsonb, guardrails=$8::jsonb,
                            broker=$9, mode=$10, updated_at=NOW()
                        WHERE id=$1 AND user_id=$2
                        """,
                        bot.id, bot.user_id, bot.name, bot.status.value,
                        bot.decision_mode.value, bot.require_approval,
                        bot.config.model_dump_json(), bot.guardrails.model_dump_json(),
                        bot.broker, bot.mode,
                    )
                return bot
            except Exception as exc:
                logger.debug("bot update pg failed: %s", exc)
        self._bots[bot.id] = bot
        return bot

    async def set_status(self, bot_id: str, status: BotStatus, user_id: int | None = None) -> bool:
        bot = await self.get_bot(bot_id, user_id)
        if not bot:
            return False
        bot.status = status
        await self.update_bot(bot)
        return True

    async def delete_bot(self, bot_id: str, user_id: int | None = None) -> bool:
        if self._pg and user_id is not None:
            try:
                async with database.acquire() as conn:
                    out = await conn.execute(
                        "DELETE FROM bots WHERE id=$1 AND user_id=$2", bot_id, user_id
                    )
                if out and out.endswith(" 1"):
                    return True
            except Exception as exc:
                logger.debug("bot delete pg failed: %s", exc)
        return self._bots.pop(bot_id, None) is not None

    # ── events ────────────────────────────────────────────────────────────

    async def record_event(self, event: BotEvent) -> None:
        if self._pg and event.user_id is not None:
            try:
                async with database.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO bot_events (bot_id, user_id, ts, kind, detail) "
                        "VALUES ($1,$2,$3,$4,$5::jsonb)",
                        event.bot_id, event.user_id, event.ts, event.kind,
                        json.dumps(event.detail, default=str),
                    )
                return
            except Exception as exc:
                logger.debug("bot event pg failed: %s", exc)
        self._events.append(event)

    async def list_events(self, bot_id: str, limit: int = 100) -> list[BotEvent]:
        if self._pg:
            try:
                async with database.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT bot_id, user_id, ts, kind, detail FROM bot_events "
                        "WHERE bot_id=$1 ORDER BY ts DESC LIMIT $2",
                        bot_id, int(limit),
                    )
                return [
                    BotEvent(
                        bot_id=r["bot_id"], user_id=r["user_id"], ts=r["ts"], kind=r["kind"],
                        detail=_jsonb(r["detail"]),
                    )
                    for r in rows
                ]
            except Exception as exc:
                logger.debug("bot events list pg failed: %s", exc)
        return list(reversed([e for e in self._events if e.bot_id == bot_id]))[:limit]

    # ── orders ────────────────────────────────────────────────────────────

    async def record_order(self, order: BotOrder) -> None:
        if self._pg and order.user_id is not None:
            try:
                async with database.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO bot_orders (id, bot_id, user_id, alpaca_order_id,
                            client_order_id, symbol, side, qty, intent, status, submitted_at)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb,$10,$11)
                        """,
                        order.id, order.bot_id, order.user_id, order.alpaca_order_id,
                        order.client_order_id, order.symbol, order.side, order.qty,
                        json.dumps(order.intent, default=str), order.status, order.submitted_at,
                    )
                return
            except Exception as exc:
                logger.debug("bot order pg failed: %s", exc)
        self._orders.append(order)

    async def list_orders(self, bot_id: str, limit: int = 100) -> list[BotOrder]:
        if self._pg:
            try:
                async with database.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT * FROM bot_orders WHERE bot_id=$1 ORDER BY submitted_at DESC LIMIT $2",
                        bot_id, int(limit),
                    )
                return [_row_to_order(r) for r in rows]
            except Exception as exc:
                logger.debug("bot orders list pg failed: %s", exc)
        return list(reversed([o for o in self._orders if o.bot_id == bot_id]))[:limit]

    async def count_orders_today(self, bot_id: str) -> int:
        start = _today_start()
        if self._pg:
            try:
                async with database.acquire() as conn:
                    val = await conn.fetchval(
                        "SELECT COUNT(*) FROM bot_orders WHERE bot_id=$1 AND submitted_at >= $2",
                        bot_id, start,
                    )
                return int(val or 0)
            except Exception as exc:
                logger.debug("bot count_orders pg failed: %s", exc)
        return sum(
            1 for o in self._orders
            if o.bot_id == bot_id and o.submitted_at.replace(tzinfo=timezone.utc) >= start
        )

    # ── pending actions ───────────────────────────────────────────────────

    async def create_pending(self, action: PendingAction) -> PendingAction:
        if self._pg and action.user_id is not None:
            try:
                async with database.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO bot_pending_actions (id, bot_id, user_id, created_at, intent, status) "
                        "VALUES ($1,$2,$3,$4,$5::jsonb,$6)",
                        action.id, action.bot_id, action.user_id, action.created_at,
                        action.intent.model_dump_json(), action.status,
                    )
                return action
            except Exception as exc:
                logger.debug("pending create pg failed: %s", exc)
        self._pending[action.id] = action
        return action

    async def list_pending(self, bot_id: str | None = None, user_id: int | None = None) -> list[PendingAction]:
        if self._pg and user_id is not None:
            try:
                async with database.acquire() as conn:
                    if bot_id:
                        rows = await conn.fetch(
                            "SELECT * FROM bot_pending_actions WHERE user_id=$1 AND bot_id=$2 "
                            "AND status='pending' ORDER BY created_at DESC", user_id, bot_id)
                    else:
                        rows = await conn.fetch(
                            "SELECT * FROM bot_pending_actions WHERE user_id=$1 AND status='pending' "
                            "ORDER BY created_at DESC", user_id)
                return [_row_to_pending(r) for r in rows]
            except Exception as exc:
                logger.debug("pending list pg failed: %s", exc)
        out = [
            p for p in self._pending.values()
            if p.status == "pending"
            and (bot_id is None or p.bot_id == bot_id)
            and (user_id is None or p.user_id == user_id)
        ]
        return sorted(out, key=lambda p: p.created_at, reverse=True)

    async def get_pending(self, action_id: str, user_id: int | None = None) -> PendingAction | None:
        if self._pg and user_id is not None:
            try:
                async with database.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT * FROM bot_pending_actions WHERE id=$1 AND user_id=$2",
                        action_id, user_id)
                return _row_to_pending(row) if row else None
            except Exception as exc:
                logger.debug("pending get pg failed: %s", exc)
        return self._pending.get(action_id)

    async def resolve_pending(self, action_id: str, status: str, user_id: int | None = None) -> bool:
        if self._pg and user_id is not None:
            try:
                async with database.acquire() as conn:
                    out = await conn.execute(
                        "UPDATE bot_pending_actions SET status=$3, resolved_at=NOW() "
                        "WHERE id=$1 AND user_id=$2 AND status='pending'",
                        action_id, user_id, status)
                if out and out.endswith(" 1"):
                    return True
            except Exception as exc:
                logger.debug("pending resolve pg failed: %s", exc)
        p = self._pending.get(action_id)
        if p and p.status == "pending":
            p.status = status
            p.resolved_at = datetime.utcnow()
            return True
        return False


# ── row → model helpers ────────────────────────────────────────────────────


def _jsonb(value) -> dict:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return value or {}


def _row_to_bot(row) -> Bot:
    keys = row.keys()
    return Bot(
        id=row["id"], user_id=row["user_id"], name=row["name"], status=row["status"],
        broker=row["broker"] if "broker" in keys else "alpaca",
        mode=row["mode"], decision_mode=row["decision_mode"],
        require_approval=row["require_approval"],
        config=_jsonb(row["config"]), guardrails=_jsonb(row["guardrails"]),
        created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _row_to_order(row) -> BotOrder:
    return BotOrder(
        id=row["id"], bot_id=row["bot_id"], user_id=row["user_id"],
        alpaca_order_id=row["alpaca_order_id"], client_order_id=row["client_order_id"],
        symbol=row["symbol"], side=row["side"], qty=row["qty"] or 0.0,
        intent=_jsonb(row["intent"]), status=row["status"], submitted_at=row["submitted_at"],
    )


def _row_to_pending(row) -> PendingAction:
    return PendingAction(
        id=row["id"], bot_id=row["bot_id"], user_id=row["user_id"],
        created_at=row["created_at"], intent=_jsonb(row["intent"]),
        status=row["status"], resolved_at=row["resolved_at"],
    )


store = BotStore()
