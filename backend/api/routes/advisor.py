"""AI Advisor API — eleven capabilities, all streaming.

Each route accepts a JSON body containing the active symbol + optional
extra payload (the user's question for /ask, the alert blob for /alert-
analysis, the trade thesis for /validate-thesis, etc.), builds the
full context via advisor.build_context, and streams Claude tokens as
text/plain.

Endpoints (existing five):
- POST /api/advisor/review
- POST /api/advisor/picks
- POST /api/advisor/ask
- POST /api/advisor/brief
- POST /api/advisor/alert-analysis

Endpoints (Phase 9.2):
- POST /api/advisor/validate-thesis
- POST /api/advisor/simulate
- POST /api/advisor/earnings-prep
- POST /api/advisor/rebalance
- POST /api/advisor/open-brief
- POST /api/advisor/post-mortem
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ...services import advisor

logger = logging.getLogger(__name__)
router = APIRouter()


class _ChatTurn(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class _BaseAdvisorRequest(BaseModel):
    active_symbol: str | None = None
    watchlist: list[str] | None = None
    history: list[_ChatTurn] | None = None


class AskRequest(_BaseAdvisorRequest):
    question: str


class AlertAnalysisRequest(_BaseAdvisorRequest):
    alert: dict[str, Any]


class ValidateThesisRequest(_BaseAdvisorRequest):
    ticker: str
    thesis: str
    intended_size_usd: float | None = None


class SimulateRequest(_BaseAdvisorRequest):
    scenario: str


class EarningsPrepRequest(_BaseAdvisorRequest):
    ticker: str


class PostMortemRequest(_BaseAdvisorRequest):
    ticker: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    original_thesis: str


def _history_dicts(req: _BaseAdvisorRequest) -> list[dict[str, str]] | None:
    if not req.history:
        return None
    return [{"role": t.role, "content": t.content} for t in req.history]


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


# ── existing five capabilities ──────────────────────────────────────────


@router.post("/review")
async def post_review(req: _BaseAdvisorRequest):
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.active_symbol, watchlist=req.watchlist
    )
    return _stream_response(advisor.stream_review(ctx, _history_dicts(req)))


@router.post("/picks")
async def post_picks(req: _BaseAdvisorRequest):
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.active_symbol, watchlist=req.watchlist
    )
    return _stream_response(advisor.stream_picks(ctx, _history_dicts(req)))


@router.post("/ask")
async def post_ask(req: AskRequest):
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.active_symbol, watchlist=req.watchlist
    )
    return _stream_response(
        advisor.stream_ask(ctx, req.question, _history_dicts(req))
    )


@router.post("/brief")
async def post_brief(req: _BaseAdvisorRequest):
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.active_symbol,
        watchlist=req.watchlist,
        include_news=False,
    )
    return _stream_response(advisor.stream_brief(ctx, _history_dicts(req)))


@router.post("/alert-analysis")
async def post_alert_analysis(req: AlertAnalysisRequest):
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.active_symbol, watchlist=req.watchlist
    )
    return _stream_response(
        advisor.stream_alert_analysis(ctx, req.alert, _history_dicts(req))
    )


# ── Phase 9.2: six new capabilities ─────────────────────────────────────


@router.post("/validate-thesis")
async def post_validate_thesis(req: ValidateThesisRequest):
    """Grade the user's stated thesis against current regime, fundamentals,
    and portfolio fragility. Streams a structured response."""
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.ticker or req.active_symbol,
        watchlist=req.watchlist,
    )
    return _stream_response(
        advisor.stream_validate_thesis(
            ctx, req.ticker, req.thesis, req.intended_size_usd
        )
    )


@router.post("/simulate")
async def post_simulate(req: SimulateRequest):
    """Run a free-form scenario simulation against the live portfolio. The
    scenario is interpreted by the model against CONTEXT — no separate
    quantitative engine is invoked."""
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.active_symbol,
        watchlist=req.watchlist,
    )
    return _stream_response(advisor.stream_simulate(ctx, req.scenario))


@router.post("/earnings-prep")
async def post_earnings_prep(req: EarningsPrepRequest):
    """Pre-earnings briefing — pulls historical earnings reactions for the
    requested ticker and the next earnings event from Finnhub."""
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.ticker,
        watchlist=req.watchlist,
        include_earnings_reactions=True,
    )
    return _stream_response(advisor.stream_earnings_prep(ctx, req.ticker))


@router.post("/rebalance")
async def post_rebalance(req: _BaseAdvisorRequest):
    """Run a portfolio-wide rebalance review. No extra input required."""
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.active_symbol,
        watchlist=req.watchlist,
    )
    return _stream_response(advisor.stream_rebalance(ctx))


@router.post("/open-brief")
async def post_open_brief(req: _BaseAdvisorRequest):
    """Market-open briefing — overnight macro, watchlist movers, regime
    delta, top three things to watch today."""
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.active_symbol,
        watchlist=req.watchlist,
        include_news=True,
    )
    return _stream_response(advisor.stream_open_brief(ctx))


@router.post("/post-mortem")
async def post_post_mortem(req: PostMortemRequest):
    """Structured post-mortem on a closed trade — regime at entry vs exit,
    thesis verdict, primary outcome driver, lesson classification."""
    _503_if_no_llm()
    ctx = await advisor.build_context(
        active_symbol=req.ticker,
        watchlist=req.watchlist,
    )
    return _stream_response(
        advisor.stream_post_mortem(
            ctx,
            req.ticker,
            req.entry_date,
            req.entry_price,
            req.exit_date,
            req.exit_price,
            req.original_thesis,
        )
    )


# ── V2.7: Day Trader mode capabilities ──────────────────────────────────


class DtFlowConfirmRequest(_BaseAdvisorRequest):
    idea: str


class DtRRRequest(_BaseAdvisorRequest):
    entry: float
    stop: float
    target: float
    account_size: float | None = None


@router.post("/dt/setup")
async def post_dt_setup(req: _BaseAdvisorRequest):
    _503_if_no_llm()
    ctx = await advisor.build_dt_context(
        active_symbol=req.active_symbol, watchlist=req.watchlist
    )
    return _stream_response(advisor.stream_dt_setup(ctx))


@router.post("/dt/levels")
async def post_dt_levels(req: _BaseAdvisorRequest):
    _503_if_no_llm()
    ctx = await advisor.build_dt_context(
        active_symbol=req.active_symbol, watchlist=req.watchlist
    )
    return _stream_response(advisor.stream_dt_levels(ctx))


@router.post("/dt/flow-confirm")
async def post_dt_flow_confirm(req: DtFlowConfirmRequest):
    _503_if_no_llm()
    ctx = await advisor.build_dt_context(
        active_symbol=req.active_symbol, watchlist=req.watchlist
    )
    return _stream_response(advisor.stream_dt_flow_confirm(ctx, req.idea))


@router.post("/dt/risk-reward")
async def post_dt_risk_reward(req: DtRRRequest):
    _503_if_no_llm()
    ctx = await advisor.build_dt_context(
        active_symbol=req.active_symbol, watchlist=req.watchlist
    )
    return _stream_response(
        advisor.stream_dt_risk_reward(
            ctx,
            entry=req.entry,
            stop=req.stop,
            target=req.target,
            account_size=req.account_size,
        )
    )


@router.post("/dt/eod-recap")
async def post_dt_eod(req: _BaseAdvisorRequest):
    _503_if_no_llm()
    ctx = await advisor.build_dt_context(
        active_symbol=req.active_symbol, watchlist=req.watchlist
    )
    return _stream_response(advisor.stream_dt_eod(ctx))


@router.post("/dt/ask")
async def post_dt_ask(req: AskRequest):
    _503_if_no_llm()
    ctx = await advisor.build_dt_context(
        active_symbol=req.active_symbol, watchlist=req.watchlist
    )
    return _stream_response(
        advisor.stream_dt_ask(ctx, req.question, _history_dicts(req))
    )
