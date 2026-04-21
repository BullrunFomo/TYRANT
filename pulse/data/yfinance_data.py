"""Yahoo Finance price history — free, no API key required."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

YF_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"

ASSETS: Dict[str, str] = {
    "SPY":  "S&P 500",
    "QQQ":  "NASDAQ 100",
    "GLD":  "Gold",
    "USO":  "Oil (WTI)",
    "DIA":  "Dow Jones",
    "IWM":  "Russell 2000",
    "TLT":  "US 20Y Bonds",
    "VIX":  "Volatility Index",
}

_cache: Dict[str, tuple] = {}
_CACHE_TTL = 300.0

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


@dataclass
class AssetHistory:
    ticker: str
    name: str
    prices: List[float]
    current_price: float


async def get_asset_history(ticker: str, days: int = 90) -> Optional[AssetHistory]:
    cached = _cache.get(ticker)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    url = YF_URL.format(ticker=ticker)
    params = {"interval": "1d", "range": f"{days}d"}
    try:
        async with aiohttp.ClientSession(headers=_HEADERS) as s:
            async with s.get(url, params=params,
                             timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status != 200:
                    logger.warning("YFinance %s: HTTP %d", ticker, r.status)
                    return cached[1] if cached else None
                data = await r.json()
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        if not closes:
            return None
        result = AssetHistory(
            ticker=ticker,
            name=ASSETS.get(ticker, ticker),
            prices=closes,
            current_price=closes[-1],
        )
        _cache[ticker] = (time.time(), result)
        return result
    except Exception as exc:
        logger.error("YFinance %s: %s", ticker, exc)
        return cached[1] if cached else None


async def get_all_assets() -> Dict[str, AssetHistory]:
    import asyncio
    results = await asyncio.gather(
        *[get_asset_history(t) for t in ASSETS], return_exceptions=True
    )
    return {t: r for t, r in zip(ASSETS.keys(), results)
            if isinstance(r, AssetHistory)}
