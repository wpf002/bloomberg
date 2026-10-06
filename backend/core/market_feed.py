"""Which Alpaca equity feed each kind of request uses.

Two feeds. IEX is one venue: free and real-time, but only 3-5% of consolidated
volume (AAPL showed 543k shares against 15.5M), and its daily bar misses the
closing auction, so its close drifts a few cents off the official one. SIP is
every exchange.

Alpaca's free plan serves SIP too, just not the most recent 15 minutes. So:

  * Daily-or-longer bars always ask for SIP. On the free plan the request ends
    16 minutes ago, which costs nothing for daily data. This gives consolidated
    volume and the official close to the screener, bots, risk engine and
    factor model.
  * Live data (the quote stream, intraday bars) follows ALPACA_DATA_FEED:
    "iex" by default, "sip" once the account has Algo Trader Plus ($99/mo,
    personal use). A delayed intraday chart is worse than a thin-volume live
    one, so intraday stays on the live feed.

If the account isn't entitled to SIP, the quote stream says so on connect
(error 409, "insufficient subscription") and the process drops back to IEX for
its lifetime, logging it once. REST is quieter: on the free plan a SIP request
with no `end` comes back 15 minutes delayed rather than refused, so the stream
is what catches a wrong ALPACA_DATA_FEED. An explicit refusal (403) is handled
the same way. A wrong setting degrades data quality, never availability.

The free plan also allows one stream connection per key. A second process on
the same key (another replica, local dev) gets error 406 and receives nothing;
the streamer now logs that instead of going quiet.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from .config import settings

logger = logging.getLogger(__name__)

VALID = ("iex", "sip")

# The free plan refuses SIP data newer than 15 minutes; one extra for clock skew.
FREE_SIP_LAG = timedelta(minutes=16)

# Timeframes served from SIP even on the free plan.
_HISTORICAL_TIMEFRAMES = frozenset({"1Day", "1Week", "1Month"})

_configured = (settings.alpaca_data_feed or "iex").strip().lower()
if _configured not in VALID:
    logger.warning("ALPACA_DATA_FEED=%r is not one of %s; using iex", _configured, VALID)
    _configured = "iex"

_live = _configured          # stream + intraday bars
_historical = "sip"          # daily-or-longer bars


def current() -> str:
    """Feed for live data: the quote stream and intraday bars."""
    return _live


def configured() -> str:
    return _configured


def bar_params(timeframe: str, now: datetime | None = None) -> dict[str, str]:
    """`feed` (and `end`, when needed) for a bars request at this timeframe."""
    if timeframe not in _HISTORICAL_TIMEFRAMES:
        return {"feed": _live}
    if _historical == "iex":
        return {"feed": "iex"}
    if _live == "sip":
        return {"feed": "sip"}  # paid plan: no lag needed
    end = (now or datetime.now(timezone.utc)) - FREE_SIP_LAG
    return {"feed": "sip", "end": end.isoformat().replace("+00:00", "Z")}


def downgrade(reason: str, *, timeframe: str | None = None) -> bool:
    """Fall back to IEX for whichever path just got an entitlement error.

    Returns True only on the call that actually switched, so callers retry
    their request exactly once.
    """
    global _live, _historical
    if timeframe in _HISTORICAL_TIMEFRAMES:
        if _historical == "iex":
            return False
        _historical = "iex"
        logger.warning("SIP daily bars refused (%s); falling back to iex for bars", reason)
        return True
    if _live == "iex":
        return False
    _live = "iex"
    logger.warning(
        "ALPACA_DATA_FEED=sip but the account isn't entitled (%s); falling back to iex. "
        "Subscribe to Algo Trader Plus or unset ALPACA_DATA_FEED.",
        reason,
    )
    return True


def is_entitlement_error(status_code: int, body: str) -> bool:
    """Alpaca's REST answer when the plan doesn't cover the requested feed."""
    return status_code == 403 and "subscription" in (body or "").lower()


def _reset_for_tests(live: str = "iex", historical: str = "sip") -> None:
    global _configured, _live, _historical
    _configured = _live = live
    _historical = historical
