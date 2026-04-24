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
