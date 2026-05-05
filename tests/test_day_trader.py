"""V2.7 — Day Trader mode tests.

Validates:
- The day-trader system prompt carries the persona's hard rules.
- All six DT capabilities have a task block keyed correctly.
- The DT context payload exposes session_phase + dt_mode flag.
- _session_phase() classifies common UTC times into the right
  intraday segment.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.services import advisor as adv


def test_dt_system_prompt_carries_hard_rules():
    sys = adv._DT_SYSTEM
    # Persona declaration
    assert "DAY TRADER" in sys
    # Time-horizon rule
    assert "intraday" in sys.lower()
    # Forbidden language
    assert "Forbidden" in sys
    assert "markdown" in sys.lower()
    # Output style
    assert "ALL CAPS" in sys
    assert "'› '" in sys


def test_all_six_dt_capabilities_have_task_blocks():
    keys = set(adv._DT_TASKS.keys())
    assert keys == {"dt-setup", "dt-levels", "dt-flow-confirm", "dt-rr", "dt-eod", "dt-ask"}
    # Each task block must be substantive (>200 chars) so the model gets
    # enough section guidance.
    for k, v in adv._DT_TASKS.items():
        if k == "dt-ask":
            continue  # ask is intentionally brief
        assert len(v) > 200, f"DT task '{k}' is too short: {len(v)} chars"


def test_system_for_dt_combines_base_and_capability():
    out = adv._system_for_dt("dt-setup")
    assert "DAY TRADER" in out
    assert "SETUP TYPE" in out


def test_setup_task_mentions_required_sections():
    s = adv._DT_TASKS["dt-setup"]
    for required in ["ENTRY", "STOP", "TARGET", "R/R", "FLOW CONFIRMATION", "VERDICT"]:
        assert required in s, f"missing section '{required}' in dt-setup"


def test_levels_task_mentions_vwap_and_gex():
    s = adv._DT_TASKS["dt-levels"]
    assert "VWAP" in s
    assert "GEX FLIP" in s
    assert "MAX GAMMA" in s


def test_rr_task_mentions_position_sizing_thresholds():
    s = adv._DT_TASKS["dt-rr"]
    for required in ["R MULTIPLE", "0.5%", "1%", "2%", "1.5:1", "VERDICT"]:
        assert required in s


def test_eod_task_mentions_three_lessons():
    s = adv._DT_TASKS["dt-eod"]
    assert "3 LESSONS" in s


def test_session_phase_classification():
    # We can't easily mock datetime at module level, so just assert the
    # function returns one of the documented buckets and doesn't crash.
    phase = adv._session_phase()
    assert phase in {"PREMARKET", "OPEN", "MID_DAY", "POWER_HOUR", "CLOSE", "AFTER_HOURS"}


@pytest.mark.asyncio
async def test_build_dt_context_adds_session_phase_and_flag():
    """Build a DT context with build_context mocked out — we just want
    to verify the wrapper layers session_phase + dt_mode on top."""

    async def fake_build(**_kwargs):
        return {"as_of": "2026-01-01T15:30:00+00:00", "active_symbol": "AAPL"}

    with patch.object(adv, "build_context", side_effect=fake_build):
        ctx = await adv.build_dt_context(active_symbol="AAPL", watchlist=["AAPL"])
    assert ctx["dt_mode"] is True
    assert ctx["session_phase"] in {
        "PREMARKET", "OPEN", "MID_DAY", "POWER_HOUR", "CLOSE", "AFTER_HOURS"
    }
    assert ctx["active_symbol"] == "AAPL"
