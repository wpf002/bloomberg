"""Ken French data library — Fama-French 5 + Carhart momentum.

Daily factor returns are published as zipped CSVs at Dartmouth. Each CSV
has a small free-form header followed by a daily-frequency block, then
sometimes an annual block we have to skip.

We pull both files (5-factor + momentum), parse them in a worker thread
(zipfile + a tight CSV reader), align them on date, and cache the merged
DataFrame for 24h. Factor changes are monthly-ish at the source, so a
day-long TTL is generous.
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
import zipfile
from datetime import date, datetime
from typing import Any

import httpx

from ...core.database import cache

logger = logging.getLogger(__name__)


FF5_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
MOM_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_daily_CSV.zip"

CACHE_KEY = "bt:french:factors:v1"
CACHE_TTL_SECONDS = 24 * 3600


def _parse_french_csv(raw: bytes) -> dict[date, dict[str, float]]:
    """Returns date → {factor_name: value_in_decimal} parsed from a Ken
    French daily CSV.

    French publishes percent-of-month numbers (e.g. 0.34 == 0.34%); we
    convert to decimals here so callers can mix freely with daily
    portfolio returns.
    """
    text = raw.decode("latin-1", errors="ignore")
    lines = text.splitlines()
    out: dict[date, dict[str, float]] = {}
    headers: list[str] | None = None
    for line in lines:
        stripped = line.strip()
        if not stripped:
            headers = None  # blank line ends the daily block
            continue
        # Header rows look like "       Mkt-RF    SMB    HML    RMW    CMA    RF"
        if headers is None and re.match(r"^[A-Za-z][A-Za-z0-9\- ]+", stripped):
            tokens = re.split(r"\s+|,", stripped)
            tokens = [t for t in tokens if t]
            # Crude but reliable: the daily header has 4-6 short tokens
            if 3 <= len(tokens) <= 8 and not any(t.isdigit() for t in tokens):
                headers = tokens
            continue
        if headers is None:
            continue
        # Data rows: yyyymmdd,val,val,val,val,val[,val]
        parts = re.split(r"\s*,\s*", stripped)
        if len(parts) < 2:
            continue
        try:
            day = datetime.strptime(parts[0], "%Y%m%d").date()
        except ValueError:
            # Annual rows have 4-digit years — skip them
            headers = None
            continue
        try:
            values = [float(x) / 100.0 for x in parts[1:]]  # convert % → decimal
        except ValueError:
            continue
        if len(values) != len(headers):
            continue
        row = out.setdefault(day, {})
        for name, val in zip(headers, values):
            row[name] = val
    return out


async def _download_zip_csv(url: str) -> bytes:
    """Download a Ken French ZIP, return the inner CSV bytes."""
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "bloomberg-terminal"})
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = zf.namelist()
        if not names:
            raise RuntimeError(f"empty French zip: {url}")
        with zf.open(names[0]) as fh:
            return fh.read()


class FrenchSource:
    """Fetches and caches Ken French daily factor returns.

    `load()` returns a list of `{date, mkt_rf, smb, hml, rmw, cma, mom, rf}`
    dictionaries (decimal-scaled), sorted ascending by date. Cached for 24h
    in Redis when available; otherwise re-downloads on demand.
    """

    async def load(self) -> list[dict[str, Any]]:
        cached_payload = await self._read_cache()
        if cached_payload:
            return cached_payload

        ff5_bytes, mom_bytes = await asyncio.gather(
            _download_zip_csv(FF5_URL),
            _download_zip_csv(MOM_URL),
        )
        ff5 = await asyncio.to_thread(_parse_french_csv, ff5_bytes)
        mom = await asyncio.to_thread(_parse_french_csv, mom_bytes)

        merged: list[dict[str, Any]] = []
        for day in sorted(set(ff5) & set(mom)):
            ff = ff5[day]
            mm = mom[day]
            row = {
                "date": day.isoformat(),
                "mkt_rf": ff.get("Mkt-RF"),
                "smb": ff.get("SMB"),
                "hml": ff.get("HML"),
                "rmw": ff.get("RMW"),
                "cma": ff.get("CMA"),
                "rf": ff.get("RF"),
                "mom": next(iter(mm.values()), None),  # the file has one factor column
            }
            if all(v is not None for v in (row["mkt_rf"], row["smb"], row["hml"], row["rmw"], row["cma"], row["rf"], row["mom"])):
                merged.append(row)
        await self._write_cache(merged)
        return merged

    async def _read_cache(self) -> list[dict[str, Any]] | None:
        client = cache.client
        if client is None:
            return None
        try:
            raw = await client.get(CACHE_KEY)
            if not raw:
                return None
            import json as _json
            return _json.loads(raw)
        except Exception as exc:
            logger.debug("french cache read failed: %s", exc)
            return None

    async def _write_cache(self, rows: list[dict[str, Any]]) -> None:
        client = cache.client
        if client is None:
            return
        import json as _json
        try:
            await client.setex(CACHE_KEY, CACHE_TTL_SECONDS, _json.dumps(rows))
        except Exception as exc:
            logger.debug("french cache write failed: %s", exc)
