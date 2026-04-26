"""Unified normalization layer between data sources and panels.

Every datum that enters the system is wrapped in a NormalizedRecord, which
carries (source, symbol, series_id, timestamp, ingested_at, value, unit,
tags, raw). Rationale:

- Provenance: each value can be traced back to which source produced it
  and when it was ingested. The /api/provenance endpoint reads this back.
- Consistency: panels can rely on a single shape rather than the per-source
  schemas (Quote, MacroSeriesPoint, FilingEntry, etc.).
- Auditability: normalized records get persisted to the audit/provenance
  hypertables in Module 5 so we can reconstruct what the system knew at
  any point in time.

The normalizer ALSO keeps an in-memory ring buffer per (symbol, series_id)
so the provenance endpoint can serve recent records even before the
TimescaleDB persistence layer is wired in.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Iterable, Sequence

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)


class NormalizedRecord(BaseModel):
    """The single shape every data point flows through."""

    source: str
    symbol: str
    series_id: str
    timestamp: datetime
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    value: float | None = None
    unit: str | None = None
    tags: dict[str, Any] = Field(default_factory=dict)
    raw: dict[str, Any] | None = None


@dataclass
class _RingBuffer:
    """In-memory ring buffer: most-recent N records per (symbol, series_id).

    Used by the provenance endpoint to surface a tail of normalized records
    without requiring the audit-log database to be present. The TimescaleDB
    audit_log added in Module 5 is the durable store; this is the
    short-term cache the API queries first.
    """

    capacity: int = 500
    items: deque = field(default_factory=deque)

    def push(self, rec: NormalizedRecord) -> None:
        self.items.append(rec)
        while len(self.items) > self.capacity:
            self.items.popleft()


class Normalizer:
    """Routes raw values from source adapters into NormalizedRecords.

    Stateless except for the in-memory ring buffer used by the provenance
    endpoint. Safe to share across the FastAPI app as a process singleton.
    """

    def __init__(self, buffer_capacity: int = 500) -> None:
        self._buffers: dict[tuple[str, str], _RingBuffer] = {}
        self._buffer_capacity = buffer_capacity
        self._lock = Lock()

    # ── construction ────────────────────────────────────────────────────

    def normalize(
        self,
        *,
        source: str,
        symbol: str,
        series_id: str,
        value: float | int | None,
        timestamp: datetime | None = None,
        unit: str | None = None,
        tags: dict[str, Any] | None = None,
        raw: dict[str, Any] | None = None,
    ) -> NormalizedRecord:
        """Wrap a single value in a NormalizedRecord.

        Validates types via the pydantic model so malformed input fails
        loudly here rather than three layers deep in a panel.
        """
        ts = timestamp if timestamp is not None else datetime.now(timezone.utc)
        try:
            float_value = float(value) if value is not None else None
        except (TypeError, ValueError) as exc:
            raise ValueError(f"non-numeric value for {symbol}/{series_id}: {value!r}") from exc
        try:
            rec = NormalizedRecord(
                source=str(source),
                symbol=str(symbol).upper(),
                series_id=str(series_id),
                timestamp=ts,
                value=float_value,
                unit=unit,
                tags=dict(tags or {}),
                raw=dict(raw or {}) if raw is not None else None,
            )
        except ValidationError as exc:
            raise ValueError(f"normalize validation failed: {exc}") from exc
        self._record(rec)
        return rec

    def normalize_many(
        self,
        items: Iterable[dict[str, Any]],
    ) -> list[NormalizedRecord]:
        """Bulk variant. Each item must be a dict accepted by `normalize`.

        Malformed items are skipped (logged) rather than failing the batch —
        a single bad bar from an upstream source shouldn't blank a chart.
        """
        out: list[NormalizedRecord] = []
        for it in items:
            try:
                out.append(self.normalize(**it))
            except Exception as exc:
                logger.debug("normalize_many: skipping bad record: %s", exc)
        return out

    # ── source-specific helpers used by the adapter layer ──────────────

    def from_quote(self, source: str, quote: Any) -> NormalizedRecord | None:
        """Adapter convenience: convert a `Quote` model into a normalized
        price record. Returns None when the quote is missing a price."""
        if quote is None:
            return None
        price = getattr(quote, "price", None)
        if price is None:
            return None
        return self.normalize(
            source=source,
            symbol=getattr(quote, "symbol", "?"),
            series_id="price",
            value=price,
            timestamp=getattr(quote, "timestamp", None),
            unit="USD",
            tags={
                "change": getattr(quote, "change", None),
                "change_percent": getattr(quote, "change_percent", None),
                "volume": getattr(quote, "volume", None),
            },
            raw=None,
        )

    def from_bars(
        self,
        source: str,
        symbol: str,
        bars: Sequence[Any],
    ) -> list[NormalizedRecord]:
        """Adapter convenience: convert OHLCV bars to per-close records."""
        out: list[NormalizedRecord] = []
        for b in bars or []:
            close = getattr(b, "close", None)
            ts = getattr(b, "timestamp", None)
            if close is None or ts is None:
                continue
            try:
                out.append(
                    self.normalize(
                        source=source,
                        symbol=symbol,
                        series_id="close",
                        value=close,
                        timestamp=ts,
                        unit="USD",
                        tags={
                            "open": getattr(b, "open", None),
                            "high": getattr(b, "high", None),
                            "low": getattr(b, "low", None),
                            "volume": getattr(b, "volume", None),
                        },
                    )
                )
            except Exception as exc:
                logger.debug("from_bars skipped: %s", exc)
        return out

    def from_macro_series(self, source: str, series: Any) -> list[NormalizedRecord]:
        """Adapter convenience: convert a `MacroSeries` model into one
        normalized record per observation."""
        if series is None:
            return []
        out: list[NormalizedRecord] = []
        sid = getattr(series, "series_id", "?")
        unit = getattr(series, "units", None)
        for pt in getattr(series, "observations", []) or []:
            d = getattr(pt, "date", None)
            v = getattr(pt, "value", None)
            if d is None or v is None:
                continue
            ts = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
            try:
                out.append(
                    self.normalize(
                        source=source,
                        symbol=sid,
                        series_id=sid,
                        value=v,
                        timestamp=ts,
                        unit=unit,
                        tags={"frequency": getattr(series, "frequency", None)},
                    )
                )
            except Exception as exc:
                logger.debug("from_macro_series skipped: %s", exc)
        return out

    def from_fx_quote(self, source: str, fx: Any) -> NormalizedRecord | None:
        if fx is None:
            return None
        price = getattr(fx, "price", None)
        if price is None:
            return None
        return self.normalize(
            source=source,
            symbol=getattr(fx, "pair", "?"),
            series_id="fx_rate",
            value=price,
            timestamp=getattr(fx, "timestamp", None),
            unit=getattr(fx, "quote", None),
            tags={
                "base": getattr(fx, "base", None),
                "quote": getattr(fx, "quote", None),
            },
        )

    def from_filing(self, source: str, filing: Any) -> NormalizedRecord | None:
        """Filings carry no numeric value; we normalize them as a marker
        record with value=None and the form-type carried in tags. The
        ProvenancePanel still surfaces them so users can see which filings
        flowed through the system."""
        if filing is None:
            return None
        return self.normalize(
            source=source,
            symbol=getattr(filing, "cik", None) and (getattr(filing, "company", "?")) or "?",
            series_id=f"filing:{getattr(filing, 'form_type', '?')}",
            value=None,
            timestamp=getattr(filing, "filed_at", None),
            unit=None,
            tags={
                "company": getattr(filing, "company", None),
                "cik": getattr(filing, "cik", None),
                "accession_number": getattr(filing, "accession_number", None),
                "url": getattr(filing, "url", None),
            },
        )

    # ── provenance read API ─────────────────────────────────────────────

    def recent(
        self,
        symbol: str,
        limit: int = 50,
        series_id: str | None = None,
    ) -> list[NormalizedRecord]:
        """Most-recent normalized records for a symbol, newest first."""
        sym = symbol.upper()
        with self._lock:
            buckets = [
                buf for (s, _), buf in self._buffers.items() if s == sym
            ]
        merged: list[NormalizedRecord] = []
        for buf in buckets:
            for rec in buf.items:
                if series_id and rec.series_id != series_id:
                    continue
                merged.append(rec)
        merged.sort(key=lambda r: r.ingested_at, reverse=True)
        return merged[: max(1, int(limit))]

    def deduplicate(
        self, records: Iterable[NormalizedRecord]
    ) -> list[NormalizedRecord]:
        """Multi-source dedup by (symbol, series_id, timestamp), preferring
        records with the earliest ingestion (the first source that surfaced
        the value). Preserves input order otherwise.
        """
        seen: dict[tuple[str, str, datetime], NormalizedRecord] = {}
        for r in records:
            key = (r.symbol, r.series_id, r.timestamp)
            existing = seen.get(key)
            if existing is None or r.ingested_at < existing.ingested_at:
                seen[key] = r
        return list(seen.values())

    # ── internals ───────────────────────────────────────────────────────

    def _record(self, rec: NormalizedRecord) -> None:
        key = (rec.symbol, rec.series_id)
        with self._lock:
            buf = self._buffers.get(key)
            if buf is None:
                buf = _RingBuffer(capacity=self._buffer_capacity)
                self._buffers[key] = buf
            buf.push(rec)


_normalizer_singleton: Normalizer | None = None


def get_normalizer() -> Normalizer:
    """Process-wide normalizer. Adapters and routes both use this."""
    global _normalizer_singleton
    if _normalizer_singleton is None:
        _normalizer_singleton = Normalizer()
    return _normalizer_singleton
