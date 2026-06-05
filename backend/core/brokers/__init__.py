"""Broker abstraction for the bot engine.

The bot engine executes through a `Broker` rather than the global Alpaca
singleton, so per-user keys, paper vs. live, and alternate brokers
(Robinhood) all plug in at one seam: `resolve_execution_broker(...)`.

Market data (quotes/bars) stays on the shared env Alpaca feed via
`market_data_source()` — data is account-agnostic and Robinhood has no bar
feed, so it's deliberately kept off the execution-broker path.
"""

from .base import Broker, BrokerError, BrokerNotConfigured, BrokerNotWired
from .resolver import market_data_source, resolve_execution_broker

__all__ = [
    "Broker",
    "BrokerError",
    "BrokerNotConfigured",
    "BrokerNotWired",
    "resolve_execution_broker",
    "market_data_source",
]
