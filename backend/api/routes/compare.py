"""LLM-synthesized two-symbol comparison — the AAPL MSFT COMPARE mnemonic.

Gathers fundamentals + last-7-day news for both symbols, then asks Claude
to produce a side-by-side numeric table plus a short qualitative read.
Cached for 30 minutes per sorted (symbol_a, symbol_b) pair.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ...core.cache_utils import cached
from ...core.config import settings
from ...core.llm import LLMNotConfigured, synthesize
from ...data.sources import RssSource, YFinanceSource, get_alpaca_source
from ...models.schemas import ComparisonBrief

logger = logging.getLogger(__name__)
router = APIRouter()

_yf = YFinanceSource()
_alpaca = get_alpaca_source()
_rss = RssSource()


def _compact_fundamentals(f) -> str:
    if f is None:
        return "{}"
    data = f.model_dump(mode="json") if hasattr(f, "model_dump") else dict(f)
    trimmed = {k: v for k, v in data.items() if v not in (None, "", 0, 0.0)}
    return json.dumps(trimmed, indent=2, sort_keys=True)


def _news_lines(items, limit: int = 6) -> str:
    lines = []
    for it in items[:limit]:
        pub = it.published_at.date().isoformat() if hasattr(it, "published_at") else "?"
        lines.append(f"{pub} [{it.source}] {it.headline}")
    return "\n".join(lines) if lines else "(no recent headlines)"


async def _gather_for(symbol: str) -> tuple[Any, list]:
    async def safe(coro, default):
        try:
            return await coro
        except Exception as exc:
            logger.warning("compare context source failed: %s", exc)
            return default

    fundamentals, alpaca_news, rss_news = await asyncio.gather(
        safe(_yf.get_fundamentals(symbol), None),
        safe(_alpaca.news([symbol], limit=8), []),
        safe(_rss.fetch([symbol], limit=8), []),
    )
    seen: set[str] = set()
    news = []
    for src in (alpaca_news or [], rss_news or []):
        for n in src:
            key = getattr(n, "url", None) or getattr(n, "id", "")
            if key and key not in seen:
                seen.add(key)
                news.append(n)
    news.sort(key=lambda n: n.published_at, reverse=True)
    return fundamentals, news


@cached("llm:compare", ttl=1800, model=ComparisonBrief)
async def _build_comparison(symbol_a: str, symbol_b: str) -> ComparisonBrief:
    (fa, news_a), (fb, news_b) = await asyncio.gather(
        _gather_for(symbol_a),
        _gather_for(symbol_b),
    )
    body = await synthesize(
        "compare",
        {
            "symbol_a": symbol_a,
            "symbol_b": symbol_b,
            "as_of": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "fundamentals_a_json": _compact_fundamentals(fa),
            "fundamentals_b_json": _compact_fundamentals(fb),
            "news_a_lines": _news_lines(news_a),
            "news_b_lines": _news_lines(news_b),
        },
        max_tokens=1500,
    )
    return ComparisonBrief(
        symbols=[symbol_a, symbol_b],
        body=body,
        model=settings.anthropic_model,
    )


@router.get("", response_model=ComparisonBrief)
async def get_compare(
    symbols: str = Query(..., description="Two tickers, comma-separated (e.g. AAPL,MSFT)"),
) -> ComparisonBrief:
    parsed = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if len(parsed) != 2:
        raise HTTPException(
            status_code=400,
            detail="compare requires exactly two symbols (e.g. ?symbols=AAPL,MSFT)",
        )
    a, b = parsed
    if a == b:
        raise HTTPException(status_code=400, detail="compare needs two distinct symbols")
    try:
        return await _build_comparison(a, b)
    except LLMNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("compare failed for %s vs %s", a, b)
        raise HTTPException(status_code=502, detail=f"compare error: {exc}") from exc
