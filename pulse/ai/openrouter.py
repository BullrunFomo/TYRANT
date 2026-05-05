"""Async OpenRouter chat-completion client. One function: `chat_completion()`.

Pattern matches the rest of the codebase — fresh `aiohttp.ClientSession` per call,
explicit timeout, raises `OpenRouterError` on any non-200 / network / parse issue.
Callers handle the exception and fall back to non-AI behavior.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import aiohttp

from pulse import config

logger = logging.getLogger(__name__)


class OpenRouterError(Exception):
    """Any failure during an OpenRouter call. Callers should catch and fall back."""


async def chat_completion(
    *,
    model: str,
    system: str,
    user: str,
    image_url: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 500,
    response_format: Optional[dict] = None,
    timeout_s: int = 30,
) -> dict:
    """One chat completion call.

    Returns the parsed JSON object if the model returned valid JSON.
    Returns `{"_text": raw}` if it returned non-JSON (caller decides what to do).
    Raises OpenRouterError on HTTP / network / shape errors.
    """
    if not config.OPENROUTER_API_KEY:
        raise OpenRouterError("OPENROUTER_API_KEY is empty")
    if not model:
        raise OpenRouterError("model is empty")

    user_content: Any = user
    if image_url:
        user_content = [
            {"type": "text", "text": user},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]

    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        body["response_format"] = response_format

    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": config.OPENROUTER_REFERER,
        "X-Title": config.OPENROUTER_TITLE,
    }

    url = f"{config.OPENROUTER_BASE_URL}/chat/completions"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout_s),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise OpenRouterError(f"HTTP {resp.status}: {text[:400]}")
                data = await resp.json()
    except aiohttp.ClientError as e:
        raise OpenRouterError(f"network: {e}") from e
    except OpenRouterError:
        raise
    except Exception as e:
        raise OpenRouterError(f"unexpected: {e}") from e

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise OpenRouterError(f"bad response shape: {str(data)[:300]}") from e

    return _parse_json_loose(content)


def _parse_json_loose(text: str) -> dict:
    """Try to parse JSON. Strip ``` fences if present. Return {'_text': raw} on failure."""
    s = text.strip()
    if s.startswith("```"):
        # remove leading fence (and optional `json` tag) + trailing fence
        first_nl = s.find("\n")
        if first_nl != -1:
            s = s[first_nl + 1 :]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3].rstrip()
    try:
        obj = json.loads(s)
        if isinstance(obj, dict):
            return obj
        return {"_text": text}
    except json.JSONDecodeError:
        return {"_text": text}
