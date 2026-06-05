"""Resolve which Broker a bot executes through.

This is the single seam where per-user keys (#4), paper vs. live (#3), and
alternate brokers (#1) come together. The bot engine calls
`resolve_execution_broker(...)` instead of touching the Alpaca singleton.

Resolution order for Alpaca:
  1. The user's encrypted keys for the requested mode (paper/live), if set.
  2. Otherwise the process env keys (single-user convenience — env = "me").
     Env fallback is allowed for paper; live always requires explicit live
     keys + the BOTS_ALLOW_LIVE master switch.
"""

from __future__ import annotations

import logging

from ...data.sources.alpaca_source import AlpacaSource, get_alpaca_source
from ..config import settings
from .base import Broker, BrokerNotConfigured, BrokerNotWired
from .credentials import get_decrypted
from .robinhood_mcp import RobinhoodMcpBroker

logger = logging.getLogger(__name__)


def _alpaca_base(mode: str) -> str:
    return settings.alpaca_base_url if mode == "paper" else settings.alpaca_live_base_url


def market_data_source() -> AlpacaSource:
    """Shared env Alpaca source for quotes/bars — account-agnostic market
    data, kept off the per-user execution path."""
    return get_alpaca_source()


def live_enabled() -> bool:
    return bool(settings.bots_allow_live)


async def resolve_execution_broker(
    user_id: int | None,
    broker: str = "alpaca",
    mode: str = "paper",
) -> Broker:
    broker = (broker or "alpaca").lower()
    mode = (mode or "paper").lower()

    if broker == "robinhood":
        if not settings.robinhood_enabled:
            raise BrokerNotWired(
                "Robinhood broker is not enabled (set ROBINHOOD_ENABLED=true once "
                "the MCP client is wired)."
            )
        return RobinhoodMcpBroker(mode=mode)

    if broker != "alpaca":
        raise BrokerNotConfigured(f"unknown broker '{broker}'")

    # Live is gated by the master switch regardless of keys.
    if mode == "live" and not settings.bots_allow_live:
        raise BrokerNotConfigured(
            "live trading is disabled — set BOTS_ALLOW_LIVE=true and add live keys to enable it"
        )

    creds = await get_decrypted(user_id, "alpaca", mode)
    base = _alpaca_base(mode)
    if creds:
        key, secret = creds
        return AlpacaSource(api_key=key, api_secret=secret, base_url=base)

    # No per-user keys → env fallback (paper only). Live demands explicit keys.
    if mode == "live":
        raise BrokerNotConfigured(
            "no live Alpaca keys configured for this account — add them in Settings"
        )
    src = AlpacaSource(base_url=base)  # uses env keys
    if not src.credentials_configured():
        raise BrokerNotConfigured("no Alpaca paper credentials configured")
    return src
