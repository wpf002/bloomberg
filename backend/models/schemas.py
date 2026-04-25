from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class Quote(BaseModel):
    symbol: str
    price: float
    change: float = 0.0
    change_percent: float = 0.0
    volume: int = 0
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    previous_close: Optional[float] = None
    market_cap: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class QuoteHistoryPoint(BaseModel):
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class CryptoQuote(BaseModel):
    symbol: str
    price: float
    change_24h: float = 0.0
    change_percent_24h: float = 0.0
    volume_24h: float = 0.0
    market_cap: Optional[float] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class MacroSeriesPoint(BaseModel):
    date: date
    value: float


class MacroSeries(BaseModel):
    series_id: str
    title: str
    units: Optional[str] = None
    frequency: Optional[str] = None
    observations: List[MacroSeriesPoint] = Field(default_factory=list)


class NewsItem(BaseModel):
    id: str
    headline: str
    summary: Optional[str] = None
    source: str
    url: str
    symbols: List[str] = Field(default_factory=list)
    published_at: datetime


class FilingEntry(BaseModel):
    accession_number: str
    cik: str
    company: str
    form_type: str
    filed_at: datetime
    primary_document: Optional[str] = None
    url: str


class FxQuote(BaseModel):
    pair: str
    base: str
    quote: str
    price: float
    change: float = 0.0
    change_percent: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class OptionContract(BaseModel):
    contract_symbol: str
    option_type: str
    strike: float
    expiration: str
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    volume: int = 0
    open_interest: int = 0
    implied_volatility: float = 0.0
    in_the_money: bool = False
    delta: Optional[float] = None
    gamma: Optional[float] = None
    vega: Optional[float] = None
    theta: Optional[float] = None
    rho: Optional[float] = None
    moneyness: Optional[float] = None


class OptionChain(BaseModel):
    symbol: str
    underlying_price: Optional[float] = None
    selected_expiration: Optional[str] = None
    expirations: List[str] = Field(default_factory=list)
    calls: List[OptionContract] = Field(default_factory=list)
    puts: List[OptionContract] = Field(default_factory=list)


class OverviewTile(BaseModel):
    symbol: str
    label: str
    asset_class: str
    price: float
    change: float = 0.0
    change_percent: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Fundamentals(BaseModel):
    symbol: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    country: Optional[str] = None
    employees: Optional[int] = None
    website: Optional[str] = None
    market_cap: Optional[float] = None
    enterprise_value: Optional[float] = None
    shares_outstanding: Optional[float] = None
    float_shares: Optional[float] = None
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_book: Optional[float] = None
    price_to_sales: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    dividend_yield: Optional[float] = None
    payout_ratio: Optional[float] = None
    beta: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    revenue_ttm: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    profit_margin: Optional[float] = None
    net_income_ttm: Optional[float] = None
    earnings_growth_yoy: Optional[float] = None
    eps_ttm: Optional[float] = None
    free_cash_flow_ttm: Optional[float] = None
    debt_to_equity: Optional[float] = None
    return_on_equity: Optional[float] = None
    return_on_assets: Optional[float] = None
    analyst_target: Optional[float] = None
    analyst_recommendation: Optional[str] = None
    currency: Optional[str] = None
    exchange: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class EarningsEvent(BaseModel):
    symbol: str
    name: Optional[str] = None
    event_date: date
    when: Optional[str] = None
    eps_estimate: Optional[float] = None
    eps_actual: Optional[float] = None
    eps_surprise_percent: Optional[float] = None
    revenue_estimate: Optional[float] = None
    revenue_actual: Optional[float] = None
    source: str = "finnhub"


class MarketOverview(BaseModel):
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    tiles: List[OverviewTile] = Field(default_factory=list)


