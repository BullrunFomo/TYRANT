"""
TYRANT — Main entry point.
Starts the meme-launch loop and the Textual dashboard concurrently.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from pulse import config
from pulse.market.meme_scanner import scan_and_launch

if TYPE_CHECKING:
    from pulse.dashboard.app import PulseApp

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("tyrant.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


# ── Launch loop ────────────────────────────────────────────────────────────────

async def launch_loop(app: "PulseApp") -> None:
    """Main scan-launch cycle integrated with the dashboard."""

    scan_count = 0

    while True:
        scan_count += 1
        app.set_scan_status(f"SCANNING #{scan_count}")
        app.log_msg(f"Scan #{scan_count} — scraping KnowYourMeme...", "SCAN")

        cycle_start = time.monotonic()

        try:
            launched = await scan_and_launch()

            n_ok = sum(1 for l in launched if l.status in ("LAUNCHED", "DRY_RUN"))
            n_fail = sum(1 for l in launched if l.status == "FAILED")

            if launched:
                app.log_msg(
                    f"Cycle #{scan_count}: {n_ok} launched, {n_fail} failed "
                    f"({len(launched)} total)", "OK"
                )
                for launch in launched:
                    if launch.status in ("LAUNCHED", "DRY_RUN"):
                        tag = "DRY" if launch.status == "DRY_RUN" else "LAUNCH"
                        app.add_exec_entry(
                            tag,
                            launch.source.upper(),
                            f"{launch.name[:28]} ({launch.ticker})"
                            + (f" tx={launch.tx_sig[:12]}" if launch.tx_sig and not launch.tx_sig.startswith("DRY") else ""),
                        )
                        app.record_source_activity(launch.source)
                        app.log_msg(
                            f"  ✓ {launch.name} | {launch.ticker} | "
                            f"mint={launch.mint_address[:8]}...", "OK"
                        )
                    else:
                        app.add_exec_entry("FAILED", launch.source.upper(), f"{launch.name[:28]}: {launch.error[:40]}")
                        app.log_msg(f"  ✗ {launch.name}: {launch.error}", "ERROR")
            else:
                app.log_msg("No new memes found this cycle", "INFO")

        except Exception as exc:
            logger.exception("Launch loop error: %s", exc)
            app.log_msg(f"Loop error: {exc}", "ERROR")

        elapsed = time.monotonic() - cycle_start
        app.set_scan_status(f"IDLE  (last: {elapsed:.1f}s)")
        app.log_msg(
            f"Cycle #{scan_count} done in {elapsed:.1f}s — "
            f"next scan in {config.SCAN_INTERVAL_SECONDS}s", "SCAN"
        )

        await asyncio.sleep(config.SCAN_INTERVAL_SECONDS)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    from pulse.dashboard.app import PulseApp

    app = PulseApp()
    app.register_trading_loop(launch_loop)

    logger.info("Starting TYRANT//BOT...")
    app.run()


if __name__ == "__main__":
    main()
