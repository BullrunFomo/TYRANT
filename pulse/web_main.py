"""
TYRANT — Web dashboard entry point.
Runs FastAPI on localhost:8000 + the meme-launch loop in the same asyncio event loop.
"""
from __future__ import annotations

import asyncio
import logging
import time

import uvicorn

from pulse import config
from pulse.db import database as db
from pulse.market.meme_scanner import scan_for_new_memes
from pulse.web.server import app, emit_log, emit_exec, emit_stats, emit_pnl_history, register_startup

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("tyrant.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


# ── Launch loop ────────────────────────────────────────────────────────────────

async def launch_loop() -> None:
    await emit_log("TYRANT//BOT initializing...", "SYSTEM")
    await emit_log(f"Mode: {'DRY RUN' if config.DRY_RUN else 'LIVE'}", "SYSTEM")
    await emit_log(f"Scan interval: {config.SCAN_INTERVAL_SECONDS}s", "SYSTEM")
    await emit_log(f"Max launches/cycle: {config.MAX_LAUNCHES_PER_CYCLE}", "SYSTEM")

    scan_count = 0

    while True:
        scan_count += 1
        await emit_log(f"Scan #{scan_count} — scraping KnowYourMeme...", "SCAN")

        try:
            new_memes = await scan_for_new_memes()

            if new_memes:
                new_memes = new_memes[:config.MAX_LAUNCHES_PER_CYCLE]
                await emit_log(
                    f"Cycle #{scan_count}: {len(new_memes)} new meme(s) — auto-launching", "OK"
                )
                from pulse.launchers.pumpfun import make_ticker, launch_token
                from pulse.db.database import Launch
                import time as _time
                for entry in new_memes:
                    ticker = make_ticker(entry.title)
                    await emit_log(f"  → Launching: {entry.title} ({ticker})…", "INFO")
                    await emit_exec("LAUNCH", entry.source.upper(), f"{entry.title[:28]} ({ticker})")
                    result = await launch_token(
                        name=entry.title,
                        ticker=ticker,
                        image_url=entry.image_url or "",
                        description=entry.description or f"KYM {entry.source} meme. Source: {entry.url}",
                    )
                    if config.DRY_RUN:
                        status = "DRY_RUN"
                    elif config.SIMULATE:
                        status = "SIMULATED" if result.success else "FAILED"
                    else:
                        status = "LAUNCHED" if result.success else "FAILED"
                    record = Launch(
                        id=None, timestamp=_time.time(),
                        name=entry.title, ticker=ticker,
                        source=entry.source, meme_url=entry.url,
                        image_url=entry.image_url or "", description=entry.description or "",
                        tx_sig=result.tx_sig, mint_address=result.mint_address,
                        status=status, sol_spent=result.sol_spent, error=result.error,
                    )
                    await db.insert_launch(record)
                    await db.snapshot_launch_count()
                    if result.success:
                        tag = "[DRY] " if config.DRY_RUN else ("[SIM] " if config.SIMULATE else "")
                        await emit_log(
                            f"  ✓ {tag}Launched {entry.title} ({ticker})"
                            f" mint={result.mint_address[:8]} tx={result.tx_sig[:16]}", "OK"
                        )
                    else:
                        await emit_log(f"  ✗ Launch failed: {result.error}", "ERROR")
            else:
                await emit_log("No new memes found this cycle", "INFO")

        except Exception as exc:
            logger.exception("Launch loop error: %s", exc)
            await emit_log(f"Loop error: {exc}", "ERROR")

        await _push_stats(scan_count)
        await emit_log(
            f"Cycle #{scan_count} complete — next scan in {config.SCAN_INTERVAL_SECONDS}s", "SCAN"
        )

        elapsed = 0
        while elapsed < config.SCAN_INTERVAL_SECONDS:
            await asyncio.sleep(1)
            elapsed += 1


async def _push_stats(scan_count: int = 0):
    launches = await db.get_launches(200)
    total = await db.get_total_launches()
    today = await db.get_today_launches()
    sol_spent = await db.get_total_sol_spent()
    history = await db.get_launch_history(200)

    n_ok = sum(1 for l in launches if l.status in ("LAUNCHED", "SIMULATED", "DRY_RUN"))
    n_fail = sum(1 for l in launches if l.status == "FAILED")
    n_real_ok = sum(1 for l in launches if l.status in ("LAUNCHED", "SIMULATED"))
    n_real_attempts = n_real_ok + n_fail

    await emit_stats({
        "total_launches": total,
        "today_launches": len(today),
        "sol_spent": sol_spent,
        "n_ok": n_ok,
        "n_fail": n_fail,
        "n_real_attempts": n_real_attempts,
        "success_rate": (n_real_ok / n_real_attempts) if n_real_attempts else 0.0,
        "dry_run": config.DRY_RUN,
        "scan_count": scan_count,
    })
    await emit_pnl_history({
        "timestamps": [h.timestamp for h in history],
        "values": [float(h.count) for h in history],
    })


@register_startup
async def on_startup():
    asyncio.create_task(launch_loop())


def main():
    import os
    port = int(os.environ.get("PORT", 8000))
    logger.info("Starting TYRANT//BOT web dashboard on http://0.0.0.0:%d", port)
    uvicorn.run(
        "pulse.web_main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
