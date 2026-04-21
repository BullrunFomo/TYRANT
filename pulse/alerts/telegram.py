"""Telegram alert system — only fires on executed trades and daily summaries."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from pulse import config
from pulse.db.database import Trade

logger = logging.getLogger(__name__)

_bot = None


def _get_bot():
    global _bot
    if _bot is None and config.TELEGRAM_BOT_TOKEN:
        try:
            from telegram import Bot
            _bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
        except ImportError:
            logger.warning("python-telegram-bot not installed")
    return _bot


async def send_message(text: str) -> None:
    """Send a plain text message. Silently no-ops if not configured."""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    bot = _get_bot()
    if not bot:
        return
    try:
        await bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=text,
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.error("Telegram send_message error: %s", exc)


async def notify_trade_executed(trade: Trade) -> None:
    """Alert on a successfully filled trade."""
    sign = "🟢" if trade.pnl >= 0 else "🔴"
    pnl_str = f"+${trade.pnl:.2f}" if trade.pnl >= 0 else f"-${abs(trade.pnl):.2f}"
    mode = "DRY RUN" if config.DRY_RUN else "LIVE"

    msg = (
        f"<b>{sign} PULSE TRADE [{mode}]</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"🏙  <b>City:</b>     {trade.city}\n"
        f"📋 <b>Market:</b>  {trade.market_title[:60]}\n"
        f"📌 <b>Side:</b>     {trade.outcome} @ {trade.price:.3f}\n"
        f"💵 <b>Size:</b>     ${trade.size_usd:.2f}\n"
        f"📊 <b>Edge:</b>     {trade.edge:+.1%}\n"
        f"🔑 <b>Order:</b>   <code>{trade.order_id[:16]}</code>\n"
        f"💰 <b>P&L:</b>      {pnl_str}"
    )
    await send_message(msg)


async def notify_daily_summary(
    total_pnl: float,
    daily_pnl: float,
    n_trades: int,
    win_rate: float,
    equity: float,
) -> None:
    """Daily end-of-day summary."""
    sign = "🟢" if daily_pnl >= 0 else "🔴"
    pnl_str = f"+${daily_pnl:.2f}" if daily_pnl >= 0 else f"-${abs(daily_pnl):.2f}"
    total_str = f"+${total_pnl:.2f}" if total_pnl >= 0 else f"-${abs(total_pnl):.2f}"

    msg = (
        f"<b>{sign} PULSE DAILY SUMMARY</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📅 <b>Date:</b>       {time.strftime('%Y-%m-%d')}\n"
        f"📈 <b>Today P&L:</b>  {pnl_str}\n"
        f"💰 <b>Total P&L:</b>  {total_str}\n"
        f"🏦 <b>Equity:</b>     ${equity:.2f}\n"
        f"🎯 <b>Trades:</b>     {n_trades}\n"
        f"✅ <b>Win rate:</b>   {win_rate:.1%}"
    )
    await send_message(msg)


async def notify_circuit_breaker(reason: str) -> None:
    msg = (
        f"<b>⚠️ CIRCUIT BREAKER TRIPPED</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"Reason: {reason}\n"
        f"Trading halted. Investigate before resuming."
    )
    await send_message(msg)
