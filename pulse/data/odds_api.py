"""The Odds API — sports betting odds. Free tier: 500 req/month. Requires API key."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import aiohttp

from pulse import config

logger = logging.getLogger(__name__)

ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/{sport}/odds"

SPORT_KEYS = [
    "americanfootball_nfl",
    "basketball_nba",
    "baseball_mlb",
    "icehockey_nhl",
    "soccer_epl",
    "soccer_mls",
]

_cache: Dict[str, tuple] = {}
_CACHE_TTL = 1800.0  # 30 min — conserve the 500/month free quota


@dataclass
class GameOdds:
    sport: str
    home_team: str
    away_team: str
    commence_time: str
    home_prob: float    # vig-removed
    away_prob: float
    draw_prob: float    # 0.0 for no-draw sports


async def get_sport_odds(sport_key: str) -> List[GameOdds]:
    if not config.ODDS_API_KEY:
        return []

    cached = _cache.get(sport_key)
    if cached and time.time() - cached[0] < _CACHE_TTL:
        return cached[1]

    url = ODDS_API_URL.format(sport=sport_key)
    params = {
        "apiKey": config.ODDS_API_KEY,
        "regions": "us",
        "markets": "h2h",
        "oddsFormat": "decimal",
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params,
                             timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 401:
                    logger.warning("Odds API: invalid key")
                    return []
                if r.status == 422:
                    return []   # sport not available right now (off-season)
                if r.status != 200:
                    logger.warning("Odds API %s: HTTP %d", sport_key, r.status)
                    return []
                data = await r.json()
        results = []
        for game in data:
            probs = _extract_probs(game)
            if probs:
                results.append(GameOdds(
                    sport=sport_key,
                    home_team=game.get("home_team", ""),
                    away_team=game.get("away_team", ""),
                    commence_time=game.get("commence_time", ""),
                    home_prob=probs[0],
                    away_prob=probs[1],
                    draw_prob=probs[2],
                ))
        _cache[sport_key] = (time.time(), results)
        logger.info("Odds API %s: %d games cached", sport_key, len(results))
        return results
    except Exception as exc:
        logger.error("Odds API %s: %s", sport_key, exc)
        return cached[1] if cached else []


def _extract_probs(game: dict) -> Optional[tuple]:
    for bk in game.get("bookmakers", []):
        for market in bk.get("markets", []):
            if market.get("key") != "h2h":
                continue
            outcomes = market.get("outcomes", [])
            raw = [1.0 / o["price"] for o in outcomes if o.get("price", 0) > 0]
            if not raw:
                continue
            total = sum(raw)
            norm_probs = [r / total for r in raw]
            if len(norm_probs) == 2:
                return (norm_probs[0], norm_probs[1], 0.0)
            if len(norm_probs) == 3:
                return (norm_probs[0], norm_probs[1], norm_probs[2])
    return None


async def get_all_odds() -> Dict[str, List[GameOdds]]:
    import asyncio
    results = await asyncio.gather(
        *[get_sport_odds(sk) for sk in SPORT_KEYS], return_exceptions=True
    )
    return {sk: r for sk, r in zip(SPORT_KEYS, results) if isinstance(r, list)}
