from typing import Any, List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import SecEdgarSource, get_meilisearch
from ...models.schemas import FilingEntry

router = APIRouter()
_edgar = SecEdgarSource()


@router.get("/search")
async def search_filings(
    q: str = Query(..., min_length=1, description="Full-text search query"),
    symbol: str | None = Query(None, description="Optional symbol filter"),
    form_type: str | None = Query(None, description="Optional form filter (e.g. 10-K)"),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Full-text filings search via Meilisearch.

    Indexing happens on demand via POST /api/filings/{symbol}/index — a
    fresh deployment with no indexed filings will return zero hits until
    the user requests indexing for the symbols they care about.
    """
    meili = get_meilisearch()
    hits = await meili.search(q, limit=limit, symbol=symbol, form_type=form_type)
    return {"query": q, "hits": hits, "count": len(hits)}


@router.post("/{symbol}/index")
async def index_filings_for_symbol(
    symbol: str,
    forms: str = Query("10-K,10-Q,8-K", description="Comma-separated SEC form types"),
    limit: int = Query(10, ge=1, le=40),
    full_text: bool = Query(False, description="Also fetch+index document body (slow)"),
) -> dict[str, Any]:
    sym = symbol.upper()
    form_types = [f.strip().upper() for f in forms.split(",") if f.strip()]
    try:
        filings = await _edgar.recent_filings(sym, form_types=form_types, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"edgar error: {exc}") from exc
    meili = get_meilisearch()
    if not await meili.health():
        raise HTTPException(status_code=503, detail="meilisearch unavailable")
    indexed = await meili.index_filings_metadata(sym, filings)
    bodies_indexed = 0
    if full_text:
        for f in filings:
            ok = await meili.index_filing_body(f)
            if ok:
                bodies_indexed += 1
    return {
        "symbol": sym,
        "indexed": indexed,
        "bodies_indexed": bodies_indexed,
        "filings": [f.accession_number for f in filings],
    }


@router.get("/{symbol}", response_model=List[FilingEntry])
async def get_filings(
    symbol: str,
    forms: str = Query("10-K,10-Q,8-K", description="Comma-separated SEC form types"),
    limit: int = Query(20, ge=1, le=100),
) -> List[FilingEntry]:
    form_types = [f.strip().upper() for f in forms.split(",") if f.strip()]
    try:
        return await _edgar.recent_filings(symbol.upper(), form_types=form_types, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"edgar error: {exc}") from exc
