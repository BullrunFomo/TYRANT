"""Wallet helpers — keypair loading + SOL balance fetch.

Single source of truth for both the web layer (`/api/wallet-balance`) and the
launcher loop (pre-launch balance snapshot for PnL).
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import aiohttp

from pulse import config

logger = logging.getLogger(__name__)

LAMPORTS_PER_SOL = 1_000_000_000


def load_keypair():
    """Decode SOLANA_PRIVATE_KEY (base58 string OR JSON byte array). Returns
    a solders.Keypair, or None if no key set / decode fails.
    """
    if not config.SOLANA_PRIVATE_KEY:
        return None
    try:
        from solders.keypair import Keypair
        raw = config.SOLANA_PRIVATE_KEY.strip()
        if raw.startswith("["):
            return Keypair.from_bytes(bytes(json.loads(raw)))
        return Keypair.from_base58_string(raw)
    except Exception as exc:
        logger.warning("Wallet load failed: %s", exc)
        return None


async def get_sol_balance(pubkey: Optional[str] = None) -> Optional[float]:
    """Fetch SOL balance for `pubkey` (or the configured wallet's pubkey).
    Returns balance in SOL, or None on RPC / decode failure.
    """
    if pubkey is None:
        kp = load_keypair()
        if kp is None:
            return None
        pubkey = str(kp.pubkey())

    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getBalance",
        "params": [pubkey, {"commitment": "confirmed"}],
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config.SOLANA_RPC_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                lamports = (data.get("result") or {}).get("value", 0)
                return float(lamports) / LAMPORTS_PER_SOL
    except Exception as exc:
        logger.warning("Balance fetch failed for %s: %s", pubkey, exc)
        return None
