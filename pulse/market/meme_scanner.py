"""Meme scanner — scrapes KYM, deduplicates, and fires pump.fun launches."""
from __future__ import annotations

import logging
import time
from typing import List

import aiohttp

from pulse import config
from pulse.data.knowyourmeme import scrape_all_categories, fetch_og_image, MemeEntry
from pulse.db import database as db
from pulse.launchers.pumpfun import launch_token, make_ticker, LaunchResult
from pulse.db.database import Launch

logger = logging.getLogger(__name__)


async def scan_for_new_memes() -> List[MemeEntry]:
    """
    Scrape all KYM categories and return unseen memes, marking them seen immediately.
    Used by the web mode (connect-wallet flow) — no launching happens here.
    """
    async with aiohttp.ClientSession() as session:
        entries = await scrape_all_categories(session)

    new_entries: List[MemeEntry] = []
    for entry in entries:
        if not await db.is_meme_seen(entry.url):
            await db.mark_meme_seen(entry.url)
            new_entries.append(entry)

    logger.info("KYM scraped %d total, %d new", len(entries), len(new_entries))
    return new_entries


async def scan_and_launch() -> List[Launch]:
    """
    Full pipeline:
    1. Scrape all KYM categories
    2. Filter out already-seen memes
    3. Launch a pump.fun token for each new meme (up to MAX_LAUNCHES_PER_CYCLE)
    4. Persist results to DB
    Returns list of Launch records (both successes and failures).
    """
    launched: List[Launch] = []

    async with aiohttp.ClientSession() as session:
        # 1. Scrape KYM
        entries = await scrape_all_categories(session)
        logger.info("KYM scraped %d total entries across all categories", len(entries))

        # 2. Filter seen
        new_entries: List[MemeEntry] = []
        for entry in entries:
            if not await db.is_meme_seen(entry.url):
                new_entries.append(entry)

        logger.info("%d new (unseen) memes found", len(new_entries))

        if not new_entries:
            return []

        # 3. Launch up to MAX_LAUNCHES_PER_CYCLE
        to_launch = new_entries[:config.MAX_LAUNCHES_PER_CYCLE]

        for entry in to_launch:
            # Mark seen immediately to avoid relaunching on retry
            await db.mark_meme_seen(entry.url)

            # Resolve image URL if missing
            image_url = entry.image_url
            if not image_url:
                image_url = await fetch_og_image(session, entry.url)

            ticker = make_ticker(entry.title)
            description = (
                f"KYM {entry.source.upper()} meme. "
                f"Auto-launched by TYRANT//BOT. Source: {entry.url}"
            )

            logger.info(
                "Launching [%s] %s (%s) from %s",
                entry.source, entry.title, ticker, entry.url,
            )

            result: LaunchResult = await launch_token(
                name=entry.title,
                ticker=ticker,
                image_url=image_url,
                description=description,
            )

            status = "LAUNCHED" if result.success else "FAILED"
            if config.DRY_RUN and result.success:
                status = "DRY_RUN"

            record = Launch(
                id=None,
                timestamp=time.time(),
                name=entry.title,
                ticker=ticker,
                source=entry.source,
                meme_url=entry.url,
                image_url=image_url,
                description=description,
                tx_sig=result.tx_sig,
                mint_address=result.mint_address,
                status=status,
                sol_spent=result.sol_spent,
                error=result.error,
            )

            record.id = await db.insert_launch(record)
            launched.append(record)

            if result.success:
                logger.info(
                    "  ✓ %s (%s) launched — tx=%s mint=%s",
                    entry.title, ticker, result.tx_sig[:16], result.mint_address[:8],
                )
            else:
                logger.error("  ✗ %s failed: %s", entry.title, result.error)

    # Snapshot cumulative count for chart
    await db.snapshot_launch_count()

    return launched
