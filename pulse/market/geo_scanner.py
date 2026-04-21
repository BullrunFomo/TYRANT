"""Earthquake market scanner — USGS + Poisson probability model."""
from __future__ import annotations

import logging
from typing import Any, List

from pulse.market.polymarket import get_client, get_all_markets_cached, filter_markets
from pulse.market.geo_parser import ParsedGeoMarket, parse_geo_title
from pulse.data.usgs import get_recent_quakes
from pulse.data import geo_models
from pulse import config

logger = logging.getLogger(__name__)

GEO_KEYWORDS = [
    "earthquake", "quake", "seismic", "magnitude", "tremor",
    "richter", "7.0", "6.0", "7.5", "8.0",
]


async def scan_geo() -> List[Any]:
    if not config.GEO_MARKETS_ENABLED:
        return []

    quakes = await get_recent_quakes(min_magnitude=2.5)
    if not quakes:
        logger.warning("No USGS data — skipping geo scan")
        return []
    logger.info("Loaded %d recent quake events from USGS", len(quakes))

    client = get_client()
    all_markets = await get_all_markets_cached(client)
    markets = [m for m in filter_markets(all_markets, GEO_KEYWORDS) if m.active]
    logger.info("Scanning %d geo markets", len(markets))

    if markets:
        logger.info("Geo sample titles: %s",
                    " | ".join(m.title[:55] for m in markets[:5]))

    opportunities = []
    parsed_count = 0
    for market in markets:
        if market.liquidity < config.MIN_LIQUIDITY_USD:
            continue

        parsed = parse_geo_title(market.title)
        if not parsed:
            continue
        parsed_count += 1

        true_prob = geo_models.quake_prob(
            quakes, parsed.region, parsed.min_magnitude, parsed.days
        )

        market_prob = market.yes_price
        if market_prob <= 0.01 or market_prob >= 0.99:
            continue

        edge_yes = true_prob - market_prob
        edge_no  = (1.0 - true_prob) - (1.0 - market_prob)
        if abs(edge_yes) >= abs(edge_no):
            edge, outcome = edge_yes, "YES"
        else:
            edge, outcome = edge_no, "NO"

        if abs(edge) < config.MIN_EDGE_THRESHOLD:
            continue

        token_id = _token_id(market, outcome)
        if not token_id:
            continue

        price = market.yes_price if outcome == "YES" else market.no_price
        opportunities.append(_Opp(market, parsed, true_prob, market_prob, edge, outcome, price, token_id))
        logger.info("Geo edge: M%.1f+ %s (%d days) | model=%.1f%% mkt=%.1f%% edge=%+.1f%%",
                    parsed.min_magnitude, parsed.region, parsed.days,
                    true_prob * 100, market_prob * 100, edge * 100)

    logger.info("Geo parse rate: %d/%d titles matched", parsed_count, len(markets))
    opportunities.sort(key=lambda o: abs(o.edge), reverse=True)
    return opportunities


class _Opp:
    def __init__(self, market, parsed, true_prob, market_prob, edge,
                 recommended_outcome, recommended_price, token_id):
        self.market = market
        self.parsed = parsed
        self.true_prob = true_prob
        self.market_prob = market_prob
        self.edge = edge
        self.recommended_outcome = recommended_outcome
        self.recommended_price = recommended_price
        self.token_id = token_id
        self.forecast = None


def _token_id(market, outcome: str):
    for tok in market.tokens:
        if (tok.get("outcome") or "").upper() == outcome.upper():
            return tok.get("token_id")
    return None
