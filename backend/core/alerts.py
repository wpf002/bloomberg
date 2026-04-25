"""Rule-based alert engine.

Storage:
  Rules live in Redis under `bt:alerts:rules` (a hash keyed by rule id).
  Fired events are appended to a Redis Stream `bt:alerts:events` so they
  survive a frontend reload — `XREVRANGE` gives us the recent feed.

Evaluation:
  Subscribes to the in-process `quotes` topic of `streaming.hub`. On every
  trade/quote/snapshot tick, evaluates all active rules for that symbol
  against the latest cached price. A per-rule cooldown prevents storm-fire
  while a condition stays true.

If Redis isn't connected, rules are kept in a process-local dict so the
panel still works for development. Persistence is a nice-to-have, not a
correctness boundary.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from ..models.schemas import AlertCondition, AlertEvent, AlertRule
from .database import cache
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
        self._fallback_rules: dict[str, AlertRule] = {}
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

    async def list_rules(self) -> list[AlertRule]:
        client = cache.client
        if client is None:
            return list(self._fallback_rules.values())
        try:
            raw = await client.hgetall(RULES_HASH)
        except Exception as exc:
            logger.debug("alerts redis hgetall failed: %s", exc)
            return list(self._fallback_rules.values())
        out: list[AlertRule] = []
        for v in raw.values():
            try:
                out.append(AlertRule.model_validate_json(v))
            except Exception:
                continue
        return out

    async def add_rule(
        self,
        symbol: str,
        conditions: list[AlertCondition],
        name: str | None = None,
        cooldown_seconds: int = 300,
    ) -> AlertRule:
        rule = AlertRule(
            id=uuid.uuid4().hex[:12],
            symbol=symbol.upper(),
            name=name,
            conditions=conditions,
            cooldown_seconds=cooldown_seconds,
            active=True,
        )
        client = cache.client
        if client is None:
            self._fallback_rules[rule.id] = rule
            return rule
        try:
            await client.hset(RULES_HASH, rule.id, rule.model_dump_json())
        except Exception as exc:
            logger.debug("alerts redis hset failed, falling back: %s", exc)
            self._fallback_rules[rule.id] = rule
        return rule

    async def delete_rule(self, rule_id: str) -> bool:
        client = cache.client
        if client is None:
            return self._fallback_rules.pop(rule_id, None) is not None
        try:
            removed = await client.hdel(RULES_HASH, rule_id)
            return bool(removed)
        except Exception:
            return self._fallback_rules.pop(rule_id, None) is not None

    async def recent_events(self, limit: int = 50) -> list[AlertEvent]:
        client = cache.client
        if client is None:
            return list(reversed(self._fallback_events[-limit:]))
        try:
            entries = await client.xrevrange(EVENTS_STREAM, count=limit)
        except Exception as exc:
            logger.debug("alerts xrevrange failed: %s", exc)
            return list(reversed(self._fallback_events[-limit:]))
        out: list[AlertEvent] = []
        for _id, fields in entries:
            try:
                payload = fields.get("payload") if isinstance(fields, dict) else None
                if payload:
                    out.append(AlertEvent.model_validate_json(payload))
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
        rules = [r for r in await self.list_rules() if r.active and r.symbol == sym]
        if not rules:
            return
        now_mono = time.monotonic()
        for rule in rules:
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
            )
            await self._record_event(event)
            await hub.publish("alerts", event.model_dump(mode="json"))

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
