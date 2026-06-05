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


# ── tool name auto-mapping ──────────────────────────────────────────────────
# Heuristic: map discovered MCP tool names onto our four operations by the
# keywords in the name. Action verbs (place/submit/buy/sell) drive place_order
# so a read tool like "get_orders" is never mistaken for an order placer.
# Explicit ROBINHOOD_TOOL_* always overrides this.

_OP_KEYWORDS: dict[str, list[str]] = {
    "account": ["account", "buying_power", "balance", "cash", "equity"],
    "positions": ["position", "holding"],
    "place_order": ["place_order", "submit_order", "create_order", "place", "submit", "buy", "sell"],
    "cancel_order": ["cancel"],
}
# read-ish prefixes that should never be treated as an order *placer*
_READ_PREFIXES = ("get_", "list_", "fetch_", "read_", "view_")


def _norm(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_").replace(".", "_")


def _score(op: str, normalized: str) -> int:
    score = sum(1 for kw in _OP_KEYWORDS[op] if kw in normalized)
    if op == "place_order":
        if normalized.startswith(_READ_PREFIXES):
            return 0  # a getter can't be the order placer
        # strong signal for explicit place/submit/create-order tools
        if any(p in normalized for p in ("place_order", "submit_order", "create_order")):
            score += 2
    return score


def auto_map_tools(tool_names: list[str]) -> dict[str, str | None]:
    """Best-effort op → tool-name mapping from a discovered tool list."""
    norm = {t: _norm(t) for t in tool_names}
    out: dict[str, str | None] = {}
    # cancel first so it can be excluded from the place_order candidates
    cancel = _pick("cancel_order", tool_names, norm)
    out["cancel_order"] = cancel
    for op in ("account", "positions", "place_order"):
        candidates = [t for t in tool_names if t != cancel]
        out[op] = _pick(op, candidates, norm)
    return out


def _pick(op: str, names: list[str], norm: dict[str, str]) -> str | None:
    best, best_score = None, 0
    for t in names:
        s = _score(op, norm[t])
        if s > best_score:
            best, best_score = t, s
    return best


class RobinhoodMcpBroker:
    name = "robinhood"

    def __init__(self, *, mode: str = "live") -> None:
        self._mode = mode
        self.endpoint = settings.robinhood_mcp_endpoint
        self.token = settings.robinhood_mcp_token
        self._id = 0
        self._session_id: str | None = None
        self._tool_map: dict[str, str | None] | None = None

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

    # ── tool resolution (explicit override → auto-map from discovery) ─────

    _explicit = {
        "account": "robinhood_tool_account",
        "positions": "robinhood_tool_positions",
        "place_order": "robinhood_tool_place_order",
        "cancel_order": "robinhood_tool_cancel_order",
    }

    async def resolve_tools(self) -> dict[str, str | None]:
        """Resolve op → tool name. Explicit ROBINHOOD_TOOL_* wins; otherwise,
        when auto-map is on, derive from the discovered tool list. Cached per
        instance."""
        if self._tool_map is not None:
            return self._tool_map
        explicit = {op: getattr(settings, attr) for op, attr in self._explicit.items()}
        if all(explicit.values()) or not settings.robinhood_auto_map:
            self._tool_map = explicit
            return self._tool_map
        try:
            tools = await self.list_tools()
            names = [t.get("name") for t in tools if t.get("name")]
        except Exception as exc:
            logger.debug("robinhood tool discovery failed: %s", exc)
            names = []
        auto = auto_map_tools(names)
        # explicit overrides take precedence over auto-mapped picks
        self._tool_map = {op: explicit[op] or auto.get(op) for op in self._explicit}
        return self._tool_map

    async def _tool_for(self, op: str) -> str:
        tool = (await self.resolve_tools()).get(op)
        if not tool:
            raise BrokerNotWired(
                f"Robinhood '{op}' tool could not be resolved — set "
                f"ROBINHOOD_TOOL_{op.upper()} explicitly (discover names via "
                f"GET /api/bots/robinhood/tools)."
            )
        return tool

    async def get_account(self) -> Account | None:
        raw = await self.call_tool(await self._tool_for("account"), {})
        return _coerce_account(raw)

    async def get_positions(self) -> List[Position]:
        raw = await self.call_tool(await self._tool_for("positions"), {})
        return _coerce_positions(raw)

    async def place_order(self, order: OrderRequest) -> Order:
        tool = await self._tool_for("place_order")  # raises if unresolved — no blind real-money order
        raw = await self.call_tool(tool, {
            "symbol": order.symbol, "qty": order.qty, "side": order.side,
            "type": order.type, "time_in_force": order.time_in_force,
        })
        return _coerce_order(raw, order)

    async def cancel_order(self, order_id: str) -> bool:
        await self.call_tool(await self._tool_for("cancel_order"), {"order_id": order_id})
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
