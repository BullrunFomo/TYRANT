"""USGS earthquake feed — free, no API key required."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import aiohttp

logger = logging.getLogger(__name__)

USGS_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_month.geojson"

REGIONS: Dict[str, Dict[str, Tuple[float, float]]] = {
    "California":        {"lat": (32.5, 42.0),  "lon": (-124.5, -114.1)},
    "Pacific Northwest": {"lat": (42.0, 49.5),  "lon": (-124.6, -116.5)},
    "Alaska":            {"lat": (54.0, 71.5),  "lon": (-168.0, -130.0)},
    "Japan":             {"lat": (30.0, 46.0),  "lon": (129.0,  146.0)},
    "Turkey":            {"lat": (36.0, 42.5),  "lon": (26.0,   45.0)},
    "Chile":             {"lat": (-56.0, -17.0),"lon": (-75.0,  -66.0)},
    "Italy":             {"lat": (36.5, 47.5),  "lon": (6.5,    18.5)},
    "New Zealand":       {"lat": (-47.0, -34.0),"lon": (166.0,  178.0)},
    "Indonesia":         {"lat": (-11.0, 6.0),  "lon": (95.0,   141.0)},
}

_cache: Optional[tuple] = None
_CACHE_TTL = 600.0


@dataclass
class QuakeEvent:
    magnitude: float
    lat: float
    lon: float
    depth_km: float
    time: datetime
    place: str


async def get_recent_quakes(min_magnitude: float = 2.5) -> List[QuakeEvent]:
    global _cache
    if _cache and time.time() - _cache[0] < _CACHE_TTL:
        return [q for q in _cache[1] if q.magnitude >= min_magnitude]

    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(USGS_URL, timeout=aiohttp.ClientTimeout(total=20)) as r:
                if r.status != 200:
                    logger.warning("USGS: HTTP %d", r.status)
                    return []
                data = await r.json()
        events = []
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            coords = feat.get("geometry", {}).get("coordinates", [0, 0, 0])
            mag = props.get("mag") or 0
            if mag < 1.0:
                continue
            try:
                events.append(QuakeEvent(
                    magnitude=float(mag),
                    lat=float(coords[1]),
                    lon=float(coords[0]),
                    depth_km=float(coords[2]),
                    time=datetime.utcfromtimestamp(props["time"] / 1000),
                    place=props.get("place", ""),
                ))
            except Exception:
                continue
        _cache = (time.time(), events)
        return [q for q in events if q.magnitude >= min_magnitude]
    except Exception as exc:
        logger.error("USGS fetch error: %s", exc)
        return [q for q in _cache[1] if q.magnitude >= min_magnitude] if _cache else []
