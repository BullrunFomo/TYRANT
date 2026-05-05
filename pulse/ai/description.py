"""Punchy on-chain description rewriter.

Returns the AI-written description on success, or `None` on any failure
(caller is expected to fall back to the existing template).
"""
from __future__ import annotations

import logging
from typing import Optional

from pulse import config
from pulse.ai.openrouter import OpenRouterError, chat_completion
from pulse.ai.prompts import load_prompt

logger = logging.getLogger(__name__)


async def generate_description(
    name: str,
    ticker: str,
    title: str,
    kym_description: str = "",
) -> Optional[str]:
    if not config.DESCRIPTION_ENABLED or not config.OPENROUTER_API_KEY:
        return None

    try:
        prompt = load_prompt("description")
        system, user = prompt.render(
            name=name,
            ticker=ticker,
            title=title or "",
            kym_description=(kym_description or "")[:400],
        )
        model = config.OPENROUTER_MODEL_DESCRIPTION or prompt.model
        result = await chat_completion(
            model=model,
            system=system,
            user=user,
            temperature=prompt.temperature,
            max_tokens=prompt.max_tokens,
            response_format=prompt.response_format,
        )
    except OpenRouterError as e:
        logger.warning("Description AI failed (%s) — using template fallback", e)
        return None
    except Exception:
        logger.exception("Description AI unexpected error — using template fallback")
        return None

    if "_text" in result:
        logger.warning("Description: non-JSON response, fallback. raw=%r", result["_text"][:120])
        return None

    desc = str(result.get("description") or "").strip()
    if not (10 <= len(desc) <= 220):
        logger.warning("Description: bad length %d, fallback", len(desc))
        return None
    if "http://" in desc or "https://" in desc or "\n" in desc:
        logger.warning("Description: contains URL/newline, fallback")
        return None
    return desc
