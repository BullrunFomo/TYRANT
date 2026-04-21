"""Kelly criterion position sizing."""
from __future__ import annotations

from pulse import config


def kelly_fraction(p: float, b: float) -> float:
    """
    Full Kelly fraction: f* = (p*b - q) / b  where q = 1-p, b = net odds.

    For a binary prediction market at price `price` (0–1):
      - b  = (1 - price) / price   (net odds of winning on a YES bet)
      - p  = our estimated true probability
    """
    q = 1.0 - p
    if b <= 0:
        return 0.0
    f = (p * b - q) / b
    return max(0.0, f)


def size_trade(bankroll: float, true_prob: float,
               market_price: float) -> float:
    """
    Return recommended trade size in USD using fractional Kelly.

    Applies:
      1. Full Kelly formula
      2. Multiplied by KELLY_FRACTION (e.g. 0.25 = quarter-Kelly)
      3. Capped at MAX_TRADE_SIZE_USD
    """
    if market_price <= 0 or market_price >= 1:
        return 0.0

    # Net odds for a YES purchase at `market_price`
    b = (1.0 - market_price) / market_price
    f_full = kelly_fraction(true_prob, b)
    f_frac = f_full * config.KELLY_FRACTION

    raw_size = bankroll * f_frac
    capped = min(raw_size, config.MAX_TRADE_SIZE_USD)
    return round(max(0.0, capped), 2)
