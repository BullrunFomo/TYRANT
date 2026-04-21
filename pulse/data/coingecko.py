"""CoinGecko price history — free, no API key required."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)

COINGECKO_URL = "https://api.coingecko.com/api/v3/coins/{id}/market_chart"

COINS: Dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
}

_cache: Dict[str, tuple] = {}
_CACHE_TTL = 300.0


@dataclass
class CoinHistory:
    symbol: str
    prices: List[float]
    current_price: float


async def get_coin_history(symbol: str, days: int = 90) -> Optional[CoinHistory]:
    coin_id = COINS.get(symbol.upper())
    if not coin_id:
        return None

    cached = _cache.get(symbol)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    url = COINGECKO_URL.format(id=coin_id)
    params = {"vs_currency": "usd", "days": days, "interval": "daily"}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params,
                             timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 429:
                    logger.warning("CoinGecko rate limit hit — using cached data")
                    return cached[1] if cached else None
                if r.status != 200:
                    logger.warning("CoinGecko %s: HTTP %d", symbol, r.status)
                    return None
                data = await r.json()
        prices = [p[1] for p in data.get("prices", []) if p[1] is not None]
        if not prices:
            return None
        result = CoinHistory(symbol=symbol, prices=prices, current_price=prices[-1])
        _cache[symbol] = (time.time(), result)
        return result
    except Exception as exc:
        logger.error("CoinGecko %s: %s", symbol, exc)
        return cached[1] if cached else None


async def get_all_coins() -> Dict[str, CoinHistory]:
    import asyncio
    results = await asyncio.gather(
        *[get_coin_history(s) for s in COINS], return_exceptions=True
    )
    return {sym: r for sym, r in zip(COINS.keys(), results)
            if isinstance(r, CoinHistory)}
