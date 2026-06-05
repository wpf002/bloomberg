"""Robinhood agentic-trading broker — SCAFFOLD (not yet functional).

Robinhood's agentic surface is exposed as a Model Context Protocol (MCP)
*server* (https://robinhood.com/us/en/support/articles/agentic-trading-overview/):
an AI agent connects to Robinhood's MCP endpoint and places orders into a
dedicated, fund-isolated account. To drive it from this backend we'd be an
MCP *client* of that endpoint.

Status: the class is registered and selectable so the rest of the system is
"wired and ready", but every call raises `BrokerNotWired` until the MCP
client is implemented. Completing it is a contained task:

  TODO(robinhood):
    1. Add an MCP client dependency (e.g. the `mcp` package) to requirements.
    2. In `connect()`, open an MCP session to `settings.robinhood_mcp_endpoint`
       authenticated with `settings.robinhood_mcp_token`.
    3. Map `get_account` / `get_positions` / `place_order` / `cancel_order`
       onto the MCP tools Robinhood exposes (see their docs for tool names).
    4. Flip `settings.robinhood_enabled` on and remove the guards below.

Nothing here touches real money; it only ever raises until wired.
"""

from __future__ import annotations

import logging
from typing import List

from ...models.schemas import Account, Order, OrderRequest, Position
from ..config import settings
from .base import BrokerNotWired

logger = logging.getLogger(__name__)

_NOT_WIRED = (
    "Robinhood MCP broker is registered but not yet wired. Set "
    "ROBINHOOD_ENABLED=true and complete the MCP client in "
    "backend/core/brokers/robinhood_mcp.py to activate it."
)


class RobinhoodMcpBroker:
    """Inert until the MCP client is implemented (see module docstring)."""

    name = "robinhood"

    def __init__(self, *, mode: str = "live") -> None:
        self._mode = mode
        self.endpoint = settings.robinhood_mcp_endpoint
        self.token = settings.robinhood_mcp_token

    @property
    def mode(self) -> str:
        return self._mode

    def credentials_configured(self) -> bool:
        # "Configured" means the operator has both enabled it and provided an
        # endpoint + token. Even then, calls raise until the client is built.
        return bool(settings.robinhood_enabled and self.endpoint and self.token)

    async def connect(self):  # pragma: no cover - scaffold
        raise BrokerNotWired(_NOT_WIRED)

    async def get_account(self) -> Account | None:  # pragma: no cover - scaffold
        raise BrokerNotWired(_NOT_WIRED)

    async def get_positions(self) -> List[Position]:  # pragma: no cover - scaffold
        raise BrokerNotWired(_NOT_WIRED)

    async def place_order(self, order: OrderRequest) -> Order:  # pragma: no cover - scaffold
        raise BrokerNotWired(_NOT_WIRED)

    async def cancel_order(self, order_id: str) -> bool:  # pragma: no cover - scaffold
        raise BrokerNotWired(_NOT_WIRED)

