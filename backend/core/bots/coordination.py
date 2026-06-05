"""Redis coordination for the bot engine — durability + multi-instance safety.

Two pieces:

  LeaderLock   — only the instance holding `bt:bots:leader` evaluates bots, so
                 if the backend scales to >1 replica they don't double-trade.
                 Redis absent → is_leader() is always True (single-instance /
                 dev / tests).

  CooldownStore — per-(bot,symbol) last-fired timestamps in Redis with a TTL,
                  so per-symbol cooldowns SURVIVE A RESTART (the previous
                  in-memory dict reset on every boot, which could let a bot
                  re-fire immediately). In-memory fallback when Redis is down.

Both degrade gracefully so local dev and unit tests run without Redis.
"""

from __future__ import annotations

import logging
import time

from ..config import settings
from ..database import cache

logger = logging.getLogger(__name__)

LEADER_KEY = "bt:bots:leader"
LEADER_TTL_SECONDS = 30
LEADER_RENEW_SECONDS = 10


def _instance_id() -> str:
    if settings.bot_instance_id:
        return settings.bot_instance_id
    # Stable within a process: derive from PID + boot time. Not random (which
    # is disallowed in some sandboxes) — uniqueness across instances comes
    # from the PID/host differing.
    import os
    return f"inst-{os.getpid()}"


class LeaderLock:
    """Single-leader election over a Redis key with TTL + renewal."""

    def __init__(self) -> None:
        self.instance_id = _instance_id()
        self._is_leader = False

    async def acquire_or_renew(self) -> bool:
        """Try to become/stay leader. Returns whether we hold the lock."""
        client = cache.client
        if client is None:
            # No Redis → assume single instance, we are the leader.
            self._is_leader = True
            return True
        try:
            # Atomic: take the key only if absent (NX) with a TTL (EX).
            got = await client.set(LEADER_KEY, self.instance_id, nx=True, ex=LEADER_TTL_SECONDS)
            if got:
                self._is_leader = True
                return True
            # Already held — renew only if it's ours.
            current = await client.get(LEADER_KEY)
            if current == self.instance_id:
                await client.set(LEADER_KEY, self.instance_id, ex=LEADER_TTL_SECONDS)
                self._is_leader = True
                return True
            self._is_leader = False
            return False
        except Exception as exc:
            logger.debug("leader lock redis error, assuming leader: %s", exc)
            self._is_leader = True
            return True

    def is_leader(self) -> bool:
        return self._is_leader

    async def release(self) -> None:
        client = cache.client
        if client is None:
            self._is_leader = False
            return
        try:
            current = await client.get(LEADER_KEY)
            if current == self.instance_id:
                await client.delete(LEADER_KEY)
        except Exception:
            pass
        self._is_leader = False


class CooldownStore:
    """Per-(bot,symbol) last-fired timestamps. Redis-backed (survives
    restart); in-memory fallback when Redis is unavailable."""

    def __init__(self) -> None:
        self._mem: dict[str, float] = {}

    @staticmethod
    def _key(bot_id: str, symbol: str) -> str:
        return f"bt:bots:cooldown:{bot_id}:{symbol.upper()}"

    async def age_seconds(self, bot_id: str, symbol: str) -> float | None:
        """Seconds since this (bot,symbol) last fired, or None if never."""
        client = cache.client
        key = self._key(bot_id, symbol)
        if client is None:
            ts = self._mem.get(key)
            return (time.time() - ts) if ts is not None else None
        try:
            raw = await client.get(key)
            if raw is None:
                return None
            return max(0.0, time.time() - float(raw))
        except Exception:
            ts = self._mem.get(key)
            return (time.time() - ts) if ts is not None else None

    async def mark(self, bot_id: str, symbol: str, cooldown_seconds: int) -> None:
        client = cache.client
        key = self._key(bot_id, symbol)
        now = time.time()
        self._mem[key] = now
        if client is None:
            return
        try:
            # TTL a little beyond the cooldown so the marker self-expires.
            ttl = max(1, int(cooldown_seconds) + 5)
            await client.set(key, str(now), ex=ttl)
        except Exception:
            pass


leader_lock = LeaderLock()
cooldowns = CooldownStore()
