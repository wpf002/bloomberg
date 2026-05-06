from typing import Any, List

from fastapi import APIRouter, HTTPException, Query

from ...data.sources import SecEdgarSource, get_meilisearch
from ...models.schemas import FilingEntry

router = APIRouter()
_edgar = SecEdgarSource()


# SEC climate-rule + ESG form type families. Items 1.05 (cybersecurity)
# and 1.10 (climate) on 8-Ks bleed into the same searches; we lean
# permissive here because the indexer also surfaces text matches.
ESG_FORM_TYPES = [
    "S-K",        # the climate disclosure rule itself, plus subsections
    "10-K",       # contains Item 1C cybersecurity + climate risk discussion
    "8-K",        # current-event filings often cite climate / ESG
    "DEF 14A",    # proxy statements with ESG disclosures
]


@router.get("/search")
async def search_filings(
    q: str = Query(..., min_length=1, description="Full-text search query"),
    symbol: str | None = Query(None, description="Optional symbol filter"),
    form_type: str | None = Query(None, description="Optional form filter (e.g. 10-K)"),
    category: str | None = Query(
        None,
        description="Optional category preset: 'esg' restricts to ESG/climate-relevant form families",
    ),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Full-text filings search via Meilisearch.

    Indexing happens automatically on startup (and daily via the cron) for
    the default watchlist; per-symbol on-demand for everything else via
    POST /api/filings/{symbol}/index.

    `category=esg` is a preset that restricts hits to filing types that
    typically carry ESG/climate disclosures (10-K, 8-K, DEF 14A, S-K).
    Combine with a free-text query like "climate risk" or "GHG emissions"
    for tighter results.
    """
    meili = get_meilisearch()
    # Without this guard, an unreachable Meili silently returns [] and the
    # panel shows "No hits" — indistinguishable from a real zero-match
    # query. Surface the outage so the frontend can render an error.
    if not await meili.health():
        raise HTTPException(status_code=503, detail="search service unavailable")
    if category and category.lower() == "esg" and not form_type:
        # Meilisearch doesn't accept an OR over filterable attributes from
        # a single search call cleanly without a filter expression — issue
        # one call per form type and merge.
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for ft in ESG_FORM_TYPES:
            for hit in await meili.search(q, limit=limit, symbol=symbol, form_type=ft):
                key = hit.get("id") or hit.get("accession_number")
                if key and key not in seen:
                    seen.add(key)
                    merged.append(hit)
                if len(merged) >= limit:
                    break
            if len(merged) >= limit:
                break
        return {"query": q, "hits": merged, "count": len(merged), "category": "esg"}

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
