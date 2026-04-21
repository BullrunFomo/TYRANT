"""Parse Polymarket earthquake and natural disaster market titles."""
from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Optional

from pulse.data.usgs import REGIONS

logger = logging.getLogger(__name__)

_MAG_RE  = re.compile(
    r'magnitude\s*(\d+(?:\.\d+)?)\+?|(\d+(?:\.\d+)?)\+?\s*magnitude'
    r'|m\s*(\d+(?:\.\d+)?)\+',
    re.IGNORECASE,
)
_DAYS_RE = re.compile(r'(?:next|in(?:\s+the\s+next)?)\s+(\d+)\s*days?', re.IGNORECASE)

_REGION_ALIASES = {
    "california": "California",
    "san francisco": "California",
    "los angeles": "California",
    "bay area": "California",
    "seattle": "Pacific Northwest",
    "oregon": "Pacific Northwest",
    "pacific northwest": "Pacific Northwest",
    "alaska": "Alaska",
    "japan": "Japan",
    "tokyo": "Japan",
    "turkey": "Turkey",
    "istanbul": "Turkey",
    "chile": "Chile",
    "italy": "Italy",
    "rome": "Italy",
    "new zealand": "New Zealand",
    "indonesia": "Indonesia",
    "jakarta": "Indonesia",
}


@dataclass
class ParsedGeoMarket:
    event_type: str      # EARTHQUAKE
    region: str
    min_magnitude: float
    days: int
    raw_title: str

    @property
    def city(self) -> str:
        return f"GEO_{self.event_type}"

    @property
    def date_str(self) -> str:
        return "N/A"


def parse_geo_title(title: str) -> Optional[ParsedGeoMarket]:
    t = title.lower()

    if not any(k in t for k in ("earthquake", "quake", "seismic", "tremor")):
        return None

    mag_m = _MAG_RE.search(title)
    if mag_m:
        min_mag = float(mag_m.group(1) or mag_m.group(2) or mag_m.group(3))
    elif "major" in t:
        min_mag = 6.5
    elif "significant" in t or "strong" in t:
        min_mag = 6.0
    elif "moderate" in t:
        min_mag = 5.0
    else:
        return None

    days_m = _DAYS_RE.search(t)
    days = int(days_m.group(1)) if days_m else 30

    region = _detect_region(t)

    return ParsedGeoMarket(
        event_type="EARTHQUAKE",
        region=region,
        min_magnitude=min_mag,
        days=days,
        raw_title=title,
    )


def _detect_region(t: str) -> str:
    for alias, region in _REGION_ALIASES.items():
        if alias in t:
            return region
    for region in REGIONS:
        if region.lower() in t:
            return region
    return "California"
