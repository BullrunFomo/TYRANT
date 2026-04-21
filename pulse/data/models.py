"""Statistical probability models for temperature forecasts."""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np
from scipy import stats

from pulse.data.weather import CityForecast

logger = logging.getLogger(__name__)


def prob_above_threshold(forecast: CityForecast, date_str: str,
                          threshold_f: float) -> float:
    """
    P(daily_high >= threshold_f) using ensemble distribution.

    Falls back to a Gaussian fit from the deterministic forecast + climatological
    spread (~3 °F std-dev) when ensemble data is unavailable.
    """
    ensemble = forecast.ensemble_highs(date_str)

    if len(ensemble) >= 5:
        return _ensemble_prob(ensemble, threshold_f)

    # Fallback: deterministic + assumed spread
    det_high = forecast.daily_high(date_str)
    if det_high is None:
        logger.warning("No forecast data for %s %s", forecast.city, date_str)
        return 0.5   # no information — return neutral
    return _gaussian_prob(det_high, std=3.5, threshold=threshold_f)


def prob_in_range(forecast: CityForecast, date_str: str,
                  low_f: float, high_f: float) -> float:
    """P(low_f <= daily_high < high_f)."""
    p_above_low = prob_above_threshold(forecast, date_str, low_f)
    p_above_high = prob_above_threshold(forecast, date_str, high_f)
    return max(0.0, p_above_low - p_above_high)


def prob_below_threshold(forecast: CityForecast, date_str: str,
                          threshold_f: float) -> float:
    """P(daily_high < threshold_f)."""
    return 1.0 - prob_above_threshold(forecast, date_str, threshold_f)


def temperature_distribution(forecast: CityForecast,
                              date_str: str) -> Tuple[float, float]:
    """Return (mean, std) of daily high distribution in °F."""
    ensemble = forecast.ensemble_highs(date_str)
    if len(ensemble) >= 2:
        return float(np.mean(ensemble)), float(np.std(ensemble, ddof=1))
    det = forecast.daily_high(date_str)
    if det is not None:
        return det, 3.5
    return 70.0, 5.0   # default fallback


# ── Private helpers ────────────────────────────────────────────────────────────

def _ensemble_prob(members: List[float], threshold: float) -> float:
    """Empirical CDF from ensemble members — P(max >= threshold)."""
    arr = np.array(members, dtype=float)
    return float(np.mean(arr >= threshold))


def _gaussian_prob(mean: float, std: float, threshold: float) -> float:
    """P(X >= threshold) for X ~ N(mean, std)."""
    return float(1.0 - stats.norm.cdf(threshold, loc=mean, scale=std))
