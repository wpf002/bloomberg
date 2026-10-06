"""Trailing-twelve-month fundamentals from SEC XBRL `companyfacts`.

SEC publishes every US filer's tagged financials as JSON, free and public
domain, which makes it the one fundamentals source with no plan limits and no
redistribution question. The work is turning raw tagged facts into TTM figures:

* Facts repeat across filings (each 10-Q restates prior periods). Dedupe on
  the exact (start, end) period and keep the most recently filed value, so
  restatements win.
* Companies report 3-month quarters in 10-Qs but rarely a standalone fourth
  quarter; the 10-K gives the full year instead. Q4 is derived as the fiscal
  year minus its first three quarters.
* TTM is the sum of the four most recent contiguous quarters, using exact
  period dates. That works for off-calendar fiscal years (Apple ends in
  September, Microsoft in June), which SEC's calendar-aligned `frames` API
  can't.

Everything here is pure: dict in, dict out, so it's tested against fixtures
without the network.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

# Tried in order; the concept with the most recent data wins. Filers switched
# concepts over the years (SalesRevenueNet before ASC 606, the
# RevenueFromContract... family after), and banks use their own.
REVENUE_CONCEPTS = (
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "RevenuesNetOfInterestExpense",
)
NET_INCOME_CONCEPTS = (
    "NetIncomeLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
    "ProfitLoss",
)
EQUITY_CONCEPTS = (
    "StockholdersEquity",
    "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
)

FORMS = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT", "10-QT"})

QUARTER_DAYS = (80, 100)   # 13-week quarters are 91 days; 14-week ones 98
YEAR_DAYS = (350, 380)     # 52/53-week fiscal years are 364 or 371 days
CONTIGUOUS_GAP = 5         # days allowed between one quarter's end and the next's start
STALE_AFTER = timedelta(days=460)  # ~15 months: older than that, the filer has gone quiet


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _facts(doc: dict, taxonomy: str, concept: str, unit: str) -> list[dict]:
    try:
        return doc["facts"][taxonomy][concept]["units"][unit]
    except (KeyError, TypeError):
        return []


def _durations(facts: Iterable[dict]) -> dict[tuple[date, date], float]:
    """{(start, end): value}, one per exact period, latest filing wins."""
    best: dict[tuple[date, date], dict] = {}
    for f in facts:
        if f.get("form") not in FORMS or "start" not in f or f.get("val") is None:
            continue
        try:
            key = (_d(f["start"]), _d(f["end"]))
        except (KeyError, ValueError):
            continue
        prior = best.get(key)
        if prior is None or f.get("filed", "") >= prior.get("filed", ""):
            best[key] = f
    return {k: float(v["val"]) for k, v in best.items()}


def _quarters(periods: dict[tuple[date, date], float]) -> list[tuple[date, date, float]]:
    """Every 3-month period, plus fourth quarters derived from fiscal years."""
    qs = {
        (s, e): v for (s, e), v in periods.items()
        if QUARTER_DAYS[0] <= (e - s).days <= QUARTER_DAYS[1]
    }
    years = [
        (s, e, v) for (s, e), v in periods.items()
        if YEAR_DAYS[0] <= (e - s).days <= YEAR_DAYS[1]
    ]
    for ys, ye, yv in years:
        inside = sorted(
            (qs_, qe, qv) for (qs_, qe), qv in qs.items()
            if qs_ >= ys - timedelta(days=CONTIGUOUS_GAP) and qe <= ye + timedelta(days=CONTIGUOUS_GAP)
        )
        if len(inside) != 3:
            continue
        last_end = inside[-1][1]
        # Only derive when the missing quarter is the last one; a gap in the
        # middle means the facts are irregular, so leave it alone.
        if (ye - last_end).days < QUARTER_DAYS[0]:
            continue
        q4_start = last_end + timedelta(days=1)
        if (q4_start, ye) not in qs:
            qs[(q4_start, ye)] = yv - sum(q[2] for q in inside)
    return sorted((s, e, v) for (s, e), v in qs.items())


def _ttm_ending(quarters: list[tuple[date, date, float]], end: date | None = None):
    """Sum of four contiguous quarters ending at `end` (or the latest).
    Returns (value, period_end) or None."""
    if not quarters:
        return None
    if end is None:
        idx = len(quarters) - 1
    else:
        candidates = [i for i, q in enumerate(quarters) if abs((q[1] - end).days) <= 10]
        if not candidates:
            return None
        idx = candidates[-1]
    chain = [quarters[idx]]
    for prev in reversed(quarters[:idx]):
        gap = (chain[-1][0] - prev[1]).days
        if 0 <= gap <= CONTIGUOUS_GAP:
            chain.append(prev)
            if len(chain) == 4:
                break
        elif gap > CONTIGUOUS_GAP:
            break
        # gap < 0: overlapping period from an odd filing; skip it
    if len(chain) < 4:
        return None
    return sum(q[2] for q in chain), chain[0][1]


def _ttm(doc: dict, concepts: Iterable[str], *, merge: bool = False):
    """Best TTM across candidate concepts: the one ending most recently.
    Returns (value, period_end, prior_year_value_or_None) or None.

    `merge` fills periods missing from a higher-priority concept with values
    from lower-priority ones. Revenue needs it: filers move between revenue
    tags, and Alphabet's Q4 2024 sits under a different tag than the quarters
    around it, which broke its prior-year chain. Only gaps are filled, so a
    period's value always comes from the highest-priority tag that has it.
    Net income must not merge: its variants measure different things
    (ProfitLoss includes noncontrolling interests).
    """
    concepts = list(concepts)
    if merge:
        merged: dict[tuple[date, date], float] = {}
        for concept in concepts:
            for k, v in _durations(_facts(doc, "us-gaap", concept, "USD")).items():
                merged.setdefault(k, v)
        candidates = [merged] if merged else []
    else:
        candidates = [_durations(_facts(doc, "us-gaap", c, "USD")) for c in concepts]

    best = None
    for periods in candidates:
        if not periods:
            continue
        qs = _quarters(periods)
        now = _ttm_ending(qs)
        if now is None:
            # Fall back to the latest full fiscal year if quarters don't chain.
            years = [(e, v) for (s, e), v in periods.items()
                     if YEAR_DAYS[0] <= (e - s).days <= YEAR_DAYS[1]]
            if not years:
                continue
            e, v = max(years)
            now = (v, e)
        prior = _ttm_ending(qs, now[1] - timedelta(days=364))
        candidate = (now[0], now[1], prior[0] if prior else None)
        if best is None or candidate[1] > best[1]:
            best = candidate
    return best


def _latest_instant(doc: dict, taxonomy: str, concepts: Iterable[str], unit: str):
    """(value, end) of the most recent point-in-time fact across concepts."""
    best = None
    for concept in concepts:
        for f in _facts(doc, taxonomy, concept, unit):
            if f.get("val") is None or "start" in f:
                continue
            try:
                end = _d(f["end"])
            except (KeyError, ValueError):
                continue
            if best is None or (end, f.get("filed", "")) > (best[1], best[2]):
                best = (float(f["val"]), end, f.get("filed", ""))
    return (best[0], best[1]) if best else None


def _shares_outstanding(doc: dict):
    """Cover-page shares outstanding, summed across share classes.

    Multi-class filers (Alphabet's A/B/C) report one value per class on the
    same date in the same filing; the total is their sum.
    """
    facts = _facts(doc, "dei", "EntityCommonStockSharesOutstanding", "shares")
    dated = []
    for f in facts:
        if f.get("val") is None:
            continue
        try:
            dated.append((_d(f["end"]), f.get("accn", ""), float(f["val"])))
        except (KeyError, ValueError):
            continue
    if not dated:
        return None
    latest_end = max(d[0] for d in dated)
    on_date = [d for d in dated if d[0] == latest_end]
    accn = max(d[1] for d in on_date)  # one filing's view of that date
    total = sum(d[2] for d in on_date if d[1] == accn)
    return (total, latest_end) if total > 0 else None


def _weighted_diluted_shares(doc: dict):
    """Latest quarter's weighted-average diluted share count.

    Fallback for filers whose cover-page share count is reported per class
    (Alphabet, Berkshire), which companyfacts leaves out. It's the total
    across classes, so it slightly overstates shares outstanding, by the
    dilution. Berkshire states it in Class A equivalents; the caller guards
    tickers whose classes trade at very different prices.
    """
    for concept in ("WeightedAverageNumberOfDilutedSharesOutstanding",
                    "WeightedAverageNumberOfSharesOutstandingBasic"):
        periods = _durations(_facts(doc, "us-gaap", concept, "shares"))
        quarters = [(e, v) for (s, e), v in periods.items()
                    if QUARTER_DAYS[0] <= (e - s).days <= QUARTER_DAYS[1] and v > 0]
        if quarters:
            e, v = max(quarters)
            return v, e
    return None


def extract_fundamentals(doc: dict, today: date) -> dict[str, Any] | None:
    """TTM revenue and net income, revenue growth, equity and shares out.

    Returns None when the filer has no usable recent data (funds, shells,
    foreign filers on IFRS, companies that stopped filing).
    """
    if not isinstance(doc, dict) or "facts" not in doc:
        return None
    revenue = _ttm(doc, REVENUE_CONCEPTS, merge=True)
    income = _ttm(doc, NET_INCOME_CONCEPTS)
    if revenue is None and income is None:
        return None

    period_end = max(x[1] for x in (revenue, income) if x is not None)
    if today - period_end > STALE_AFTER:
        return None

    equity = _latest_instant(doc, "us-gaap", EQUITY_CONCEPTS, "USD")
    shares = _shares_outstanding(doc)
    if shares is None or (period_end - shares[1]).days > 200:
        shares = _weighted_diluted_shares(doc) or shares

    # Market value of non-affiliate shares, in USD, from the 10-K cover. Used
    # downstream to sanity-check shares x price (see sql_engine).
    pf = _latest_instant(doc, "dei", ("EntityPublicFloat",), "USD")

    growth = None
    if revenue and revenue[2] and revenue[2] > 0:
        growth = (revenue[0] / revenue[2] - 1.0) * 100.0

    return {
        "ttm_revenue": revenue[0] if revenue else None,
        "ttm_net_income": income[0] if income else None,
        "revenue_growth_pct": growth,
        "equity": equity[0] if equity else None,
        "shares_out": shares[0] if shares else None,
        "public_float": pf[0] if pf and pf[0] > 0 else None,
        "period_end": period_end,
    }
