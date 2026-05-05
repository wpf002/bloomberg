"""V2.3 — Options-flow endpoint structure + filter param tests.

We don't hit the live Unusual Whales / BullFlow APIs in CI. Without
keys configured, every endpoint must return an empty payload tagged
with `needs_key=True` instead of raising. Filters and sector
aggregation are exercised against an in-process aggregator so we
verify the pure logic here.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api.routes.flow import (
    SECTOR_MAP,
    _aggregate_sectors,
    _filter_items,
    _sector_for,
)
from backend.main import app


def _client() -> TestClient:
    return TestClient(app)


def test_options_endpoint_responds_when_no_keys_configured():
    with _client() as c:
        r = c.get("/api/flow/options")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["needs_key"] is True
    assert "sources_configured" in body
    assert body["filters"]["min_premium"] == 100_000.0


def test_darkpool_endpoint_responds_when_no_keys_configured():
    with _client() as c:
        r = c.get("/api/flow/darkpool")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["needs_key"] is True


def test_sweeps_endpoint_responds_when_no_keys_configured():
    with _client() as c:
        r = c.get("/api/flow/sweeps")
    assert r.status_code == 200
    assert r.json()["needs_key"] is True


def test_unusual_endpoint_responds_when_no_keys_configured():
    with _client() as c:
        r = c.get("/api/flow/unusual")
    assert r.status_code == 200
    assert r.json()["needs_key"] is True


def test_heatmap_endpoint_responds_when_no_keys_configured():
    with _client() as c:
        r = c.get("/api/flow/heatmap")
    assert r.status_code == 200
    body = r.json()
    assert body["buckets"] == []
    assert body["needs_key"] is True


def test_filter_min_premium_drops_small_trades():
    items = [
        {"symbol": "AAPL", "side": "bullish", "premium": 50_000.0},
        {"symbol": "AAPL", "side": "bullish", "premium": 250_000.0},
    ]
    out = _filter_items(items, side="all", min_premium=100_000.0, sector=None)
    assert len(out) == 1
    assert out[0]["premium"] == 250_000.0


def test_filter_side_keeps_only_bullish_when_requested():
    items = [
        {"symbol": "AAPL", "side": "bullish", "premium": 200_000.0},
        {"symbol": "AAPL", "side": "bearish", "premium": 200_000.0},
    ]
    out = _filter_items(items, side="bullish", min_premium=0.0, sector=None)
    assert len(out) == 1
    assert out[0]["side"] == "bullish"


def test_filter_sector_isolates_one_industry():
    items = [
        {"symbol": "AAPL", "side": "bullish", "premium": 200_000.0},
        {"symbol": "JPM",  "side": "bullish", "premium": 200_000.0},
    ]
    out = _filter_items(items, side="all", min_premium=0.0, sector="Financials")
    assert len(out) == 1
    assert out[0]["symbol"] == "JPM"


def test_sector_for_known_ticker():
    assert _sector_for("AAPL") == "Technology"
    assert _sector_for("JPM") == "Financials"
    assert _sector_for("XOM") == "Energy"
    assert _sector_for("ZZZUNKNOWN") == "Other"


def test_aggregate_sectors_emits_one_bucket_per_sector_plus_other():
    items = [
        {"symbol": "AAPL", "side": "bullish", "premium": 1_000_000.0},
        {"symbol": "AAPL", "side": "bearish", "premium":   400_000.0},
        {"symbol": "JPM",  "side": "bullish", "premium":   500_000.0},
    ]
    buckets = _aggregate_sectors(items)
    sectors = {b.sector for b in buckets}
    # Must contain every defined sector + "Other"
    for s in SECTOR_MAP.keys():
        assert s in sectors
    assert "Other" in sectors
    tech = next(b for b in buckets if b.sector == "Technology")
    assert tech.bullish_premium == 1_000_000.0
    assert tech.bearish_premium == 400_000.0
    assert tech.net_premium == 600_000.0
    assert tech.trade_count == 2
    assert 0.0 < tech.bullish_dominance <= 1.0
    fin = next(b for b in buckets if b.sector == "Financials")
    assert fin.net_premium == 500_000.0


def test_aggregate_sectors_balanced_dominance_for_zero_premium():
    items = [{"symbol": "AAPL", "side": "neutral", "premium": 0.0}]
    buckets = _aggregate_sectors(items)
    tech = next(b for b in buckets if b.sector == "Technology")
    assert tech.bullish_dominance == 0.5
