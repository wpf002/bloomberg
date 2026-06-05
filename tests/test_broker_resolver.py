"""Broker resolver — per-user keys, paper/live gating, robinhood scaffold."""

import asyncio

import pytest

from backend.core.brokers import resolver
from backend.core.brokers.base import BrokerNotConfigured, BrokerNotWired
from backend.core.config import settings
from backend.data.sources.alpaca_source import AlpacaSource


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    # Default: no live, no robinhood, no per-user keys (DB unavailable in tests).
    monkeypatch.setattr(settings, "bots_allow_live", False, raising=False)
    monkeypatch.setattr(settings, "robinhood_enabled", False, raising=False)
    monkeypatch.setattr(settings, "alpaca_api_key", "envkey", raising=False)
    monkeypatch.setattr(settings, "alpaca_api_secret", "envsecret", raising=False)
    yield


def test_paper_falls_back_to_env_keys():
    broker = asyncio.run(resolver.resolve_execution_broker(1, "alpaca", "paper"))
    assert isinstance(broker, AlpacaSource)
    assert broker.mode == "paper"
    assert broker.credentials_configured()


def test_paper_without_any_keys_raises(monkeypatch):
    monkeypatch.setattr(settings, "alpaca_api_key", None, raising=False)
    monkeypatch.setattr(settings, "alpaca_api_secret", None, raising=False)
    with pytest.raises(BrokerNotConfigured):
        asyncio.run(resolver.resolve_execution_broker(1, "alpaca", "paper"))


def test_live_blocked_without_master_switch():
    with pytest.raises(BrokerNotConfigured):
        asyncio.run(resolver.resolve_execution_broker(1, "alpaca", "live"))


def test_live_enabled_but_no_live_keys_raises(monkeypatch):
    monkeypatch.setattr(settings, "bots_allow_live", True, raising=False)
    monkeypatch.setattr(settings, "alpaca_live_api_key", None, raising=False)
    monkeypatch.setattr(settings, "alpaca_live_api_secret", None, raising=False)
    # no per-user live keys, no env live keys → refuse (never fall back to PAPER env)
    with pytest.raises(BrokerNotConfigured):
        asyncio.run(resolver.resolve_execution_broker(1, "alpaca", "live"))


def test_live_uses_env_live_keys_when_set(monkeypatch):
    monkeypatch.setattr(settings, "bots_allow_live", True, raising=False)
    monkeypatch.setattr(settings, "alpaca_live_api_key", "LIVEKEY", raising=False)
    monkeypatch.setattr(settings, "alpaca_live_api_secret", "LIVESECRET", raising=False)
    broker = asyncio.run(resolver.resolve_execution_broker(1, "alpaca", "live"))
    assert isinstance(broker, AlpacaSource)
    assert broker.mode == "live"
    assert broker._api_key == "LIVEKEY"


def test_live_does_not_use_paper_env_keys(monkeypatch):
    # paper env keys present, live env keys absent → live must still refuse
    monkeypatch.setattr(settings, "bots_allow_live", True, raising=False)
    monkeypatch.setattr(settings, "alpaca_api_key", "PAPERKEY", raising=False)
    monkeypatch.setattr(settings, "alpaca_api_secret", "PAPERSECRET", raising=False)
    monkeypatch.setattr(settings, "alpaca_live_api_key", None, raising=False)
    monkeypatch.setattr(settings, "alpaca_live_api_secret", None, raising=False)
    with pytest.raises(BrokerNotConfigured):
        asyncio.run(resolver.resolve_execution_broker(1, "alpaca", "live"))


def test_live_with_user_keys_resolves(monkeypatch):
    monkeypatch.setattr(settings, "bots_allow_live", True, raising=False)

    async def fake_get(user_id, broker, mode):
        return ("livekey", "livesecret") if mode == "live" else None

    monkeypatch.setattr(resolver, "get_decrypted", fake_get)
    broker = asyncio.run(resolver.resolve_execution_broker(1, "alpaca", "live"))
    assert isinstance(broker, AlpacaSource)
    assert broker.mode == "live"


def test_user_keys_preferred_over_env(monkeypatch):
    async def fake_get(user_id, broker, mode):
        return ("userkey", "usersecret")

    monkeypatch.setattr(resolver, "get_decrypted", fake_get)
    broker = asyncio.run(resolver.resolve_execution_broker(7, "alpaca", "paper"))
    assert broker._api_key == "userkey"


def test_robinhood_disabled_raises():
    with pytest.raises(BrokerNotWired):
        asyncio.run(resolver.resolve_execution_broker(1, "robinhood", "live"))


def test_unknown_broker_raises():
    with pytest.raises(BrokerNotConfigured):
        asyncio.run(resolver.resolve_execution_broker(1, "etrade", "paper"))
