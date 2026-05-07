"""AI-generated launch tweet. Falls back to the template builder on any failure."""
from __future__ import annotations

import logging
import re
from typing import Optional

from pulse import config
from pulse.ai.openrouter import OpenRouterError, chat_completion
from pulse.ai.prompts import load_prompt

logger = logging.getLogger(__name__)

_TWEET_RE = re.compile(r"^[^\n]{20,240}$")


async def generate_tweet(
    name: str,
    ticker: str,
    description: str,
    title: str = "",
) -> Optional[str]:
    """Return AI tweet body (no ticker tag — caller appends it), or None on failure."""
    if not config.TWEET_AI_ENABLED or not config.OPENROUTER_API_KEY:
        return None

    try:
        prompt = load_prompt("tweet")
        system, user = prompt.render(
            name=name,
            ticker=ticker,
            description=(description or "")[:200],
            title=title or "",
        )
        model = config.OPENROUTER_MODEL_TWEET or prompt.model
        result = await chat_completion(
            model=model,
            system=system,
            user=user,
            temperature=prompt.temperature,
            max_tokens=prompt.max_tokens,
            response_format=prompt.response_format,
        )
    except OpenRouterError as e:
        logger.warning("Tweet AI failed (%s) — using template fallback", e)
        return None
    except Exception:
        logger.exception("Tweet AI unexpected error — using template fallback")
        return None

    if "_text" in result:
        logger.warning("Tweet AI: non-JSON response, fallback. raw=%r", result["_text"][:120])
        return None

    tweet = str(result.get("tweet") or "").strip()

    if not _TWEET_RE.match(tweet):
        logger.warning("Tweet AI: invalid output %r, fallback", tweet[:80])
        return None
    if "http://" in tweet or "https://" in tweet or "\n" in tweet:
        logger.warning("Tweet AI: contains URL/newline, fallback")
        return None

    return tweet