class Account(BaseModel):
    account_number: Optional[str] = None
    status: Optional[str] = None
    currency: str = "USD"
    cash: float = 0.0
    buying_power: float = 0.0
    portfolio_value: float = 0.0
    equity: float = 0.0
    last_equity: float = 0.0
    long_market_value: float = 0.0
    short_market_value: float = 0.0
    daytrade_count: int = 0
    pattern_day_trader: bool = False
    source: str = "alpaca-paper"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Position(BaseModel):
    symbol: str
    asset_class: Optional[str] = None
    exchange: Optional[str] = None
    qty: float
    side: str = "long"
    avg_entry_price: float
    current_price: Optional[float] = None
    market_value: Optional[float] = None
    cost_basis: Optional[float] = None
    unrealized_pl: Optional[float] = None
    unrealized_pl_percent: Optional[float] = None
    unrealized_intraday_pl: Optional[float] = None
    unrealized_intraday_pl_percent: Optional[float] = None
    change_today_percent: Optional[float] = None
    source: str = "alpaca-paper"


class SizingRow(BaseModel):
    risk_pct: float  # % of account equity at risk per trade
    max_loss_usd: float  # dollar amount at risk
    shares: int  # floor(max_loss / risk_per_share)
    notional_usd: float  # shares * price
    notional_pct: float  # notional / equity * 100


class PositionSize(BaseModel):
    symbol: str
    price: float
    equity: float
    stop_pct: float  # % below entry you'd exit a losing trade
    rows: List[SizingRow] = Field(default_factory=list)
    source: str = "alpaca-paper"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Brief(BaseModel):
    """LLM-synthesized single-symbol briefing (EXPLAIN)."""
    symbol: str
    body: str
    model: str
    as_of: datetime = Field(default_factory=datetime.utcnow)


class ComparisonBrief(BaseModel):
    """LLM-synthesized multi-symbol comparison (COMPARE)."""
    symbols: List[str]
    body: str
    model: str
    as_of: datetime = Field(default_factory=datetime.utcnow)


class OrderRequest(BaseModel):
    """Inbound order ticket. Mirrors the subset of Alpaca's POST /v2/orders we
    care about — equity orders, including bracket / OCO / OTO order classes
    for set-and-forget retail workflows."""
    symbol: str
    qty: float = Field(gt=0)
    side: str = Field(description="buy or sell")
    type: str = Field(default="market", description="market | limit | stop | stop_limit")
    time_in_force: str = Field(default="day", description="day | gtc | ioc | fok | opg | cls")
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    extended_hours: bool = False
    client_order_id: Optional[str] = None
    # Order class. `simple` is the default single-leg order; `bracket`
    # attaches matching take-profit + stop-loss legs that fill once the entry
    # fills; `oco` is two paired exit legs (no entry leg); `oto` is the entry
    # plus one of the two exit legs.
    order_class: str = Field(default="simple", description="simple | bracket | oco | oto")
    take_profit_limit_price: Optional[float] = None
    stop_loss_stop_price: Optional[float] = None
    stop_loss_limit_price: Optional[float] = None


class Order(BaseModel):
    id: str
    client_order_id: Optional[str] = None
    symbol: str
    asset_class: Optional[str] = None
    side: str
    type: str
    time_in_force: str
    qty: float
    filled_qty: float = 0.0
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    filled_avg_price: Optional[float] = None
    status: str
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    canceled_at: Optional[datetime] = None
    extended_hours: bool = False
    order_class: Optional[str] = None  # simple | bracket | oco | oto
    legs: List["Order"] = Field(default_factory=list)  # bracket/oco children
    source: str = "alpaca-paper"


class AlertCondition(BaseModel):
    """One leaf of an alert rule. Evaluated against the latest quote for
    `symbol`. Operators: `>`, `<`, `>=`, `<=`, `==`."""
    field: str = Field(description="price | change_percent | volume | day_high | day_low")
    op: str = Field(description="> | < | >= | <= | ==")
    value: float


class AlertRule(BaseModel):
    """A user-defined alert. Fires when *all* conditions hold.

    `cooldown_seconds` rate-limits re-firing while the condition stays true —
    without it, a price oscillating around the threshold would spam the user.
    """
    id: str
    symbol: str
    name: Optional[str] = None
    conditions: List[AlertCondition] = Field(default_factory=list)
    cooldown_seconds: int = 300
    active: bool = True
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AlertEvent(BaseModel):
    """Fired event broadcast to WS subscribers + persisted to a Redis stream.

    `user_id` is set when the rule belongs to a signed-in user; None for
    legacy global rules. The streaming layer fans out per-user events on
    `alerts:user:{id}` so users only see their own fires.
    """
    rule_id: str
    symbol: str
    name: Optional[str] = None
    matched_at: datetime = Field(default_factory=datetime.utcnow)
    snapshot: dict = Field(default_factory=dict)
    user_id: Optional[int] = None


