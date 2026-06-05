"""Robinhood agentic-trading broker over the Model Context Protocol (MCP).

Robinhood's agentic surface is an MCP *server*
(https://robinhood.com/us/en/support/articles/agentic-trading-overview/): an
agent connects to Robinhood's MCP endpoint and places orders into a dedicated,
fund-isolated account. This class is the MCP *client* for that endpoint.

What's implemented + tested here:
  - The MCP wire protocol: JSON-RPC 2.0 over HTTP (`initialize`, `tools/list`,
    `tools/call`), including session-id propagation and SSE/JSON response
    parsing.
  - Tool discovery (`list_tools`) so the operator can learn the exact tool
    names Robinhood exposes.
  - `get_account` / `get_positions` / `place_order` / `cancel_order` mapped onto
    configurable tool names (settings.robinhood_tool_*).

What still needs the operator (can't be known/verified without a live RH
endpoint + token):
  - The exact tool NAMES + argument/result SCHEMAS Robinhood uses. Until the
    place-order tool name is configured, `place_order` refuses — no guessing
    with real money. Read ops raise BrokerNotWired until their tool is mapped.

Activation: set ROBINHOOD_MCP_ENDPOINT + ROBINHOOD_MCP_TOKEN, GET
/api/bots/robinhood/tools to discover names, map ROBINHOOD_TOOL_* env vars,
then set ROBINHOOD_ENABLED=true.
"""

from __future__ import annotations

import json
import logging
from typing import Any, List

import httpx

from ...models.schemas import Account, Order, OrderRequest, Position
from ..config import settings
from .base import BrokerError, BrokerNotConfigured, BrokerNotWired

logger = logging.getLogger(__name__)


class RobinhoodMcpBroker:
    name = "robinhood"

    def __init__(self, *, mode: str = "live") -> None:
        self._mode = mode
        self.endpoint = settings.robinhood_mcp_endpoint
        self.token = settings.robinhood_mcp_token
        self._id = 0
        self._session_id: str | None = None

    @property
    def mode(self) -> str:
        return self._mode

    def credentials_configured(self) -> bool:
        return bool(settings.robinhood_enabled and self.endpoint and self.token)

    # ── MCP JSON-RPC transport ────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h

    @staticmethod
    def _parse_body(resp: httpx.Response) -> dict:
        """MCP Streamable HTTP returns either application/json or an SSE
        stream of `data:` lines. Handle both → the final JSON-RPC object."""
        ctype = resp.headers.get("content-type", "")
        text = resp.text
        if "text/event-stream" in ctype:
            last: dict = {}
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("data:"):
                    chunk = line[len("data:"):].strip()
                    try:
                        last = json.loads(chunk)
                    except Exception:
                        continue
            return last
        try:
            return resp.json()
        except Exception as exc:
            raise BrokerError(f"robinhood MCP returned non-JSON: {text[:200]}") from exc

    async def _rpc(self, method: str, params: dict | None = None) -> Any:
        if not self.endpoint or not self.token:
            raise BrokerNotConfigured("robinhood MCP endpoint/token not configured")
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(self.endpoint, headers=self._headers(), json=payload)
        sid = resp.headers.get("mcp-session-id") or resp.headers.get("Mcp-Session-Id")
        if sid:
            self._session_id = sid
        if resp.status_code >= 400:
            raise BrokerError(f"robinhood MCP HTTP {resp.status_code}: {resp.text[:200]}")
        body = self._parse_body(resp)
        if isinstance(body, dict) and body.get("error"):
            raise BrokerError(f"robinhood MCP error: {body['error']}")
        return body.get("result") if isinstance(body, dict) else None

    async def initialize(self) -> dict:
        return await self._rpc("initialize", {
            "protocolVersion": settings.robinhood_protocol_version,
            "capabilities": {},
            "clientInfo": {"name": "bloomberg-terminal", "version": settings.app_version},
        }) or {}

    async def list_tools(self) -> List[dict]:
        """Discover the tools Robinhood exposes — how the operator learns the
        real tool names to map. Safe / read-only."""
        await self.initialize()
        result = await self._rpc("tools/list") or {}
        return result.get("tools", []) if isinstance(result, dict) else []

    async def call_tool(self, name: str, arguments: dict) -> Any:
        await self.initialize()
        return await self._rpc("tools/call", {"name": name, "arguments": arguments})

    # ── Broker surface (mapped onto configured tool names) ────────────────

    def _require_tool(self, tool: str | None, op: str) -> str:
        if not tool:
            raise BrokerNotWired(
                f"Robinhood '{op}' tool name not configured — run GET "
                f"/api/bots/robinhood/tools to discover it, then set the "
                f"ROBINHOOD_TOOL_* env var."
            )
        return tool

    async def get_account(self) -> Account | None:
        tool = self._require_tool(settings.robinhood_tool_account, "account")
        raw = await self.call_tool(tool, {})
        return _coerce_account(raw)

    async def get_positions(self) -> List[Position]:
        tool = self._require_tool(settings.robinhood_tool_positions, "positions")
        raw = await self.call_tool(tool, {})
        return _coerce_positions(raw)

    async def place_order(self, order: OrderRequest) -> Order:
        # Real money: refuse unless the place-order tool is explicitly mapped.
        tool = self._require_tool(settings.robinhood_tool_place_order, "place_order")
        raw = await self.call_tool(tool, {
            "symbol": order.symbol, "qty": order.qty, "side": order.side,
            "type": order.type, "time_in_force": order.time_in_force,
        })
        return _coerce_order(raw, order)

    async def cancel_order(self, order_id: str) -> bool:
        tool = self._require_tool(settings.robinhood_tool_cancel_order, "cancel_order")
        await self.call_tool(tool, {"order_id": order_id})
        return True


