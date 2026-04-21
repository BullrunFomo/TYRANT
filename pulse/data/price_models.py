"""Lognormal (GBM) probability model for crypto and financial price markets."""
from __future__ import annotations

import math
from typing import List

from scipy.stats import norm


def _gbm_params(prices: List[float]):
    """Return (mu, sigma) of daily log-returns."""
    log_rets = [math.log(prices[i] / prices[i - 1])
                for i in range(1, len(prices)) if prices[i - 1] > 0]
    if len(log_rets) < 5:
        return 0.0, 0.02
    mu = sum(log_rets) / len(log_rets)
    var = sum((r - mu) ** 2 for r in log_rets) / max(len(log_rets) - 1, 1)
    return mu, math.sqrt(var)


def prob_above(prices: List[float], target: float, days_ahead: int) -> float:
    """P(price > target in `days_ahead` trading days) under GBM."""
    if not prices or target <= 0 or days_ahead <= 0:
        return 0.5
    mu, sigma = _gbm_params(prices)
    current = prices[-1]
    drift = (mu - 0.5 * sigma ** 2) * days_ahead
    vol = sigma * math.sqrt(days_ahead)
    if vol < 1e-10:
        return 1.0 if current > target else 0.0
    z = (math.log(target / current) - drift) / vol
    return float(1.0 - norm.cdf(z))


def prob_below(prices: List[float], target: float, days_ahead: int) -> float:
    return 1.0 - prob_above(prices, target, days_ahead)


def prob_in_range(prices: List[float], low: float, high: float, days_ahead: int) -> float:
    return max(0.0, prob_above(prices, low, days_ahead) - prob_above(prices, high, days_ahead))
