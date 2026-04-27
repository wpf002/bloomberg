"""Meilisearch client for full-text filings search.

We index two layers:

  - Filing metadata (symbol, form, date, accession, url) — always cheap,
    indexed via `index_filings_metadata`.
  - The text of the primary document — fetched from EDGAR on demand and
    capped at ~500KB per filing (most 10-Ks are larger; we trade
    completeness for latency and disk).

The HTTP layer is thin and uses httpx so we don't pull a dedicated client
library. Meilisearch's REST API is small.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Iterable

import httpx

from ...core.config import settings
from ...models.schemas import FilingEntry

logger = logging.getLogger(__name__)


FILINGS_INDEX = "filings"
PRIMARY_KEY = "id"


def _accession_id(accession: str) -> str:
    return accession.replace("-", "")


def _strip_html(html: str) -> str:
    """Cheap HTML/text cleanup. EDGAR docs are large and full of XBRL noise;
    a heavy parse isn't worth it. Drop tags + whitespace-collapse."""
    no_script = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    no_tags = re.sub(r"<[^>]+>", " ", no_script)
    return re.sub(r"\s+", " ", no_tags).strip()


class MeilisearchSource:
    def __init__(self) -> None:
        self._base = settings.meilisearch_url.rstrip("/")
        # `meilisearch_secret` resolves either MEILISEARCH_KEY (Railway) or
        # MEILISEARCH_MASTER_KEY (local docker-compose).
        self._headers = {
            "Authorization": f"Bearer {settings.meilisearch_secret}",
            "Content-Type": "application/json",
        }

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self._base}/health")
            return resp.status_code == 200
        except Exception:
            return False

    async def ensure_index(self) -> None:
        """Create the filings index + searchable attributes if absent.
        Best-effort — if Meili isn't reachable, skip silently."""
        if not await self.health():
            return
        async with httpx.AsyncClient(timeout=10.0) as client:
            create = await client.post(
                f"{self._base}/indexes",
                headers=self._headers,
                json={"uid": FILINGS_INDEX, "primaryKey": PRIMARY_KEY},
            )
            if create.status_code not in (200, 201, 202, 409):
                logger.warning("meili create index -> %s: %s", create.status_code, create.text[:200])
            await client.patch(
                f"{self._base}/indexes/{FILINGS_INDEX}/settings",
                headers=self._headers,
                json={
                    "searchableAttributes": ["headline", "company", "symbol", "form_type", "body"],
                    "filterableAttributes": ["symbol", "form_type"],
                    "sortableAttributes": ["filed_at_ts"],
                    "displayedAttributes": [
                        "id", "symbol", "company", "form_type", "filed_at",
                        "filed_at_ts", "accession_number", "primary_document",
                        "url", "headline", "snippet",
                    ],
                },
            )

    async def index_filings_metadata(self, symbol: str, filings: Iterable[FilingEntry]) -> int:
        if not await self.health():
            return 0
        documents: list[dict[str, Any]] = []
        for f in filings:
            filed_ts = int(f.filed_at.timestamp()) if f.filed_at else 0
            documents.append(
                {
                    "id": _accession_id(f.accession_number),
                    "symbol": symbol.upper(),
                    "company": f.company,
                    "form_type": f.form_type,
                    "accession_number": f.accession_number,
                    "filed_at": f.filed_at.isoformat() if f.filed_at else None,
                    "filed_at_ts": filed_ts,
                    "primary_document": f.primary_document,
                    "url": f.url,
                    "headline": f"{symbol.upper()} {f.form_type} — {f.company}",
                }
            )
        if not documents:
            return 0
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{self._base}/indexes/{FILINGS_INDEX}/documents",
                headers=self._headers,
                json=documents,
            )
        if resp.status_code not in (200, 202):
            logger.warning("meili index metadata -> %s: %s", resp.status_code, resp.text[:200])
            return 0
        return len(documents)

    async def index_filing_body(self, filing: FilingEntry, max_chars: int = 500_000) -> bool:
        """Fetch the primary document, strip HTML, and patch the body+snippet
        onto the filing's existing index document. Returns True on success.
        Skipped silently if Meili is down."""
        if not await self.health():
            return False
        if not filing.url:
            return False
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                resp = await client.get(
                    filing.url,
                    headers={"User-Agent": settings.sec_user_agent, "Accept": "*/*"},
                )
            except Exception as exc:
                logger.debug("meili fetch body %s failed: %s", filing.accession_number, exc)
                return False
        if resp.status_code != 200:
            return False
        text = _strip_html(resp.text or "")
        if not text:
            return False
        body = text[:max_chars]
        snippet = text[:300]
        document = {
            "id": _accession_id(filing.accession_number),
            "body": body,
            "snippet": snippet,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            patch = await client.put(
                f"{self._base}/indexes/{FILINGS_INDEX}/documents",
                headers=self._headers,
                json=[document],
            )
        return patch.status_code in (200, 202)

    async def search(
        self,
        query: str,
        limit: int = 20,
        symbol: str | None = None,
        form_type: str | None = None,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        if not await self.health():
            return []
        filters: list[str] = []
        if symbol:
            filters.append(f'symbol = "{symbol.upper()}"')
        if form_type:
            filters.append(f'form_type = "{form_type.upper()}"')
        body: dict[str, Any] = {
            "q": query,
            "limit": max(1, min(100, limit)),
            "attributesToHighlight": ["body", "headline", "snippet"],
            "highlightPreTag": "<mark>",
            "highlightPostTag": "</mark>",
            "attributesToCrop": ["body"],
            "cropLength": 40,
        }
        if filters:
            body["filter"] = " AND ".join(filters)
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(
                f"{self._base}/indexes/{FILINGS_INDEX}/search",
                headers=self._headers,
                json=body,
            )
        if resp.status_code != 200:
            logger.warning("meili search -> %s: %s", resp.status_code, resp.text[:200])
            return []
        return (resp.json() or {}).get("hits", []) or []


_singleton: MeilisearchSource | None = None


def get_meilisearch() -> MeilisearchSource:
    global _singleton
    if _singleton is None:
        _singleton = MeilisearchSource()
    return _singleton
