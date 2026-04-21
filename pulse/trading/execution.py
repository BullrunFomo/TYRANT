"""Trade execution engine — combines sizing, risk checks, and order placement."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import List, Optional

from pulse import config
from pulse.db import database as db
from pulse.db.database import Trade
from pulse.market.polymarket import get_client, OrderResult
from pulse.market.scanner import Opportunity
from pulse.trading import kelly, risk

logger = logging.getLogger(__name__)

# Event bus for dashboard notifications
_event_listeners: List = []


def add_listener(fn):
    _event_listeners.append(fn)


def _emit(event: str, **kwargs):
    for fn in _event_listeners:
        try:
            fn(event, **kwargs)
        except Exception:
            pass


async def execute_opportunities(opportunities: List[Opportunity]) -> List[Trade]:
    """
    Execute the best opportunities, respecting the one-trade-per-event constraint.
    Returns list of Trade records (including FAILED ones for logging).
    """
    executed: List[Trade] = []
    traded_events: set = set()   # city+date — one trade per event

    rs = risk.get_state()
    bankroll = rs.current_equity

    for opp in opportunities:
        event_key = f"{opp.parsed.city}:{opp.parsed.date_str}"

        # One trade per event
        if event_key in traded_events:
            logger.debug("Skipping duplicate event: %s", event_key)
            continue

        # Skip if already traded today
        if await db.is_market_traded_today(opp.market.condition_id):
            logger.debug("Already traded %s today", opp.market.condition_id[:12])
            continue

        # Kelly sizing
        size_usd = kelly.size_trade(bankroll, opp.true_prob, opp.recommended_price)
        if size_usd < 1.0:
            logger.debug("Trade size too small (%.2f) for %s", size_usd, event_key)
            continue

        # Risk check
        ok, reason = await risk.can_trade(size_usd)
        if not ok:
            logger.warning("Trade blocked by risk manager: %s", reason)
            _emit("risk_block", reason=reason, opportunity=opp)
            break   # if risk says no, stop processing

        # Place order
        trade = await _execute_single(opp, size_usd)
        executed.append(trade)
        traded_events.add(event_key)

        # Update exposure
        if trade.status in ("PENDING", "FILLED"):
            await risk.add_exposure(size_usd)

        # Micro-delay between orders
        await asyncio.sleep(0.5)

    return executed


async def _execute_single(opp: Opportunity, size_usd: float) -> Trade:
    """Place a single order and persist the result."""
    client = get_client()
    price = opp.recommended_price
    # Convert USD size to token units (Polymarket uses USDC, so 1:1)
    token_size = round(size_usd / price, 2) if price > 0 else 0

    log_entry = Trade(
        id=None,
        timestamp=time.time(),
        market_id=opp.market.condition_id,
        market_title=opp.market.title[:120],
        city=opp.parsed.city,
        outcome=opp.recommended_outcome,
        side="BUY",
        size_usd=size_usd,
        price=price,
        edge=opp.edge,
        order_id="",
        status="PENDING",
    )

    trade_id = await db.insert_trade(log_entry)
    log_entry.id = trade_id

    _emit("trade_attempt", trade=log_entry, size=size_usd, price=price)
    logger.info("ENTRY | %s %s @ %.3f | size=$%.2f | edge=%.1f%%",
                opp.parsed.city, opp.recommended_outcome, price, size_usd, opp.edge * 100)

    # --- Place order ---
    result: OrderResult = await client.place_order(
        token_id=opp.token_id,
        price=price,
        size=token_size,
        side="BUY",
    )

    if result.status == "FILLED":
        final_status = "FILLED"
        logger.info("EXEC  | order_id=%s filled=%.2f avg=%.3f",
                    result.order_id[:16], result.filled_size, result.avg_price)
        _emit("trade_filled", trade=log_entry, result=result)
    else:
        final_status = "FAILED" if not result.order_id else "CANCELLED"
        logger.warning("ORDER %s | %s | %s",
                       final_status, result.order_id[:16], result.error)
        _emit("trade_failed", trade=log_entry, result=result)

    await db.update_trade_status(trade_id, final_status,
                                  pnl=0.0, order_id=result.order_id)
    log_entry.status = final_status
    log_entry.order_id = result.order_id
    return log_entry
