"""AI Financial Advisor — Claude-powered, fully context-aware.

Receives, on every call, a structured CONTEXT payload describing the
user's live portfolio, current macro regime, fragility, sector rotation,
and recent news. Phase 9.2 expands the payload with watchlist quotes,
Finnhub earnings estimates, Alpaca pre-market snapshots, RSS news
filtered to the last 12 hours, the last 5 fired alerts, the active
symbol's historical earnings reactions, current yield-curve shape, and
the mortgage-treasury spread.

Eleven capabilities, each with a dedicated builder that constructs a
system + user message pair and returns an AsyncIterator of token deltas
via the Anthropic streaming API.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic

from ..core.alerts import engine as alert_engine
from ..core.config import settings
from ..core.llm import LLMNotConfigured
from ..data.sources import (
    FinnhubSource,
    FredSource,
    RssSource,
    SecEdgarSource,
    get_alpaca_source,
)
from ..models.schemas import Position
from . import intelligence_engine, risk_engine

logger = logging.getLogger(__name__)

# Model ID locked per the spec. Settings.anthropic_model stays intact for the
# legacy explain/compare endpoints; the advisor pins its own model so prompt-
# engineering stays predictable.
ADVISOR_MODEL = "claude-sonnet-4-20250514"


def _client() -> AsyncAnthropic:
    if not settings.anthropic_api_key:
        raise LLMNotConfigured(
            "ANTHROPIC_API_KEY not set. Add it to .env (get a key at "
            "console.anthropic.com) and restart the backend."
        )
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


# ── context builder ────────────────────────────────────────────────────


async def _safe(coro, default):
    """Swallow exceptions from a sub-source so context build stays atomic."""
    try:
        return await coro
    except Exception as exc:
        logger.debug("advisor context source failed: %s", exc)
        return default


async def _watchlist_quotes(alpaca, symbols: list[str]) -> list[dict[str, Any]]:
    if not symbols:
        return []
    out: list[dict[str, Any]] = []
    quotes = await asyncio.gather(
        *[_safe(alpaca.get_stock_quote(sym), None) for sym in symbols],
        return_exceptions=False,
    )
    for sym, q in zip(symbols, quotes):
        if q is not None:
            out.append({
                "symbol": sym,
                "price": q.price,
                "change_percent": q.change_percent,
                "previous_close": q.previous_close,
            })
    return out


async def _earnings_estimates(finnhub: FinnhubSource, symbols: list[str]) -> list[dict[str, Any]]:
    """Pull next earnings event per symbol from Finnhub. Returns the next
    upcoming event with EPS / revenue estimate fields when present."""
    if not symbols or not finnhub.enabled():
        return []
    today = datetime.now(timezone.utc).date()
    horizon = today.replace(year=today.year + (1 if today.month > 9 else 0))
    # Single market-wide call we can filter cheaper than N per-symbol calls.
    results = await asyncio.gather(
        *[_safe(finnhub.get_earnings_calendar(symbol=sym, from_date=today), []) for sym in symbols],
    )
    out: list[dict[str, Any]] = []
    for sym, events in zip(symbols, results):
        nxt = next((e for e in events if e.event_date >= today), None)
        if nxt is None:
            continue
        out.append({
            "symbol": sym,
            "event_date": nxt.event_date.isoformat(),
            "when": nxt.when,
            "eps_estimate": nxt.eps_estimate,
            "revenue_estimate": nxt.revenue_estimate,
        })
    return out


async def _historical_earnings_reactions(
    alpaca, finnhub: FinnhubSource, symbol: str
) -> list[dict[str, Any]]:
    """Last 4 quarters of earnings reactions: % move from close-of-day-of
    earnings to close-of-next-day. Skipped silently if either source can't
    serve the data (e.g. Finnhub past-earnings call returns nothing)."""
    if not symbol or not finnhub.enabled():
        return []
    today = datetime.now(timezone.utc).date()
    one_year_ago = today - timedelta(days=400)
    events = await _safe(
        finnhub.get_earnings_calendar(symbol=symbol, from_date=one_year_ago, to_date=today),
        [],
    )
    past = [e for e in events if e.event_date <= today][-4:]
    if not past:
        return []
    bars = await _safe(alpaca.get_stock_bars(symbol, period="1y", interval="1d"), [])
    if not bars:
        return []
    by_date = {b.timestamp.date(): b for b in bars}
    out: list[dict[str, Any]] = []
    sorted_dates = sorted(by_date.keys())
    for ev in past:
        d = ev.event_date
        bar_today = by_date.get(d)
        # Find next trading day after earnings
        next_trading = next((td for td in sorted_dates if td > d), None)
        bar_next = by_date.get(next_trading) if next_trading else None
        if bar_today is None or bar_next is None:
            continue
        move_pct = (bar_next.close - bar_today.close) / bar_today.close * 100.0 if bar_today.close else None
        out.append({
            "earnings_date": d.isoformat(),
            "close_t0": bar_today.close,
            "close_t1": bar_next.close,
            "move_percent_t1": move_pct,
            "eps_actual": ev.eps_actual,
            "eps_estimate": ev.eps_estimate,
            "eps_surprise_percent": ev.eps_surprise_percent,
        })
    return out


async def _recent_news_12h(rss: RssSource, symbols: list[str]) -> list[dict[str, Any]]:
    """RSS news for watchlist filtered to the last 12 hours. The RSS source
    aggregates per-symbol feeds; we trim to the freshness window here."""
    if not symbols:
        return []
    items = await _safe(rss.fetch(symbols, limit=40), [])
    cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    out: list[dict[str, Any]] = []
    for n in items:
        if n.published_at >= cutoff:
            out.append({
                "headline": n.headline,
                "source": n.source,
                "symbols": list(n.symbols or []),
                "published": n.published_at.isoformat(),
            })
    return out


async def _yield_curve_state(fred: FredSource) -> dict[str, Any]:
    """Just the shape + 2Y/10Y spread; we don't need the full curve in context."""
    # Reuse the same FRED tenor pulls the curve route uses, but only 2Y/10Y.
    pulls = await asyncio.gather(
        _safe(fred.get_series("DGS2", limit=3), None),
        _safe(fred.get_series("DGS10", limit=3), None),
    )
    def _last(s):
        if s is None or not s.observations:
            return None
        return float(s.observations[-1].value) if s.observations[-1].value is not None else None
    y2 = _last(pulls[0])
    y10 = _last(pulls[1])
    spread_bps = round((y10 - y2) * 100, 1) if (y2 is not None and y10 is not None) else None
    if spread_bps is None:
        shape = "unknown"
    elif spread_bps < -10:
        shape = "inverted"
    elif spread_bps < 10:
        shape = "flat"
    else:
        shape = "normal"
    return {"shape": shape, "spread_2y10y_bps": spread_bps, "dgs2": y2, "dgs10": y10}


