"""Forecasting models for economic indicators (CPI, unemployment)."""
from __future__ import annotations

import logging
from typing import List, Optional, Tuple

import numpy as np
from scipy import stats

from pulse.data.fred import EconSeries

logger = logging.getLogger(__name__)


# ── CPI ────────────────────────────────────────────────────────────────────────

def forecast_cpi_mom(cpi_series: EconSeries) -> Tuple[float, float]:
    """
    Forecast next month's CPI month-over-month % change.
    Returns (mean_pct, std_pct).

    Polymarket CPI markets ask "Will inflation be > X% from Month A to Month B?"
    which is MoM % change of the CPI index.
    """
    values = np.array(cpi_series.values)
    if len(values) < 4:
        return 0.3, 0.2

    mom = (values[1:] / values[:-1] - 1.0) * 100   # MoM % changes

    if len(mom) < 3:
        return float(mom[-1]), 0.2

    # AR(1) on MoM changes
    y, x = mom[1:], mom[:-1]
    beta, alpha, _, _, _ = stats.linregress(x, y)
    forecast = float(np.clip(alpha + beta * mom[-1], -1.0, 2.0))
    resid_std = float(np.std(y - (alpha + beta * x), ddof=2))

    return forecast, max(resid_std, 0.05)


def forecast_cpi_yoy(cpi_series: EconSeries) -> Tuple[float, float]:
    """
    Forecast next month's CPI year-over-year % change.
    Returns (mean_pct, std_pct).
    """
    values = np.array(cpi_series.values)
    if len(values) < 14:
        return 3.0, 0.5

    yoy = (values[12:] / values[:-12] - 1.0) * 100

    if len(yoy) < 3:
        return float(yoy[-1]), 0.3

    y, x = yoy[1:], yoy[:-1]
    beta, alpha, _, _, _ = stats.linregress(x, y)
    forecast = float(np.clip(alpha + beta * yoy[-1], 0.0, 15.0))
    resid_std = float(np.std(y - (alpha + beta * x), ddof=2))

    return forecast, max(resid_std, 0.1)


# ── Unemployment ───────────────────────────────────────────────────────────────

def forecast_unemployment(unemp_series: EconSeries) -> Tuple[float, float]:
    """
    Forecast next month's unemployment rate.
    Returns (mean_pct, std_pct).
    """
    values = np.array(unemp_series.values)
    if len(values) < 3:
        return 4.0, 0.3

    y, x = values[1:], values[:-1]
    beta, alpha, _, _, _ = stats.linregress(x, y)
    forecast = float(np.clip(alpha + beta * values[-1], 2.0, 15.0))
    resid_std = float(np.std(y - (alpha + beta * x), ddof=2))

    return forecast, max(resid_std, 0.05)


# ── Probability helpers ────────────────────────────────────────────────────────

def prob_above(mean: float, std: float, threshold: float) -> float:
    return float(1.0 - stats.norm.cdf(threshold, loc=mean, scale=std))


def prob_below(mean: float, std: float, threshold: float) -> float:
    return float(stats.norm.cdf(threshold, loc=mean, scale=std))
