"""Futures source: live via Massive (Polygon futures) when entitled, FRED
daily-spot fallback otherwise."""

import asyncio

import pytest

from backend.data.sources import futures_source as fs


@pytest.fixture(autouse=True)
def _restore_loop():
    # asyncio.run() closes its loop and leaves none current; restore a fresh
    # one so sibling tests relying on the implicit loop aren't disturbed.
    yield
    asyncio.set_event_loop(asyncio.new_event_loop())


class FakeMassive:
    configured = True

    async def futures_contracts(self, product, *, limit=12):
        months = ["09", "12", "03"][:limit]
        return [{"ticker": f"{product}{m}24", "expiration": f"2024-{m}-20"} for m in months]

    async def futures_recent_closes(self, ticker, *, limit=2):
        return [100.0, 95.0]


def test_dashboard_uses_massive_when_entitled(monkeypatch):
    monkeypatch.setattr(fs, "MassiveSource", lambda: FakeMassive())
    out = asyncio.run(fs.FuturesSource().dashboard())
    # every root resolves via Massive → live front-month tile
    assert len(out) == len(fs.ROOTS)
    cl = next(c for c in out if c.contract_symbol.startswith("CL"))
    assert cl.price == 100.0 and cl.change == 5.0
    assert "FRED" not in cl.contract_symbol  # came from Massive, not the FRED fallback
    assert cl.expiration == "2024-09-20"     # Massive contract metadata


def test_dashboard_falls_back_to_fred(monkeypatch):
    class NoMassive:
        configured = False

    monkeypatch.setattr(fs, "MassiveSource", lambda: NoMassive())

    async def fake_fred(root):
        return (50.0, 1.0, 2.0) if root in ("CL", "NG") else None

    monkeypatch.setattr(fs, "_fred_quote", fake_fred)
    out = asyncio.run(fs.FuturesSource().dashboard())
    assert len(out) == 2  # only CL/NG have a FRED fallback series
    assert all("FRED" in c.contract_symbol for c in out)


def test_curve_builds_term_structure_from_massive(monkeypatch):
    monkeypatch.setattr(fs, "MassiveSource", lambda: FakeMassive())
    curve = asyncio.run(fs.FuturesSource().get_curve("CL"))
    assert curve.root == "CL"
    assert len(curve.contracts) >= 2  # a real multi-contract curve
    assert curve.front_month_price == 100.0


def test_curve_unknown_root_is_graceful(monkeypatch):
    monkeypatch.setattr(fs, "MassiveSource", lambda: FakeMassive())
    curve = asyncio.run(fs.FuturesSource().get_curve("ZZ"))
    assert curve.contracts == []
