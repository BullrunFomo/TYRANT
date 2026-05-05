"""Name + ticker + twitter_query rewriter.

Falls back to the algorithmic name (raw KYM title) and ticker (`make_ticker`-equivalent)
on any failure — disabled flag, missing key, network error, invalid output.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from pulse import config
from pulse.ai.openrouter import OpenRouterError, chat_completion
from pulse.ai.prompts import load_prompt

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[A-Za-z0-9 .,!&\-]{1,32}$")
_TICKER_RE = re.compile(r"^[A-Z0-9]{3,6}$")
_QUERY_RE = re.compile(r"^[^\n#]{1,60}$")


def algorithmic_ticker(name: str) -> str:
    """Algorithmic fallback. Delegates to the canonical make_ticker so the
    fallback path produces the exact same output that the bot used pre-AI.
    """
    from pulse.launchers.pumpfun import make_ticker
    return make_ticker(name)


async def generate_name_and_ticker(
    title: str,
    description: str = "",
    source: str = "",
) -> tuple[str, str, Optional[str]]:
    """Returns (name, ticker, twitter_query). On failure: (title[:32], algorithmic_ticker, None)."""
    fallback = (title[:32], algorithmic_ticker(title), None)

    if not config.NAMING_ENABLED or not config.OPENROUTER_API_KEY:
        return fallback

    try:
        prompt = load_prompt("naming")
        system, user = prompt.render(
            title=title or "",
            source=source or "",
            description=(description or "")[:600],
        )
        model = config.OPENROUTER_MODEL_NAMING or prompt.model
        result = await chat_completion(
            model=model,
            system=system,
            user=user,
            temperature=prompt.temperature,
            max_tokens=prompt.max_tokens,
            response_format=prompt.response_format,
        )
    except OpenRouterError as e:
        logger.warning("Naming AI failed (%s) — using algorithmic fallback", e)
        return fallback
    except Exception:
        logger.exception("Naming AI unexpected error — using algorithmic fallback")
        return fallback

    if "_text" in result:
        logger.warning("Naming: non-JSON response, fallback. raw=%r", result["_text"][:120])
        return fallback

    name = str(result.get("name") or "").strip()
    ticker = str(result.get("ticker") or "").strip().upper()
    twitter_query: Optional[str] = str(result.get("twitter_query") or "").strip() or None

    if not _NAME_RE.match(name):
        logger.warning("Naming: invalid name %r, fallback", name)
        return fallback
    if not _TICKER_RE.match(ticker):
        logger.warning("Naming: invalid ticker %r, fallback", ticker)
        return fallback
    if twitter_query and not _QUERY_RE.match(twitter_query):
        twitter_query = None

    return name, ticker, twitter_query