class SharedLayout(BaseModel):
    """A Launchpad layout published as a public-read URL."""
    slug: str
    owner_login: str
    name: str
    layouts: dict
    hidden: List[str] = Field(default_factory=list)
    view_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FactorReport(BaseModel):
    """Fama-French 5 + Carhart momentum regression of the user's current
    Alpaca paper portfolio against Ken French daily factors. `alpha_annual`
    is the daily intercept × 252; positive means the portfolio outperforms
    its factor exposures."""
    alpha_annual: float
    alpha_daily: float
    factors: dict  # mkt_rf / smb / hml / rmw / cma / mom betas
    r_squared: float
    observations: int
    first_date: str
    last_date: str
    weights: dict  # symbol → portfolio weight as a check
    insufficient_data: bool = False
    message: Optional[str] = None


class TreasuryAuction(BaseModel):
    """One upcoming or recently announced US Treasury auction."""
    cusip: Optional[str] = None
    security_type: Optional[str] = None  # Bill | Note | Bond | TIPS | FRN
    security_term: Optional[str] = None  # "13-Week" / "10-Year" etc.
    auction_date: Optional[str] = None
    issue_date: Optional[str] = None
    maturity_date: Optional[str] = None
    offering_amount: Optional[float] = None
    high_yield: Optional[float] = None
    interest_rate: Optional[float] = None


class TraceAggregate(BaseModel):
    """One row from FINRA's monthly Treasury trade aggregates dataset.

    The free FINRA developer tier doesn't entitle accounts to corporate-
    bond TRACE prints (those need a paid subscription); the public free
    dataset for retail dev accounts is `treasuryMonthlyAggregates`. We
    keep the schema intentionally generic so future entitlements (corp
    bonds, agency, etc.) can flow through the same pydantic shape.
    """
    period: Optional[str] = None  # month / week label
    security_type: Optional[str] = None  # On-the-Run, Off-the-Run, etc.
    benchmark_term: Optional[str] = None  # 10-Year, 30-Year, etc.
    trade_date: Optional[str] = None
    total_par_volume: Optional[float] = None
    total_trade_count: Optional[int] = None
    avg_trade_size: Optional[float] = None
    pct_dealer_to_customer: Optional[float] = None
    pct_dealer_to_dealer: Optional[float] = None
    raw: Optional[dict] = None  # full source row for the UI to surface unmapped fields


class FuturesContract(BaseModel):
    """Single point on a futures term-structure curve."""
    contract_symbol: str
    expiration: Optional[str] = None
    price: float
    change: float = 0.0
    change_percent: float = 0.0
    volume: int = 0


class FuturesCurve(BaseModel):
    root: str  # CL / GC / NG / ZC / ZS
    label: str
    front_month_price: Optional[float] = None
    contracts: List[FuturesContract] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PayoffLeg(BaseModel):
    """One leg of an options strategy. `type` accepts 'call', 'put', or
    'stock' (stock legs ignore strike/expiration, premium is the cost basis)."""
    type: str
    side: str  # 'long' | 'short'
    strike: float = 0.0
    premium: float = 0.0
    qty: int = 1
    expiration: Optional[str] = None


class PayoffPoint(BaseModel):
    spot: float
    pnl: float


class PayoffCurve(BaseModel):
    underlying_price: float
    legs: List[PayoffLeg]
    points: List[PayoffPoint]
    breakevens: List[float] = Field(default_factory=list)
    max_profit: Optional[float] = None  # None == unbounded
    max_loss: Optional[float] = None  # None == unbounded
    net_premium: float = 0.0  # negative = debit, positive = credit
    contract_multiplier: int = 100
