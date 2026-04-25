"""Rule-based alert engine.

Storage:
  - **Authenticated users** (since Phase 7): rules persist to Postgres
    `user_alert_rules` (PK id, user_id, payload jsonb). The engine evaluates
    them across the same hub topics as global rules.
  - **Unauthenticated / legacy** rules live in a Redis hash
    `bt:alerts:rules` for back-compat with deployments that don't have OAuth
    set up.
  - Fired events go to Redis Stream `bt:alerts:events` (user_id-tagged) so
    `XREVRANGE` gives us the recent feed; per-user feed filters by user_id.

Evaluation:
  Subscribes to the in-process `quotes` topic of `streaming.hub`. On every
  trade/quote/snapshot tick, evaluates all active rules for that symbol
  against the latest cached price. A per-rule cooldown prevents storm-fire
  while a condition stays true.

Fan-out:
  Events are published to two hub topics:
    `alerts`              — back-compat global topic (unauth WS subscribers)
    `alerts:user:{id}`    — per-user topic, only gets that user's fires
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from ..models.schemas import AlertCondition, AlertEvent, AlertRule
from .database import cache, database
from .streaming import hub, iter_topic

logger = logging.getLogger(__name__)

RULES_HASH = "bt:alerts:rules"
EVENTS_STREAM = "bt:alerts:events"
EVENTS_MAXLEN = 500


def _condition_matches(field_value: float | None, op: str, target: float) -> bool:
    if field_value is None:
        return False
    try:
        v = float(field_value)
    except (TypeError, ValueError):
        return False
    if op == ">":
        return v > target
    if op == "<":
        return v < target
    if op == ">=":
        return v >= target
    if op == "<=":
        return v <= target
    if op == "==":
        return abs(v - target) < 1e-9
    return False


class AlertEngine:
    """Evaluate alert rules against the streaming hub."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._fallback_rules: dict[str, tuple[int | None, AlertRule]] = {}
        self._fallback_events: list[AlertEvent] = []
        self._last_fired: dict[str, float] = {}  # rule_id -> monotonic seconds
        # Track latest snapshot per symbol so multi-condition rules can
        # check derived fields that aren't in every trade tick.
        self._snapshots: dict[str, dict] = {}

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="alert-engine")

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    # ── rules CRUD ──────────────────────────────────────────────────────

    async def list_rules(self, user_id: int | None = None) -> list[AlertRule]:
        """Return rules visible to the given user.

        - `user_id is None`: legacy view — returns Redis-backed global rules.
        - `user_id is set`: returns that user's Postgres-backed rules.
        """
        if user_id is None:
            return await self._list_global_rules()
        return await self._list_user_rules(user_id)

    async def _list_global_rules(self) -> list[AlertRule]:
        client = cache.client
        if client is None:
            return [
                rule for (uid, rule) in self._fallback_rules.values() if uid is None
            ]
        try:
            raw = await client.hgetall(RULES_HASH)
        except Exception as exc:
            logger.debug("alerts redis hgetall failed: %s", exc)
            return [
                rule for (uid, rule) in self._fallback_rules.values() if uid is None
            ]
        out: list[AlertRule] = []
        for v in raw.values():
            try:
                out.append(AlertRule.model_validate_json(v))
            except Exception:
                continue
        return out

    async def _list_user_rules(self, user_id: int) -> list[AlertRule]:
        if database.pool is None:
            return [
                rule
                for (uid, rule) in self._fallback_rules.values()
                if uid == user_id
            ]
        async with database.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, payload FROM user_alert_rules WHERE user_id = $1 ORDER BY created_at",
                user_id,
            )
        out: list[AlertRule] = []
        for row in rows:
            payload = row["payload"]
            try:
                if isinstance(payload, str):
                    out.append(AlertRule.model_validate_json(payload))
                else:
                    out.append(AlertRule.model_validate(payload))
            except Exception:
                continue
        return out

    async def list_all_rules(self) -> list[tuple[int | None, AlertRule]]:
        """Every active rule across every user — used by the eval loop. The
        first element of each tuple is the owning user id (None for legacy
        global rules)."""
        out: list[tuple[int | None, AlertRule]] = []
        for rule in await self._list_global_rules():
            out.append((None, rule))
        if database.pool is not None:
            try:
                async with database.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT user_id, payload FROM user_alert_rules"
                    )
                for row in rows:
                    payload = row["payload"]
                    try:
                        if isinstance(payload, str):
                            rule = AlertRule.model_validate_json(payload)
                        else:
                            rule = AlertRule.model_validate(payload)
                        out.append((int(row["user_id"]), rule))
                    except Exception:
                        continue
            except Exception as exc:
                logger.debug("alerts list_all_rules pg fetch failed: %s", exc)
        # Fallback in-memory rules (used when Redis + Postgres both down).
        for (uid, rule) in self._fallback_rules.values():
            out.append((uid, rule))
        return out

    async def add_rule(
        self,
        symbol: str,
        conditions: list[AlertCondition],
        name: str | None = None,
        cooldown_seconds: int = 300,
        user_id: int | None = None,
    ) -> AlertRule:
        rule = AlertRule(
            id=uuid.uuid4().hex[:12],
            symbol=symbol.upper(),
            name=name,
            conditions=conditions,
            cooldown_seconds=cooldown_seconds,
            active=True,
        )
        if user_id is not None and database.pool is not None:
            try:
                async with database.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO user_alert_rules (id, user_id, payload)
                        VALUES ($1, $2, $3::jsonb)
                        """,
                        rule.id,
                        user_id,
                        rule.model_dump_json(),
                    )
                return rule
            except Exception as exc:
                logger.warning("alerts pg insert failed, falling back: %s", exc)
                self._fallback_rules[rule.id] = (user_id, rule)
                return rule
        # Unauth path → Redis global hash (back-compat).
        client = cache.client
        if client is None:
            self._fallback_rules[rule.id] = (None, rule)
            return rule
        try:
            await client.hset(RULES_HASH, rule.id, rule.model_dump_json())
        except Exception as exc:
            logger.debug("alerts redis hset failed, falling back: %s", exc)
            self._fallback_rules[rule.id] = (None, rule)
        return rule

    async def delete_rule(self, rule_id: str, user_id: int | None = None) -> bool:
        # Try Postgres first when authenticated — only allow deleting your
        # own rule.
        if user_id is not None and database.pool is not None:
            try:
                async with database.acquire() as conn:
                    out = await conn.execute(
                        "DELETE FROM user_alert_rules WHERE id = $1 AND user_id = $2",
                        rule_id,
                        user_id,
                    )
                if out and out.endswith(" 1"):
                    return True
            except Exception as exc:
                logger.debug("alerts pg delete failed: %s", exc)
        # Then global (Redis).
        client = cache.client
        if client is not None:
            try:
                removed = await client.hdel(RULES_HASH, rule_id)
                if removed:
                    return True
            except Exception:
                pass
        # Finally fallback.
        existed = self._fallback_rules.pop(rule_id, None) is not None
        return existed

    async def recent_events(
        self, limit: int = 50, user_id: int | None = None
    ) -> list[AlertEvent]:
        client = cache.client
        if client is None:
            events = list(reversed(self._fallback_events[-limit * 4:]))
            if user_id is not None:
                events = [e for e in events if e.user_id == user_id]
            return events[:limit]
        try:
            entries = await client.xrevrange(EVENTS_STREAM, count=limit * 4)
        except Exception as exc:
            logger.debug("alerts xrevrange failed: %s", exc)
            return []
        out: list[AlertEvent] = []
        for _id, fields in entries:
            try:
                payload = fields.get("payload") if isinstance(fields, dict) else None
                if not payload:
                    continue
                event = AlertEvent.model_validate_json(payload)
                if user_id is not None and event.user_id != user_id:
                    continue
                out.append(event)
                if len(out) >= limit:
                    break
            except Exception:
                continue
        return out

    # ── evaluation loop ────────────────────────────────────────────────

    async def _run(self) -> None:
        async for msg in iter_topic("quotes"):
            try:
                await self._on_tick(msg)
            except Exception as exc:
                logger.debug("alert eval error: %s", exc)

    def _ingest_tick(self, msg: dict) -> None:
        sym = (msg.get("symbol") or "").upper()
        if not sym:
            return
        snap = self._snapshots.setdefault(sym, {})
        if msg.get("type") == "trade":
            snap["price"] = float(msg.get("price") or snap.get("price") or 0.0)
            snap["volume"] = int(msg.get("size") or 0) + int(snap.get("volume") or 0)
        elif msg.get("type") == "quote":
            mid = (float(msg.get("bid") or 0.0) + float(msg.get("ask") or 0.0)) / 2 or snap.get("price")
            if mid:
                snap["price"] = mid
        elif msg.get("type") in ("snapshot", "synthetic"):
            for key in ("price", "change_percent", "day_high", "day_low"):
                if msg.get(key) is not None:
                    snap[key] = msg[key]

    async def _on_tick(self, msg: dict) -> None:
        self._ingest_tick(msg)
        sym = (msg.get("symbol") or "").upper()
        if not sym:
            return
        snap = self._snapshots.get(sym, {})
        all_rules = await self.list_all_rules()
        relevant = [(uid, r) for (uid, r) in all_rules if r.active and r.symbol == sym]
        if not relevant:
            return
        now_mono = time.monotonic()
        for user_id, rule in relevant:
            cooldown_ok = (now_mono - self._last_fired.get(rule.id, 0.0)) >= rule.cooldown_seconds
            if not cooldown_ok:
                continue
            if not all(_condition_matches(snap.get(c.field), c.op, c.value) for c in rule.conditions):
                continue
            self._last_fired[rule.id] = now_mono
            event = AlertEvent(
                rule_id=rule.id,
                symbol=rule.symbol,
                name=rule.name,
                matched_at=datetime.now(timezone.utc),
                snapshot={k: snap.get(k) for k in ("price", "change_percent", "day_high", "day_low")},
                user_id=user_id,
            )
            await self._record_event(event)
            # Always publish to the global topic for back-compat with old
            # AlertsPanel deployments. Also publish to the user-specific
            # topic so signed-in users don't see other users' fires.
            await hub.publish("alerts", event.model_dump(mode="json"))
            if user_id is not None:
                await hub.publish(f"alerts:user:{user_id}", event.model_dump(mode="json"))

    async def _record_event(self, event: AlertEvent) -> None:
        client = cache.client
        if client is None:
            self._fallback_events.append(event)
            return
        try:
            await client.xadd(
                EVENTS_STREAM,
                {"payload": event.model_dump_json()},
                maxlen=EVENTS_MAXLEN,
                approximate=True,
            )
        except Exception as exc:
            logger.debug("alerts xadd failed: %s", exc)
            self._fallback_events.append(event)


engine = AlertEngine()
