"""Vision-based launchability gate. Built but disabled by default — KYM is curated.

Enable via `QUALITY_GATE_ENABLED=true` once we add non-curated sources (X, Reddit).
When disabled OR on any error, returns a permissive pass so the launcher proceeds.
"""
from __future__ import annotations

import logging
from typing import Optional

from pulse import config
from pulse.ai.openrouter import OpenRouterError, chat_completion
from pulse.ai.prompts import load_prompt

logger = logging.getLogger(__name__)


async def score_launchability(
    title: str,
    description: str = "",
    source: str = "",
    image_url: Optional[str] = None,
) -> dict:
    """Returns {'pass': bool, 'score': 0..100, 'reasons': list[str]}.

    Always permissive on disable / failure — never block the launcher on AI issues.
    """
    if not config.QUALITY_GATE_ENABLED or not config.OPENROUTER_API_KEY:
        return {"pass": True, "score": 0, "reasons": ["gate disabled"]}

    try:
        prompt = load_prompt("quality_gate")
        system, user = prompt.render(
            title=title or "",
            description=(description or "")[:400],
            source=source or "",
        )
        model = config.OPENROUTER_MODEL_QUALITY or prompt.model
        result = await chat_completion(
            model=model,
            system=system,
            user=user,
            image_url=image_url or None,
            temperature=prompt.temperature,
            max_tokens=prompt.max_tokens,
            response_format=prompt.response_format,
        )
    except OpenRouterError as e:
        logger.warning("Quality gate failed (%s) — allowing launch", e)
        return {"pass": True, "score": 0, "reasons": [f"gate error: {e}"]}
    except Exception:
        logger.exception("Quality gate unexpected error — allowing launch")
        return {"pass": True, "score": 0, "reasons": ["gate exception"]}

    if "_text" in result:
        logger.warning("Quality gate: non-JSON response, allowing launch")
        return {"pass": True, "score": 0, "reasons": ["gate non-json"]}

    try:
        score = int(result.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    passed = bool(result.get("pass", score >= 60))
    reasons_raw = result.get("reasons") or []
    reasons = [str(r) for r in (reasons_raw if isinstance(reasons_raw, list) else [reasons_raw])][:5]
    return {"pass": passed, "score": score, "reasons": reasons}