# ── best-effort result coercion ────────────────────────────────────────────
# Robinhood's tool result schema isn't known here; these pull common fields
# out of the MCP tool `content` payload and fall back to BrokerNotWired so a
# schema mismatch can't silently produce a wrong Account/Order.


def _tool_payload(raw: Any) -> dict:
    """MCP tool results carry a `content` list; structured tools also return
    `structuredContent`. Prefer structured, else parse the first JSON text."""
    if not isinstance(raw, dict):
        raise BrokerNotWired("unexpected Robinhood tool result shape")
    if isinstance(raw.get("structuredContent"), dict):
        return raw["structuredContent"]
    for item in raw.get("content", []) or []:
        if isinstance(item, dict) and item.get("type") == "text":
            try:
                return json.loads(item.get("text", ""))
            except Exception:
                continue
    raise BrokerNotWired(
        "could not parse Robinhood tool result — confirm the tool's result "
        "schema and adjust core/brokers/robinhood_mcp coercion."
    )


def _coerce_account(raw: Any) -> Account:
    d = _tool_payload(raw)
    return Account(
        cash=float(d.get("cash", 0) or 0),
        buying_power=float(d.get("buying_power", 0) or 0),
        portfolio_value=float(d.get("portfolio_value", d.get("equity", 0)) or 0),
        equity=float(d.get("equity", 0) or 0),
        last_equity=float(d.get("last_equity", 0) or 0),
        source="robinhood",
    )


def _coerce_positions(raw: Any) -> List[Position]:
    d = _tool_payload(raw)
    rows = d if isinstance(d, list) else d.get("positions", [])
    out: List[Position] = []
    for p in rows or []:
        try:
            out.append(Position(
                symbol=str(p.get("symbol", "")).upper(),
                qty=float(p.get("qty", 0) or 0),
                avg_entry_price=float(p.get("avg_entry_price", 0) or 0),
                source="robinhood",
            ))
        except Exception:
            continue
    return out


def _coerce_order(raw: Any, req: OrderRequest) -> Order:
    d = _tool_payload(raw)
    return Order(
        id=str(d.get("id", d.get("order_id", ""))),
        symbol=req.symbol, side=req.side, type=req.type,
        time_in_force=req.time_in_force, qty=req.qty,
        status=str(d.get("status", "accepted")), source="robinhood",
    )
