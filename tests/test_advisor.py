"""Pytest coverage for backend/services/advisor.py.

Network-free: we exercise the prompt builder + import surface so we
catch regressions in the system-prompt assembly without burning Claude
tokens. Live-streaming tests run in /scripts/smoke.py.
"""

from __future__ import annotations

import pytest

from backend.services.advisor import _system_for, ADVISOR_MODEL


def test_advisor_model_id_pinned():
    # Spec: claude-sonnet-4-20250514. If we ever bump it, do so in one place.
    assert ADVISOR_MODEL == "claude-sonnet-4-20250514"


@pytest.mark.parametrize(
    "capability",
    ["review", "picks", "ask", "brief", "alert-analysis"],
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
    for cap in ("review", "picks", "ask", "brief", "alert-analysis"):
        prompt = _system_for(cap)
        assert "Never invent" in prompt


def test_advisor_route_module_imports_clean():
    # Route layer pulls FastAPI + the advisor service together. If anything
    # in the wiring is broken we want pytest to surface it before runtime.
    from backend.api.routes import advisor as advisor_route  # noqa: F401
    from backend.api import api_router  # noqa: F401
