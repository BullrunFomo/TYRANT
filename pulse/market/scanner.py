"""Market scanner — combines market data with weather forecasts to find edge."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from pulse.market.polymarket import Market, get_client, get_all_markets_cached
from pulse.market.parser import ParsedMarket, parse_market_title
from pulse.market.econ_scanner import scan_econ
from pulse.market.crypto_scanner import scan_crypto
from pulse.market.financial_scanner import scan_financial
from pulse.market.sports_scanner import scan_sports
from pulse.market.geo_scanner import scan_geo
from pulse.data.weather import CityForecast, get_all_forecasts
from pulse.data import models as prob_models
from pulse import config

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


@dataclass
class Opportunity:
    market: Market
    parsed: Any             # ParsedMarket or ParsedEconMarket
    forecast: Optional[CityForecast]
    true_prob: float
    market_prob: float
    edge: float
    recommended_outcome: str
    recommended_price: float
    token_id: str


async def scan() -> List[Opportunity]:
    opportunities: List[Opportunity] = []

    if config.WEATHER_MARKETS_ENABLED:
        forecasts: Dict[str, CityForecast] = await get_all_forecasts()
        if not forecasts:
            logger.warning("No weather forecasts available — skipping weather scan")
        else:
            client = get_client()
            markets = await client.get_all_weather_markets()
            logger.info("Scanning %d weather markets", len(markets))
            parsed_count = 0
            for market in markets:
                before = len(opportunities)
                _process_weather_market(market, forecasts, opportunities)
                if parse_market_title(market.title):
                    parsed_count += 1
            logger.info("Weather parse rate: %d/%d titles matched", parsed_count, len(markets))
            if parsed_count == 0 and markets:
                logger.info("Sample titles (first 5): %s",
                            " | ".join(m.title[:60] for m in markets[:5]))
    else:
        logger.info("Weather markets disabled — skipping")

    for name, enabled, scanner in [
        ("Economic",   config.ECON_MARKETS_ENABLED,      scan_econ),
        ("Crypto",     config.CRYPTO_MARKETS_ENABLED,    scan_crypto),
        ("Financial",  config.FINANCIAL_MARKETS_ENABLED, scan_financial),
        ("Sports",     config.SPORTS_MARKETS_ENABLED,    scan_sports),
        ("Geo",        config.GEO_MARKETS_ENABLED,       scan_geo),
    ]:
        if enabled:
            try:
                opps = await scanner()
                opportunities.extend(opps)
            except Exception as exc:
                logger.error("%s scan error: %s", name, exc)
        else:
            logger.info("%s markets disabled — skipping", name)

    opportunities.sort(key=lambda o: abs(o.edge), reverse=True)
    logger.info("Scan complete — %d opportunities found (%d econ)",
                len(opportunities), sum(1 for o in opportunities
                                        if hasattr(o.parsed, 'market_type')))
    return opportunities


_weather_debug_done = False

def _process_weather_market(market: Market, forecasts: Dict[str, CityForecast],
                             opportunities: List[Opportunity]) -> None:
    global _weather_debug_done
    if not market.active:
        return
    if market.liquidity < config.MIN_LIQUIDITY_USD:
        return

    parsed = parse_market_title(market.title)
    if not parsed:
        if not _weather_debug_done:
            logger.info("PARSE FAIL samples (first 5):")
        if not _weather_debug_done:
            _weather_debug_done = True  # will be reset after logging 5
        return

    forecast = forecasts.get(parsed.city)
    if not forecast:
        return

    true_prob = _compute_true_prob(parsed, forecast)
    if true_prob is None:
        return

    market_prob = market.yes_price
    if market_prob <= 0.01 or market_prob >= 0.99:
        return

    edge_yes = true_prob - market_prob
    edge_no  = (1.0 - true_prob) - (1.0 - market_prob)

    if abs(edge_yes) >= abs(edge_no):
        edge, outcome = edge_yes, "YES"
    else:
        edge, outcome = edge_no, "NO"

    # Log best near-misses even below threshold
    if abs(edge) >= config.MIN_EDGE_THRESHOLD * 0.5:
        logger.info("Near-miss: %s | model=%.1f%% mkt=%.1f%% edge=%+.1f%% (threshold=%.0f%%)",
                    market.title[:50], true_prob*100, market_prob*100,
                    edge*100, config.MIN_EDGE_THRESHOLD*100)

    if abs(edge) < config.MIN_EDGE_THRESHOLD:
        return

    token_id = _get_token_id(market, outcome)
    if not token_id:
        return

    price = market.yes_price if outcome == "YES" else market.no_price
    opportunities.append(Opportunity(
        market=market,
        parsed=parsed,
        forecast=forecast,   # type: ignore[arg-type]
        true_prob=true_prob,
        market_prob=market_prob,
        edge=edge,
        recommended_outcome=outcome,
        recommended_price=price,
        token_id=token_id,
    ))
    logger.info("Edge found: %s | %s=%s | edge=%.1f%%",
                parsed.city, market.title[:40], outcome, edge * 100)


def _compute_true_prob(parsed: ParsedMarket, forecast: CityForecast) -> Optional[float]:
    try:
        if parsed.outcome_type == "ABOVE":
            return prob_models.prob_above_threshold(forecast, parsed.date_str, parsed.threshold_f)
        elif parsed.outcome_type == "BELOW":
            return prob_models.prob_below_threshold(forecast, parsed.date_str, parsed.threshold_f)
        elif parsed.outcome_type == "RANGE" and parsed.threshold_high_f is not None:
            return prob_models.prob_in_range(forecast, parsed.date_str,
                                              parsed.threshold_f, parsed.threshold_high_f)
    except Exception as exc:
        logger.error("Probability computation error: %s", exc)
    return None


def _get_token_id(market: Market, outcome: str) -> Optional[str]:
    for tok in market.tokens:
        if (tok.get("outcome") or "").upper() == outcome.upper():
            return tok.get("token_id")
    return None
