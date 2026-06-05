"""Leader lock + cooldown store — Redis-backed with graceful fallback."""

import asyncio

import pytest

from backend.core import database as db_mod
from backend.core.bots.coordination import CooldownStore, LeaderLock


class FakeRedis:
    """Minimal async Redis double honoring SET NX/EX, GET, DELETE."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def get(self, key):
        return self.store.get(key)

    async def delete(self, key):
        self.store.pop(key, None)
        return 1


# ── leader lock ────────────────────────────────────────────────────────────


def test_leader_true_without_redis(monkeypatch):
    monkeypatch.setattr(db_mod.cache, "client", None, raising=False)
    lock = LeaderLock()
    assert asyncio.run(lock.acquire_or_renew()) is True
    assert lock.is_leader() is True


def test_leader_contention_with_redis(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(db_mod.cache, "client", fake, raising=False)
    a, b = LeaderLock(), LeaderLock()
    a.instance_id, b.instance_id = "A", "B"

    async def scenario():
        first = await a.acquire_or_renew()   # A takes the lock
        second = await b.acquire_or_renew()  # B contends, loses
        renew = await a.acquire_or_renew()   # A renews its own lock
        return first, second, renew

    first, second, renew = asyncio.run(scenario())
    assert first is True
    assert second is False
    assert renew is True


def test_leader_release_frees_lock(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(db_mod.cache, "client", fake, raising=False)
    a, b = LeaderLock(), LeaderLock()
    a.instance_id, b.instance_id = "A", "B"

    async def scenario():
        await a.acquire_or_renew()
        await a.release()
        return await b.acquire_or_renew()  # B can now take it

    assert asyncio.run(scenario()) is True


# ── cooldown store ───────────────────────────────────────────────────────────


def test_cooldown_inmemory_without_redis(monkeypatch):
    monkeypatch.setattr(db_mod.cache, "client", None, raising=False)
    cd = CooldownStore()

    async def scenario():
        assert await cd.age_seconds("bot1", "AAPL") is None
        await cd.mark("bot1", "AAPL", 300)
        age = await cd.age_seconds("bot1", "AAPL")
        return age

    age = asyncio.run(scenario())
    assert age is not None and age >= 0


def test_cooldown_redis_backed(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(db_mod.cache, "client", fake, raising=False)
    cd = CooldownStore()

    async def scenario():
        await cd.mark("bot1", "MSFT", 300)
        return await cd.age_seconds("bot1", "MSFT")

    age = asyncio.run(scenario())
    assert age is not None and age >= 0
    assert any("MSFT" in k for k in fake.store)
