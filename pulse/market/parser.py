"""Parse Polymarket weather market titles into structured data."""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Known city aliases that might appear in market titles
CITY_ALIASES: dict[str, str] = {
    "miami":       "Miami",
    "phoenix":     "Phoenix",
    "chicago":     "Chicago",
    "new york":    "New York",
    "nyc":         "New York",
    "los angeles": "Los Angeles",
    "la":          "Los Angeles",
    "houston":     "Houston",
    "dallas":      "Dallas",
    "seattle":     "Seattle",
}

# Degree patterns: 90°F, 90 degrees, 90F
TEMP_PATTERN = re.compile(
    r"(\d{2,3})\s*(?:°|degrees?)?\s*[Ff](?:ahrenheit)?",
    re.IGNORECASE,
)

# Date patterns
DATE_PATTERNS = [
    re.compile(r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
               r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
               r"Dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?", re.IGNORECASE),
    re.compile(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?"),
    re.compile(r"(\d{4})-(\d{2})-(\d{2})"),
]

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Outcome patterns
ABOVE_PATTERN = re.compile(r"(?:reach|above|at least|or higher|exceed|≥|>=)", re.IGNORECASE)
BELOW_PATTERN = re.compile(r"(?:below|under|less than|not reach|<)", re.IGNORECASE)
RANGE_PATTERN = re.compile(r"between\s+(\d{2,3})\s*[°F]*\s*and\s+(\d{2,3})\s*[°F]*", re.IGNORECASE)


@dataclass
class ParsedMarket:
    city: str
    date_str: str          # YYYY-MM-DD
    threshold_f: float
    threshold_high_f: Optional[float]   # set for range markets
    outcome_type: str      # ABOVE / BELOW / RANGE
    raw_title: str


def parse_market_title(title: str) -> Optional[ParsedMarket]:
    """Extract city, date, temperature, and outcome type from a market title."""
    lower = title.lower()

    city = _extract_city(lower)
    if not city:
        return None

    date_str = _extract_date(title)
    if not date_str:
        return None

    # Range market: "between 85°F and 90°F"
    range_match = RANGE_PATTERN.search(title)
    if range_match:
        low_t = float(range_match.group(1))
        high_t = float(range_match.group(2))
        return ParsedMarket(city=city, date_str=date_str,
                            threshold_f=low_t, threshold_high_f=high_t,
                            outcome_type="RANGE", raw_title=title)

    temps = TEMP_PATTERN.findall(title)
    if not temps:
        return None
    threshold = float(temps[0])

    if ABOVE_PATTERN.search(title):
        outcome = "ABOVE"
    elif BELOW_PATTERN.search(title):
        outcome = "BELOW"
    else:
        outcome = "ABOVE"   # default assumption

    return ParsedMarket(city=city, date_str=date_str,
                        threshold_f=threshold, threshold_high_f=None,
                        outcome_type=outcome, raw_title=title)


# ── Private helpers ────────────────────────────────────────────────────────────

def _extract_city(lower_title: str) -> Optional[str]:
    for alias, canonical in CITY_ALIASES.items():
        if alias in lower_title:
            return canonical
    return None


def _extract_date(title: str) -> Optional[str]:
    now = datetime.utcnow()

    # Named month: "April 20, 2024" or "April 20"
    m = DATE_PATTERNS[0].search(title)
    if m:
        month_str = m.group(1)[:3].lower()
        month = MONTH_MAP.get(month_str)
        if not month:
            return None
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else now.year
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            return None

    # Numeric: MM/DD or MM/DD/YYYY
    m = DATE_PATTERNS[1].search(title)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
        year_raw = m.group(3)
        year = int(year_raw) if year_raw else now.year
        if year < 100:
            year += 2000
        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            return None

    # ISO: YYYY-MM-DD
    m = DATE_PATTERNS[2].search(title)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    return None
