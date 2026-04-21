"""Parse Polymarket financial market titles (indices, gold, oil)."""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)

ASSET_KEYWORDS = {
    "SPY": ["s&p 500", "sp 500", "sp500", "s&p500", "spx", "spy"],
    "QQQ": ["nasdaq", "qqq", "nasdaq 100", "ndx"],
    "GLD": ["gold", "xau/usd", "xauusd", "gold price"],
    "USO": ["oil", "crude oil", "wti", "brent", "crude"],
    "DIA": ["dow jones", "djia", "dow 30", "dow index"],
}

_NUM_RE  = re.compile(r'([\d,]+(?:\.\d+)?)\s*([kK]?)')
_MONTH_MAP = {
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
    "jan":1,"feb":2,"mar":3,"apr":4,"jun":6,"jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12,
}
_DATE_RE = re.compile(
    r'(january|february|march|april|may|june|july|august|september|october|november|december'
    r'|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)[,\s]+(\d{4})'
    r'|end of (\d{4})|by (\d{4})|(\d{4})',
    re.IGNORECASE,
)


@dataclass
class ParsedFinancialMarket:
    ticker: str
    direction: str
    target_level: float
    year: int
    month: int
    raw_title: str

    @property
    def city(self) -> str:
        return f"FIN_{self.ticker}"

    @property
    def date_str(self) -> str:
        return f"{self.year}-{self.month:02d}"


def parse_financial_title(title: str) -> Optional[ParsedFinancialMarket]:
    t = title.lower()

    ticker = None
    for sym, kws in ASSET_KEYWORDS.items():
        if any(kw in t for kw in kws):
            ticker = sym
            break
    if not ticker:
        return None

    # Collect all numeric values and pick the most plausible price level
    candidates: List[float] = []
    for m in _NUM_RE.finditer(title.replace(",", "")):
        try:
            v = float(m.group(1))
            if m.group(2).lower() == "k":
                v *= 1000
            if v > 10:
                candidates.append(v)
        except ValueError:
            pass
    if not candidates:
        return None
    target = max(candidates)

    year, month = _parse_date(t)
    if year is None:
        year = datetime.now().year

    return ParsedFinancialMarket(
        ticker=ticker,
        direction=_direction(t),
        target_level=target,
        year=year,
        month=month or 0,
        raw_title=title,
    )


def _direction(t: str) -> str:
    if any(k in t for k in ("above","exceed","higher","over","at least","reach","hit","close above")):
        return "ABOVE"
    return "BELOW"


def _parse_date(t: str):
    m = _DATE_RE.search(t)
    if not m:
        return None, None
    if m.group(1):
        return int(m.group(2)), _MONTH_MAP.get(m.group(1).lower(), 0)
    for g in (m.group(3), m.group(4), m.group(5)):
        if g:
            return int(g), None
    return None, None
