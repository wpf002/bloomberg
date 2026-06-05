"""Broker protocol + error types.

The protocol intentionally mirrors the method names AlpacaSource already
exposes, so AlpacaSource *is* a structural Broker with no adapter shim.
"""

from __future__ import annotations

from typing import List, Protocol, runtime_checkable

from ...models.schemas import Account, Order, OrderRequest, Position


class BrokerError(RuntimeError):
    """Base class for broker failures."""


class BrokerNotConfigured(BrokerError):
    """Credentials for the requested broker/mode are missing."""


class BrokerNotWired(BrokerError):
    """The broker exists as a scaffold but its integration isn't finished
    (e.g. Robinhood MCP). Raised so callers can degrade gracefully."""


@runtime_checkable
class Broker(Protocol):
    """The execution surface the bot engine needs from any broker."""

    name: str

    @property
    def mode(self) -> str:  # "paper" | "live"
        ...

    def credentials_configured(self) -> bool:
        ...

    async def get_account(self) -> Account | None:
        ...

    async def get_positions(self) -> List[Position]:
        ...

    async def place_order(self, order: OrderRequest) -> Order:
        ...

    async def cancel_order(self, order_id: str) -> bool:
        ...
