"""Sports market scanner — The Odds API + vig-free probability comparison."""
from __future__ import annotations

import logging
from difflib import SequenceMatcher
from typing import Any, List

from pulse.market.polymarket import get_client, get_all_markets_cached, filter_markets
from pulse.market.sports_parser import ParsedSportsMarket, parse_sports_title
from pulse.data.odds_api import GameOdds, get_all_odds
from pulse import config

logger = logging.getLogger(__name__)

SPORTS_KEYWORDS = [
    "nfl", "nba", "mlb", "nhl", "super bowl", "championship",
    "premier league", "champions league", "mls",
    "win the", "will the", "beat", "advance",
]


async def scan_sports() -> List[Any]:
    if not config.SPORTS_MARKETS_ENABLED:
        return []
    if not config.ODDS_API_KEY:
        logger.debug("ODDS_API_KEY not set — skipping sports scan")
        return []

    all_odds = await get_all_odds()
    all_games: List[GameOdds] = [g for games in all_odds.values() for g in games]
    if not all_games:
        logger.info("No odds data available — skipping sports scan")
        return []

    client = get_client()
    all_markets = await get_all_markets_cached(client)
    markets = [m for m in filter_markets(all_markets, SPORTS_KEYWORDS) if m.active]
    logger.info("Scanning %d sports markets", len(markets))

    opportunities = []
    for market in markets:
        if market.liquidity < config.MIN_LIQUIDITY_USD:
            continue

        parsed = parse_sports_title(market.title)
        if not parsed:
            continue

        game = _find_game(parsed.team, all_games)
        if not game:
            continue

        # Is the market asking about home or away team?
        home_sim = _sim(parsed.team, game.home_team)
        away_sim = _sim(parsed.team, game.away_team)
        true_prob = game.home_prob if home_sim >= away_sim else game.away_prob

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
        logger.info("Sports edge: %s vs %s | model=%.1f%% mkt=%.1f%% edge=%+.1f%%",
                    game.home_team, game.away_team,
                    true_prob * 100, market_prob * 100, edge * 100)

    opportunities.sort(key=lambda o: abs(o.edge), reverse=True)
    return opportunities


def _find_game(team_name: str, games: List[GameOdds]) -> GameOdds | None:
    best, best_score = None, 0.4
    for game in games:
        score = max(_sim(team_name, game.home_team), _sim(team_name, game.away_team))
        if score > best_score:
            best, best_score = game, score
    return best


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


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
