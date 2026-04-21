"""Financial market scanner — Yahoo Finance + lognormal model."""
from __future__ import annotations

import logging
from typing import Any, List

from pulse.market.polymarket import get_client, get_all_markets_cached, filter_markets
from pulse.market.financial_parser import ParsedFinancialMarket, parse_financial_title
from pulse.data.yfinance_data import get_all_assets
from pulse.data import price_models
from pulse import config

logger = logging.getLogger(__name__)

FINANCIAL_KEYWORDS = [
    "s&p 500", "sp500", "nasdaq", "dow jones", "djia",
    "gold price", "xau", "crude oil", "oil price", "wti",
    "stock market", "index", "spy", "qqq",
]

_DAYS_HORIZON = 30


async def scan_financial() -> List[Any]:
    if not config.FINANCIAL_MARKETS_ENABLED:
        return []

    assets = await get_all_assets()
    if not assets:
        logger.warning("No Yahoo Finance data — skipping financial scan")
        return []

    client = get_client()
    all_markets = await get_all_markets_cached(client)
    markets = [m for m in filter_markets(all_markets, FINANCIAL_KEYWORDS) if m.active]
    logger.info("Scanning %d financial markets", len(markets))

    opportunities = []
    for market in markets:
        if market.liquidity < config.MIN_LIQUIDITY_USD:
            continue

        parsed = parse_financial_title(market.title)
        if not parsed:
            continue

        asset = assets.get(parsed.ticker)
        if not asset or len(asset.prices) < 10:
            continue

        if parsed.direction == "ABOVE":
            true_prob = price_models.prob_above(asset.prices, parsed.target_level, _DAYS_HORIZON)
        else:
            true_prob = price_models.prob_below(asset.prices, parsed.target_level, _DAYS_HORIZON)

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
        logger.info("Financial edge: %s %s @ %.0f | model=%.1f%% mkt=%.1f%% edge=%+.1f%%",
                    parsed.ticker, parsed.direction, parsed.target_level,
                    true_prob * 100, market_prob * 100, edge * 100)

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
