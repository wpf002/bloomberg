"""ConduitSource against a stub bridge.

The stub speaks the same newline-delimited JSON as the real one, so these tests
cover the framing, the id dispatch and the Quote mapping without needing Node,
Conduit or a vendor key.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap

import pytest

from backend.data.sources.conduit_source import (
    ConduitSource,
    ConduitUnavailable,
    _ns_to_datetime,
    _to_quote,
)

SNAPSHOT = {
    "kind": "snapshot",
    "symbol": "AAPL",
    "provider": "alpaca",
    "tsEvent": "1790366399911684512",
    "tsConduitRecv": "1790366399911999999",
    "lastPx": 341.02,
    "lastSz": 40,
    "bidPx": 319.05,
    "askPx": 0,
    "day": {"open": 335.955, "high": 341.67, "low": 334.6, "close": 341.02, "volume": 842202},
    "prevClose": 335.88,
}


def _stub_bridge(tmp_path, body: str) -> str:
    """A Python script that behaves like the bridge, so no Node is required."""
    script = tmp_path / "stub_bridge.py"
    script.write_text(textwrap.dedent(body))
    return str(script)


@pytest.fixture
def stub(tmp_path, monkeypatch):
    def build(body: str) -> ConduitSource:
        path = _stub_bridge(tmp_path, body)
        return ConduitSource(bridge_path=path, node_path=sys.executable, timeout=10.0)

    return build


WELL_BEHAVED = """
    import json, sys
    print(json.dumps({"type": "ready", "providers": ["alpaca"], "coverage": {}}), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req = json.loads(line)
        if req["op"] == "summary":
            rows = [dict(SNAPSHOT, symbol=s) for s in req["symbols"]]
            print(json.dumps({"type": "result", "id": req["id"], "data": rows}), flush=True)
        elif req["op"] == "health":
            print(json.dumps({"type": "result", "id": req["id"],
                              "data": {"alpaca": {"state": "healthy"}}}), flush=True)
        else:
            print(json.dumps({"type": "error", "id": req["id"], "code": "coverage",
                              "message": "nope"}), flush=True)
    SNAPSHOT = None
"""


def _with_snapshot(body: str) -> str:
    return f"SNAPSHOT = {json.dumps(SNAPSHOT)}\n" + textwrap.dedent(body)


class TestQuoteMapping:
    def test_maps_a_snapshot_to_a_quote(self):
        quote = _to_quote(SNAPSHOT)
        assert quote is not None
        assert quote.symbol == "AAPL"
        assert quote.price == pytest.approx(341.02)
        assert quote.previous_close == pytest.approx(335.88)
        assert quote.change == pytest.approx(5.14, abs=0.01)
        assert quote.change_percent == pytest.approx(1.53, abs=0.01)
        assert quote.volume == 842202
        assert quote.day_high == pytest.approx(341.67)

    def test_falls_back_to_the_day_close_when_there_is_no_last_trade(self):
        quote = _to_quote({**SNAPSHOT, "lastPx": None})
        assert quote is not None
        assert quote.price == pytest.approx(341.02)

    def test_returns_none_without_a_usable_price(self):
        assert _to_quote({**SNAPSHOT, "lastPx": None, "day": {}}) is None
        assert _to_quote({**SNAPSHOT, "lastPx": 0, "day": {"close": 0}}) is None

    def test_zero_change_when_there_is_no_previous_close(self):
        quote = _to_quote({**SNAPSHOT, "prevClose": None})
        assert quote is not None
        assert quote.change == 0.0
        assert quote.change_percent == 0.0

    def test_reads_nanoseconds_from_a_decimal_string(self):
        # JSON has no 64-bit int, so the bridge sends text. Parsing it as a float
        # would lose sub-second precision.
        parsed = _ns_to_datetime("1790366399911684512")
        assert parsed.year == 2026
        assert parsed.tzinfo is not None

    def test_survives_a_missing_or_junk_timestamp(self):
        for value in (None, "", "not a number", {}):
            assert _ns_to_datetime(value).tzinfo is not None


class TestDisabled:
    def test_is_disabled_without_a_bridge_path(self, monkeypatch):
        monkeypatch.delenv("CONDUIT_BRIDGE", raising=False)
        source = ConduitSource()
        assert source._enabled() is False
        assert source.credentials_configured() is False

    def test_is_disabled_when_the_path_does_not_exist(self):
        assert ConduitSource(bridge_path="/nonexistent/bridge.js")._enabled() is False

    @pytest.mark.asyncio
    async def test_returns_none_rather_than_raising_when_disabled(self):
        source = ConduitSource(bridge_path=None)
        # Callers fall back to another source on None, so a disabled Conduit must
        # not break them.
        assert await source.get_stock_quote("AAPL") is None
        assert await source.get_stock_quotes(["AAPL"]) == {}


class TestAgainstStubBridge:
    @pytest.mark.asyncio
    async def test_spawns_waits_for_ready_and_answers(self, stub):
        source = stub(_with_snapshot(WELL_BEHAVED))
        try:
            quote = await source.get_stock_quote("AAPL")
            assert quote is not None
            assert quote.price == pytest.approx(341.02)
            assert source.providers == ["alpaca"]
        finally:
            await source.aclose()

    @pytest.mark.asyncio
    async def test_one_request_for_several_symbols(self, stub):
        source = stub(_with_snapshot(WELL_BEHAVED))
        try:
            quotes = await source.get_stock_quotes(["AAPL", "MSFT", "SPY"])
            assert sorted(quotes) == ["AAPL", "MSFT", "SPY"]
        finally:
            await source.aclose()

    @pytest.mark.asyncio
    async def test_reuses_one_subprocess_across_calls(self, stub):
        source = stub(_with_snapshot(WELL_BEHAVED))
        try:
            await source.get_stock_quote("AAPL")
            first = source._proc
            await source.get_stock_quote("MSFT")
            assert source._proc is first
        finally:
            await source.aclose()

    @pytest.mark.asyncio
    async def test_concurrent_requests_do_not_cross_wires(self, stub):
        import asyncio

        source = stub(_with_snapshot(WELL_BEHAVED))
        try:
            results = await asyncio.gather(
                source.get_stock_quote("AAPL"),
                source.get_stock_quote("MSFT"),
                source.get_stock_quote("SPY"),
            )
            assert [q.symbol for q in results] == ["AAPL", "MSFT", "SPY"]
        finally:
            await source.aclose()

    @pytest.mark.asyncio
    async def test_reports_health(self, stub):
        source = stub(_with_snapshot(WELL_BEHAVED))
        try:
            assert (await source.health())["alpaca"]["state"] == "healthy"
        finally:
            await source.aclose()

    @pytest.mark.asyncio
    async def test_an_error_response_yields_no_quote(self, stub):
        source = stub(
            _with_snapshot("""
                import json, sys
                print(json.dumps({"type": "ready", "providers": [], "coverage": {}}), flush=True)
                for line in sys.stdin:
                    if not line.strip():
                        continue
                    req = json.loads(line)
                    print(json.dumps({"type": "error", "id": req["id"], "code": "coverage",
                                      "message": "no provider covers quote_l1"}), flush=True)
            """)
        )
        try:
            assert await source.get_stock_quote("AAPL") is None
        finally:
            await source.aclose()

    @pytest.mark.asyncio
    async def test_a_bridge_that_never_becomes_ready_is_unavailable(self, stub):
        source = stub("""
            import time
            time.sleep(30)
        """)
        source._timeout = 1.0
        try:
            with pytest.raises(ConduitUnavailable):
                await source._ensure_proc()
        finally:
            await source.aclose()

    @pytest.mark.asyncio
    async def test_a_bridge_that_dies_mid_request_fails_the_waiter(self, stub):
        source = stub("""
            import json, sys
            print(json.dumps({"type": "ready", "providers": [], "coverage": {}}), flush=True)
            sys.stdin.readline()
            sys.exit(1)
        """)
        try:
            # The reader loop must fail the pending future rather than hang it.
            assert await source.get_stock_quote("AAPL") is None
        finally:
            await source.aclose()

    @pytest.mark.asyncio
    async def test_ignores_an_unparseable_line(self, stub):
        source = stub(
            _with_snapshot("""
                import json, sys
                print(json.dumps({"type": "ready", "providers": [], "coverage": {}}), flush=True)
                for line in sys.stdin:
                    if not line.strip():
                        continue
                    req = json.loads(line)
                    print("this is not json", flush=True)
                    rows = [dict(SNAPSHOT, symbol=s) for s in req["symbols"]]
                    print(json.dumps({"type": "result", "id": req["id"], "data": rows}), flush=True)
            """)
        )
        try:
            quote = await source.get_stock_quote("AAPL")
            assert quote is not None
        finally:
            await source.aclose()

    @pytest.mark.asyncio
    async def test_aclose_is_idempotent(self, stub):
        source = stub(_with_snapshot(WELL_BEHAVED))
        await source.get_stock_quote("AAPL")
        await source.aclose()
        await source.aclose()
        assert source._proc is None
