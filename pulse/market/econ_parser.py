"""Parse Polymarket economic market titles into structured data."""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

_THRESHOLD_RE  = re.compile(r"(\d+(?:\.\d+)?)\s*%")
_MONTH_YEAR_RE = re.compile(
    r"(january|february|march|april|may|june|july|august|"
    r"september|october|november|december|jan|feb|mar|apr|"
    r"jun|jul|aug|sep|oct|nov|dec)[,\s]+(\d{4})",
    re.IGNORECASE,
)
# "from January to February 2025"
_MOM_RE = re.compile(
    r"from\s+(january|february|march|april|may|june|july|august|"
    r"september|october|november|december|jan|feb|mar|apr|jun|jul|"
    r"aug|sep|oct|nov|dec)\s+to\s+"
    r"(january|february|march|april|may|june|july|august|"
    r"september|october|november|december|jan|feb|mar|apr|jun|jul|"
    r"aug|sep|oct|nov|dec)\s+(\d{4})",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"\b(202\d)\b")
_BPS_RE  = re.compile(r"(\d+)\s*bps?", re.IGNORECASE)


@dataclass
class ParsedEconMarket:
    market_type: str    # CPI_MOM | CPI_YOY | UNEMPLOYMENT | FED_RATE
    direction: str      # ABOVE | BELOW | CUT | HIKE | HOLD
    threshold: float    # e.g. 0.3 for CPI > 0.3%
    year: int
    month: int          # end month; 0 if unknown
    raw_title: str

    # Duck-type compatibility with ParsedMarket (used by execution engine)
    @property
    def city(self) -> str:
        return f"US_{self.market_type}"

    @property
    def date_str(self) -> str:
        return f"{self.year}-{self.month:02d}"


def parse_econ_title(title: str) -> Optional[ParsedEconMarket]:
    t = title.lower().strip()
    return (
        _try_cpi_mom(t, title)
        or _try_cpi_yoy(t, title)
        or _try_unemployment(t, title)
        or _try_fed_rate(t, title)
    )


# ── CPI MoM ────────────────────────────────────────────────────────────────────

def _try_cpi_mom(t: str, raw: str) -> Optional[ParsedEconMarket]:
    """Matches: 'Will inflation be > 0.3% from January to February 2025?'"""
    if not any(k in t for k in ("inflation", "cpi", "consumer price")):
        return None
    m = _MOM_RE.search(t)
    if not m:
        return None

    threshold = _threshold(t)
    if threshold is None:
        return None

    # End month is the second month in "from X to Y"
    end_month = MONTH_MAP.get(m.group(2).lower(), 0)
    year = int(m.group(3))

    return ParsedEconMarket(
        market_type="CPI_MOM",
        direction=_direction(t),
        threshold=threshold,
        year=year,
        month=end_month,
        raw_title=raw,
    )


# ── CPI YoY ────────────────────────────────────────────────────────────────────

def _try_cpi_yoy(t: str, raw: str) -> Optional[ParsedEconMarket]:
    """Matches: 'Will CPI YoY be above 3% in January 2025?'"""
    if not any(k in t for k in ("cpi", "inflation", "consumer price")):
        return None
    if "yoy" not in t and "year" not in t and "annual" not in t and "year-over-year" not in t:
        return None

    threshold = _threshold(t)
    if threshold is None:
        return None

    month, year = _month_year(t)
    if year is None:
        return None

    return ParsedEconMarket(
        market_type="CPI_YOY",
        direction=_direction(t),
        threshold=threshold,
        year=year,
        month=month or 0,
        raw_title=raw,
    )


# ── Unemployment ───────────────────────────────────────────────────────────────

def _try_unemployment(t: str, raw: str) -> Optional[ParsedEconMarket]:
    if not any(k in t for k in ("unemployment", "jobless")):
        return None

    threshold = _threshold(t)
    if threshold is None:
        return None

    month, year = _month_year(t)
    if year is None:
        return None

    return ParsedEconMarket(
        market_type="UNEMPLOYMENT",
        direction=_direction(t),
        threshold=threshold,
        year=year,
        month=month or 0,
        raw_title=raw,
    )


# ── Fed rate ───────────────────────────────────────────────────────────────────

def _try_fed_rate(t: str, raw: str) -> Optional[ParsedEconMarket]:
    if not any(k in t for k in ("fed", "federal funds", "fomc", "rate cut", "rate hike", "interest rate")):
        return None
    if not any(k in t for k in ("cut", "hike", "raise", "lower", "hold", "pause", "bps", "basis", "decrease", "increase")):
        return None

    month, year = _month_year(t)
    # Default to current year when title omits it (common for Fed meeting markets)
    if year is None:
        from datetime import datetime as _dt
        year = _dt.now().year

    if any(k in t for k in ("cut", "lower", "reduce", "decrease")):
        direction = "CUT"
    elif any(k in t for k in ("hike", "raise", "increase")):
        direction = "HIKE"
    else:
        direction = "HOLD"

    bps = _BPS_RE.search(t)
    threshold = float(bps.group(1)) if bps else (_threshold(t) or 0.0)

    return ParsedEconMarket(
        market_type="FED_RATE",
        direction=direction,
        threshold=threshold,
        year=year,
        month=month or 0,
        raw_title=raw,
    )


# ── Helpers ────────────────────────────────────────────────────────────────────

def _threshold(t: str) -> Optional[float]:
    m = _THRESHOLD_RE.search(t)
    return float(m.group(1)) if m else None


def _direction(t: str) -> str:
    if any(k in t for k in ("above", "exceed", "greater", "higher", "more than", "over", "or higher", "at least")):
        return "ABOVE"
    if any(k in t for k in ("below", "under", "less than", "lower than", "or lower", "at most")):
        return "BELOW"
    return "ABOVE"


def _month_year(t: str):
    m = _MONTH_YEAR_RE.search(t)
    if m:
        return MONTH_MAP.get(m.group(1).lower(), 0), int(m.group(2))
    y = _YEAR_RE.search(t)
    if y:
        return None, int(y.group(1))
    return None, None
