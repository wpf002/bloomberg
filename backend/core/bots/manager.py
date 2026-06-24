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
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..brokers import market_data_source, resolve_execution_broker
from ..brokers.base import BrokerError
from ..streaming import hub, iter_topic, streamer
from . import advisor as advisor_mod
from . import health as health_mod
from . import executor as executor_mod
from . import guardrails as guardrails_mod
from . import tuner as tuner_mod
from .coordination import cooldowns, leader_lock
from .guardrails import GuardrailContext
from .outcomes import outcome_store
from .schemas import Bot, BotEvent, BotStatus, DecisionMode, StrategyKind, TradeOutcome
from .store import store
from .strategies import StrategyContext, evaluate

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_INTERVAL_SECONDS = 60
_LEADER_RENEW_SECONDS = 10
# Watchdog: during market hours an active bot should heartbeat well within this
# window. Past it, the engine isn't reaching the bot → flag it in the feed.
_STALE_SECONDS = 300
# Grace after a bot first appears active (or after a restart) before a missing
# heartbeat counts as stale — gives the streamer time to warm up.
_WARMUP_SECONDS = 150
_BARS_STRATEGIES = {
    StrategyKind.ma_crossover, StrategyKind.rsi_reversion,
    StrategyKind.bollinger, StrategyKind.breakout,
}
_INTERVAL_STRATEGIES = {StrategyKind.rebalance}
_REGIME_TTL = 300   # seconds between regime refreshes in the interval loop


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
        self._last_health: dict[str, float] = {}
        self._stale_warned: set[str] = set()       # bots currently flagged stale
        self._watch_since: dict[str, float] = {}    # first-seen-active (warmup grace)
        # Learning engine state
        self._current_regime: str = "any"           # cached regime label
        self._regime_ts: float = 0.0                # monotonic time of last regime fetch
        self._learned_overlay: dict[str, dict] = {} # bot_id → param overlay for current regime

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
        # Self-reconnecting: if the quote stream ends, loop back and re-subscribe
        # rather than letting the tick loop die permanently.
        while True:
            try:
                async for msg in iter_topic("quotes"):
                    try:
                        await self._on_tick(msg)
                    except Exception as exc:
                        logger.debug("bot tick eval error: %s", exc)
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("bot tick loop restart: %s", exc)
                await asyncio.sleep(1)

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
            # Per-bot isolation: one bot's failure must not starve the others
            # sharing this tick.
            try:
                broker = await self._broker_for(bot)
                if broker is None:
                    continue
                account = await broker.get_account()
                if account is None:
                    continue
                positions = await broker.get_positions()
                posmap = {p.symbol: p for p in positions}
                await self._eval(bot, sym, price, account, posmap, broker, data)
            except Exception as exc:
                logger.debug("bot %s eval failed: %s", bot.id, exc)

    # ── interval loop (rebalance) ─────────────────────────────────────────

    async def _interval_run(self) -> None:
        while True:
            try:
                await asyncio.sleep(_INTERVAL_SECONDS)
                if not leader_lock.is_leader():
                    continue
                active = await store.list_active_bots()
                data = market_data_source()

                # Refresh regime label and learned-param overlay periodically.
                await self._refresh_regime()
                await self._refresh_learned_overlay(active)

                if market_open():
                    # Flag any bot whose heartbeat went stale...
                    await self._watchdog(active)
                    # ...then RE-EVALUATE EVERY ACTIVE BOT via direct quote
                    # polling. This is the reliability floor: a dead or
                    # disconnected quote stream can never make a bot silently
                    # stop — every bot trades on at least the interval cadence.
                    # The tick loop stays the fast path; cooldowns + idempotent
                    # order ids make the overlap safe.
                    for bot in active:
                        await self._eval_bot_once(bot, data)
                    # Learning engine: check whether any bot has accumulated
                    # enough new outcomes to warrant a parameter tune.
                    for bot in active:
                        await self._maybe_tune_bot(bot, data)
                else:
                    # Market closed: nothing to trade, but keep the heartbeat
                    # fresh so the bot visibly stays alive instead of looking off.
                    for bot in active:
                        await self._standby_heartbeat(bot, data)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("bot interval eval error: %s", exc)

    async def _refresh_regime(self) -> None:
        mono = time.monotonic()
        if mono - self._regime_ts < _REGIME_TTL:
            return
        try:
            from ...services.intelligence_engine import regime_now  # avoid circular at import time
            payload = await regime_now()
            self._current_regime = payload.get("regime", "any") or "any"
        except Exception as exc:
            logger.debug("regime refresh failed: %s", exc)
        self._regime_ts = time.monotonic()

    async def _refresh_learned_overlay(self, active: list[Bot]) -> None:
        """Reload learned params for the current regime for every active bot."""
        regime = self._current_regime
        for bot in active:
            try:
                learned = await outcome_store.get_learned(bot.id, regime)
                if learned and learned.params:
                    self._learned_overlay[bot.id] = learned.params
                else:
                    self._learned_overlay.pop(bot.id, None)
            except Exception as exc:
                logger.debug("learned overlay refresh failed for bot %s: %s", bot.id, exc)

    async def _maybe_tune_bot(self, bot: Bot, data) -> None:
        """Run the parameter tuner for a bot if enough new outcomes have arrived."""
        try:
            syms = [s.upper() for s in bot.config.symbols]
            sym = syms[0] if syms else None
            if not sym:
                return
            bars = await data.get_stock_bars(sym, period="3mo", interval="1d")
            closes = [b.close for b in bars if b.close]
            if not closes:
                return
            result = await tuner_mod.maybe_tune(bot, closes, regime=self._current_regime)
            if result and result.improved:
                self._learned_overlay[bot.id] = result.params
                await store.record_event(BotEvent(
                    bot_id=bot.id, user_id=bot.user_id, kind="tune",
                    detail={
                        "regime": result.regime,
                        "score": result.score,
                        "params": result.params,
                        "note": f"params updated for regime={result.regime} (score {result.score:.3f})",
                    },
                ))
        except Exception as exc:
            logger.debug("tune failed for bot %s: %s", bot.id, exc)

    async def _eval_bot_once(self, bot: Bot, data) -> None:
        """Evaluate one bot across its symbols via direct quote polling —
        independent of the streaming pipeline. Per-bot isolation."""
        try:
            broker = await self._broker_for(bot)
            if broker is None:
                return
            account = await broker.get_account()
            if account is None:
                return
            positions = await broker.get_positions()
            posmap = {p.symbol: p for p in positions}
            for sym in {s.upper() for s in bot.config.symbols}:
                quote = await data.get_stock_quote(sym)
                price = quote.price if quote else self._prices.get(sym)
                if price:
                    await self._eval(bot, sym, price, account, posmap, broker, data)
        except Exception as exc:
            logger.debug("bot %s interval eval failed: %s", bot.id, exc)

    async def _standby_heartbeat(self, bot: Bot, data) -> None:
        """Off-hours heartbeat: prove the bot is alive and standing by without
        running the strategy (which would only reject on 'market closed')."""
        syms = sorted({s.upper() for s in bot.config.symbols})
        sym = syms[0] if syms else ""
        price = None
        try:
            quote = await data.get_stock_quote(sym) if sym else None
            price = (quote.price if quote else None) or self._prices.get(sym)
        except Exception:
            price = self._prices.get(sym)
        note = f"{sym} {price:.2f} · standing by (market closed)" if price else "standing by — market closed"
        self._last_health[bot.id] = time.monotonic()
        try:
            await health_mod.write(bot.id, {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "symbol": sym, "price": round(price, 4) if price else None,
                "note": note, "orders_today": 0,
                "market_open": False, "is_leader": leader_lock.is_leader(),
            })
        except Exception as exc:
            logger.debug("standby heartbeat failed for bot %s: %s", bot.id, exc)

    async def _broker_for(self, bot: Bot):
        try:
            return await resolve_execution_broker(bot.user_id, bot.broker, bot.mode)
        except BrokerError as exc:
            logger.debug("bot %s broker unresolved (%s) — skipping", bot.id, exc)
            return None

    # ── heartbeat ─────────────────────────────────────────────────────────

    def _status_note(self, bot: Bot, symbol: str, price: float, reference_price: float | None) -> str:
        """Human-readable one-liner: how far is price from doing something."""
        strat = bot.config.strategy
        if strat == StrategyKind.threshold_dca and reference_price:
            drop = float(bot.config.params.get("drop_pct", 2.0) or 2.0)
            pct = (price / reference_price - 1.0) * 100.0
            return f"{symbol} {price:.2f} · {pct:+.2f}% vs prior close (buys at -{drop:.1f}%)"
        if strat == StrategyKind.take_profit_stop:
            return f"{symbol} {price:.2f} · watching for take-profit / stop"
        return f"{symbol} {price:.2f} · evaluating {strat.value}"

    async def _heartbeat(self, bot: Bot, symbol: str, price: float, reference_price: float | None) -> None:
        # Throttle to ~once / 15s per bot so we don't hammer Redis on every tick.
        now = time.monotonic()
        if (now - self._last_health.get(bot.id, 0.0)) < 15.0:
            return
        self._last_health[bot.id] = now
        try:
            orders_today = await store.count_orders_today(bot.id)
        except Exception:
            orders_today = 0
        try:
            await health_mod.write(bot.id, {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "symbol": symbol,
                "price": round(price, 4),
                "note": self._status_note(bot, symbol, price, reference_price),
                "orders_today": orders_today,
                "market_open": market_open(),
                "is_leader": leader_lock.is_leader(),
                "regime": self._current_regime,
                "learned": bool(self._learned_overlay.get(bot.id)),
            })
        except Exception as exc:
            logger.debug("heartbeat write failed for bot %s: %s", bot.id, exc)

    async def _watchdog(self, active: list[Bot]) -> None:
        """Flag active bots whose heartbeat has gone stale during market hours
        by recording a warning event (which streams to the activity feed) — one
        warning per stale episode, plus a recovery note when it resumes. Runs
        only on the leader, only when the market is open."""
        now = datetime.now(timezone.utc)
        mono = time.monotonic()
        live_ids = {b.id for b in active}
        snaps = await health_mod.read_many(list(live_ids))
        # forget bots that are no longer active
        self._stale_warned &= live_ids
        for stale_id in list(self._watch_since):
            if stale_id not in live_ids:
                self._watch_since.pop(stale_id, None)

        for bot in active:
            snap = snaps.get(bot.id)
            reason: str | None = None
            if snap and snap.get("ts"):
                self._watch_since.pop(bot.id, None)
                try:
                    ts = datetime.fromisoformat(snap["ts"])
                    age = (now - ts).total_seconds()
                except ValueError:
                    age = 0.0
                if age > _STALE_SECONDS:
                    reason = f"no heartbeat for {int(age // 60)}m (last check {ts.strftime('%H:%M')} UTC) — engine not reaching this bot"
            else:
                first = self._watch_since.setdefault(bot.id, mono)
                if (mono - first) > _WARMUP_SECONDS:
                    reason = "no heartbeat since it went active — engine isn't evaluating this bot"

            if reason and bot.id not in self._stale_warned:
                self._stale_warned.add(bot.id)
                logger.warning("bot %s stale: %s", bot.id, reason)
                await executor_mod._emit(bot, "warning", {"action": "heartbeat_stale", "note": reason})
            elif not reason and bot.id in self._stale_warned:
                self._stale_warned.discard(bot.id)
                await executor_mod._emit(bot, "warning", {
                    "action": "heartbeat_recovered",
                    "note": "heartbeat resumed — bot is evaluating again",
                })

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

        # Reference price for threshold-style strategies (DCA): the PRIOR
        # close — never the current mark (which equals the live tick and would
        # make a "drop vs reference" impossible to detect). Prefer the bar
        # series' prior close; otherwise the latest quote's previous_close.
        # Without this, threshold_dca could never fire in the live loop.
        reference_price = closes[-2] if len(closes) >= 2 else None
        if reference_price is None:
            try:
                q = await data.get_stock_quote(symbol)
                if q and q.previous_close:
                    reference_price = q.previous_close
            except Exception:
                reference_price = None

        # Apply learned param overlay for the current regime (if available).
        active_params = dict(bot.config.params)
        overlay = self._learned_overlay.get(bot.id)
        if overlay:
            active_params = {**active_params, **overlay}

        ctx = StrategyContext(
            symbol=symbol, price=price, closes=closes or [price],
            position_qty=pos_qty, position_avg=pos_avg,
            equity=account.equity, position_market_value=pos_mv,
            reference_price=reference_price,
            params=active_params,
        )
        intents = evaluate(bot.config.strategy, ctx)
        # Heartbeat on EVERY eval (throttled), so "Active + empty feed" reads as
        # alive-and-waiting, with how far price is from triggering.
        await self._heartbeat(bot, symbol, price, reference_price)
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
                    # Daily-loss breach → pause the bot and stop processing any
                    # further intents this tick (they'd all be killed anyway).
                    await self._auto_pause(bot, decision.reason)
                    return
                continue
            await cooldowns.mark(bot.id, symbol, bot.guardrails.per_symbol_cooldown_seconds)
            fired_intent = decision.intent or intent
            result = await executor_mod.execute(bot, fired_intent, broker=broker)
            gctx.orders_today += 1  # reflect within this tick
            # Learning engine: log a trade-context snapshot for every fired intent.
            try:
                snap: dict = {
                    "price": price,
                    "reference_price": reference_price,
                    "closes_tail": (closes or [])[-5:],
                    "position_qty": pos_qty,
                    "position_avg": pos_avg,
                    "strategy": bot.config.strategy.value,
                    "active_params": active_params,
                    "regime": self._current_regime,
                    "learned_overlay": bool(overlay),
                }
                await outcome_store.log_trade(TradeOutcome(
                    bot_id=bot.id, user_id=bot.user_id,
                    bot_order_id=result.get("bot_order_id") if isinstance(result, dict) else None,
                    symbol=symbol, side=fired_intent.side,
                    price=price, qty=fired_intent.qty or 0.0,
                    regime=self._current_regime,
                    indicator_snap=snap,
                ))
            except Exception as exc:
                logger.debug("outcome log failed for bot %s: %s", bot.id, exc)

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
