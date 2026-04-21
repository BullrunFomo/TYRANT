"""FRED API client — fetches CPI, unemployment, and Fed rate data."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Tuple

import aiohttp

from pulse import config

logger = logging.getLogger(__name__)

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"


@dataclass
class EconSeries:
    series_id: str
    values: List[float]
    dates: List[str]   # YYYY-MM-DD, chronological

    @property
    def latest(self) -> Optional[float]:
        return self.values[-1] if self.values else None

    @property
    def latest_date(self) -> Optional[str]:
        return self.dates[-1] if self.dates else None

    def recent(self, n: int = 24) -> List[float]:
        return self.values[-n:]


async def fetch_series(series_id: str, limit: int = 48) -> Optional[EconSeries]:
    if not config.FRED_API_KEY:
        return None

    params = {
        "series_id": series_id,
        "api_key": config.FRED_API_KEY,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit,
    }

    timeout = aiohttp.ClientTimeout(total=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(FRED_URL, params=params) as r:
                r.raise_for_status()
                data = await r.json()

        obs = data.get("observations", [])
        valid = [(o["date"], float(o["value"]))
                 for o in reversed(obs) if o.get("value") not in (".", None, "")]
        if not valid:
            return None

        dates, values = zip(*valid)
        return EconSeries(series_id=series_id, values=list(values), dates=list(dates))

    except Exception as exc:
        logger.error("FRED fetch failed for %s: %s", series_id, exc)
        return None


async def get_cpi() -> Optional[EconSeries]:
    """Monthly CPI index (CPIAUCSL). MoM % changes are derived in models."""
    return await fetch_series("CPIAUCSL", limit=48)


async def get_unemployment() -> Optional[EconSeries]:
    """US unemployment rate, seasonally adjusted (UNRATE)."""
    return await fetch_series("UNRATE", limit=48)


async def get_fed_target() -> Optional[Tuple[float, float]]:
    """Return current (lower, upper) Fed funds target range."""
    import asyncio
    lower, upper = await asyncio.gather(
        fetch_series("DFEDTARL", limit=3),
        fetch_series("DFEDTARU", limit=3),
    )
    if lower and upper:
        return lower.latest, upper.latest
    return None
