"""Economic market scanner — finds edge between model forecasts and Polymarket prices."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from pulse.market.polymarket import Market, get_client, get_all_markets_cached, filter_markets
from pulse.market.econ_parser import ParsedEconMarket, parse_econ_title
from pulse.data.fred import get_cpi, get_unemployment, EconSeries
from pulse.data import econ_models
from pulse import config

logger = logging.getLogger(__name__)

ECON_KEYWORDS = [
    "cpi", "consumer price", "inflation",
    "unemployment", "jobless",
    "fed ", "fomc", "federal funds", "rate cut", "rate hike", "interest rate",
    "non-farm", "nonfarm", "payroll",
]


async def scan_econ() -> List[Any]:
    """
    Econ scan: fetch FRED data, find Polymarket econ markets, return Opportunity-compatible list.
    Returns empty list if FRED_API_KEY is not configured.
    """
    if not config.FRED_API_KEY:
        logger.debug("FRED_API_KEY not set — skipping econ scan")
        return []

    # Fetch FRED data concurrently
    cpi_data, unemp_data = await asyncio.gather(
        get_cpi(), get_unemployment(), return_exceptions=True
    )
    if isinstance(cpi_data, Exception):
        logger.error("CPI FRED fetch error: %s", cpi_data)
        cpi_data = None
    if isinstance(unemp_data, Exception):
        logger.error("Unemployment FRED fetch error: %s", unemp_data)
        unemp_data = None

    forecasts = _build_forecasts(cpi_data, unemp_data)
    if not forecasts:
        logger.warning("No econ forecasts available — skipping econ scan")
        return []

    client = get_client()
    all_markets = await get_all_markets_cached(client)
    markets = [m for m in filter_markets(all_markets, ECON_KEYWORDS) if m.active]
    logger.info("Scanning %d economic markets", len(markets))

    opportunities = []

    for market in markets:
        if not market.active or market.liquidity < config.MIN_LIQUIDITY_USD:
            continue

        parsed = parse_econ_title(market.title)
        if not parsed:
            continue

        true_prob = _compute_prob(parsed, forecasts)
        if true_prob is None:
            continue

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
        opp = _EconOpportunity(
            market=market,
            parsed=parsed,
            true_prob=true_prob,
            market_prob=market_prob,
            edge=edge,
            recommended_outcome=outcome,
            recommended_price=price,
            token_id=token_id,
        )
        opportunities.append(opp)
        logger.info("Econ edge: [%s] %s=%s | model=%.1f%% mkt=%.1f%% edge=%+.1f%%",
                    parsed.market_type, market.title[:50], outcome,
                    true_prob * 100, market_prob * 100, edge * 100)

    opportunities.sort(key=lambda o: abs(o.edge), reverse=True)
    logger.info("Econ scan complete — %d opportunities found", len(opportunities))
    return opportunities


# ── Internal opportunity type (duck-types Opportunity) ─────────────────────────

class _EconOpportunity:
    """Duck-type compatible with weather Opportunity — same interface for execution."""
    def __init__(self, market, parsed, true_prob, market_prob, edge,
                 recommended_outcome, recommended_price, token_id):
        self.market = market
        self.parsed = parsed           # ParsedEconMarket (has .city and .date_str)
        self.true_prob = true_prob
        self.market_prob = market_prob
        self.edge = edge
        self.recommended_outcome = recommended_outcome
        self.recommended_price = recommended_price
        self.token_id = token_id
        self.forecast = None           # no weather forecast for econ markets


# ── Forecast cache ─────────────────────────────────────────────────────────────

def _build_forecasts(cpi: Optional[EconSeries],
                     unemp: Optional[EconSeries]) -> Dict[str, Tuple[float, float]]:
    fc: Dict[str, Tuple[float, float]] = {}

    if cpi:
        mean_mom, std_mom = econ_models.forecast_cpi_mom(cpi)
        fc["CPI_MOM"] = (mean_mom, std_mom)
        logger.info("CPI MoM forecast: %+.3f%% ± %.3f%%", mean_mom, std_mom)

        mean_yoy, std_yoy = econ_models.forecast_cpi_yoy(cpi)
        fc["CPI_YOY"] = (mean_yoy, std_yoy)
        logger.info("CPI YoY forecast: %.2f%% ± %.2f%%", mean_yoy, std_yoy)

    if unemp:
        mean_u, std_u = econ_models.forecast_unemployment(unemp)
        fc["UNEMPLOYMENT"] = (mean_u, std_u)
        logger.info("Unemployment forecast: %.2f%% ± %.2f%%", mean_u, std_u)

    return fc


def _compute_prob(parsed: ParsedEconMarket,
                  forecasts: Dict[str, Tuple[float, float]]) -> Optional[float]:
    fc = forecasts.get(parsed.market_type)
    if fc is None:
        return None

    mean, std = fc
    if parsed.direction == "ABOVE":
        return econ_models.prob_above(mean, std, parsed.threshold)
    elif parsed.direction == "BELOW":
        return econ_models.prob_below(mean, std, parsed.threshold)
    return None


async def _get_econ_markets(client) -> List[Market]:
    """Fetch all Polymarket markets and filter to economic ones."""
    markets: List[Market] = []
    cursor = ""
    pages = 0

    while pages < 20:
        try:
            data = await client.get_markets(cursor)
        except Exception as exc:
            logger.error("CLOB fetch error (econ, page %d): %s", pages, exc)
            break

        for item in data.get("data", []):
            if _is_econ_market(item):
                from pulse.market.polymarket import _parse_market
                markets.append(_parse_market(item))

        cursor = data.get("next_cursor", "")
        pages += 1
        if not cursor or cursor == "LTE=":
            break

        import asyncio as _asyncio
        await _asyncio.sleep(0.1)

    logger.info("Found %d econ markets after scanning %d pages", len(markets), pages)
    return markets


def _is_econ_market(item: dict) -> bool:
    text = ((item.get("question") or "") + " " + (item.get("description") or "")).lower()
    return any(kw in text for kw in ECON_KEYWORDS)


def _token_id(market: Market, outcome: str) -> Optional[str]:
    for tok in market.tokens:
        if (tok.get("outcome") or "").upper() == outcome.upper():
            return tok.get("token_id")
    return None