async def _mortgage_spread(fred: FredSource) -> dict[str, Any]:
    pulls = await asyncio.gather(
        _safe(fred.get_series("MORTGAGE30US", limit=3), None),
        _safe(fred.get_series("DGS10", limit=3), None),
    )
    def _last(s):
        if s is None or not s.observations:
            return None
        return float(s.observations[-1].value) if s.observations[-1].value is not None else None
    mort = _last(pulls[0])
    ten = _last(pulls[1])
    spread = round(mort - ten, 3) if (mort is not None and ten is not None) else None
    return {"mortgage30y": mort, "treasury10y": ten, "spread_pp": spread}


async def _recent_alerts(user_id: int | None) -> list[dict[str, Any]]:
    try:
        events = await alert_engine.recent_events(limit=5, user_id=user_id)
    except Exception as exc:
        logger.debug("recent alerts pull failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for e in events:
        out.append({
            "rule_id": e.rule_id,
            "symbol": e.symbol,
            "name": e.name,
            "matched_at": e.matched_at.isoformat() if hasattr(e.matched_at, "isoformat") else str(e.matched_at),
            "snapshot": dict(e.snapshot) if e.snapshot else {},
        })
    return out


async def build_context(
    *,
    active_symbol: str | None = None,
    watchlist: list[str] | None = None,
    include_news: bool = True,
    include_earnings_reactions: bool = False,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Assemble the full context payload sent to Claude on every advisor call.

    Each subsystem call is wrapped in `_safe` so a transient failure (Alpaca
    down, FRED rate-limited, etc.) leaves the payload partially populated
    rather than blowing up the whole request. The system prompt explicitly
    tells Claude to never invent data — missing fields stay missing.
    """
    alpaca = get_alpaca_source()
    edgar = SecEdgarSource()
    rss = RssSource()
    finnhub = FinnhubSource()
    fred = FredSource()

    watchlist = list(watchlist or [])

    async def _no_news() -> list[dict[str, Any]]:
        return []

    # Run independent fetches in parallel where possible.
    (
        positions,
        account,
        regime,
        fragility,
        rotation,
        var_data,
        watchlist_q,
        earnings_est,
        recent_news,
        curve_state,
        mortgage_state,
        alerts_recent,
    ) = await asyncio.gather(
        _safe(alpaca.get_positions(), []),
        _safe(alpaca.get_account(), None),
        _safe(intelligence_engine.regime_now(), {}),
        _safe(intelligence_engine.fragility_now(), {}),
        _safe(intelligence_engine.sector_rotation(), {}),
        _safe(risk_engine.compute_var(), {}),
        _watchlist_quotes(alpaca, watchlist),
        _earnings_estimates(finnhub, watchlist),
        _recent_news_12h(rss, watchlist) if include_news else _no_news(),
        _yield_curve_state(fred),
        _mortgage_spread(fred),
        _recent_alerts(user_id),
    )

    active_quote = None
    active_news: list[dict[str, Any]] = []
    earnings_reactions: list[dict[str, Any]] = []
    pre_market: dict[str, Any] | None = None
    gex_levels: dict[str, Any] | None = None
    if active_symbol:
        try:
            quote = await alpaca.get_stock_quote(active_symbol)
            if quote:
                active_quote = quote.model_dump(mode="json")
                pre_market = {
                    "symbol": active_symbol,
                    "price": quote.price,
                    "change_percent": quote.change_percent,
                    "session": "extended_or_regular",
                }
        except Exception:
            pass
        if include_news:
            try:
                news_items = await rss.fetch([active_symbol], limit=8)
                active_news = [
                    {
                        "headline": n.headline,
                        "source": n.source,
                        "published": n.published_at.isoformat(),
                    }
                    for n in news_items
                ]
            except Exception:
                pass
        if include_earnings_reactions:
            earnings_reactions = await _historical_earnings_reactions(
                alpaca, finnhub, active_symbol
            )
        # V2.4: dealer positioning for the active symbol. Computed from
        # the Alpaca options chain — failure is non-fatal.
        try:
            from . import risk_engine as _re

            gex_levels = await _re.compute_gex_levels(active_symbol)
        except Exception:
            gex_levels = None

    return {
        "as_of": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "active_symbol": active_symbol,
        "watchlist": watchlist,
        "watchlist_quotes": watchlist_q,
        "watchlist_pre_market": watchlist_q,  # Alpaca snapshot covers pre-market in same field
        "account": account.model_dump(mode="json") if account else None,
        "positions": [p.model_dump(mode="json") for p in positions],
        "regime": regime,
        "fragility": fragility,
        "rotation": rotation,
        "var_metrics": var_data,
        "active_quote": active_quote,
        "active_pre_market": pre_market,
        "active_news": active_news,
        "watchlist_news_12h": recent_news,
        "earnings_estimates_watchlist": earnings_est,
        "earnings_reactions_active": earnings_reactions,
        "yield_curve": curve_state,
        "mortgage_spread": mortgage_state,
        "recent_alerts": alerts_recent,
        "gex_levels": gex_levels,
    }


# ── prompts (kept inline so the advisor module is self-contained) ─────


_BASE_SYSTEM = """\
You are AURORA, an institutional-grade portfolio advisor embedded in a
terminal. You receive a JSON CONTEXT payload on every call describing the
user's live portfolio, current macro regime, fragility, sector rotation,
and recent news. You MUST:

- Only reference data present in the CONTEXT. Never invent numbers,
  prices, or holdings. When a field is missing, say "n/a".
- ABSOLUTELY NO MARKDOWN. Do not use `#`, `##`, `**`, `__`, backticks,
  bullet markers like `*` or `-`, or any other markdown formatting.
  Section headings are ALL-CAPS plain text (e.g. "STATE", "FRAGILITIES")
  on their own line. Lists use the character "›" followed by a space.
- Terse, fact-dense, no hedging language, no "as an AI", no
  legal disclaimers.
- Cite specific numbers when present ("VaR-95: -1.42%", "fragility 78
  → HIGH RISK", "AAPL 12.4% of book"), never vague qualifiers.
- Respect the user's regime: in RISK_OFF, lean defensive; in RISK_ON,
  lean opportunistic. Always tie advice back to the regime.
- When PRIOR_CONVERSATION is supplied below, treat it as the running
  thread — build on what you already said instead of repeating it.
"""


_CAPABILITY_TASKS: dict[str, str] = {
    "review": (
        "TASK: Produce a structured PORTFOLIO REVIEW. Sections: STATE, "
        "WHAT'S WORKING, FRAGILITIES, REGIME ALIGNMENT, NEXT MOVES. "
        "Each section heading on its own line in ALL CAPS, no markdown. "
        "List items prefixed with '› '. Reference per-position numbers "
        "from CONTEXT.positions."
    ),
    "picks": (
        "TASK: Recommend 3-5 NEW positions or adjustments. Each pick "
        "appears as: a TICKER line in ALL CAPS, then THESIS: line "
        "(1-2 sentences), ENTRY: line (price levels / triggers / sizing "
        "relative to current book), RISK: line (what would invalidate "
        "the thesis). Plain text only — no markdown headings, no bold, "
        "no bullets. Picks must align with the current regime and "
        "rotation phase. Never recommend without a stated thesis."
    ),
    "ask": (
        "TASK: Answer the user's QUESTION using only CONTEXT. Be terse. "
        "If the question requires data not in CONTEXT, say so explicitly "
        "and recommend which mnemonic to run. Plain text only — no "
        "markdown."
    ),
    "brief": (
        "TASK: Produce a WEEKLY RISK BRIEF. Sections: PORTFOLIO DELTA, "
        "MACRO REGIME, TOP FRAGILITY RISKS, SECTOR ROTATION UPDATE, "
        "3 THINGS TO WATCH NEXT WEEK. Each heading on its own line in "
        "ALL CAPS, no markdown. List items prefixed with '› '. Output "
        "is exported verbatim, so keep it readable as plain text."
    ),
    "alert-analysis": (
        "TASK: Explain the supplied ALERT in plain language and assess "
        "its impact on the user's specific portfolio. Sections: WHAT "
        "FIRED, WHY IT MATTERS FOR YOU, RECOMMENDED ACTION. Plain text "
        "only, headings in ALL CAPS, ≤150 words."
    ),
    "validate-thesis": (
        "TASK: Validate the user's TRADE THESIS. Sections: THESIS STRENGTH "
        "(score 1-10 with reasoning), SUPPORTING EVIDENCE (cite regime, "
        "fundamentals, sector rotation, news from CONTEXT), COUNTER-"
        "ARGUMENTS, REGIME ALIGNMENT (does the current regime favour this "
        "trade?), RISK ASSESSMENT (impact on portfolio fragility), "
        "POSITION SIZING (compare user's intended size to Kelly-derived "
        "size from CONTEXT.var_metrics and recommend adjustment). Plain "
        "text only, headings in ALL CAPS, lists with '› '. Never invent "
        "data; if Kelly sizing isn't in CONTEXT, say so explicitly."
    ),
    "simulate": (
        "TASK: Run a SCENARIO SIMULATION. Sections: SCENARIO INTERPRETATION "
        "(restate the user's hypothetical against current regime + "
        "positions), PER-POSITION IMPACT (one '› SYMBOL: direction "
        "(positive/negative/neutral), reasoning' per position from "
        "CONTEXT.positions), PORTFOLIO P/L IMPACT RANGE (low/mid/high % "
        "with confidence — directional, not precise), MOST EXPOSED "
        "POSITIONS (rank top 3 by exposure to this scenario), HEDGES & "
        "ADJUSTMENTS (concrete recommendations). Plain text only."
    ),
    "earnings-prep": (
        "TASK: Build an EARNINGS PRE-BRIEF for the requested ticker. "
        "Sections: STREET EXPECTATIONS (pull from CONTEXT.earnings_"
        "estimates_watchlist or earnings_reactions_active — never invent), "
        "KEY METRICS TO WATCH (revenue, EPS, guidance — based on prior "
        "quarters where data is in CONTEXT), HISTORICAL EARNINGS REACTION "
        "(summarize CONTEXT.earnings_reactions_active — last up to 4 "
        "quarters), IMPLIED MOVE (derive from ATM straddle in CONTEXT if "
        "available, otherwise OMIT this section entirely), REGIME CONTEXT "
        "(does CONTEXT.regime favour beats or punish misses harder right "
        "now?), POSITIONING RECOMMENDATION (hold through / trim before / "
        "add before / use options to define risk — pick one, justify). "
        "Plain text only, lists with '› '."
    ),
    "rebalance": (
        "TASK: Build a REBALANCE PLAN for CONTEXT.positions. Sections: "
        "OVERSIZED VS KELLY (which positions exceed CONTEXT-implied "
        "Kelly fraction), HIGH FRAGILITY TO REDUCE (positions where "
        "CONTEXT.fragility.positions[*].score > 70), SECTOR CONCENTRATIONS "
        "(any sector exceeding 30% of MV from CONTEXT.var_metrics or "
        "CONTEXT.positions sector tally), REGIME MISMATCHES (positions "
        "misaligned with CONTEXT.regime), RANKED ACTION LIST (numbered "
        "TRIM/ADD/HOLD per position with one-line reasoning each), "
        "FRAGILITY IMPACT (estimated portfolio_score after rebalance "
        "executes). Plain text, lists with '› '."
    ),
    "open-brief": (
        "TASK: Produce a MARKET OPEN BRIEFING for this morning. Sections: "
        "OVERNIGHT MACRO (summarize CONTEXT.watchlist_news_12h that's "
        "macro-relevant — never invent), PRE-MARKET MOVERS (CONTEXT.watchlist_"
        "pre_market sorted by % move), OVERNIGHT EARNINGS (CONTEXT.earnings_"
        "estimates_watchlist with event_date == today), REGIME DELTA (did "
        "CONTEXT.regime change vs the user's last brief? if you don't know, "
        "state CURRENT REGIME), TOP 3 THINGS TO WATCH TODAY (concrete, with "
        "tickers + reasoning), ALERTS OVERNIGHT (CONTEXT.recent_alerts that "
        "fired in the last 12h, if any). Plain text, ALL CAPS headings, "
        "lists with '› '. Output is exported verbatim as markdown later, so "
        "keep it readable as plain text."
    ),
    "post-mortem": (
        "TASK: Conduct a structured POSITION POST-MORTEM. Sections: "
        "ENTRY VS EXIT REGIME (compare regime at entry to regime at exit "
        "— use CONTEXT.regime if available; if not, state what's known), "
        "THESIS VERDICT (correct / partially correct / wrong, with "
        "reasoning), DATA AT ENTRY (what CONTEXT-comparable data would "
        "have supported or contradicted the thesis at entry), PRIMARY "
        "DRIVER OF OUTCOME (macro / sector / company-specific / timing — "
        "pick one with reasoning), WHAT TO DO DIFFERENTLY (concrete "
        "actionable lesson), LESSON CLASSIFICATION (one of: SIZING, "
        "TIMING, THESIS, REGIME-ALIGNMENT, RISK-MANAGEMENT). Plain text "
        "only, lists with '› '."
    ),
}


def _system_for(capability: str) -> str:
    extras = _CAPABILITY_TASKS.get(capability, "")
    return _BASE_SYSTEM + "\n\n" + extras


# ── streaming wrapper ──────────────────────────────────────────────────


def _build_messages(
    context: dict[str, Any],
    user_message: str,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    """Build the messages list passed to Anthropic's streaming API.

    The first user turn always carries the CONTEXT JSON so freshness is
    guaranteed (data may have changed since the last turn). Prior chat
    turns are appended verbatim so Claude can build on what it already
    said instead of restarting from scratch.
    """
    messages: list[dict[str, str]] = []
    primer = (
        f"CONTEXT (JSON):\n{json.dumps(context, default=str)}\n\n"
        "Acknowledge in one short sentence that the context loaded; the "
        "next user message will state the actual task."
    )
    messages.append({"role": "user", "content": primer})
    messages.append(
        {"role": "assistant", "content": "Context loaded. Ready for the task."}
    )
    for turn in history or []:
        role = turn.get("role")
        text = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and text:
            messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": user_message})
    return messages


async def stream_advisor(
    *,
    capability: str,
    user_message: str,
    context: dict[str, Any],
    history: list[dict[str, str]] | None = None,
    max_tokens: int = 2000,
) -> AsyncIterator[str]:
    """Stream Claude tokens as plain text chunks. The caller wraps these
    in a FastAPI StreamingResponse with media_type='text/plain'."""
    client = _client()
    system = _system_for(capability)
    messages = _build_messages(context, user_message, history)
    try:
        async with client.messages.stream(
            model=ADVISOR_MODEL,
            max_tokens=max_tokens,
            temperature=0.4,
            system=system,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except Exception as exc:
        logger.exception("advisor stream failed")
        yield f"\n\n[advisor error: {exc}]"


# ── existing five capabilities ─────────────────────────────────────────


async def stream_review(
    context: dict[str, Any], history: list[dict[str, str]] | None = None
) -> AsyncIterator[str]:
    return stream_advisor(
        capability="review",
        user_message="Produce a complete portfolio review now.",
        context=context,
        history=history,
    )


async def stream_picks(
    context: dict[str, Any], history: list[dict[str, str]] | None = None
) -> AsyncIterator[str]:
    return stream_advisor(
        capability="picks",
        user_message=(
            "Recommend 3-5 new positions or adjustments aligned with the "
            "current regime, rotation, and fragility profile."
        ),
        context=context,
        history=history,
    )


async def stream_ask(
    context: dict[str, Any],
    question: str,
    history: list[dict[str, str]] | None = None,
) -> AsyncIterator[str]:
    return stream_advisor(
        capability="ask", user_message=question, context=context, history=history
    )


async def stream_brief(
    context: dict[str, Any], history: list[dict[str, str]] | None = None
) -> AsyncIterator[str]:
    return stream_advisor(
        capability="brief",
        user_message="Produce this week's risk brief now.",
        context=context,
        history=history,
    )


async def stream_alert_analysis(
    context: dict[str, Any],
    alert: dict[str, Any],
    history: list[dict[str, str]] | None = None,
) -> AsyncIterator[str]:
    return stream_advisor(
        capability="alert-analysis",
        user_message=f"Alert payload: {json.dumps(alert, default=str)}",
        context=context,
        history=history,
    )


# ── new capabilities (Phase 9.2) ───────────────────────────────────────


async def stream_validate_thesis(
    context: dict[str, Any],
    ticker: str,
    thesis: str,
    intended_size_usd: float | None,
) -> AsyncIterator[str]:
    payload = {
        "ticker": ticker.upper(),
        "thesis": thesis,
        "intended_size_usd": intended_size_usd,
    }
    user_msg = (
        "Validate this trade thesis and grade it. User input:\n"
        f"{json.dumps(payload, default=str)}"
    )
    return stream_advisor(capability="validate-thesis", user_message=user_msg, context=context)


async def stream_simulate(
    context: dict[str, Any], scenario: str
) -> AsyncIterator[str]:
    user_msg = (
        "Run the following hypothetical scenario against the current "
        f"portfolio and regime. Scenario: {scenario}"
    )
    return stream_advisor(capability="simulate", user_message=user_msg, context=context)


async def stream_earnings_prep(
    context: dict[str, Any], ticker: str
) -> AsyncIterator[str]:
    user_msg = (
        f"Build the pre-earnings briefing for {ticker.upper()} now. "
        "Use only CONTEXT data; do not fabricate consensus numbers."
    )
    return stream_advisor(capability="earnings-prep", user_message=user_msg, context=context)


async def stream_rebalance(context: dict[str, Any]) -> AsyncIterator[str]:
    user_msg = (
        "Run the portfolio rebalance review now. Identify oversized vs "
        "Kelly, high-fragility positions, sector concentrations, regime "
        "mismatches, and produce a ranked action list."
    )
    return stream_advisor(capability="rebalance", user_message=user_msg, context=context)


async def stream_open_brief(context: dict[str, Any]) -> AsyncIterator[str]:
    user_msg = (
        "Produce this morning's market open briefing now."
    )
    return stream_advisor(capability="open-brief", user_message=user_msg, context=context)


async def stream_post_mortem(
    context: dict[str, Any],
    ticker: str,
    entry_date: str,
    entry_price: float,
    exit_date: str,
    exit_price: float,
    original_thesis: str,
) -> AsyncIterator[str]:
    payload = {
        "ticker": ticker.upper(),
        "entry_date": entry_date,
        "entry_price": entry_price,
        "exit_date": exit_date,
        "exit_price": exit_price,
        "original_thesis": original_thesis,
        "realized_pl_pct": (
            (exit_price - entry_price) / entry_price * 100.0 if entry_price else None
        ),
    }
    user_msg = (
        "Conduct a structured post-mortem on this closed trade:\n"
        f"{json.dumps(payload, default=str)}"
    )
    return stream_advisor(capability="post-mortem", user_message=user_msg, context=context)
