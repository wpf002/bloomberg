"""Pytest coverage for backend/services/advisor.py.

Network-free: we exercise the prompt builder + import surface so we
catch regressions in the system-prompt assembly without burning Claude
tokens. Live-streaming tests run in /scripts/smoke.py.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from backend.services import advisor
from backend.services.advisor import _system_for, ADVISOR_MODEL


# ── existing coverage ─────────────────────────────────────────────────


def test_advisor_model_id_pinned():
    # Spec: claude-sonnet-4-20250514. If we ever bump it, do so in one place.
    assert ADVISOR_MODEL == "claude-sonnet-4-20250514"


@pytest.mark.parametrize(
    "capability",
    [
        "review",
        "picks",
        "ask",
        "brief",
        "alert-analysis",
        "validate-thesis",
        "simulate",
        "earnings-prep",
        "rebalance",
        "open-brief",
        "post-mortem",
    ],
)
def test_system_prompt_includes_capability_specific_directive(capability):
    prompt = _system_for(capability)
    assert "AURORA" in prompt
    assert "CONTEXT" in prompt
    assert "TASK:" in prompt


def test_system_prompt_for_picks_demands_thesis():
    prompt = _system_for("picks")
    assert "THESIS" in prompt
    assert "Never recommend without a stated thesis" in prompt


def test_system_prompt_forbids_invention():
    for cap in (
        "review",
        "picks",
        "ask",
        "brief",
        "alert-analysis",
        "validate-thesis",
        "simulate",
        "earnings-prep",
        "rebalance",
        "open-brief",
        "post-mortem",
    ):
        prompt = _system_for(cap)
        assert "Never invent" in prompt


def test_advisor_route_module_imports_clean():
    from backend.api.routes import advisor as advisor_route  # noqa: F401
    from backend.api import api_router  # noqa: F401


# ── Phase 9.2: 6 new capabilities ────────────────────────────────────


def test_validate_thesis_prompt_demands_kelly_comparison():
    prompt = _system_for("validate-thesis")
    assert "POSITION SIZING" in prompt
    assert "Kelly" in prompt or "kelly" in prompt.lower()


def test_simulate_prompt_demands_per_position_impact():
    prompt = _system_for("simulate")
    assert "PER-POSITION IMPACT" in prompt
    assert "MOST EXPOSED" in prompt


def test_earnings_prep_prompt_lists_required_sections():
    prompt = _system_for("earnings-prep")
    for sec in ("STREET EXPECTATIONS", "KEY METRICS TO WATCH", "HISTORICAL EARNINGS REACTION", "POSITIONING RECOMMENDATION"):
        assert sec in prompt


def test_rebalance_prompt_covers_kelly_fragility_concentration():
    prompt = _system_for("rebalance")
    assert "OVERSIZED VS KELLY" in prompt
    assert "HIGH FRAGILITY TO REDUCE" in prompt
    assert "SECTOR CONCENTRATIONS" in prompt
    assert "RANKED ACTION LIST" in prompt


def test_open_brief_prompt_expects_overnight_inputs():
    prompt = _system_for("open-brief")
    for sec in ("OVERNIGHT MACRO", "PRE-MARKET MOVERS", "REGIME DELTA", "TOP 3 THINGS TO WATCH TODAY", "ALERTS OVERNIGHT"):
        assert sec in prompt


def test_post_mortem_prompt_classifies_lessons():
    prompt = _system_for("post-mortem")
    assert "LESSON CLASSIFICATION" in prompt
    for cls in ("SIZING", "TIMING", "THESIS", "REGIME-ALIGNMENT", "RISK-MANAGEMENT"):
        assert cls in prompt


# ── stream helpers exist + return async iterator coroutines ──────────


@pytest.mark.parametrize(
    "fn,args",
    [
        ("stream_review", (lambda: ({}, None))),
        ("stream_picks", (lambda: ({}, None))),
        ("stream_ask", (lambda: ({}, "what is up?", None))),
        ("stream_brief", (lambda: ({}, None))),
        ("stream_alert_analysis", (lambda: ({}, {"symbol": "AAPL"}, None))),
        ("stream_validate_thesis", (lambda: ({}, "AAPL", "thesis text", 1000.0))),
        ("stream_simulate", (lambda: ({}, "rates rise 100bps"))),
        ("stream_earnings_prep", (lambda: ({}, "NVDA"))),
        ("stream_rebalance", (lambda: ({},))),
        ("stream_open_brief", (lambda: ({},))),
        ("stream_post_mortem", (lambda: ({}, "AAPL", "2025-01-01", 100.0, "2025-04-01", 110.0, "thesis"))),
    ],
)
def test_stream_helpers_resolve_to_async_iterators(fn, args):
    # The helpers are `async def` returning AsyncIterator[str]. They are
    # coroutines that, when awaited, produce the iterator. We don't iterate
    # (would call the LLM) — only verify the wiring.
    helper = getattr(advisor, fn)
    assert inspect.iscoroutinefunction(helper)
    coro = helper(*args())
    assert inspect.iscoroutine(coro)
    coro.close()


# ── context payload has the new fields plumbed in ─────────────────────


def test_build_context_returns_all_expected_keys():
    """Run build_context with no upstream sources reachable. All sources
    fail safely (no env vars in the test process) and we still get a
    fully-shaped context dict with every Phase-9.2 key present."""
    ctx = asyncio.get_event_loop().run_until_complete(
        advisor.build_context(active_symbol="AAPL", watchlist=["AAPL", "MSFT"])
    )
    # Original Module-4 keys
    for key in (
        "as_of",
        "active_symbol",
        "watchlist",
        "account",
        "positions",
        "regime",
        "fragility",
        "rotation",
        "var_metrics",
        "active_quote",
        "active_news",
    ):
        assert key in ctx
    # Phase 9.2 additions
    for key in (
        "watchlist_quotes",
        "watchlist_pre_market",
        "active_pre_market",
        "watchlist_news_12h",
        "earnings_estimates_watchlist",
        "earnings_reactions_active",
        "yield_curve",
        "mortgage_spread",
        "recent_alerts",
    ):
        assert key in ctx
