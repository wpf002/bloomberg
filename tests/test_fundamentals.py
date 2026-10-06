"""SEC XBRL fundamentals: TTM extraction, the screener join, and the
universe filter."""

from __future__ import annotations

import asyncio
import datetime as dt
import json

import duckdb
import pytest

from backend.core.xbrl import extract_fundamentals

TODAY = dt.date(2026, 10, 6)


# ── fixture builders ───────────────────────────────────────────────────────

def _fact(start, end, val, form="10-Q", filed="2026-08-01", accn="0000-26-000001"):
    f = {"end": end, "val": val, "form": form, "filed": filed, "accn": accn}
    if start:
        f["start"] = start
    return f


def _doc(**concepts):
    """{'Revenues': [facts], 'dei:EntityCommonStockSharesOutstanding': [facts]}"""
    facts = {"us-gaap": {}, "dei": {}}
    for name, items in concepts.items():
        tax, concept = ("dei", name[4:]) if name.startswith("dei_") else ("us-gaap", name)
        unit = "shares" if "Shares" in concept else "USD"
        facts[tax][concept] = {"units": {unit: items}}
    return {"facts": facts}


CAL_QUARTERS = [
    ("2025-01-01", "2025-03-31"), ("2025-04-01", "2025-06-30"),
    ("2025-07-01", "2025-09-30"), ("2025-10-01", "2025-12-31"),
    ("2026-01-01", "2026-03-31"), ("2026-04-01", "2026-06-30"),
]


# ── TTM extraction ─────────────────────────────────────────────────────────

def test_ttm_sums_last_four_contiguous_quarters():
    rev = [_fact(s, e, v) for (s, e), v in zip(CAL_QUARTERS, [10, 11, 12, 13, 14, 15])]
    f = extract_fundamentals(_doc(Revenues=rev, NetIncomeLoss=rev), TODAY)
    assert f["ttm_revenue"] == 12 + 13 + 14 + 15
    assert f["period_end"] == dt.date(2026, 6, 30)


def test_missing_q4_is_derived_from_the_fiscal_year():
    """Filers rarely tag a standalone Q4; the 10-K reports the year instead."""
    rev = [
        _fact("2025-01-01", "2025-03-31", 10), _fact("2025-04-01", "2025-06-30", 11),
        _fact("2025-07-01", "2025-09-30", 12),
        _fact("2025-01-01", "2025-12-31", 50, form="10-K", filed="2026-02-20"),  # Q4 = 17
        _fact("2026-01-01", "2026-03-31", 14), _fact("2026-04-01", "2026-06-30", 15),
    ]
    f = extract_fundamentals(_doc(Revenues=rev, NetIncomeLoss=rev), TODAY)
    assert f["ttm_revenue"] == 12 + 17 + 14 + 15


def test_off_calendar_fiscal_year():
    """Apple-style 52/53-week year ending in late September."""
    q = [("2024-09-29", "2024-12-28"), ("2024-12-29", "2025-03-29"),
         ("2025-03-30", "2025-06-28"), ("2025-06-29", "2025-09-27"),
         ("2025-09-28", "2025-12-27"), ("2025-12-28", "2026-03-28"),
         ("2026-03-29", "2026-06-27")]
    rev = [_fact(s, e, v) for (s, e), v in zip(q, [100, 90, 85, 95, 140, 110, 105])]
    f = extract_fundamentals(_doc(Revenues=rev, NetIncomeLoss=rev), TODAY)
    assert f["ttm_revenue"] == 95 + 140 + 110 + 105
    assert f["period_end"] == dt.date(2026, 6, 27)


def test_restatement_wins_over_original_filing():
    rev = [_fact(s, e, v) for (s, e), v in zip(CAL_QUARTERS[2:], [12, 13, 14, 15])]
    rev.append(_fact("2026-04-01", "2026-06-30", 16, filed="2026-09-15"))  # restated Q2
    f = extract_fundamentals(_doc(Revenues=rev, NetIncomeLoss=rev), TODAY)
    assert f["ttm_revenue"] == 12 + 13 + 14 + 16


