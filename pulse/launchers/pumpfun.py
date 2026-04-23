"""pump.fun token launcher — uploads metadata to IPFS and creates a Solana token."""
from __future__ import annotations

import base64
import logging
import re
from dataclasses import dataclass
from typing import Optional

import aiohttp

from pulse import config

logger = logging.getLogger(__name__)

PUMPFUN_IPFS_URL = "https://pump.fun/api/ipfs"
PUMPFUN_TRADE_URL = "https://pump.fun/api/trade-local"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


@dataclass
class LaunchResult:
    success: bool
    tx_sig: str = ""
    mint_address: str = ""
    metadata_uri: str = ""
    error: str = ""
    sol_spent: float = 0.0


def make_ticker(name: str) -> str:
    """Generate a pump.fun-compatible ticker symbol from a meme name."""
    clean = re.sub(r"[^a-zA-Z0-9\s]", "", name).strip()
    words = clean.split()
    if not words:
        return "MEME"

    if len(words) == 1:
        return words[0][:6].upper()

    # Multi-word: take initials, then pad with extra chars if too short
    initials = "".join(w[0] for w in words if w)[:6].upper()
    if len(initials) < 3 and len(words) >= 2:
        return (words[0][:3] + words[1][:3])[:6].upper()
    return initials


async def _download_image(session: aiohttp.ClientSession, image_url: str) -> Optional[bytes]:
    """Download image bytes from URL."""
    if not image_url:
        return None
    try:
        async with session.get(
            image_url,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status == 200:
                return await resp.read()
            logger.warning("Image download failed: %s -> %s", image_url, resp.status)
    except Exception as exc:
        logger.error("Image download error: %s", exc)
    return None


async def _upload_metadata(
    session: aiohttp.ClientSession,
    name: str,
    ticker: str,
    description: str,
    image_data: Optional[bytes],
    image_url: str,
) -> Optional[str]:
    """Upload token metadata + image to pump.fun IPFS. Returns metadataUri."""
    form = aiohttp.FormData()
    form.add_field("name", name[:32])
    form.add_field("symbol", ticker[:10])
    form.add_field("description", description[:500] or f"Auto-launched meme coin: {name}")
    form.add_field("showName", "true")

    if image_data:
        # Detect content type from bytes magic
        content_type = "image/jpeg"
        if image_data[:4] == b"\x89PNG":
            content_type = "image/png"
        elif image_data[:3] == b"GIF":
            content_type = "image/gif"
        elif image_data[:4] == b"RIFF":
            content_type = "image/webp"

        form.add_field(
            "file",
            image_data,
            filename="meme.jpg",
            content_type=content_type,
        )
    elif image_url:
        # Pass image URL as a text field as fallback
        form.add_field("imageUrl", image_url)

    try:
        async with session.post(
            PUMPFUN_IPFS_URL,
            data=form,
            headers=HEADERS,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error("IPFS upload failed %s: %s", resp.status, body[:200])
                return None
            data = await resp.json()
            uri = data.get("metadataUri", "")
            if not uri:
                logger.error("IPFS response missing metadataUri: %s", data)
                return None
            logger.info("Metadata uploaded: %s", uri)
            return uri
    except Exception as exc:
        logger.error("IPFS upload error: %s", exc)
        return None


async def _build_create_tx(
    session: aiohttp.ClientSession,
    wallet_pubkey: str,
    mint_pubkey: str,
    name: str,
    ticker: str,
    metadata_uri: str,
) -> Optional[bytes]:
    """Ask pump.fun to build the create transaction. Returns raw bytes."""
    payload = {
        "publicKey": wallet_pubkey,
        "action": "create",
        "tokenMetadata": {
            "name": name[:32],
            "symbol": ticker[:10],
            "uri": metadata_uri,
        },
        "mint": mint_pubkey,
        "denominatedInSol": "true",
        "amount": config.PUMPFUN_INITIAL_BUY_SOL,
        "slippage": config.PUMPFUN_SLIPPAGE,
        "priorityFee": config.PUMPFUN_PRIORITY_FEE,
        "pool": "pump",
    }

    try:
        async with session.post(
            PUMPFUN_TRADE_URL,
            json=payload,
            headers={**HEADERS, "Content-Type": "application/json"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error("TX build failed %s: %s", resp.status, body[:200])
                return None
            return await resp.read()
    except Exception as exc:
        logger.error("TX build error: %s", exc)
        return None


async def _sign_and_send(tx_bytes: bytes, wallet_kp, mint_kp) -> Optional[str]:
    """Sign the transaction and submit via RPC. Returns signature."""
    try:
        from solders.transaction import VersionedTransaction

        tx = VersionedTransaction.from_bytes(tx_bytes)
        signed = VersionedTransaction(tx.message, [wallet_kp, mint_kp])
        tx_b64 = base64.b64encode(bytes(signed)).decode()

        if config.SIMULATE:
            rpc_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "simulateTransaction",
                "params": [
                    tx_b64,
                    {
                        "encoding": "base64",
                        "commitment": "confirmed",
                        "sigVerify": True,
                        "replaceRecentBlockhash": False,
                    },
                ],
            }
        else:
            rpc_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sendTransaction",
                "params": [
                    tx_b64,
                    {
                        "encoding": "base64",
                        "skipPreflight": False,
                        "preflightCommitment": "confirmed",
                        "maxRetries": 3,
                    },
                ],
            }

        async with aiohttp.ClientSession() as rpc_session:
            async with rpc_session.post(
                config.SOLANA_RPC_URL,
                json=rpc_payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                result = await resp.json()
                if "error" in result:
                    logger.error("RPC %s error: %s",
                                "simulate" if config.SIMULATE else "send",
                                result["error"])
                    return None
                if config.SIMULATE:
                    sim = result.get("result", {}).get("value", {})
                    if sim.get("err") is not None:
                        logger.error("Simulation failed: err=%s logs=%s",
                                     sim.get("err"), sim.get("logs", [])[-5:])
                        return None
                    logger.info("TX simulated OK: units=%s logs_tail=%s",
                                sim.get("unitsConsumed"), sim.get("logs", [])[-3:])
                    return "SIM_OK"
                sig = result.get("result", "")
                logger.info("TX sent: %s", sig)
                return sig

    except Exception as exc:
        logger.error("Sign/send error: %s", exc)
        return None


async def prepare_launch_tx(
    name: str,
    ticker: str,
    image_url: str,
    description: str,
    wallet_pubkey: str,
) -> Optional[dict]:
    """
    Prepare an unsigned pump.fun create transaction for browser-side wallet signing.

    Flow:
      1. Download meme image
      2. Upload metadata + image to pump.fun IPFS
      3. Generate a fresh mint keypair
      4. Ask pump.fun to build the create transaction
      5. Return: unsigned tx bytes (b64), mint secret (b64 of full 64-byte keypair),
                 mint pubkey, and metadata URI

    The caller (browser) must:
      a. Reconstruct the mint keypair from mint_secret_b64
      b. Sign the tx with the mint keypair
      c. Sign the tx with the user's wallet (Phantom / Solflare)
      d. Submit the fully-signed tx to Solana RPC
    """
    if not wallet_pubkey:
        return None

    try:
        from solders.keypair import Keypair
        mint_kp = Keypair()
        mint_pubkey = str(mint_kp.pubkey())
        mint_secret_b64 = base64.b64encode(bytes(mint_kp)).decode()
    except Exception as exc:
        logger.error("Keypair generation error: %s", exc)
        return None

    async with aiohttp.ClientSession() as session:
        image_data = await _download_image(session, image_url)

        metadata_uri = await _upload_metadata(
            session, name, ticker, description, image_data, image_url
        )
        if not metadata_uri:
            return None

        tx_bytes = await _build_create_tx(
            session, wallet_pubkey, mint_pubkey, name, ticker, metadata_uri
        )
        if not tx_bytes:
            return None

    tx_b64 = base64.b64encode(tx_bytes).decode()
    return {
        "tx_b64": tx_b64,
        "mint_secret_b64": mint_secret_b64,
        "mint_pubkey": mint_pubkey,
        "metadata_uri": metadata_uri,
    }


async def launch_token(
    name: str,
    ticker: str,
    image_url: str,
    description: str = "",
) -> LaunchResult:
    """
    Full pump.fun token launch:
    1. Download meme image
    2. Upload metadata + image to pump.fun IPFS
    3. Build, sign and submit create transaction
    """
    if config.DRY_RUN:
        logger.info("[DRY RUN] Would launch: %s (%s)", name, ticker)
        return LaunchResult(
            success=True,
            tx_sig="DRY_RUN_" + ticker,
            mint_address="DRY_RUN_MINT",
            metadata_uri="dry://run",
            sol_spent=0.0,
        )

    if not config.SOLANA_PRIVATE_KEY:
        return LaunchResult(success=False, error="No wallet configured — paste your private key in the dashboard")

    try:
        from solders.keypair import Keypair
        import json as _json

        raw = config.SOLANA_PRIVATE_KEY.strip()
        if raw.startswith('['):
            wallet_kp = Keypair.from_bytes(bytes(_json.loads(raw)))
        else:
            wallet_kp = Keypair.from_base58_string(raw)
        mint_kp = Keypair()
        wallet_pubkey = str(wallet_kp.pubkey())
        mint_pubkey = str(mint_kp.pubkey())
    except Exception as exc:
        return LaunchResult(success=False, error=f"Keypair error: {exc}")

    async with aiohttp.ClientSession() as session:
        # 1. Download image
        image_data = await _download_image(session, image_url)

        # 2. Upload metadata
        metadata_uri = await _upload_metadata(
            session, name, ticker, description, image_data, image_url
        )
        if not metadata_uri:
            return LaunchResult(success=False, error="IPFS upload failed")

        # 3. Build transaction
        tx_bytes = await _build_create_tx(
            session, wallet_pubkey, mint_pubkey, name, ticker, metadata_uri
        )
        if not tx_bytes:
            return LaunchResult(success=False, error="TX build failed")

    # 4. Sign and send (separate session for RPC)
    sig = await _sign_and_send(tx_bytes, wallet_kp, mint_kp)
    if not sig:
        return LaunchResult(success=False, error="TX submission failed")

    return LaunchResult(
        success=True,
        tx_sig=sig,
        mint_address=mint_pubkey,
        metadata_uri=metadata_uri,
        sol_spent=0.0 if config.SIMULATE else (config.PUMPFUN_INITIAL_BUY_SOL + config.PUMPFUN_PRIORITY_FEE),
    )
