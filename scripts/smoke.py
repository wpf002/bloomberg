"""Offline smoke test for the Bloomberg Terminal backend.

Runs without hitting any network: exercises module imports, pydantic schema
construction, Black-Scholes Greeks sanity, and asserts every FastAPI route is
registered. Exit non-zero on any failure so CI / pre-push hooks can block.

Run from repo root:
    python scripts/smoke.py
or with uv:
    uv run --python 3.11 python scripts/smoke.py
"""

from __future__ import annotations

import importlib
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}{(' :: ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


# ─── modules ────────────────────────────────────────────────────────────────
print("== modules ==")
MODULES = [
    "backend.main",
    "backend.core.config",
    "backend.core.database",
    "backend.core.cache_utils",
    "backend.core.bsm",
    "backend.core.llm",
    "backend.models.schemas",
    "backend.api",
    "backend.api.routes.quotes",
    "backend.api.routes.macro",
    "backend.api.routes.crypto",
    "backend.api.routes.fx",
    "backend.api.routes.options",
    "backend.api.routes.overview",
    "backend.api.routes.fundamentals",
    "backend.api.routes.calendar",
    "backend.api.routes.news",
    "backend.api.routes.filings",
    "backend.api.routes.portfolio",
    "backend.api.routes.sizing",
    "backend.api.routes.explain",
    "backend.api.routes.compare",
    "backend.data.sources",
    "backend.data.sources.alpaca_source",
    "backend.data.sources.fred_source",
    "backend.data.sources.rss_source",
    "backend.data.sources.sec_edgar_source",
    "backend.data.sources.yfinance_source",
]
for name in MODULES:
    try:
        importlib.import_module(name)
        check(name, True)
    except Exception as exc:
        check(name, False, repr(exc))


# ─── schemas ────────────────────────────────────────────────────────────────
print("\n== schemas ==")
from backend.models.schemas import (  # noqa: E402
    Account,
    Brief,
    ComparisonBrief,
    EarningsEvent,
    Fundamentals,
    OptionChain,
    OptionContract,
    Position,
    PositionSize,
    Quote,
    SizingRow,
)

check("Quote", bool(Quote(symbol="AAPL", price=200.0)))
check("Fundamentals", bool(Fundamentals(symbol="AAPL", pe_ratio=30.0)))
check(
    "OptionChain+Contract",
    bool(
        OptionChain(
            symbol="AAPL",
            calls=[
                OptionContract(
                    contract_symbol="AAPL240621C00200000",
                    option_type="call",
                    strike=200.0,
                    expiration="2024-06-21",
                    implied_volatility=0.25,
                )
            ],
        )
    ),
)
check(
    "EarningsEvent",
    bool(EarningsEvent(symbol="AAPL", event_date=date(2024, 8, 1))),
)
check(
    "Account",
    bool(
        Account(
            account_number="PA123",
            status="ACTIVE",
            cash=10_000.0,
            buying_power=40_000.0,
            portfolio_value=50_000.0,
            equity=50_000.0,
            last_equity=49_500.0,
        )
    ),
)
check(
    "Position",
    bool(
        Position(
            symbol="AAPL",
            qty=10.0,
            avg_entry_price=180.0,
            current_price=200.0,
            market_value=2000.0,
            unrealized_pl=200.0,
            unrealized_pl_percent=11.11,
        )
    ),
)
check(
    "PositionSize",
    bool(
        PositionSize(
            symbol="AAPL",
            price=200.0,
            equity=100_000.0,
            stop_pct=5.0,
            rows=[SizingRow(risk_pct=1.0, max_loss_usd=1000.0, shares=100, notional_usd=20_000.0, notional_pct=20.0)],
        )
    ),
)
check("Brief", bool(Brief(symbol="AAPL", body="…", model="claude-sonnet-4-6")))
check(
    "ComparisonBrief",
    bool(ComparisonBrief(symbols=["AAPL", "MSFT"], body="…", model="claude-sonnet-4-6")),
)


# ─── BSM Greeks sanity ──────────────────────────────────────────────────────
print("\n== BSM Greeks ==")
from backend.core.bsm import bsm_greeks  # noqa: E402

# 1-year ATM options, 4.5% risk-free, 20% vol
call = bsm_greeks(spot=100.0, strike=100.0, t_years=1.0, rate=0.045, sigma=0.2, is_call=True)
put = bsm_greeks(spot=100.0, strike=100.0, t_years=1.0, rate=0.045, sigma=0.2, is_call=False)

check("ATM call delta in (0,1)", 0.0 < call.delta < 1.0, f"delta={call.delta:.4f}")
check("ATM put delta in (-1,0)", -1.0 < put.delta < 0.0, f"delta={put.delta:.4f}")
check("call/put gamma equal", abs(call.gamma - put.gamma) < 1e-9)
check("call/put vega equal", abs(call.vega - put.vega) < 1e-9)
check("positive gamma", call.gamma > 0)
check("positive vega", call.vega > 0)


# ─── routes ─────────────────────────────────────────────────────────────────
print("\n== routes ==")
from backend.main import app  # noqa: E402

registered = {
    (method, route.path)
    for route in app.routes
    if hasattr(route, "methods")
    for method in route.methods
}

EXPECTED = [
    ("GET", "/"),
    ("GET", "/healthz"),
    ("GET", "/api/quotes"),
    ("GET", "/api/quotes/{symbol}"),
    ("GET", "/api/quotes/{symbol}/history"),
    ("GET", "/api/macro/series"),
    ("GET", "/api/crypto"),
    ("GET", "/api/fx"),
    ("GET", "/api/options/{symbol}"),
    ("GET", "/api/overview"),
    ("GET", "/api/fundamentals/{symbol}"),
    ("GET", "/api/calendar/earnings"),
    ("GET", "/api/news"),
    ("GET", "/api/filings/{symbol}"),
    ("GET", "/api/portfolio/account"),
    ("GET", "/api/portfolio/positions"),
    ("GET", "/api/sizing/{symbol}"),
    ("GET", "/api/explain/{symbol}"),
    ("GET", "/api/compare"),
]
for method, path in EXPECTED:
    check(f"{method} {path}", (method, path) in registered)


# ─── summary ────────────────────────────────────────────────────────────────
print("")
if failures:
    print(f"FAIL :: {len(failures)} failing check(s):")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)

print("OK :: all smoke checks passed")