def test_revenue_growth_compares_to_ttm_a_year_earlier():
    quarters = [
        ("2024-07-01", "2024-09-30"), ("2024-10-01", "2024-12-31"),
        *CAL_QUARTERS,
    ]
    vals = [10, 10, 10, 10, 11, 11, 11, 11]  # TTM 40 -> 44
    rev = [_fact(s, e, v) for (s, e), v in zip(quarters, vals)]
    f = extract_fundamentals(_doc(Revenues=rev, NetIncomeLoss=rev), TODAY)
    assert f["revenue_growth_pct"] == pytest.approx(10.0)


def test_revenue_gap_is_filled_from_another_tag():
    """Alphabet's Q4 2024 sits under a different revenue tag than the quarters
    around it; without merging, its prior-year TTM can't chain."""
    q = [("2024-07-01", "2024-09-30"), ("2024-10-01", "2024-12-31"), *CAL_QUARTERS]
    vals = [10, 10, 10, 10, 11, 11, 11, 11]
    main = [_fact(s, e, v) for (s, e), v in zip(q, vals) if s != "2024-10-01"]
    other = [_fact("2024-10-01", "2024-12-31", 10)]
    f = extract_fundamentals(_doc(
        Revenues=main,
        RevenueFromContractWithCustomerExcludingAssessedTax=other,
        NetIncomeLoss=main,
    ), TODAY)
    assert f["revenue_growth_pct"] == pytest.approx(10.0)


def test_multi_class_shares_are_summed_per_filing():
    shares = [
        _fact(None, "2026-07-20", 5.8e9, accn="A"),   # class A
        _fact(None, "2026-07-20", 0.86e9, accn="A"),  # class B
        _fact(None, "2026-07-20", 5.4e9, accn="A"),   # class C
        _fact(None, "2026-04-20", 12.5e9, accn="Z"),  # older filing, ignored
    ]
    rev = [_fact(s, e, 1) for s, e in CAL_QUARTERS]
    f = extract_fundamentals(_doc(Revenues=rev, NetIncomeLoss=rev,
                                  dei_EntityCommonStockSharesOutstanding=shares), TODAY)
    assert f["shares_out"] == pytest.approx(12.06e9)


def test_falls_back_to_diluted_shares_when_cover_page_missing():
    rev = [_fact(s, e, 1) for s, e in CAL_QUARTERS]
    diluted = [_fact("2026-04-01", "2026-06-30", 12.3e9)]
    f = extract_fundamentals(_doc(Revenues=rev, NetIncomeLoss=rev,
                                  WeightedAverageNumberOfDilutedSharesOutstanding=diluted), TODAY)
    assert f["shares_out"] == pytest.approx(12.3e9)


def test_stale_filer_returns_none():
    old = [_fact(s.replace("2025", "2023").replace("2026", "2024"),
                 e.replace("2025", "2023").replace("2026", "2024"), 1) for s, e in CAL_QUARTERS]
    assert extract_fundamentals(_doc(Revenues=old, NetIncomeLoss=old), TODAY) is None


def test_fund_with_no_financials_returns_none():
    assert extract_fundamentals({"facts": {"dei": {}}}, TODAY) is None
    assert extract_fundamentals({}, TODAY) is None


def test_equity_is_latest_instant():
    rev = [_fact(s, e, 1) for s, e in CAL_QUARTERS]
    eq = [_fact(None, "2025-12-31", 900), _fact(None, "2026-06-30", 1000)]
    f = extract_fundamentals(_doc(Revenues=rev, NetIncomeLoss=rev, StockholdersEquity=eq), TODAY)
    assert f["equity"] == 1000


# ── screener join ──────────────────────────────────────────────────────────

