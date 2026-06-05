"""Per-account cache isolation — different accounts must not collide on a
shared cache key (matters for live multi-account sizing)."""

import asyncio

from backend.core import cache_utils
from backend.core import database as db_mod
from backend.core.cache_utils import cached
from backend.data.sources.alpaca_source import AlpacaSource


def test_alpaca_salt_differs_by_account():
    a = AlpacaSource(api_key="KEY_A", api_secret="s", base_url="https://paper-api.alpaca.markets")
    b = AlpacaSource(api_key="KEY_B", api_secret="s", base_url="https://paper-api.alpaca.markets")
    same = AlpacaSource(api_key="KEY_A", api_secret="s", base_url="https://paper-api.alpaca.markets")
    assert a._cache_key_salt and b._cache_key_salt
    assert a._cache_key_salt != b._cache_key_salt          # different account → different keyspace
    assert a._cache_key_salt == same._cache_key_salt        # same account → shared keyspace
    # live vs paper for the same key also separate (different host)
    live = AlpacaSource(api_key="KEY_A", api_secret="s", base_url="https://api.alpaca.markets")
    assert live._cache_key_salt != a._cache_key_salt


def test_cached_keys_isolated_by_salt(monkeypatch):
    """Two instances with different salts hit different cache keys and so see
    their own values (no cross-account leakage)."""

    class FakeRedis:
        def __init__(self):
            self.store = {}
            self.keys_seen = []

        async def get(self, key):
            self.keys_seen.append(key)
            return self.store.get(key)

        async def setex(self, key, ttl, value):
            self.store[key] = value

    fake = FakeRedis()
    monkeypatch.setattr(db_mod.cache, "client", fake, raising=False)

    class Source:
        def __init__(self, salt, value):
            self._cache_key_salt = salt
            self._value = value

        @cached("acct", ttl=10, model=None)
        async def get_account(self):
            return {"v": self._value}

    a = Source("saltA", "A")
    b = Source("saltB", "B")

    async def scenario():
        ra = await a.get_account()   # miss → stores under salt A
        rb = await b.get_account()   # miss → stores under salt B (no collision)
        ra2 = await a.get_account()  # hit under salt A
        return ra, rb, ra2

    ra, rb, ra2 = asyncio.run(scenario())
    assert ra["v"] == "A"
    assert rb["v"] == "B"      # would be "A" if keys collided
    assert ra2["v"] == "A"
    # both salts appear in the keys that were queried
    assert any("saltA" in k for k in fake.keys_seen)
    assert any("saltB" in k for k in fake.keys_seen)
