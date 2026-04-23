"""Meme scanner — scrapes KYM and returns unseen memes."""
from __future__ import annotations

import logging
from typing import List

import aiohttp

from pulse.data.knowyourmeme import scrape_all_categories, fetch_og_image, MemeEntry
from pulse.db import database as db

logger = logging.getLogger(__name__)


async def scan_for_new_memes() -> List[MemeEntry]:
    """
    Scrape all KYM categories and return unseen memes, marking them seen immediately.
    Backfills missing image_url via og:image so the caller always has one.
    The caller (web_main) drives the pump.fun launch loop.
    """
    async with aiohttp.ClientSession() as session:
        entries = await scrape_all_categories(session)

        new_entries: List[MemeEntry] = []
        for entry in entries:
            if await db.is_meme_seen(entry.url):
                continue
            await db.mark_meme_seen(entry.url)
            if not entry.image_url:
                entry.image_url = await fetch_og_image(session, entry.url) or ""
            new_entries.append(entry)

    logger.info("KYM scraped %d total, %d new", len(entries), len(new_entries))
    return new_entries