def _metrics_with(fund_rows, price=50.0):
    from backend.core.screener import METRICS_SQL
    con = duckdb.connect(":memory:")
    con.execute("""CREATE TABLE bars(symbol TEXT, timestamp TIMESTAMP, open DOUBLE,
                   high DOUBLE, low DOUBLE, close DOUBLE, volume BIGINT)""")
    con.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?)", [
        ("ACME", dt.datetime(2026, 1, 1) + dt.timedelta(days=i), price, price, price, price, 1000)
        for i in range(80)
    ])
    con.execute("""CREATE TABLE fundamentals (symbol TEXT, cik TEXT, shares_out DOUBLE,
                   ttm_revenue DOUBLE, ttm_net_income DOUBLE, equity DOUBLE,
                   revenue_growth_pct DOUBLE, period_end DATE, fetched_at TIMESTAMP)""")
    if fund_rows:
        con.executemany("INSERT INTO fundamentals VALUES (?,?,?,?,?,?,?,?,?)", fund_rows)
    cur = con.execute(METRICS_SQL.format(min_bars=60, where=""))
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, cur.fetchone()))


def test_ratios_computed_from_price_and_fundamentals():
    # 100 shares x $50 = $5,000 market cap
    r = _metrics_with([("ACME", "1", 100, 2500, 250, 1000, 12.0, dt.date(2026, 6, 30), None)])
    assert r["market_cap"] == pytest.approx(5000)
    assert r["pe_ratio"] == pytest.approx(20)
    assert r["ps_ratio"] == pytest.approx(2)
    assert r["pb_ratio"] == pytest.approx(5)
    assert r["net_margin"] == pytest.approx(10)
    assert r["revenue_growth"] == pytest.approx(12)


def test_pe_and_pb_null_when_meaningless():
    r = _metrics_with([("ACME", "1", 100, 2500, -50, -10, None, dt.date(2026, 6, 30), None)])
    assert r["pe_ratio"] is None   # loss-making
    assert r["pb_ratio"] is None   # negative equity
    assert r["net_margin"] == pytest.approx(-2)


def test_symbol_without_fundamentals_still_screens():
    r = _metrics_with([])
    assert r["price"] == 50
    assert r["market_cap"] is None and r["pe_ratio"] is None


# ── refresh: market-cap sanity check against public float ─────────────────

def _filing(shares, public_float):
    rev = [_fact(st, en, 1e9) for st, en in CAL_QUARTERS]
    doc = _doc(Revenues=rev, NetIncomeLoss=rev,
               dei_EntityCommonStockSharesOutstanding=[_fact(None, "2026-07-20", shares)])
    doc["facts"]["dei"]["EntityPublicFloat"] = {"units": {"USD": [
        _fact(None, "2025-06-30", public_float, form="10-K", filed="2026-02-20")]}}
    return json.dumps(doc).encode()


def test_market_cap_checked_against_public_float(monkeypatch):
    """Share counts are company-wide, so they're only right for some tickers.
    Berkshire states shares in Class A equivalents: fine for BRK.A, absurd for
    BRK.B. The earlier price-ratio guard also wrongly nulled JPM and GOOGL,
    whose preferreds share the CIK; preferreds are now out of the universe,
    and the float check judges each ticker on its own."""
    from backend.core import sql_engine as se

    monkeypatch.setattr(se.settings, "duckdb_path", "")
    eng = se.SqlEngine()
    eng.con.execute("""CREATE TABLE screener_metrics AS SELECT * FROM (VALUES
        ('BRK.A', 750000.0), ('BRK.B', 500.0),
        ('GOOGL', 250.0), ('GOOG', 251.0),
        ('JPM', 300.0)) AS t(symbol, price)""")

    filings = {
        "0001067983": _filing(shares=2e6, public_float=1.0e12),     # BRK, A-equivalents
        "0001652044": _filing(shares=12.0e9, public_float=2.0e12),  # Alphabet
        "0000019617": _filing(shares=2.66e9, public_float=7.0e11),  # JPMorgan
    }

    class FakeEdgar:
        async def ticker_map(self):
            return {"BRK-A": "0001067983", "BRK-B": "0001067983",
                    "GOOGL": "0001652044", "GOOG": "0001652044",
                    "JPM": "0000019617"}

        async def company_facts(self, client, cik):
            return filings[cik]

    monkeypatch.setattr(se, "SecEdgarSource", lambda: FakeEdgar())
    monkeypatch.setattr(eng, "_rebuild_metrics", lambda cur=None: None)

    assert asyncio.run(eng.refresh_fundamentals()) == 5
    shares = dict(eng.con.execute("SELECT symbol, shares_out FROM fundamentals").fetchall())
    assert shares["BRK.A"] == 2e6        # 2M x $750k = $1.5T vs $1T float: plausible
    assert shares["BRK.B"] is None       # 2M x $500 = $1B: wrong units, dropped
    assert shares["GOOGL"] == 12.0e9 and shares["GOOG"] == 12.0e9
    assert shares["JPM"] == 2.66e9       # 2.66B x $300 = $798B vs $700B float
    # Fundamentals other than market cap still land for every ticker.
    n = eng.con.execute("SELECT COUNT(ttm_revenue) FROM fundamentals").fetchone()[0]
    assert n == 5


