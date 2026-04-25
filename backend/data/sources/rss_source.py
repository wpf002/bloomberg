"""RSS news aggregator — merges public feeds into NewsItem shape.

No third-party RSS parser: RSS 2.0 and Atom both flatten to XML, and we only
need a small subset of fields (title, link, pubDate, description). Keeping
this stdlib-only avoids adding another dependency.

Feeds are intentionally skewed toward retail-accessible sources (Yahoo,
MarketWatch, SEC press releases) and are per-symbol when the feed supports
it. Reuters and Bloomberg's own RSS have been unstable historically, so
they're only included when the feed URL is actually reachable.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterable, List, Sequence
from xml.etree import ElementTree as ET

import httpx

from ...core.cache_utils import cached
from ...core.config import settings
from ...models.schemas import NewsItem

logger = logging.getLogger(__name__)

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _symbol_feeds(symbol: str) -> list[tuple[str, str]]:
    sym = symbol.upper()
    return [
        (f"https://www.nasdaq.com/feed/rssoutbound?symbol={sym}", "Nasdaq"),
    ]


GENERAL_FEEDS: list[tuple[str, str]] = [
    ("https://feeds.marketwatch.com/marketwatch/topstories/", "MarketWatch"),
    ("https://www.sec.gov/news/pressreleases.rss", "SEC"),
]


def _parse_datetime(raw: str | None) -> datetime:
    if not raw:
        return datetime.now(timezone.utc)
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return datetime.now(timezone.utc)


def _stable_id(url: str, title: str) -> str:
    return hashlib.sha1(f"{url}|{title}".encode("utf-8")).hexdigest()[:20]


def _parse_feed(body: bytes, source: str, symbol: str | None) -> list[NewsItem]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        logger.debug("rss parse failed for %s: %s", source, exc)
        return []

    items: list[NewsItem] = []

    # RSS 2.0 — <rss><channel><item>
    for item in root.iterfind(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip() or None
        pub = _parse_datetime(item.findtext("pubDate"))
        if not title or not link:
            continue
        items.append(
            NewsItem(
                id=_stable_id(link, title),
                headline=title,
                summary=desc,
                source=source,
                url=link,
                symbols=[symbol] if symbol else [],
                published_at=pub,
            )
        )

    # Atom — <feed><entry>
    for entry in root.iterfind("atom:entry", ATOM_NS):
        title = (entry.findtext("atom:title", default="", namespaces=ATOM_NS) or "").strip()
        link_el = entry.find("atom:link", ATOM_NS)
        link = link_el.get("href", "") if link_el is not None else ""
        summary = (entry.findtext("atom:summary", default="", namespaces=ATOM_NS) or "").strip() or None
        pub = _parse_datetime(entry.findtext("atom:updated", namespaces=ATOM_NS))
        if not title or not link:
            continue
        items.append(
            NewsItem(
                id=_stable_id(link, title),
                headline=title,
                summary=summary,
                source=source,
                url=link,
                symbols=[symbol] if symbol else [],
                published_at=pub,
            )
        )

    return items


class RssSource:
    """Fan-out RSS fetcher with per-feed caching and fault tolerance."""

    def __init__(self) -> None:
        self._headers = {
            "User-Agent": settings.sec_user_agent,
            "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
        }

    @cached("rss:merged", ttl=120, model=NewsItem)
    async def fetch(self, symbols: Sequence[str] | None, limit: int = 30) -> List[NewsItem]:
        feeds: list[tuple[str, str, str | None]] = []
        if symbols:
            for sym in symbols:
                for url, source in _symbol_feeds(sym):
                    feeds.append((url, source, sym.upper()))
        else:
            for url, source in GENERAL_FEEDS:
                feeds.append((url, source, None))

        async with httpx.AsyncClient(
            timeout=settings.rss_timeout_seconds,
            follow_redirects=True,
            headers=self._headers,
        ) as client:
            results = await asyncio.gather(
                *(self._fetch_one(client, url, source, symbol) for url, source, symbol in feeds),
                return_exceptions=True,
            )

        merged: list[NewsItem] = []
        seen: set[str] = set()
        for result in results:
            if isinstance(result, Exception) or not result:
                continue
            for item in result:
                key = item.url or item.headline
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)

        merged.sort(key=lambda n: n.published_at, reverse=True)
        return merged[:limit]

    async def _fetch_one(
        self,
        client: httpx.AsyncClient,
        url: str,
        source: str,
        symbol: str | None,
    ) -> Iterable[NewsItem]:
        try:
            resp = await client.get(url)
        except httpx.HTTPError as exc:
            logger.debug("rss fetch failed %s: %s", url, exc)
            return []
        if resp.status_code != 200:
            logger.debug("rss fetch %s -> %s", url, resp.status_code)
            return []
        return _parse_feed(resp.content, source, symbol)
