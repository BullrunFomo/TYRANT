"""Poisson earthquake probability model using USGS historical data."""
from __future__ import annotations

import math
from typing import List

from pulse.data.usgs import QuakeEvent, REGIONS


def quake_prob(quakes: List[QuakeEvent], region: str,
               min_mag: float, days: int) -> float:
    """P(≥1 quake ≥ min_mag in region within `days` days) using Poisson process."""
    bounds = REGIONS.get(region)
    if not bounds:
        return 0.5

    lat_min, lat_max = bounds["lat"]
    lon_min, lon_max = bounds["lon"]

    # Count events in this region at or above min_mag in the last 30 days
    in_region = sum(
        1 for q in quakes
        if q.magnitude >= min_mag
        and lat_min <= q.lat <= lat_max
        and lon_min <= q.lon <= lon_max
    )

    rate_per_day = in_region / 30.0

    # Gutenberg-Richter floor: globally ~10^(8-1.5*M) events/year of magnitude M+
    gr_floor = (10 ** (8.0 - 1.5 * min_mag)) / 365.0 * 0.005  # local fraction
    rate_per_day = max(rate_per_day, gr_floor)

    # P(at least 1) = 1 - e^(-λt)
    prob = 1.0 - math.exp(-rate_per_day * days)
    return max(0.01, min(0.99, prob))