@pytest.mark.parametrize("shares,price,float_,ok", [
    (1e9, 100.0, 1e11, True),     # 1.0x float
    (1e9, 100.0, 4e11, True),     # 0.25x: a stock down 75% since the float date
    (1e9, 100.0, 6e11, False),    # 0.17x: implausible
    (1e9, 100.0, 2.1e10, True),   # 4.8x: a big rally
    (1e9, 100.0, 1.9e10, False),  # 5.3x: implausible
    (1e9, 100.0, None, True),     # no float reported: nothing to check against
    (None, 100.0, 1e11, False),
    (1e9, None, 1e11, False),
])
def test_plausible_market_cap_band(shares, price, float_, ok):
    from backend.core.sql_engine import _plausible_market_cap
    assert _plausible_market_cap(shares, price, float_) is ok


# ── universe filter ────────────────────────────────────────────────────────

@pytest.mark.parametrize("name,symbol,exchange", [
    ("Apple Inc. Common Stock", "AAPL", "NASDAQ"),
    ("MPLX LP Common Units Representing Limited Partner Interests", "MPLX", "NYSE"),
    ("Enterprise Products Partners L.P. Common Units", "EPD", "NYSE"),
    ("Taiwan Semiconductor Manufacturing Company Ltd. American Depositary Shares", "TSM", "NYSE"),
    ("SPDR S&P 500 ETF Trust", "SPY", "ARCA"),
    ("Berkshire Hathaway Inc. Class B", "BRK.B", "NYSE"),
])
def test_screenable_keeps_common_stock_mlps_adrs_and_etfs(name, symbol, exchange):
    from backend.core.sql_engine import _screenable
    assert _screenable({"symbol": symbol, "name": name, "exchange": exchange, "tradable": True})


@pytest.mark.parametrize("name,symbol,exchange", [
    ("Morgan Stanley Depositary Shares, each representing 1/1,000th of 6.5% Preferred Stock", "MS.PRP", "NYSE"),
    ("The Allstate Corporation", "ALL.PRH", "NYSE"),        # caught by symbol
    ("ATHENA TECHNOLOGY ACQUISITION CORP II Warrant", "ATEKW", "NYSE"),
    ("Pono Capital Four, Inc. Units", "PONOU", "NASDAQ"),
    ("QuasarEdge Acquisition Corporation Rights", "QRED.RT", "NASDAQ"),
    ("Unum Group 6.250% Junior Subordinated Notes due 2058", "UNMA", "NYSE"),
    ("ONTRAK INC CUM RED PFD SER A 9.50%", "OTRQQ", "OTC"),
    ("Some Pink Sheet Co", "PNKSF", "OTC"),
])
def test_screenable_drops_non_common_and_otc(name, symbol, exchange):
    from backend.core.sql_engine import _screenable
    assert not _screenable({"symbol": symbol, "name": name, "exchange": exchange, "tradable": True})
