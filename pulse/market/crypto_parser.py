"""Parse Polymarket crypto price market titles."""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

CRYPTO_SYMBOLS = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "AVAX", "LINK", "ADA", "MATIC",
]

_PRICE_RE  = re.compile(r'\$\s*([\d,]+(?:\.\d+)?)\s*([kKmM]?)')
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
class ParsedCryptoMarket:
    symbol: str
    direction: str       # ABOVE | BELOW
    target_price: float
    year: int
    month: int
    raw_title: str

    @property
    def city(self) -> str:
        return f"CRYPTO_{self.symbol}"

    @property
    def date_str(self) -> str:
        return f"{self.year}-{self.month:02d}"


def parse_crypto_title(title: str) -> Optional[ParsedCryptoMarket]:
    t = title.lower()

    symbol = next((s for s in CRYPTO_SYMBOLS if s.lower() in t), None)
    if not symbol:
        return None

    m = _PRICE_RE.search(title)
    if not m:
        return None
    price = float(m.group(1).replace(",", ""))
    suffix = m.group(2).lower()
    if suffix == "k":
        price *= 1_000
    elif suffix == "m":
        price *= 1_000_000
    if price <= 0:
        return None

    year, month = _parse_date(t)
    if year is None:
        year = datetime.now().year

    return ParsedCryptoMarket(
        symbol=symbol,
        direction=_direction(t),
        target_price=price,
        year=year,
        month=month or 0,
        raw_title=title,
    )


def _direction(t: str) -> str:
    if any(k in t for k in ("above","exceed","higher","over","at least","or more","reach","hit")):
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
