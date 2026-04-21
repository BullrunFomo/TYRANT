"""Risk management — daily loss limit, drawdown, circuit breaker."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, List

from pulse import config
from pulse.db import database as db

logger = logging.getLogger(__name__)

STATE_KEY_CONSECUTIVE_LOSSES = "consecutive_losses"
STATE_KEY_CIRCUIT_OPEN = "circuit_open"
STATE_KEY_PEAK_EQUITY = "peak_equity"


@dataclass
class RiskState:
    circuit_open: bool = False
    circuit_reason: str = ""
    consecutive_losses: int = 0
    daily_pnl: float = 0.0
    peak_equity: float = 0.0
    current_equity: float = 0.0
    drawdown_pct: float = 0.0
    exposure_usd: float = 0.0
    _callbacks: List[Callable] = field(default_factory=list)

    def add_callback(self, fn: Callable):
        self._callbacks.append(fn)

    def _notify(self, event: str, **kwargs):
        for cb in self._callbacks:
            try:
                cb(event, **kwargs)
            except Exception:
                pass


_state = RiskState()


def get_state() -> RiskState:
    return _state


async def load_state(initial_capital: float) -> None:
    """Restore persisted risk state from database."""
    global _state
    circ = await db.get_state(STATE_KEY_CIRCUIT_OPEN, "false")
    losses = int(await db.get_state(STATE_KEY_CONSECUTIVE_LOSSES, "0"))
    peak = float(await db.get_state(STATE_KEY_PEAK_EQUITY, str(initial_capital)))

    total_pnl = await db.get_total_pnl()
    daily_pnl = await db.get_daily_pnl()
    current_equity = initial_capital + total_pnl

    _state.circuit_open = circ == "true"
    _state.consecutive_losses = losses
    _state.peak_equity = max(peak, current_equity)
    _state.daily_pnl = daily_pnl
    _state.current_equity = current_equity
    _state.drawdown_pct = _calc_drawdown(current_equity, _state.peak_equity)

    logger.info("Risk state loaded — equity=$%.2f, drawdown=%.1f%%, circuit=%s",
                current_equity, _state.drawdown_pct * 100, _state.circuit_open)


async def can_trade(size_usd: float) -> tuple[bool, str]:
    """
    Returns (True, "") if a trade is allowed, or (False, reason) if blocked.
    """
    s = _state

    if s.circuit_open:
        return False, f"Circuit breaker OPEN: {s.circuit_reason}"

    daily_loss = abs(min(0.0, s.daily_pnl))
    if daily_loss >= config.MAX_DAILY_LOSS_USD:
        await _trip_circuit(f"Daily loss limit ${config.MAX_DAILY_LOSS_USD:.0f} reached")
        return False, "Daily loss limit reached"

    if s.drawdown_pct >= config.MAX_DRAWDOWN_PCT:
        await _trip_circuit(f"Max drawdown {config.MAX_DRAWDOWN_PCT*100:.0f}% breached")
        return False, f"Max drawdown {config.MAX_DRAWDOWN_PCT*100:.0f}% breached"

    if s.exposure_usd + size_usd > config.MAX_EXPOSURE_USD:
        return False, f"Exposure limit ${config.MAX_EXPOSURE_USD:.0f} would be exceeded"

    return True, ""


async def record_trade_result(pnl: float, size_usd: float) -> None:
    """Update risk state after a trade result is known."""
    s = _state
    s.daily_pnl += pnl
    s.current_equity += pnl
    s.exposure_usd = max(0.0, s.exposure_usd - size_usd)

    if pnl < 0:
        s.consecutive_losses += 1
        if s.consecutive_losses >= config.CIRCUIT_BREAKER_LOSSES:
            await _trip_circuit(
                f"{config.CIRCUIT_BREAKER_LOSSES} consecutive losses"
            )
    else:
        s.consecutive_losses = 0

    if s.current_equity > s.peak_equity:
        s.peak_equity = s.current_equity

    s.drawdown_pct = _calc_drawdown(s.current_equity, s.peak_equity)

    # Persist
    await db.set_state(STATE_KEY_CONSECUTIVE_LOSSES, str(s.consecutive_losses))
    await db.set_state(STATE_KEY_PEAK_EQUITY, str(s.peak_equity))
    await db.snapshot_pnl(s.current_equity)

    s._notify("trade_result", pnl=pnl, equity=s.current_equity)


async def add_exposure(size_usd: float) -> None:
    _state.exposure_usd += size_usd


async def reset_circuit() -> None:
    """Manually reset the circuit breaker (e.g. new trading day)."""
    _state.circuit_open = False
    _state.circuit_reason = ""
    _state.consecutive_losses = 0
    _state.daily_pnl = 0.0
    await db.set_state(STATE_KEY_CIRCUIT_OPEN, "false")
    await db.set_state(STATE_KEY_CONSECUTIVE_LOSSES, "0")
    logger.warning("Circuit breaker manually reset")


async def _trip_circuit(reason: str) -> None:
    if _state.circuit_open:
        return
    _state.circuit_open = True
    _state.circuit_reason = reason
    await db.set_state(STATE_KEY_CIRCUIT_OPEN, "true")
    logger.critical("CIRCUIT BREAKER TRIPPED: %s", reason)
    _state._notify("circuit_tripped", reason=reason)


def _calc_drawdown(current: float, peak: float) -> float:
    if peak <= 0:
        return 0.0
    return max(0.0, (peak - current) / peak)
