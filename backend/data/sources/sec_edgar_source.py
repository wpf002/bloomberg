import logging
from datetime import datetime
from typing import List

import httpx

from ...core.cache_utils import cached
from ...core.config import settings
from ...models.schemas import FilingEntry

logger = logging.getLogger(__name__)

EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"


class SecEdgarSource:
    """Minimal client for the SEC EDGAR submissions and ticker endpoints."""

    def __init__(self) -> None:
        self._headers = {
            "User-Agent": settings.sec_user_agent,
            "Accept": "application/json",
        }
        self._ticker_cache: dict[str, str] | None = None

    async def _load_ticker_map(self, client: httpx.AsyncClient) -> dict[str, str]:
        if self._ticker_cache is not None:
            return self._ticker_cache
        resp = await client.get(EDGAR_TICKERS_URL, headers=self._headers)
        resp.raise_for_status()
        raw = resp.json()
        self._ticker_cache = {
            row["ticker"].upper(): str(row["cik_str"]).zfill(10)
            for row in raw.values()
        }
        return self._ticker_cache

    @cached("edgar:filings", ttl=600, model=FilingEntry)
    async def recent_filings(
        self,
        symbol: str,
        form_types: List[str] | None = None,
        limit: int = 20,
    ) -> List[FilingEntry]:
        form_types = [f.upper() for f in (form_types or ["10-K", "10-Q", "8-K"])]
        async with httpx.AsyncClient(timeout=15.0) as client:
            tickers = await self._load_ticker_map(client)
            cik = tickers.get(symbol.upper())
            if not cik:
                logger.info("SEC EDGAR: ticker %s not found", symbol)
                return []
            url = EDGAR_SUBMISSIONS_URL.format(cik=cik)
            resp = await client.get(url, headers=self._headers)
        if resp.status_code != 200:
            logger.warning("EDGAR submissions %s -> %s", cik, resp.status_code)
            return []
        payload = resp.json()
        company = payload.get("name", symbol.upper())
        recent = payload.get("filings", {}).get("recent", {})
        accession_numbers = recent.get("accessionNumber", [])
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])
        out: List[FilingEntry] = []
        for idx, form in enumerate(forms):
            if form.upper() not in form_types:
                continue
            accession = accession_numbers[idx]
            primary = primary_docs[idx] if idx < len(primary_docs) else None
            stripped = accession.replace("-", "")
            filing_url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{stripped}/"
                f"{primary}" if primary else
                f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}"
            )
            out.append(
                FilingEntry(
                    accession_number=accession,
                    cik=cik,
                    company=company,
                    form_type=form,
                    filed_at=datetime.fromisoformat(dates[idx]),
                    primary_document=primary,
                    url=filing_url,
                )
            )
            if len(out) >= limit:
                break
        return out
