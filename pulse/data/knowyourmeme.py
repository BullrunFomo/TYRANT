"""KnowYourMeme scraper — uses RSS feeds for clean, structured meme data."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional
from xml.etree import ElementTree as ET

import aiohttp
from bs4 import BeautifulSoup

from pulse import config

logger = logging.getLogger(__name__)

KYM_BASE = "https://knowyourmeme.com"

RSS_URLS = {
    "confirmed":  f"{KYM_BASE}/memes/confirmed.rss",
    "submission": f"{KYM_BASE}/memes/submissions.rss",
    "newsworthy": f"{KYM_BASE}/memes/newsworthy.rss",
    "deadpool":   f"{KYM_BASE}/memes/deadpool.rss",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, text/xml, */*",
}

# Regex to pull img src from description HTML
_IMG_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)


@dataclass
class MemeEntry:
    title: str
    url: str              # canonical KYM URL, used for dedup
    image_url: str        # thumbnail from RSS description
    source: str           # confirmed / submission / newsworthy / deadpool
    description: str = ""


def _extract_image_from_description(desc_html: str) -> str:
    """Pull first <img src> from RSS description HTML snippet."""
    m = _IMG_RE.search(desc_html)
    if m:
        src = m.group(1)
        if src.startswith("//"):
            src = "https:" + src
        return src
    return ""


def _extract_text_from_description(desc_html: str) -> str:
    """Strip HTML tags from description for a plain-text summary."""
    try:
        soup = BeautifulSoup(desc_html, "lxml")
        return soup.get_text(separator=" ", strip=True)[:400]
    except Exception:
        return re.sub(r"<[^>]+>", " ", desc_html)[:400].strip()


async def scrape_category(session: aiohttp.ClientSession, category: str) -> List[MemeEntry]:
    """Fetch one KYM RSS feed and parse entries."""
    url = RSS_URLS.get(category)
    if not url:
        logger.warning("Unknown KYM category: %s", category)
        return []

    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20)) as resp:
            if resp.status != 200:
                logger.warning("KYM RSS [%s] returned %s", category, resp.status)
                return []
            xml_text = await resp.text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.error("KYM RSS fetch error for %s: %s", category, exc)
        return []

    entries: List[MemeEntry] = []

    try:
        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return []

        for item in channel.findall("item"):
            link_el = item.find("link")
            title_el = item.find("title")
            desc_el = item.find("description")

            if link_el is None or title_el is None:
                continue

            link_url = (link_el.text or "").strip()
            title = (title_el.text or "").strip()
            if not link_url or not title:
                continue

            desc_html = (desc_el.text or "") if desc_el is not None else ""
            image_url = _extract_image_from_description(desc_html)
            description = _extract_text_from_description(desc_html)

            entries.append(MemeEntry(
                title=title,
                url=link_url,
                image_url=image_url,
                source=category,
                description=description,
            ))

            if len(entries) >= config.KYM_MAX_ENTRIES_PER_CATEGORY:
                break

    except ET.ParseError as exc:
        logger.error("KYM RSS parse error for %s: %s", category, exc)

    logger.info("KYM [%s] fetched %d entries", category, len(entries))
    return entries


async def fetch_og_image(session: aiohttp.ClientSession, meme_url: str) -> str:
    """Fetch og:image from a meme detail page as fallback."""
    try:
        async with session.get(meme_url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return ""
            html = await resp.text()
        soup = BeautifulSoup(html, "html.parser")
        for attr in ("og:image", "twitter:image"):
            tag = soup.find("meta", property=attr) or soup.find("meta", attrs={"name": attr})
            if tag:
                return tag.get("content", "")
    except Exception as exc:
        logger.debug("og:image fetch error for %s: %s", meme_url, exc)
    return ""


async def scrape_all_categories(session: aiohttp.ClientSession) -> List[MemeEntry]:
    """Fetch all four KYM RSS feeds and return combined results."""
    results: List[MemeEntry] = []
    for category in config.KYM_CATEGORIES:
        entries = await scrape_category(session, category)
        results.extend(entries)
    return results
