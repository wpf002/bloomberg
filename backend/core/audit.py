"""Persistence helpers for the audit_log + intelligence_snapshots
hypertables created in Module 5.

Every write is best-effort: if Postgres is unavailable, the route still
returns the live answer (the in-memory normalizer ring buffer covers
short-term provenance reads). The TimescaleDB tables are the durable
audit trail.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from .database import database

logger = logging.getLogger(__name__)


async def persist_audit(
    *,
    record_id: str | None,
    source: str,
    symbol: str,
    endpoint_called: str | None = None,
    user_id: int | None = None,
    ingested_at: datetime | None = None,
) -> None:
    """Write one audit row. Silent on failure."""
    if database.pool is None:
        return
    ts = ingested_at or datetime.now(timezone.utc)
    try:
        async with database.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_log (ingested_at, record_id, source, symbol, endpoint_called, user_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                ts,
                record_id,
                source,
                symbol.upper(),
                endpoint_called,
                user_id,
            )
    except Exception as exc:
        logger.debug("audit insert failed: %s", exc)


async def persist_normalized(record: Any) -> None:
    """Append a normalized record to the normalized_records hypertable.

    Accepts the NormalizedRecord pydantic model from data.normalizer.
    Skipped silently when the database is unavailable so the normalizer
    can continue serving in dev environments without Postgres.
    """
    if database.pool is None:
        return
    try:
        tags_json = json.dumps(getattr(record, "tags", {}) or {})
        async with database.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO normalized_records
                    (ingested_at, "timestamp", source, symbol, series_id, value, unit, tags)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb)
                """,
                record.ingested_at,
                record.timestamp,
                record.source,
                record.symbol,
                record.series_id,
                record.value,
                record.unit,
                tags_json,
            )
    except Exception as exc:
        logger.debug("normalized insert failed: %s", exc)


def _hash_inputs(inputs: dict[str, Any]) -> str:
    payload = json.dumps(inputs, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


async def persist_intelligence_snapshot(
    kind: str,
    inputs: dict[str, Any],
    output: dict[str, Any],
) -> None:
    """Capture a (kind, inputs, output) triple — full reproducibility."""
    if database.pool is None:
        return
    try:
        async with database.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO intelligence_snapshots
                    (captured_at, kind, inputs_hash, inputs, output)
                VALUES (NOW(), $1, $2, $3::jsonb, $4::jsonb)
                """,
                kind,
                _hash_inputs(inputs),
                json.dumps(inputs, default=str),
                json.dumps(output, default=str),
            )
    except Exception as exc:
        logger.debug("intelligence snapshot insert failed: %s", exc)


async def persist_risk_snapshot(
    kind: str,
    output: dict[str, Any],
    user_id: int | None = None,
) -> None:
    if database.pool is None:
        return
    try:
        async with database.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO risk_snapshots (captured_at, kind, user_id, output)
                VALUES (NOW(), $1, $2, $3::jsonb)
                """,
                kind,
                user_id,
                json.dumps(output, default=str),
            )
    except Exception as exc:
        logger.debug("risk snapshot insert failed: %s", exc)


# ── read API ────────────────────────────────────────────────────────────


async def fetch_audit(
    symbol: str,
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    if database.pool is None:
        return []
    where = "symbol = $1"
    params: list[Any] = [symbol.upper()]
    if from_ts is not None:
        params.append(from_ts)
        where += f" AND ingested_at >= ${len(params)}"
    if to_ts is not None:
        params.append(to_ts)
        where += f" AND ingested_at <= ${len(params)}"
    params.append(int(limit))
    sql = f"""
        SELECT ingested_at, record_id, source, symbol, endpoint_called, user_id
        FROM audit_log WHERE {where}
        ORDER BY ingested_at DESC
        LIMIT ${len(params)}
    """
    try:
        async with database.acquire() as conn:
            rows = await conn.fetch(sql, *params)
    except Exception as exc:
        logger.debug("audit fetch failed: %s", exc)
        return []
    return [dict(r) for r in rows]


async def fetch_intelligence_snapshots(
    kind: str, limit: int = 50
) -> list[dict[str, Any]]:
    if database.pool is None:
        return []
    try:
        async with database.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT captured_at, kind, inputs_hash, inputs, output
                FROM intelligence_snapshots
                WHERE kind = $1
                ORDER BY captured_at DESC
                LIMIT $2
                """,
                kind,
                int(limit),
            )
    except Exception as exc:
        logger.debug("intelligence snapshots fetch failed: %s", exc)
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        for k in ("inputs", "output"):
            if isinstance(d.get(k), str):
                try:
                    d[k] = json.loads(d[k])
                except Exception:
                    pass
        out.append(d)
    return out
