"""Polymarket CLOB API client wrapper with async support and error handling."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import aiohttp

from pulse import config

logger = logging.getLogger(__name__)

CLOB_HOST = config.POLYMARKET_HOST
GAMMA_HOST = "https://gamma-api.polymarket.com"


@dataclass
class Market:
    condition_id: str
    question_id: str
    title: str
    description: str
    end_date: str
    tokens: List[Dict]          # [{token_id, outcome}]
    active: bool
    liquidity: float
    volume: float
    yes_price: float = 0.0
    no_price: float = 0.0
    best_ask: float = 0.0
    best_bid: float = 0.0
    spread: float = 0.0
    extra: Dict = field(default_factory=dict)


@dataclass
class OrderBook:
    token_id: str
    bids: List[Dict]    # [{"price": float, "size": float}]
    asks: List[Dict]
    best_bid: float
    best_ask: float
    mid: float
    spread: float


@dataclass
class OrderResult:
    order_id: str
    status: str
    filled_size: float
    avg_price: float
    error: str = ""


# ── Client ─────────────────────────────────────────────────────────────────────

class PolymarketClient:
    """Thin async wrapper around the Polymarket CLOB REST API."""

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._timeout = aiohttp.ClientTimeout(total=20)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {"Content-Type": "application/json"}
            if config.POLY_API_KEY:
                headers["POLY-API-KEY"] = config.POLY_API_KEY
                headers["POLY-API-SECRET"] = config.POLY_API_SECRET
                headers["POLY-API-PASSPHRASE"] = config.POLY_API_PASSPHRASE
            self._session = aiohttp.ClientSession(
                timeout=self._timeout, headers=headers
            )
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Markets ────────────────────────────────────────────────────────────────

    async def get_markets(self, next_cursor: str = "") -> Dict:
        """Paginated market list from CLOB (used by econ scanner legacy path)."""
        session = await self._get_session()
        params: Dict[str, str] = {}
        if next_cursor:
            params["next_cursor"] = next_cursor
        async with session.get(f"{CLOB_HOST}/markets", params=params) as r:
            r.raise_for_status()
            return await r.json()

    async def get_all_weather_markets(self) -> List[Market]:
        """Return active weather markets from the shared Gamma cache."""
        all_markets = await get_all_markets_cached(self)
        weather = [m for m in all_markets if _is_weather_market_cached(m)]
        logger.info("Found %d weather markets", len(weather))
        return weather

    async def get_market(self, condition_id: str) -> Optional[Market]:
        session = await self._get_session()
        try:
            async with session.get(f"{CLOB_HOST}/markets/{condition_id}") as r:
                r.raise_for_status()
                return _parse_market(await r.json())
        except Exception as exc:
            logger.error("get_market %s: %s", condition_id, exc)
            return None

    # ── Order book ─────────────────────────────────────────────────────────────

    async def get_order_book(self, token_id: str) -> Optional[OrderBook]:
        session = await self._get_session()
        try:
            async with session.get(
                f"{CLOB_HOST}/book", params={"token_id": token_id}
            ) as r:
                r.raise_for_status()
                data = await r.json()
                return _parse_order_book(token_id, data)
        except Exception as exc:
            logger.error("get_order_book %s: %s", token_id, exc)
            return None

    async def get_price(self, token_id: str, side: str = "buy") -> Optional[float]:
        session = await self._get_session()
        try:
            async with session.get(
                f"{CLOB_HOST}/price",
                params={"token_id": token_id, "side": side}
            ) as r:
                r.raise_for_status()
                data = await r.json()
                return float(data.get("price", 0))
        except Exception as exc:
            logger.error("get_price %s: %s", token_id, exc)
            return None

    # ── Order placement ────────────────────────────────────────────────────────

    async def place_order(self, token_id: str, price: float,
                          size: float, side: str = "BUY") -> OrderResult:
        """
        Place a limit FOK order.  Returns OrderResult with status FILLED/FAILED.
        In DRY_RUN mode, simulates the order without hitting the API.
        """
        if config.DRY_RUN:
            logger.info("[DRY RUN] Would place %s %.2f @ %.3f (token %s)",
                        side, size, price, token_id[:12])
            return OrderResult(
                order_id=f"dry_{int(time.time())}",
                status="FILLED",
                filled_size=size,
                avg_price=price,
            )

        if not config.PRIVATE_KEY:
            return OrderResult("", "FAILED", 0, 0, "No private key configured")

        # Build signed order using py-clob-client
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import OrderArgs, OrderType, ApiCreds

            creds = ApiCreds(
                api_key=config.POLY_API_KEY,
                api_secret=config.POLY_API_SECRET,
                api_passphrase=config.POLY_API_PASSPHRASE,
            ) if config.POLY_API_KEY else None

            client = ClobClient(
                host=CLOB_HOST,
                chain_id=config.CHAIN_ID,
                key=config.PRIVATE_KEY,
                creds=creds,
            )

            order_args = OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=side,
            )
            signed = client.create_order(order_args)
            resp = client.post_order(signed, OrderType.FOK)

            order_id = resp.get("orderID", "")
            status = resp.get("status", "MATCHED")
            filled = float(resp.get("sizeFilled", size))
            avg_p = float(resp.get("price", price))

            return OrderResult(order_id=order_id, status="FILLED" if filled > 0 else "CANCELLED",
                               filled_size=filled, avg_price=avg_p)

        except ImportError:
            return OrderResult("", "FAILED", 0, 0,
                               "py-clob-client not installed — pip install py-clob-client")
        except Exception as exc:
            logger.error("Order placement error: %s", exc)
            return OrderResult("", "FAILED", 0, 0, str(exc))


# ── Parsing helpers ────────────────────────────────────────────────────────────

WEATHER_KEYWORDS = [
    "temperature", "fahrenheit", "celsius",
    "°f", "°c", "degrees f", "degrees c",
    "high temp", "low temp", "avg temp",
    "precipitation", "rainfall", "snowfall", "inches of rain", "inches of snow",
]


def _is_weather_market_cached(m: Market) -> bool:
    text = (m.title + " " + m.description).lower()
    return any(kw in text for kw in WEATHER_KEYWORDS)


def _is_weather_market(item: Dict) -> bool:
    title = (item.get("question", "") or item.get("title", "")).lower()
    desc  = (item.get("description", "") or "").lower()
    text = title + " " + desc
    return any(kw in text for kw in WEATHER_KEYWORDS)


def _parse_market(item: Dict) -> Market:
    tokens = item.get("tokens", []) or []
    yes_price = no_price = 0.0
    for tok in tokens:
        outcome = (tok.get("outcome") or "").upper()
        price = float(tok.get("price", 0) or 0)
        if outcome == "YES":
            yes_price = price
        elif outcome == "NO":
            no_price = price

    return Market(
        condition_id=item.get("condition_id", ""),
        question_id=item.get("question_id", ""),
        title=item.get("question", item.get("title", "")),
        description=item.get("description", ""),
        end_date=item.get("end_date_iso", item.get("endDateIso", "")),
        tokens=tokens,
        active=bool(item.get("active", True)),
        liquidity=float(item.get("liquidity", 0) or 0),
        volume=float(item.get("volume", 0) or 0),
        yes_price=yes_price,
        no_price=no_price,
    )


def _parse_gamma_market(item: Dict) -> Market:
    """Parse a market record from the Gamma API response."""
    tokens = item.get("tokens") or []
    # Gamma sometimes stores prices in outcomePrices list [yes_price, no_price]
    outcome_prices = item.get("outcomePrices") or []
    yes_price = no_price = 0.0
    for tok in tokens:
        outcome = (tok.get("outcome") or "").upper()
        price = float(tok.get("price", 0) or 0)
        if outcome == "YES":
            yes_price = price
        elif outcome == "NO":
            no_price = price
    if not yes_price and len(outcome_prices) >= 1:
        try:
            yes_price = float(outcome_prices[0])
        except (ValueError, TypeError):
            pass
    if not no_price and len(outcome_prices) >= 2:
        try:
            no_price = float(outcome_prices[1])
        except (ValueError, TypeError):
            pass

    return Market(
        condition_id=item.get("conditionId") or item.get("id", ""),
        question_id=item.get("questionId", ""),
        title=item.get("question") or item.get("title", ""),
        description=item.get("description", ""),
        end_date=item.get("endDate") or item.get("endDateIso", ""),
        tokens=tokens,
        active=bool(item.get("active", True)),
        liquidity=float(item.get("liquidity") or 0),
        volume=float(item.get("volume") or 0),
        yes_price=yes_price,
        no_price=no_price,
    )


def _parse_order_book(token_id: str, data: Dict) -> OrderBook:
    bids = sorted(
        [{"price": float(b["price"]), "size": float(b["size"])} for b in data.get("bids", [])],
        key=lambda x: -x["price"]
    )
    asks = sorted(
        [{"price": float(a["price"]), "size": float(a["size"])} for a in data.get("asks", [])],
        key=lambda x: x["price"]
    )
    best_bid = bids[0]["price"] if bids else 0.0
    best_ask = asks[0]["price"] if asks else 1.0
    mid = (best_bid + best_ask) / 2
    spread = best_ask - best_bid
    return OrderBook(token_id=token_id, bids=bids, asks=asks,
                     best_bid=best_bid, best_ask=best_ask, mid=mid, spread=spread)


# ── Module-level singleton ─────────────────────────────────────────────────────
_client: Optional[PolymarketClient] = None


def get_client() -> PolymarketClient:
    global _client
    if _client is None:
        _client = PolymarketClient()
    return _client


# ── Shared market cache — uses Gamma API for active-only discovery ─────────────
_market_cache: List[Market] = []
_cache_ts: float = 0.0
_CACHE_TTL = 270.0

_GAMMA_URL = "https://gamma-api.polymarket.com/markets"


async def get_all_markets_cached(client: PolymarketClient) -> List[Market]:
    global _market_cache, _cache_ts
    if _market_cache and time.time() - _cache_ts < _CACHE_TTL:
        return _market_cache

    markets: List[Market] = []
    offset = 0
    limit = 100
    pages = 0

    async with aiohttp.ClientSession() as session:
        while pages < 100:  # up to 10,000 markets
            params = {
                "active": "true",
                "closed": "false",
                "archived": "false",
                "limit": limit,
                "offset": offset,
            }
            try:
                async with session.get(_GAMMA_URL, params=params,
                                       timeout=aiohttp.ClientTimeout(total=20)) as r:
                    if r.status != 200:
                        logger.error("Gamma API HTTP %d", r.status)
                        break
                    data = await r.json()
            except Exception as exc:
                logger.error("Gamma API fetch error (page %d): %s", pages, exc)
                break

            if not data:
                break

            for item in data:
                markets.append(_parse_gamma_market(item))

            pages += 1
            if len(data) < limit:
                break
            offset += limit
            await asyncio.sleep(0.05)

    if markets:
        _market_cache = markets
        _cache_ts = time.time()
        logger.info("Market cache refreshed: %d active markets (%d pages)", len(markets), pages)
    return _market_cache


def filter_markets(markets: List[Market], keywords: List[str]) -> List[Market]:
    import re as _re
    patterns = []
    for kw in keywords:
        kl = kw.lower()
        # Short tokens (≤4 chars) need word boundaries to avoid false positives
        # e.g. "eth" in "whether", "sol" in "solution"
        if len(kl) <= 4:
            patterns.append(_re.compile(r'\b' + _re.escape(kl) + r'\b'))
        else:
            patterns.append(kl)

    def _matches(m: Market) -> bool:
        text = (m.title + " " + m.description).lower()
        for pat in patterns:
            if isinstance(pat, _re.Pattern):
                if pat.search(text):
                    return True
            else:
                if pat in text:
                    return True
        return False

    return [m for m in markets if _matches(m)]
