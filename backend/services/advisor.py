"""AI Financial Advisor — Claude-powered, fully context-aware.

Replaces the standalone explain/compare prompts with a single advisor
service that receives, on every call, a structured context payload:

  - current portfolio positions + P/L
  - current macro regime classification (intelligence_engine.regime_now)
  - portfolio fragility score
  - sector rotation signals + cycle phase
  - active symbol's price + fundamentals + recent news
  - the user's watchlist

Five capabilities, each with a dedicated builder that constructs a
system + user message pair and returns an AsyncIterator of token deltas
via the Anthropic streaming API.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic

from ..core.config import settings
from ..core.llm import LLMNotConfigured
from ..data.sources import RssSource, SecEdgarSource, get_alpaca_source
from ..models.schemas import Position
from . import intelligence_engine, risk_engine

logger = logging.getLogger(__name__)

# Model ID locked per the spec — claude-sonnet-4-20250514. Settings.anthropic_model
# is left intact for the legacy explain/compare endpoints; the advisor pins
# its own model so prompt-engineering stays predictable.
ADVISOR_MODEL = "claude-sonnet-4-20250514"


def _client() -> AsyncAnthropic:
    if not settings.anthropic_api_key:
        raise LLMNotConfigured(
            "ANTHROPIC_API_KEY not set. Add it to .env (get a key at "
            "console.anthropic.com) and restart the backend."
        )
    return AsyncAnthropic(api_key=settings.anthropic_api_key)


# ── context builder ────────────────────────────────────────────────────


async def build_context(
    *,
    active_symbol: str | None = None,
    watchlist: list[str] | None = None,
    include_news: bool = True,
) -> dict[str, Any]:
    """Gather the full context payload sent to Claude on every advisor call.

    Each subsystem call is wrapped so a transient failure (Alpaca down,
    FRED rate-limited, etc.) leaves the payload partially populated rather
    than blowing up the whole request. The system prompt explicitly tells
    Claude to never invent data — missing fields stay missing.
    """
    alpaca = get_alpaca_source()
    edgar = SecEdgarSource()
    rss = RssSource()

    async def _safe(coro, default):
        try:
            return await coro
        except Exception as exc:
            logger.debug("advisor context source failed: %s", exc)
            return default

    positions: list[Position] = await _safe(alpaca.get_positions(), [])
    account = await _safe(alpaca.get_account(), None)
    regime = await _safe(intelligence_engine.regime_now(), {})
    fragility = await _safe(intelligence_engine.fragility_now(), {})
    rotation = await _safe(intelligence_engine.sector_rotation(), {})
    var_data = await _safe(risk_engine.compute_var(), {})

    active_quote = None
    active_news: list[dict[str, Any]] = []
    if active_symbol:
        try:
            quote = await alpaca.get_stock_quote(active_symbol)
            if quote:
                active_quote = quote.model_dump(mode="json")
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

    return {
        "as_of": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "active_symbol": active_symbol,
        "watchlist": watchlist or [],
        "account": account.model_dump(mode="json") if account else None,
        "positions": [p.model_dump(mode="json") for p in positions],
        "regime": regime,
        "fragility": fragility,
        "rotation": rotation,
        "var_metrics": var_data,
        "active_quote": active_quote,
        "active_news": active_news,
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


def _system_for(capability: str) -> str:
    extras = {
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
    }
    return _BASE_SYSTEM + "\n\n" + extras.get(capability, "")


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
) -> AsyncIterator[str]:
    """Stream Claude tokens as plain text chunks. The caller wraps these
    in a FastAPI StreamingResponse with media_type='text/plain'."""
    client = _client()
    system = _system_for(capability)
    messages = _build_messages(context, user_message, history)
    try:
        async with client.messages.stream(
            model=ADVISOR_MODEL,
            max_tokens=2000,
            temperature=0.4,
            system=system,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text
    except Exception as exc:
        logger.exception("advisor stream failed")
        yield f"\n\n[advisor error: {exc}]"


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
