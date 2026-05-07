"""Twitter/X integration via twikit with cookie-based auth (no login flow)."""
from __future__ import annotations

import json
import logging
import os

from pulse import config
from pulse.ai.tweet import generate_tweet

logger = logging.getLogger(__name__)

_COOKIE_FILE = "twitter_cookies.json"
_client = None


async def _get_client():
    global _client
    if _client is not None:
        return _client

    try:
        from twikit import Client
    except ImportError:
        logger.error("twikit not installed — run: pip install twikit")
        return None

    if not os.path.exists(_COOKIE_FILE):
        logger.warning(
            "Twitter: %s not found — export cookies from x.com via Cookie-Editor "
            "browser extension and save as %s in the project root",
            _COOKIE_FILE, _COOKIE_FILE,
        )
        return None

    try:
        with open(_COOKIE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)

        # Cookie-Editor exports a list of dicts; twikit wants {name: value}
        if isinstance(raw, list):
            cookies = {c["name"]: c["value"] for c in raw if "name" in c and "value" in c}
        else:
            cookies = raw

        client = Client(language="en-US")
        client.set_cookies(cookies)
        _client = client
        logger.info("Twitter: session loaded from %s", _COOKIE_FILE)
        return _client
    except Exception as exc:
        logger.error("Twitter: failed to load cookies: %s", exc)
        return None


def _build_tweet_text(name: str, ticker: str, description: str) -> str:
    ticker_tag = f"${ticker}"
    headline = name[:80]
    body = description.strip()

    # Trim body so the whole tweet fits in 280 chars
    # Budget: headline + "\n\n" + body + "\n\n" + ticker_tag
    max_body = 280 - len(headline) - len(ticker_tag) - 4
    if body and body.lower() not in headline.lower() and max_body > 20:
        body = body[:max_body].rstrip()
        if len(description.strip()) > max_body:
            body = body.rstrip(".,;: ") + "."
        parts = [headline, body, ticker_tag]
    else:
        parts = [headline, ticker_tag]

    return "\n\n".join(parts)[:280]


async def post_tweet(
    name: str, ticker: str, description: str, title: str = ""
) -> str | None:
    """
    Post a tweet and return its URL, or None on failure (never blocks the launch).
    Requires twitter_cookies.json in the project root — export from x.com via the
    Cookie-Editor browser extension while logged in as the bot account.
    """
    client = await _get_client()
    if client is None:
        return None

    ai_body = await generate_tweet(name, ticker, description, title)
    if ai_body:
        ticker_tag = f"${ticker}"
        text = f"{ai_body}\n\n{ticker_tag}"[:280]
    else:
        text = _build_tweet_text(name, ticker, description)

    try:
        tweet_id = await _post_raw(client, text)
    except Exception as exc:
        logger.error("Twitter post error: %s", exc)
        global _client
        _client = None
        return None

    if not tweet_id:
        logger.error("Twitter: could not extract tweet ID from response")
        return None

    username = config.TWITTER_USERNAME.lstrip("@")
    tweet_url = f"https://x.com/{username}/status/{tweet_id}"
    logger.info("Tweet posted: %s", tweet_url)
    return tweet_url


async def _post_raw(client, text: str) -> str | None:
    """Post via twikit's GQL layer (correct headers/transaction ID) and parse ID ourselves."""
    result = await client.gql.create_tweet(
        is_note_tweet=False,
        text=text,
        media_entities=[],
        poll_uri=None,
        reply_to=None,
        attachment_url=None,
        community_id=None,
        share_with_followers=None,
        richtext_options=None,
        edit_tweet_id=None,
        limit_mode=None,
    )
    # result is (json_dict, Response)
    data = result[0] if isinstance(result, tuple) else result
    return (
        data.get("data", {})
        .get("create_tweet", {})
        .get("tweet_results", {})
        .get("result", {})
        .get("rest_id")
    )
