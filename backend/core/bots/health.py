"""Per-bot heartbeat / health snapshot.

The manager writes a snapshot every time it evaluates a bot (throttled), so
"Active with an empty activity feed" is no longer ambiguous: the UI and any
monitor can see the bot is alive, when it last checked, the latest price, and
how far it is from triggering. Redis-backed with an in-memory fallback so it
works without Redis (dev/tests) and survives restarts in prod.
"""

from __future__ import annotations

import json
import logging

from ..database import cache

logger = logging.getLogger(__name__)

_PREFIX = "bt:bots:health:"
_TTL_SECONDS = 86_400  # a day; refreshed on every eval
_mem: dict[str, dict] = {}


async def write(bot_id: str, snapshot: dict) -> None:
    _mem[bot_id] = snapshot
    client = cache.client
    if client is None:
        return
    try:
        await client.set(f"{_PREFIX}{bot_id}", json.dumps(snapshot, default=str), ex=_TTL_SECONDS)
    except Exception as exc:
        logger.debug("bot health write failed: %s", exc)


async def read(bot_id: str) -> dict | None:
    client = cache.client
    if client is not None:
        try:
            raw = await client.get(f"{_PREFIX}{bot_id}")
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return _mem.get(bot_id)


async def read_many(bot_ids: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for bid in bot_ids:
        snap = await read(bid)
        if snap:
            out[bid] = snap
    return out
