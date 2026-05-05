"""Portfolio endpoints.

The original Phase-6 endpoints proxy Alpaca paper-trading state
(positions + account). V2.2 adds an editable layer of manual positions
the user can track alongside Alpaca holdings — useful for off-Alpaca
brokerages, simulated holdings, and pre-funding test setups.

Manual positions are stored in Postgres (`manual_positions` table —
plain table, not a TimescaleDB hypertable: one row per holding, mutated
by the user). Anonymous users get rows under user_id = 0; signed-in
users own rows under their GitHub-mapped user_id. The frontend handles
both transparently.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel, Field

from ...core.auth import current_user
from ...core.database import database
from ...data.sources import get_alpaca_source
from ...models.schemas import Account, Position

router = APIRouter()
_alpaca = get_alpaca_source()
logger = logging.getLogger(__name__)


@router.get("/account", response_model=Account | None)
async def get_account() -> Account | None:
    if not _alpaca.credentials_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Alpaca credentials not configured. Add ALPACA_API_KEY and "
                "ALPACA_API_SECRET to .env (free paper account at "
                "https://alpaca.markets/signup) and restart."
            ),
        )
    account = await _alpaca.get_account()
    if account is None:
        raise HTTPException(status_code=502, detail="Alpaca account fetch failed")
    return account


@router.get("/positions", response_model=List[Position])
async def get_positions() -> List[Position]:
    if not _alpaca.credentials_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Alpaca credentials not configured. Add ALPACA_API_KEY and "
                "ALPACA_API_SECRET to .env (free paper account at "
                "https://alpaca.markets/signup) and restart."
            ),
        )
    return await _alpaca.get_positions()


# ── V2.2: manual positions ────────────────────────────────────────────


class ManualPositionCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    quantity: float
    cost_basis: float
    entry_date: Optional[date] = None
    notes: Optional[str] = Field(default=None, max_length=512)


class ManualPositionUpdate(BaseModel):
    cost_basis: Optional[float] = None
    quantity: Optional[float] = None
    notes: Optional[str] = Field(default=None, max_length=512)
    entry_date: Optional[date] = None


class ManualPosition(BaseModel):
    id: int
    user_id: int
    symbol: str
    quantity: float
    cost_basis: float
    entry_date: Optional[date] = None
    notes: Optional[str] = None
    current_price: Optional[float] = None
    market_value: Optional[float] = None
    unrealized_pl: Optional[float] = None
    unrealized_pl_percent: Optional[float] = None
    source: str = "manual"
    created_at: datetime
    updated_at: datetime


class ImportSummary(BaseModel):
    imported: int = 0
    skipped: int = 0
    errors: List[str] = Field(default_factory=list)


def _ensure_db() -> None:
    if database.pool is None:
        raise HTTPException(status_code=503, detail="Database unavailable for manual positions.")


async def _resolve_user_id(request: Request) -> int:
    """Anonymous users use sentinel id 0. Signed-in users use their real id."""
    user = await current_user(request)
    return int(user.id) if user else 0


async def _enrich_with_quote(rows: list[dict]) -> list[ManualPosition]:
    """Augment rows with the latest Alpaca quote for P/L calculation.

    Failure to fetch a quote is non-fatal — the row is returned with
    market_value/unrealized_pl set to None so the UI can render a "--".
    """
    out: list[ManualPosition] = []
    if not rows:
        return out
    symbols = list({r["symbol"] for r in rows})
    quotes: dict[str, float] = {}
    if _alpaca.credentials_configured() and symbols:
        for sym in symbols:
            try:
                q = await _alpaca.get_stock_quote(sym)
                if q is not None and q.price is not None:
                    quotes[sym] = float(q.price)
            except Exception as exc:
                logger.debug("manual position quote fetch failed for %s: %s", sym, exc)
    for r in rows:
        sym = r["symbol"]
        qty = float(r["quantity"])
        cb = float(r["cost_basis"])
        px = quotes.get(sym)
        market_value = px * qty if px is not None else None
        upl = (px - cb) * qty if px is not None else None
        upl_pct = ((px - cb) / cb * 100.0) if (px is not None and cb) else None
        out.append(
            ManualPosition(
                id=int(r["id"]),
                user_id=int(r["user_id"]),
                symbol=sym,
                quantity=qty,
                cost_basis=cb,
                entry_date=r.get("entry_date"),
                notes=r.get("notes"),
                current_price=px,
                market_value=market_value,
                unrealized_pl=upl,
                unrealized_pl_percent=upl_pct,
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
        )
    return out


@router.get("/manual", response_model=List[ManualPosition])
async def list_manual_positions(request: Request) -> List[ManualPosition]:
    _ensure_db()
    uid = await _resolve_user_id(request)
    async with database.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, user_id, symbol, quantity, cost_basis, entry_date,
                   notes, created_at, updated_at
              FROM manual_positions
             WHERE user_id = $1
             ORDER BY created_at DESC
            """,
            uid,
        )
    return await _enrich_with_quote([dict(r) for r in rows])


