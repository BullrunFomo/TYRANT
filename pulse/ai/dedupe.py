"""Semantic deduplication against the past-N-days launch history.

The launcher calls `is_duplicate(entry)` right before firing a launch. The
check uses the LLM to decide if the candidate is essentially the same meme
as anything in `launched_memes` within the dedup window (default 7 days).

After the window passes, the same meme can be relaunched.

Permissive on any AI failure — never block the launcher.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from pulse import config
from pulse.ai.openrouter import OpenRouterError, chat_completion
from pulse.ai.prompts import load_prompt
from pulse.data.knowyourmeme import MemeEntry
from pulse.db import database as db

logger = logging.getLogger(__name__)


async def is_duplicate(entry: MemeEntry) -> tuple[bool, str]:
    """Returns (duplicate, reason). On any failure → (False, '...') so the launch proceeds."""
    if not config.DEDUPE_ENABLED or not config.OPENROUTER_API_KEY:
        return False, "dedupe disabled"

    recent = await db.get_recent_launches(within_seconds=config.DEDUPE_WINDOW_SECONDS, limit=80)
    if not recent:
        return False, "no recent launches"

    # Cheap exact-URL check first — no LLM call needed when it's an obvious match.
    for r in recent:
        if r.meme_url and r.meme_url == entry.url:
            return True, f"exact URL match: {r.name}"

    try:
        prompt = load_prompt("dedupe")
        recent_lines = []
        now = time.time()
        for r in recent:
            age_h = max(1, int((now - r.timestamp) / 3600))
            blurb = (r.description or "")[:80].replace("\n", " ").strip()
            line = f"- \"{r.name}\" ({r.ticker}) launched {age_h}h ago"
            if blurb:
                line += f" — {blurb}"
            recent_lines.append(line)
        recent_text = "\n".join(recent_lines)

        system, user = prompt.render(
            title=entry.title or "",
            description=(entry.description or "")[:300],
            recent=recent_text,
        )
        model = config.OPENROUTER_MODEL_DEDUPE or prompt.model
        result = await chat_completion(
            model=model,
            system=system,
            user=user,
            temperature=prompt.temperature,
            max_tokens=prompt.max_tokens,
            response_format=prompt.response_format,
        )
    except OpenRouterError as e:
        logger.warning("Dedupe AI failed (%s) — allowing launch", e)
        return False, f"dedupe error: {e}"
    except Exception:
        logger.exception("Dedupe unexpected error — allowing launch")
        return False, "dedupe exception"

    if "_text" in result:
        logger.warning("Dedupe: non-JSON response, allowing launch")
        return False, "non-JSON response"

    is_dup = bool(result.get("duplicate", False))
    matched = str(result.get("matched") or "").strip()
    reason = str(result.get("reason") or "").strip()[:120]
    if is_dup:
        return True, f"matched={matched!r} :: {reason}"
    return False, reason or "ok"
