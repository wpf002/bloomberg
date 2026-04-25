"""LLM-synthesized single-symbol briefing — the AAPL EXPLAIN mnemonic.

Gathers fundamentals, last-7-day news, and recent SEC filings, then asks
Claude to produce a terse analyst briefing. Cached for 30 minutes per
(symbol) pair since the underlying mix doesn't change often and LLM
calls aren't free.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from ...core.cache_utils import cached
from ...core.config import settings
from ...core.llm import LLMNotConfigured, synthesize
from ...data.sources import FmpSource, RssSource, SecEdgarSource, get_alpaca_source
from ...models.schemas import Brief, Fundamentals

logger = logging.getLogger(__name__)
router = APIRouter()

_fmp = FmpSource()
_alpaca = get_alpaca_source()
_rss = RssSource()
_edgar = SecEdgarSource()


async def _best_fundamentals(symbol: str) -> Fundamentals | None:
    """FMP only — yfinance fallback retired with the rest of the Yahoo
    deps. When FMP isn't configured the prompt gets a sparse fundamentals
    block, which the LLM handles gracefully."""
    if not _fmp.enabled():
        return None
    try:
        return await _fmp.get_fundamentals(symbol)
    except Exception as exc:
        logger.warning("FMP fundamentals failed for %s: %s", symbol, exc)
        return None


def _compact_fundamentals(f) -> str:
    """Drop nulls and stringify as pretty JSON for the prompt."""
    if f is None:
        return "{}"
    data = f.model_dump(mode="json") if hasattr(f, "model_dump") else dict(f)
    trimmed = {k: v for k, v in data.items() if v not in (None, "", 0, 0.0)}
    return json.dumps(trimmed, indent=2, sort_keys=True)


def _news_lines(items, limit: int = 8) -> str:
    lines = []
    for it in items[:limit]:
        pub = it.published_at.date().isoformat() if hasattr(it, "published_at") else "?"
        lines.append(f"{pub} [{it.source}] {it.headline}")
    return "\n".join(lines) if lines else "(no recent headlines)"


def _filings_lines(items, limit: int = 6) -> str:
    lines = []
    for it in items[:limit]:
        date = it.filed_at.date().isoformat() if hasattr(it, "filed_at") else "?"
        lines.append(f"{date} {it.form_type} — {it.company}")
    return "\n".join(lines) if lines else "(no recent filings)"


@cached("llm:explain", ttl=1800, model=Brief)
async def _build_brief(symbol: str) -> Brief:
    # Gather context concurrently; any individual source is allowed to fail.
    async def safe(coro, default):
        try:
            return await coro
        except Exception as exc:
            logger.warning("explain context source failed: %s", exc)
            return default

    fundamentals, alpaca_news, rss_news, filings = await asyncio.gather(
        safe(_best_fundamentals(symbol), None),
        safe(_alpaca.news([symbol], limit=10), []),
        safe(_rss.fetch([symbol], limit=10), []),
        safe(_edgar.recent_filings(symbol, limit=6), []),
    )

    # Merge + dedupe news by URL/id.
    seen: set[str] = set()
    news: list[Any] = []
    for src in (alpaca_news or [], rss_news or []):
        for n in src:
            key = getattr(n, "url", None) or getattr(n, "id", "")
            if key and key not in seen:
                seen.add(key)
                news.append(n)
    news.sort(key=lambda n: n.published_at, reverse=True)

    body = await synthesize(
        "explain",
        {
            "symbol": symbol,
            "as_of": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "fundamentals_json": _compact_fundamentals(fundamentals),
            "news_lines": _news_lines(news),
            "filings_lines": _filings_lines(filings or []),
        },
        max_tokens=1200,
    )
    return Brief(symbol=symbol, body=body, model=settings.anthropic_model)


@router.get("/{symbol}", response_model=Brief)
async def get_explain(symbol: str) -> Brief:
    sym = symbol.upper()
    try:
        return await _build_brief(sym)
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("explain failed for %s", sym)
        raise HTTPException(status_code=502, detail=f"explain error: {exc}") from exc
