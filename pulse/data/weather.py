"""Weather data engine — fetches GFS-based forecasts via Open-Meteo (free, no key)."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import aiohttp
import numpy as np

from pulse import config

logger = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"

# Open-Meteo ensemble model — gfs025 has 31 members (member00-member30)
ENSEMBLE_MODEL = "gfs025"


@dataclass
class HourlyForecast:
    """Temperature forecast for a single hour."""
    dt: datetime
    temp_f: float
    temp_f_ensemble: List[float] = field(default_factory=list)   # ensemble members


@dataclass
class CityForecast:
    """All forecasts for a city, keyed by ISO-date (YYYY-MM-DD)."""
    city: str
    lat: float
    lon: float
    fetched_at: float
    hourly: List[HourlyForecast] = field(default_factory=list)

    def daily_high(self, date_str: str) -> Optional[float]:
        """Return the deterministic daily high for date_str (YYYY-MM-DD)."""
        temps = [h.temp_f for h in self.hourly if h.dt.strftime("%Y-%m-%d") == date_str]
        return max(temps) if temps else None

    def ensemble_highs(self, date_str: str) -> List[float]:
        """Return per-member daily highs for the ensemble distribution."""
        highs: Dict[int, float] = {}
        for h in self.hourly:
            if h.dt.strftime("%Y-%m-%d") != date_str:
                continue
            for i, t in enumerate(h.temp_f_ensemble):
                highs[i] = max(highs.get(i, -999), t)
        return list(highs.values())


# ── Shared cache ───────────────────────────────────────────────────────────────

_cache: Dict[str, CityForecast] = {}
_cache_lock = asyncio.Lock()
_last_fetch: Dict[str, float] = {}
CACHE_TTL = 300  # seconds — match scan interval


async def get_forecast(city: str) -> Optional[CityForecast]:
    """Return a cached (or freshly fetched) forecast for *city*."""
    async with _cache_lock:
        now = time.time()
        if city in _cache and (now - _last_fetch.get(city, 0)) < CACHE_TTL:
            return _cache[city]

    coords = config.CITIES.get(city)
    if not coords:
        logger.warning("Unknown city: %s", city)
        return None

    try:
        forecast = await _fetch_forecast(city, coords["lat"], coords["lon"])
        async with _cache_lock:
            _cache[city] = forecast
            _last_fetch[city] = time.time()
        return forecast
    except Exception as exc:
        logger.error("Weather fetch failed for %s: %s", city, exc)
        return _cache.get(city)          # return stale data if available


async def get_all_forecasts() -> Dict[str, CityForecast]:
    """Fetch all configured cities concurrently."""
    tasks = [get_forecast(city) for city in config.CITIES]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return {
        city: fc
        for city, fc in zip(config.CITIES.keys(), results)
        if isinstance(fc, CityForecast)
    }


# ── Open-Meteo fetch ───────────────────────────────────────────────────────────

async def _fetch_forecast(city: str, lat: float, lon: float) -> CityForecast:
    # Requesting temperature_2m auto-includes all ensemble member columns
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "forecast_days": 7,
        "models": ENSEMBLE_MODEL,
        "timezone": "UTC",
    }

    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(OPEN_METEO_ENSEMBLE_URL, params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    # temperature_2m is the ensemble mean / control run
    temps = hourly.get("temperature_2m", [])

    # Collect ensemble member columns (member01-member30)
    member_cols: List[List[float]] = []
    for i in range(1, 31):
        col = hourly.get(f"temperature_2m_member{i:02d}", [])
        if col:
            member_cols.append(col)

    forecasts: List[HourlyForecast] = []
    for idx, (t_str, temp) in enumerate(zip(times, temps)):
        if temp is None:
            continue
        dt = datetime.fromisoformat(t_str).replace(tzinfo=timezone.utc)
        ensemble = [col[idx] for col in member_cols if idx < len(col) and col[idx] is not None]
        forecasts.append(HourlyForecast(dt=dt, temp_f=float(temp), temp_f_ensemble=ensemble))

    logger.info("Fetched %d hourly forecasts for %s", len(forecasts), city)
    return CityForecast(city=city, lat=lat, lon=lon,
                        fetched_at=time.time(), hourly=forecasts)
