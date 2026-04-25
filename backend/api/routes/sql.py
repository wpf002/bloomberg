"""Read-only SQL endpoint over DuckDB.

The frontend exposes this as the `SQL` mnemonic — Bloomberg's `BQL`
equivalent for the public-data subset we cache. See `core.sql_engine` for
table definitions and validation rules.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ...core.sql_engine import engine

router = APIRouter()


class SqlQuery(BaseModel):
    query: str = Field(min_length=1, max_length=10000)
    max_rows: int | None = Field(default=None, ge=1, le=100_000)


@router.post("")
async def run_query(body: SqlQuery) -> dict:
    try:
        return await engine.query(body.query, max_rows=body.max_rows)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"sql error: {exc}") from exc


@router.get("/tables")
async def list_tables() -> dict:
    return {"tables": engine.list_tables()}
