"""Parse Polymarket sports outcome market titles."""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

SPORT_KEYWORDS = {
    "NFL":    ["nfl", "super bowl", "chiefs", "eagles", "patriots", "cowboys",
               "49ers", "ravens", "bills", "packers", "bears", "giants", "jets"],
    "NBA":    ["nba", "lakers", "celtics", "warriors", "nets", "bucks",
               "nuggets", "heat", "suns", "clippers", "knicks", "spurs"],
    "MLB":    ["mlb", "yankees", "dodgers", "red sox", "cubs", "world series",
               "astros", "mets", "braves", "cardinals"],
    "NHL":    ["nhl", "stanley cup", "maple leafs", "bruins", "rangers",
               "penguins", "blackhawks", "oilers", "avalanche"],
    "SOCCER": ["premier league", "champions league", "mls", "world cup",
               "euro 2024", "laliga", "serie a", "bundesliga"],
}

_WIN_RE  = re.compile(r'will\s+(.+?)\s+win', re.IGNORECASE)
_VS_RE   = re.compile(r'(.+?)\s+(?:vs\.?|versus|@)\s+(.+?)(?:\?|$)', re.IGNORECASE)
_CHAMP_RE = re.compile(r'win\s+(?:the\s+)?(.+?)\s+(?:championship|title|cup|bowl|series)', re.IGNORECASE)


@dataclass
class ParsedSportsMarket:
    sport: str
    team: str           # the team the market is asking about
    opponent: str
    direction: str      # WIN
    raw_title: str

    @property
    def city(self) -> str:
        return f"SPORTS_{self.sport}"

    @property
    def date_str(self) -> str:
        return "N/A"


def parse_sports_title(title: str) -> Optional[ParsedSportsMarket]:
    t = title.lower()

    sport = next(
        (sp for sp, kws in SPORT_KEYWORDS.items() if any(kw in t for kw in kws)),
        None,
    )
    if not sport:
        return None

    # "Will X win ..."
    win_m = _WIN_RE.search(title)
    vs_m  = _VS_RE.search(title)

    if win_m:
        team = win_m.group(1).strip()[:40]
        opponent = ""
        if vs_m:
            # figure out which side is the subject
            home = vs_m.group(1).strip()
            away = vs_m.group(2).strip()
            opponent = away if team.lower() in home.lower() else home
        return ParsedSportsMarket(sport=sport, team=team,
                                   opponent=opponent, direction="WIN",
                                   raw_title=title)

    if vs_m:
        # default to asking about the home team
        team     = vs_m.group(1).strip()[-40:]
        opponent = vs_m.group(2).strip()[:40]
        return ParsedSportsMarket(sport=sport, team=team,
                                   opponent=opponent, direction="WIN",
                                   raw_title=title)

    return None
