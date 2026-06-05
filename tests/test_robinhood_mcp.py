"""Robinhood MCP client — JSON-RPC transport + tool mapping (httpx mocked)."""

import asyncio
import json

import httpx
import pytest

from backend.core.brokers import robinhood_mcp as rh
from backend.core.brokers.base import BrokerError, BrokerNotConfigured, BrokerNotWired
from backend.core.config import settings


class FakeResponse:
    def __init__(self, body: dict, status_code=200, sse=False, headers=None):
        self._body = body
        self.status_code = status_code
        self.headers = headers or {"content-type": "text/event-stream" if sse else "application/json"}
        if sse:
            self.text = f"event: message\ndata: {json.dumps(body)}\n\n"
        else:
            self.text = json.dumps(body)

    def json(self):
        return self._body


def _patch_post(monkeypatch, handler):
    """Patch httpx.AsyncClient.post to route to `handler(payload)->FakeResponse`."""

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, headers=None, json=None):
            return handler(json)

    monkeypatch.setattr(rh.httpx, "AsyncClient", FakeClient)


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    monkeypatch.setattr(settings, "robinhood_enabled", True, raising=False)
    monkeypatch.setattr(settings, "robinhood_mcp_endpoint", "https://rh.example/mcp", raising=False)
    monkeypatch.setattr(settings, "robinhood_mcp_token", "tok", raising=False)
    for attr in ("robinhood_tool_account", "robinhood_tool_positions",
                 "robinhood_tool_place_order", "robinhood_tool_cancel_order"):
        monkeypatch.setattr(settings, attr, None, raising=False)
    yield


def test_rpc_requires_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "robinhood_mcp_endpoint", None, raising=False)
    broker = rh.RobinhoodMcpBroker()
    with pytest.raises(BrokerNotConfigured):
        asyncio.run(broker._rpc("initialize"))


def test_list_tools_parses_result(monkeypatch):
    def handler(payload):
        if payload["method"] == "initialize":
            return FakeResponse({"jsonrpc": "2.0", "id": payload["id"], "result": {"protocolVersion": "x"}})
        if payload["method"] == "tools/list":
            return FakeResponse({"jsonrpc": "2.0", "id": payload["id"],
                                 "result": {"tools": [{"name": "get_account"}, {"name": "place_order"}]}})
        return FakeResponse({"jsonrpc": "2.0", "id": payload["id"], "result": {}})

    _patch_post(monkeypatch, handler)
    tools = asyncio.run(rh.RobinhoodMcpBroker().list_tools())
    assert [t["name"] for t in tools] == ["get_account", "place_order"]


def test_rpc_raises_on_jsonrpc_error(monkeypatch):
    def handler(payload):
        return FakeResponse({"jsonrpc": "2.0", "id": payload["id"], "error": {"code": -32000, "message": "nope"}})

    _patch_post(monkeypatch, handler)
    with pytest.raises(BrokerError):
        asyncio.run(rh.RobinhoodMcpBroker()._rpc("tools/list"))


def test_sse_response_is_parsed(monkeypatch):
    def handler(payload):
        return FakeResponse({"jsonrpc": "2.0", "id": payload["id"], "result": {"tools": []}}, sse=True)

    _patch_post(monkeypatch, handler)
    tools = asyncio.run(rh.RobinhoodMcpBroker().list_tools())
    assert tools == []


def test_place_order_refused_without_tool_mapping(monkeypatch):
    # place-order tool name unset → must refuse (no guessing with real money)
    def handler(payload):
        return FakeResponse({"jsonrpc": "2.0", "id": payload["id"], "result": {}})

    _patch_post(monkeypatch, handler)
    from backend.models.schemas import OrderRequest
    broker = rh.RobinhoodMcpBroker()
    with pytest.raises(BrokerNotWired):
        asyncio.run(broker.place_order(OrderRequest(symbol="AAPL", qty=1, side="buy")))


def test_get_account_maps_configured_tool(monkeypatch):
    monkeypatch.setattr(settings, "robinhood_tool_account", "get_account", raising=False)

    def handler(payload):
        if payload["method"] == "tools/call":
            return FakeResponse({"jsonrpc": "2.0", "id": payload["id"], "result": {
                "structuredContent": {"equity": 1000, "buying_power": 500, "cash": 500, "portfolio_value": 1000}
            }})
        return FakeResponse({"jsonrpc": "2.0", "id": payload["id"], "result": {}})

    _patch_post(monkeypatch, handler)
    acct = asyncio.run(rh.RobinhoodMcpBroker().get_account())
    assert acct.equity == 1000 and acct.buying_power == 500 and acct.source == "robinhood"
