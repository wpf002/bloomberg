"""AI Advisor API — five capabilities, all streaming.

Each route accepts a JSON body containing the active symbol + optional
extra payload (the user's question for /ask, the alert blob for /alert-
analysis), builds the full context via advisor.build_context, and
streams Claude tokens as text/plain.

Endpoints:
- POST /api/advisor/review
- POST /api/advisor/picks
- POST /api/advisor/ask
- POST /api/advisor/brief
- POST /api/advisor/alert-analysis
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...core.llm import LLMNotConfigured
from ...services import advisor

logger = logging.getLogger(__name__)
router = APIRouter()


class _BaseAdvisorRequest(BaseModel):
    active_symbol: str | None = None
    watchlist: list[str] | None = None


class AskRequest(_BaseAdvisorRequest):
    question: str


class AlertAnalysisRequest(_BaseAdvisorRequest):
    alert: dict[str, Any]


def _stream_response(generator) -> StreamingResponse:
    """Adapt an async generator of strings into a text/plain stream.

    `generator` may itself be a coroutine that resolves to an async
    iterator (the advisor.stream_* helpers are coroutines that build
    the iterator) — we await and then iterate so callers can write
    `await advisor.stream_review(ctx)` consistently.
    """

    async def _agen():
        gen = await generator if hasattr(generator, "__await__") else generator
        async for chunk in gen:
            yield chunk

    return StreamingResponse(_agen(), media_type="text/plain; charset=utf-8")


def _503_if_no_llm():
    from ...core.config import settings

    if not settings.anthropic_api_key:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY not set — add it to .env to enable the advisor.",
        )


@router.post("/review")
async def post_review(req: _BaseAdvisorRequest):
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.active_symbol, watchlist=req.watchlist
    )
    return _stream_response(advisor.stream_review(ctx))


@router.post("/picks")
async def post_picks(req: _BaseAdvisorRequest):
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.active_symbol, watchlist=req.watchlist
    )
    return _stream_response(advisor.stream_picks(ctx))


@router.post("/ask")
async def post_ask(req: AskRequest):
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.active_symbol, watchlist=req.watchlist
    )
    return _stream_response(advisor.stream_ask(ctx, req.question))


@router.post("/brief")
async def post_brief(req: _BaseAdvisorRequest):
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.active_symbol,
        watchlist=req.watchlist,
        include_news=False,
    )
    return _stream_response(advisor.stream_brief(ctx))


@router.post("/alert-analysis")
async def post_alert_analysis(req: AlertAnalysisRequest):
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.active_symbol, watchlist=req.watchlist
    )
    return _stream_response(advisor.stream_alert_analysis(ctx, req.alert))
