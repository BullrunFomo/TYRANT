"""Crypto market scanner — CoinGecko + lognormal model."""
from __future__ import annotations

import logging
from typing import Any, List

from pulse.market.polymarket import get_client, get_all_markets_cached, filter_markets
from pulse.market.crypto_parser import ParsedCryptoMarket, parse_crypto_title
from pulse.data.coingecko import get_all_coins
from pulse.data import price_models
from pulse import config

logger = logging.getLogger(__name__)

CRYPTO_KEYWORDS = [
    "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
    "bnb", "xrp", "ripple", "dogecoin", "doge", "avalanche", "avax",
    "crypto", "cryptocurrency",
]

_DAYS_HORIZON = 30


async def scan_crypto() -> List[Any]:
    if not config.CRYPTO_MARKETS_ENABLED:
        return []

    coins = await get_all_coins()
    if not coins:
        logger.warning("No CoinGecko data — skipping crypto scan")
        return []

    client = get_client()
    all_markets = await get_all_markets_cached(client)
    markets = [m for m in filter_markets(all_markets, CRYPTO_KEYWORDS) if m.active]
    logger.info("Scanning %d crypto markets", len(markets))

    if markets:
        logger.info("Crypto sample titles: %s",
                    " | ".join(m.title[:55] for m in markets[:5]))

    opportunities = []
    parsed_count = 0
    for market in markets:
        if market.liquidity < config.MIN_LIQUIDITY_USD:
            continue

        parsed = parse_crypto_title(market.title)
        if not parsed:
            continue
        parsed_count += 1

        coin = coins.get(parsed.symbol)
        if not coin or len(coin.prices) < 10:
            continue

        if parsed.direction == "ABOVE":
            true_prob = price_models.prob_above(coin.prices, parsed.target_price, _DAYS_HORIZON)
        else:
            true_prob = price_models.prob_below(coin.prices, parsed.target_price, _DAYS_HORIZON)

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
        logger.info("Crypto edge: %s %s @ $%.0f | model=%.1f%% mkt=%.1f%% edge=%+.1f%%",
                    parsed.symbol, parsed.direction, parsed.target_price,
                    true_prob * 100, market_prob * 100, edge * 100)

    logger.info("Crypto parse rate: %d/%d titles matched", parsed_count, len(markets))
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
