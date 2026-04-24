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


class MarketOverview(BaseModel):
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    tiles: List[OverviewTile] = Field(default_factory=list)
