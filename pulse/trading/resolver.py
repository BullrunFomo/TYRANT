"""Market resolution tracker — settles open demo trades when markets resolve."""
from __future__ import annotations

import logging

from pulse.db import database as db
from pulse.db.database import Trade
from pulse.market.polymarket import get_client
from pulse.trading import risk

logger = logging.getLogger(__name__)

# Token price at or above this means the market has resolved to that outcome
_RESOLVED_THRESHOLD = 0.98


async def resolve_open_trades() -> int:
    """
    Poll Polymarket for any open FILLED trades whose markets have now resolved.
    Calculates P&L, updates equity, and marks trades as RESOLVED.
    Returns the number of trades settled this run.
    """
    open_trades = await db.get_open_trades()
    if not open_trades:
        return 0

    client = get_client()
    settled = 0

    for trade in open_trades:
        try:
            market = await client.get_market(trade.market_id)
            if not market:
                continue

            # Still active — not resolved yet
            if market.active:
                continue

            winner = _get_winner(market)
            if winner is None:
                continue

            pnl = _calc_pnl(trade, winner)
            await db.update_trade_status(
                trade.id, "RESOLVED", pnl=pnl, order_id=trade.order_id
            )
            await risk.record_trade_result(pnl, trade.size_usd)

            result = "WIN" if pnl > 0 else "LOSS"
            logger.info(
                "RESOLVED [%s] | %s %s @ %.3f | winner=%s | pnl=$%+.2f",
                result, trade.city, trade.outcome, trade.price, winner, pnl,
            )
            settled += 1

        except Exception as exc:
            logger.error("Resolution check failed for trade %s: %s", trade.id, exc)

    if settled:
        logger.info("Resolution pass complete — settled %d trade(s)", settled)

    return settled


def _get_winner(market) -> str | None:
    """Return the winning outcome ('YES' or 'NO'), or None if still unresolved."""
    for tok in market.tokens:
        price = float(tok.get("price", 0) or 0)
        if price >= _RESOLVED_THRESHOLD:
            return (tok.get("outcome") or "").upper()
    return None


def _calc_pnl(trade: Trade, winner: str) -> float:
    """
    Binary market payoff:
      Win:  bought `size_usd` worth of tokens at `price` each → each pays $1
            pnl = size_usd * (1/price - 1)
      Lose: entire stake is lost
            pnl = -size_usd
    """
    if trade.outcome.upper() == winner:
        return round(trade.size_usd * (1.0 / trade.price - 1.0), 4)
    return -round(trade.size_usd, 4)
