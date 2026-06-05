"""The BotManager — the live trigger loop.

Subscribes to the in-process `quotes` topic and, on each tick, evaluates every
active bot watching that symbol through the full pipeline (strategy → optional
LLM advisor → guardrails → executor). A 60s interval loop drives time-based
strategies (rebalance).

Durability + multi-instance (see coordination.py):
  - Only the leader instance evaluates bots (`leader_lock`), so >1 replica
    won't double-trade.
  - Per-symbol cooldowns live in Redis (`cooldowns`) so they survive restarts.
  - Active bots reload from Postgres each tick, so they resume after a restart.

Market data (quotes/bars) comes from the shared env feed; account/positions
and order placement go through the bot's resolved broker so sizing and
execution hit the right account.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from ..brokers import market_data_source, resolve_execution_broker
from ..brokers.base import BrokerError
from ..streaming import hub, iter_topic, streamer
from . import advisor as advisor_mod
from . import executor as executor_mod
from . import guardrails as guardrails_mod
from .coordination import cooldowns, leader_lock
from .guardrails import GuardrailContext
from .schemas import Bot, BotEvent, BotStatus, DecisionMode, StrategyKind
from .store import store
from .strategies import StrategyContext, evaluate

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_INTERVAL_SECONDS = 60
_LEADER_RENEW_SECONDS = 10
_BARS_STRATEGIES = {StrategyKind.ma_crossover, StrategyKind.rsi_reversion}
_INTERVAL_STRATEGIES = {StrategyKind.rebalance}


def market_open(now: datetime | None = None) -> bool:
    """US equity regular session: Mon–Fri, 09:30–16:00 America/New_York."""
    dt = (now or datetime.now(tz=_ET)).astimezone(_ET)
    if dt.weekday() >= 5:
        return False
    minutes = dt.hour * 60 + dt.minute
    return 9 * 60 + 30 <= minutes <= 16 * 60


class BotManager:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._interval_task: asyncio.Task | None = None
        self._leader_task: asyncio.Task | None = None
        self._prices: dict[str, float] = {}

    async def start(self) -> None:
        if self._task is not None:
            return
        await leader_lock.acquire_or_renew()
        self._leader_task = asyncio.create_task(self._leader_run(), name="bot-leader")
        self._task = asyncio.create_task(self._run(), name="bot-manager")
        self._interval_task = asyncio.create_task(self._interval_run(), name="bot-interval")
        await self.sync_symbols()

    async def stop(self) -> None:
        for t in (self._task, self._interval_task, self._leader_task):
            if t and not t.done():
                t.cancel()
        self._task = self._interval_task = self._leader_task = None
        try:
            await leader_lock.release()
        except Exception:
            pass

    async def _leader_run(self) -> None:
        while True:
            try:
                await asyncio.sleep(_LEADER_RENEW_SECONDS)
                await leader_lock.acquire_or_renew()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("leader renew error: %s", exc)

    async def sync_symbols(self) -> None:
        """Ensure the streamer watches every active bot's symbols."""
        try:
            bots = await store.list_active_bots()
            syms = sorted({s.upper() for b in bots for s in b.config.symbols})
            if syms:
                await streamer.add_symbols(syms)
        except Exception as exc:
            logger.debug("bot sync_symbols failed: %s", exc)

    # ── tick loop ─────────────────────────────────────────────────────────

    async def _run(self) -> None:
        async for msg in iter_topic("quotes"):
            try:
                await self._on_tick(msg)
            except Exception as exc:
                logger.debug("bot tick eval error: %s", exc)

    def _ingest_price(self, msg: dict) -> tuple[str, float | None]:
        sym = (msg.get("symbol") or "").upper()
        if not sym:
            return "", None
        price: float | None = None
        if msg.get("type") == "trade":
            price = _f(msg.get("price"))
        elif msg.get("type") == "quote":
            bid, ask = _f(msg.get("bid")), _f(msg.get("ask"))
            price = (bid + ask) / 2 if bid and ask else (bid or ask)
        elif msg.get("price") is not None:
            price = _f(msg.get("price"))
        if price and price > 0:
            self._prices[sym] = price
        return sym, self._prices.get(sym)

    async def _on_tick(self, msg: dict) -> None:
        if not leader_lock.is_leader():
            return  # a non-leader replica stays passive — no double-trading
        sym, price = self._ingest_price(msg)
        if not sym or not price:
            return
        bots = [
            b for b in await store.list_active_bots()
            if b.config.strategy not in _INTERVAL_STRATEGIES
            and sym in {s.upper() for s in b.config.symbols}
        ]
        if not bots:
            return
        data = market_data_source()
        for bot in bots:
            broker = await self._broker_for(bot)
            if broker is None:
                continue
            account = await broker.get_account()
            if account is None:
                continue
            positions = await broker.get_positions()
            posmap = {p.symbol: p for p in positions}
            await self._eval(bot, sym, price, account, posmap, broker, data)

    # ── interval loop (rebalance) ─────────────────────────────────────────

    async def _interval_run(self) -> None:
        while True:
            try:
                await asyncio.sleep(_INTERVAL_SECONDS)
                if not leader_lock.is_leader():
                    continue
                bots = [b for b in await store.list_active_bots()
                        if b.config.strategy in _INTERVAL_STRATEGIES]
                if not bots:
                    continue
                data = market_data_source()
                for bot in bots:
                    broker = await self._broker_for(bot)
                    if broker is None:
                        continue
                    account = await broker.get_account()
                    if account is None:
                        continue
                    positions = await broker.get_positions()
                    posmap = {p.symbol: p for p in positions}
                    for sym in {s.upper() for s in bot.config.symbols}:
                        quote = await data.get_stock_quote(sym)
                        price = quote.price if quote else self._prices.get(sym)
                        if price:
                            await self._eval(bot, sym, price, account, posmap, broker, data)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("bot interval eval error: %s", exc)

    async def _broker_for(self, bot: Bot):
        try:
            return await resolve_execution_broker(bot.user_id, bot.broker, bot.mode)
        except BrokerError as exc:
            logger.debug("bot %s broker unresolved (%s) — skipping", bot.id, exc)
            return None

    # ── per-bot evaluation ────────────────────────────────────────────────

    async def _eval(self, bot: Bot, symbol: str, price: float, account, posmap, broker, data) -> None:
        pos = posmap.get(symbol)
        pos_qty = pos.qty if pos else 0.0
        pos_avg = pos.avg_entry_price if pos else 0.0
        pos_mv = (pos.market_value if pos and pos.market_value is not None else pos_qty * price)

        closes: list[float] = []
        if bot.config.strategy in _BARS_STRATEGIES:
            try:
                bars = await data.get_stock_bars(symbol, period="3mo", interval="1d")
                closes = [b.close for b in bars if b.close]
            except Exception:
                closes = []
            closes.append(price)

        ctx = StrategyContext(
            symbol=symbol, price=price, closes=closes or [price],
            position_qty=pos_qty, position_avg=pos_avg,
            equity=account.equity, position_market_value=pos_mv,
            reference_price=(pos.current_price if pos else None) or (closes[-2] if len(closes) >= 2 else None),
            params=bot.config.params,
        )
        intents = evaluate(bot.config.strategy, ctx)
        if not intents:
            return

        if bot.decision_mode == DecisionMode.hybrid:
            context = {
                "symbol": symbol, "price": price, "position_qty": pos_qty,
                "position_avg": pos_avg, "equity": account.equity,
            }
            intents, rationale = await advisor_mod.refine(bot, intents, context)
            if rationale:
                await store.record_event(BotEvent(bot_id=bot.id, user_id=bot.user_id, kind="llm", detail={"note": rationale}))

        orders_today = await store.count_orders_today(bot.id)
        age = await cooldowns.age_seconds(bot.id, symbol)
        gctx = GuardrailContext(
            price=price, equity=account.equity, buying_power=account.buying_power,
            position_qty=pos_qty, position_market_value=pos_mv,
            orders_today=orders_today, today_pnl=account.equity - account.last_equity,
            market_open=market_open(), last_fired_age=age,
        )
        for intent in intents:
            decision = guardrails_mod.check(intent, bot.guardrails, gctx, config_symbols=bot.config.symbols)
            if not decision.allow:
                await store.record_event(BotEvent(
                    bot_id=bot.id, user_id=bot.user_id, kind="reject",
                    detail={"intent": intent.model_dump(), "reason": decision.reason},
                ))
                if decision.kill:
                    await self._auto_pause(bot, decision.reason)
                continue
            await cooldowns.mark(bot.id, symbol, bot.guardrails.per_symbol_cooldown_seconds)
            await executor_mod.execute(bot, decision.intent or intent, broker=broker)
            gctx.orders_today += 1  # reflect within this tick

    async def _auto_pause(self, bot: Bot, reason: str) -> None:
        bot.status = BotStatus.paused
        await store.update_bot(bot)
        await store.record_event(BotEvent(
            bot_id=bot.id, user_id=bot.user_id, kind="lifecycle",
            detail={"action": "auto_paused", "reason": reason},
        ))
        topic = f"bots:user:{bot.user_id}" if bot.user_id is not None else "bots"
        await hub.publish(topic, {"type": "bot_paused", "bot_id": bot.id, "reason": reason})


def _f(value) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


manager = BotManager()
