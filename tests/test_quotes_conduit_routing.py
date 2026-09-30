"""Conduit's position in the quote chain in backend/api/routes/quotes.py.

The source itself is covered by tests/test_conduit_source.py. What matters here is the routing:
with nothing configured the chain must behave exactly as it did before Conduit existed, and when
Conduit is configured it must be tried first and must not be able to break the request if it fails.
"""

import pytest

from backend.api.routes import quotes as quotes_route
from backend.models.schemas import Quote


def _quote(symbol: str, price: float) -> Quote:
    return Quote(symbol=symbol, price=price)


class _StubConduit:
    def __init__(self, *, configured: bool, result=None, raises: Exception | None = None):
        self._configured = configured
        self._result = result
        self._raises = raises
        self.calls: list[str] = []

    def credentials_configured(self) -> bool:
        return self._configured

    async def get_stock_quote(self, symbol: str):
        self.calls.append(symbol)
        if self._raises is not None:
            raise self._raises
        return self._result


class _StubAlpaca:
    def __init__(self, result=None):
        self._result = result
        self.calls: list[str] = []

    async def get_stock_quote(self, symbol: str):
        self.calls.append(symbol)
        return self._result


@pytest.fixture
def wire(monkeypatch):
    def _wire(conduit: _StubConduit, alpaca: _StubAlpaca):
        monkeypatch.setattr(quotes_route, "_conduit", conduit)
        monkeypatch.setattr(quotes_route, "_alpaca", alpaca)
        return conduit, alpaca

    return _wire


@pytest.mark.asyncio
async def test_unconfigured_conduit_is_not_consulted_at_all(wire):
    """The default. CONDUIT_BRIDGE unset must leave the previous chain untouched."""
    conduit, alpaca = wire(
        _StubConduit(configured=False, result=_quote("AAPL", 1.0)),
        _StubAlpaca(_quote("AAPL", 341.02)),
    )
    got = await quotes_route._best_quote("aapl")
    assert got.price == 341.02
    assert conduit.calls == []
    assert alpaca.calls == ["AAPL"]


@pytest.mark.asyncio
async def test_configured_conduit_serves_the_quote_and_alpaca_is_not_called(wire):
    conduit, alpaca = wire(
        _StubConduit(configured=True, result=_quote("AAPL", 341.02)),
        _StubAlpaca(_quote("AAPL", 999.0)),
    )
    got = await quotes_route._best_quote("AAPL")
    assert got.price == 341.02
    assert conduit.calls == ["AAPL"]
    assert alpaca.calls == []


@pytest.mark.asyncio
async def test_a_conduit_that_returns_nothing_falls_through(wire):
    conduit, alpaca = wire(
        _StubConduit(configured=True, result=None),
        _StubAlpaca(_quote("AAPL", 341.02)),
    )
    got = await quotes_route._best_quote("AAPL")
    assert got.price == 341.02
    assert alpaca.calls == ["AAPL"]


@pytest.mark.asyncio
async def test_a_conduit_that_raises_cannot_break_the_request(wire):
    """A new dependency in front of a working one must not be able to take the endpoint down."""
    conduit, alpaca = wire(
        _StubConduit(configured=True, raises=RuntimeError("bridge died")),
        _StubAlpaca(_quote("AAPL", 341.02)),
    )
    got = await quotes_route._best_quote("AAPL")
    assert got.price == 341.02
    assert alpaca.calls == ["AAPL"]


@pytest.mark.asyncio
async def test_symbol_is_upper_cased_before_conduit_sees_it(wire):
    conduit, _ = wire(
        _StubConduit(configured=True, result=_quote("BRK.B", 500.0)),
        _StubAlpaca(None),
    )
    await quotes_route._best_quote("brk.b")
    assert conduit.calls == ["BRK.B"]