@router.post("/manual", response_model=ManualPosition, status_code=201)
async def create_manual_position(
    body: ManualPositionCreate, request: Request
) -> ManualPosition:
    _ensure_db()
    uid = await _resolve_user_id(request)
    sym = body.symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=400, detail="symbol required")
    async with database.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO manual_positions
                (user_id, symbol, quantity, cost_basis, entry_date, notes)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, user_id, symbol, quantity, cost_basis, entry_date,
                      notes, created_at, updated_at
            """,
            uid,
            sym,
            float(body.quantity),
            float(body.cost_basis),
            body.entry_date,
            body.notes,
        )
    enriched = await _enrich_with_quote([dict(row)])
    return enriched[0]


@router.put("/manual/{position_id}", response_model=ManualPosition)
async def update_manual_position(
    position_id: int, body: ManualPositionUpdate, request: Request
) -> ManualPosition:
    _ensure_db()
    uid = await _resolve_user_id(request)
    fields: list[str] = []
    values: list = []
    idx = 1
    if body.cost_basis is not None:
        fields.append(f"cost_basis = ${idx}")
        values.append(float(body.cost_basis))
        idx += 1
    if body.quantity is not None:
        fields.append(f"quantity = ${idx}")
        values.append(float(body.quantity))
        idx += 1
    if body.notes is not None:
        fields.append(f"notes = ${idx}")
        values.append(body.notes)
        idx += 1
    if body.entry_date is not None:
        fields.append(f"entry_date = ${idx}")
        values.append(body.entry_date)
        idx += 1
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    fields.append("updated_at = NOW()")
    values.extend([position_id, uid])
    sql = (
        "UPDATE manual_positions SET " + ", ".join(fields) +
        f" WHERE id = ${idx} AND user_id = ${idx+1} "
        "RETURNING id, user_id, symbol, quantity, cost_basis, entry_date, "
        "notes, created_at, updated_at"
    )
    async with database.acquire() as conn:
        row = await conn.fetchrow(sql, *values)
    if row is None:
        raise HTTPException(status_code=404, detail="manual position not found")
    enriched = await _enrich_with_quote([dict(row)])
    return enriched[0]


@router.delete("/manual/{position_id}")
async def delete_manual_position(position_id: int, request: Request) -> dict:
    _ensure_db()
    uid = await _resolve_user_id(request)
    async with database.acquire() as conn:
        out = await conn.execute(
            "DELETE FROM manual_positions WHERE id = $1 AND user_id = $2",
            position_id,
            uid,
        )
    if not out or not out.endswith(" 1"):
        raise HTTPException(status_code=404, detail="manual position not found")
    return {"id": position_id, "deleted": True}


def _parse_csv_row(row: dict, line_no: int) -> tuple[Optional[ManualPositionCreate], Optional[str]]:
    """Returns (parsed, error_message). Both can be None when the row is
    skippable (header / empty)."""
    sym_raw = (row.get("symbol") or row.get("Symbol") or "").strip().upper()
    qty_raw = (row.get("quantity") or row.get("Quantity") or "").strip()
    cb_raw = (row.get("cost_basis") or row.get("CostBasis") or row.get("cost basis") or "").strip()
    if not sym_raw and not qty_raw and not cb_raw:
        return None, None  # blank row
    if not sym_raw:
        return None, f"line {line_no}: missing symbol"
    try:
        qty = float(qty_raw)
    except ValueError:
        return None, f"line {line_no}: invalid quantity '{qty_raw}'"
    try:
        cb = float(cb_raw)
    except ValueError:
        return None, f"line {line_no}: invalid cost_basis '{cb_raw}'"
    entry_raw = (row.get("entry_date") or row.get("EntryDate") or "").strip()
    entry: Optional[date] = None
    if entry_raw:
        try:
            entry = date.fromisoformat(entry_raw)
        except ValueError:
            return None, f"line {line_no}: invalid entry_date '{entry_raw}' (expected YYYY-MM-DD)"
    notes = (row.get("notes") or row.get("Notes") or "").strip() or None
    return ManualPositionCreate(
        symbol=sym_raw, quantity=qty, cost_basis=cb, entry_date=entry, notes=notes
    ), None


@router.post("/manual/import", response_model=ImportSummary)
async def import_manual_positions(
    request: Request, file: UploadFile = File(...)
) -> ImportSummary:
    """Bulk-import manual positions from a CSV file.

    Required columns: symbol, quantity, cost_basis. Optional: entry_date
    (ISO YYYY-MM-DD), notes. Symbols are validated against Alpaca's
    asset master when available — invalid symbols are skipped and
    reported in the summary.
    """
    _ensure_db()
    uid = await _resolve_user_id(request)
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")
    summary = ImportSummary()
    reader = csv.DictReader(io.StringIO(text))
    rows: list[ManualPositionCreate] = []
    for line_no, raw_row in enumerate(reader, start=2):  # +1 for header line
        parsed, err = _parse_csv_row(raw_row, line_no)
        if err:
            summary.errors.append(err)
            summary.skipped += 1
            continue
        if parsed is None:
            continue
        rows.append(parsed)
    # Optional symbol validation against Alpaca asset master.
    valid_symbols: set[str] | None = None
    if rows and _alpaca.credentials_configured():
        try:
            assets = await _alpaca.list_active_assets()
            valid_symbols = {
                (a.get("symbol") or "").upper()
                for a in assets
                if a.get("symbol")
            }
        except Exception as exc:
            logger.debug("alpaca asset list unavailable, skipping validation: %s", exc)
            valid_symbols = None
    async with database.acquire() as conn:
        for r in rows:
            if valid_symbols is not None and r.symbol not in valid_symbols:
                summary.errors.append(f"{r.symbol}: not a recognized Alpaca asset")
                summary.skipped += 1
                continue
            try:
                await conn.execute(
                    """
                    INSERT INTO manual_positions
                        (user_id, symbol, quantity, cost_basis, entry_date, notes)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    uid,
                    r.symbol,
                    float(r.quantity),
                    float(r.cost_basis),
                    r.entry_date,
                    r.notes,
                )
                summary.imported += 1
            except Exception as exc:
                summary.errors.append(f"{r.symbol}: {exc}")
                summary.skipped += 1
    return summary
