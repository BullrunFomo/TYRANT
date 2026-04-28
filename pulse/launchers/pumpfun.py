"""pump.fun token launcher — uploads metadata to IPFS, creates token, dev-buys, then sells."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

import aiohttp

from pulse import config

logger = logging.getLogger(__name__)

PINATA_UPLOAD_URL = "https://uploads.pinata.cloud/v3/files"
PUMPFUN_TRADE_URL = "https://pumpportal.fun/api/trade-local"


def _ipfs_url(cid: str) -> str:
    gateway = config.PINATA_GATEWAY or "ipfs.io"
    return f"https://{gateway}/ipfs/{cid}"


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
    sell_sig: str = ""


def make_ticker(name: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9\s]", "", name).strip()
    words = clean.split()
    if not words:
        return "MEME"
    if len(words) == 1:
        return words[0][:6].upper()
    initials = "".join(w[0] for w in words if w)[:6].upper()
    if len(initials) < 3 and len(words) >= 2:
        return (words[0][:3] + words[1][:3])[:6].upper()
    return initials


async def _download_image(session: aiohttp.ClientSession, image_url: str) -> Optional[bytes]:
    if not image_url:
        return None
    try:
        async with session.get(
            image_url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)
        ) as resp:
            if resp.status == 200:
                return await resp.read()
            logger.warning("Image download failed: %s -> %s", image_url, resp.status)
    except Exception as exc:
        logger.error("Image download error: %s", exc)
    return None


async def _pinata_upload(
    session: aiohttp.ClientSession,
    file_bytes: bytes,
    filename: str,
    content_type: str,
) -> Optional[str]:
    if not config.PINATA_JWT:
        logger.error("PINATA_JWT not set — get a free key at https://pinata.cloud")
        return None
    form = aiohttp.FormData()
    form.add_field("file", file_bytes, filename=filename, content_type=content_type)
    form.add_field("network", "public")
    try:
        async with session.post(
            PINATA_UPLOAD_URL,
            data=form,
            headers={"Authorization": f"Bearer {config.PINATA_JWT}"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status not in (200, 201):
                body = await resp.text()
                logger.error("Pinata upload failed %s: %s", resp.status, body[:300])
                return None
            data = await resp.json()
            cid = (data.get("data") or {}).get("cid", "")
            if not cid:
                logger.error("Pinata response missing cid: %s", data)
                return None
            return cid
    except Exception as exc:
        logger.error("Pinata upload error: %s", exc)
        return None


async def _upload_metadata(
    session: aiohttp.ClientSession,
    name: str,
    ticker: str,
    description: str,
    image_data: Optional[bytes],
    image_url: str,
) -> Optional[str]:
    if image_data:
        content_type, ext = "image/jpeg", "jpg"
        if image_data[:4] == b"\x89PNG":
            content_type, ext = "image/png", "png"
        elif image_data[:3] == b"GIF":
            content_type, ext = "image/gif", "gif"
        elif image_data[:4] == b"RIFF":
            content_type, ext = "image/webp", "webp"
        img_cid = await _pinata_upload(session, image_data, f"meme.{ext}", content_type)
        if not img_cid:
            return None
        image_field = _ipfs_url(img_cid)
    else:
        image_field = image_url

    metadata = {
        "name": name[:32],
        "symbol": ticker[:10],
        "description": description[:500] or f"Auto-launched meme coin: {name}",
        "image": image_field,
        "showName": True,
    }
    meta_cid = await _pinata_upload(
        session, json.dumps(metadata).encode("utf-8"), "metadata.json", "application/json"
    )
    if not meta_cid:
        return None
    uri = _ipfs_url(meta_cid)
    logger.info("Metadata uploaded: %s", uri)
    return uri


async def _build_tx(session: aiohttp.ClientSession, payload: dict) -> Optional[bytes]:
    try:
        async with session.post(
            PUMPFUN_TRADE_URL,
            json=payload,
            headers={"Content-Type": "application/json", "User-Agent": "tyrant-bot/1.0"},
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error(
                    "TX build failed %s %s — body=%s payload=%s",
                    resp.status, resp.reason, body[:500], payload,
                )
                return None
            return await resp.read()
    except Exception as exc:
        logger.error("TX build error: %s", exc)
        return None


async def _sign_and_send(tx_bytes: bytes, signers: list) -> Optional[str]:
    """Sign with all provided signers and submit (or simulate) via RPC."""
    try:
        from solders.transaction import VersionedTransaction

        tx = VersionedTransaction.from_bytes(tx_bytes)
        signed = VersionedTransaction(tx.message, signers)
        tx_b64 = base64.b64encode(bytes(signed)).decode()

        if config.SIMULATE:
            rpc_payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "simulateTransaction",
                "params": [tx_b64, {
                    "encoding": "base64",
                    "commitment": "confirmed",
                    "sigVerify": True,
                    "replaceRecentBlockhash": False,
                }],
            }
        else:
            rpc_payload = {
                "jsonrpc": "2.0", "id": 1,
                "method": "sendTransaction",
                "params": [tx_b64, {
                    "encoding": "base64",
                    "skipPreflight": False,
                    "preflightCommitment": "confirmed",
                    "maxRetries": 3,
                }],
            }

        async with aiohttp.ClientSession() as rpc_session:
            async with rpc_session.post(
                config.SOLANA_RPC_URL,
                json=rpc_payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                result = await resp.json()
                if "error" in result:
                    logger.error("RPC error: %s", result["error"])
                    return None
                if config.SIMULATE:
                    sim = result.get("result", {}).get("value", {})
                    if sim.get("err") is not None:
                        logger.error("Simulation failed: err=%s logs=%s",
                                     sim.get("err"), sim.get("logs", [])[-5:])
                        return None
                    logger.info("TX simulated OK: units=%s", sim.get("unitsConsumed"))
                    return "SIM_OK"
                sig = result.get("result", "")
                logger.info("TX sent: %s", sig)
                return sig

    except Exception as exc:
        logger.error("Sign/send error: %s", exc)
        return None


async def _get_token_balance(wallet_pubkey: str, mint_pubkey: str) -> Optional[int]:
    """Returns raw token amount (with 6 decimals) held by wallet, or None on error."""
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            wallet_pubkey,
            {"mint": mint_pubkey},
            {"encoding": "jsonParsed"},
        ],
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config.SOLANA_RPC_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                accounts = data.get("result", {}).get("value", [])
                if not accounts:
                    return None
                amount_str = (
                    accounts[0]
                    .get("account", {})
                    .get("data", {})
                    .get("parsed", {})
                    .get("info", {})
                    .get("tokenAmount", {})
                    .get("amount", "0")
                )
                return int(amount_str)
    except Exception as exc:
        logger.error("Token balance fetch error: %s", exc)
        return None


async def _sell_all(wallet_pubkey: str, mint_pubkey: str, wallet_kp) -> Optional[str]:
    """Fetch token balance and sell 100% via pumpportal. Returns tx sig or None."""
    logger.info("Fetching token balance for dev-sell...")
    balance = await _get_token_balance(wallet_pubkey, mint_pubkey)
    if not balance or balance == 0:
        logger.warning("Dev-sell: no tokens found in wallet, skipping")
        return None

    logger.info("Dev-sell: selling %d raw tokens for %s", balance, mint_pubkey)

    async with aiohttp.ClientSession() as session:
        tx_bytes = await _build_tx(session, {
            "publicKey": wallet_pubkey,
            "action": "sell",
            "mint": mint_pubkey,
            "denominatedInSol": "false",
            "amount": balance,
            "slippage": config.PUMPFUN_SLIPPAGE,
            "priorityFee": config.PUMPFUN_PRIORITY_FEE,
            "pool": "pump",
        })

    if not tx_bytes:
        logger.error("Dev-sell TX build failed")
        return None

    sig = await _sign_and_send(tx_bytes, [wallet_kp])
    if sig:
        logger.info("Dev-sell TX: %s", sig)
    return sig


async def launch_token(
    name: str,
    ticker: str,
    image_url: str,
    description: str = "",
) -> LaunchResult:
    """
    Full pump.fun token launch:
    1. Download meme image
    2. Upload metadata + image to Pinata IPFS
    3. Build, sign, submit create tx (with 0.1 SOL dev buy bundled)
    4. Wait DEV_SELL_DELAY_SECONDS, then sell entire position
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
        from solders.keypair import Keypair as SoldersKeypair

        raw = config.SOLANA_PRIVATE_KEY.strip()
        if raw.startswith("["):
            wallet_kp = SoldersKeypair.from_bytes(bytes(json.loads(raw)))
        else:
            wallet_kp = SoldersKeypair.from_base58_string(raw)
        mint_kp = SoldersKeypair()
        wallet_pubkey = str(wallet_kp.pubkey())
        mint_pubkey = str(mint_kp.pubkey())
    except Exception as exc:
        return LaunchResult(success=False, error=f"Keypair error: {exc}")

    async with aiohttp.ClientSession() as session:
        image_data = await _download_image(session, image_url)

        metadata_uri = await _upload_metadata(
            session, name, ticker, description, image_data, image_url
        )
        if not metadata_uri:
            return LaunchResult(success=False, error="IPFS upload failed")

        # Create tx bundles the dev buy in the same transaction
        tx_bytes = await _build_tx(session, {
            "publicKey": wallet_pubkey,
            "action": "create",
            "tokenMetadata": {
                "name": name[:32],
                "symbol": ticker[:10],
                "uri": metadata_uri,
            },
            "mint": mint_pubkey,
            "denominatedInSol": "true",
            "amount": config.DEV_BUY_SOL,
            "slippage": config.PUMPFUN_SLIPPAGE,
            "priorityFee": config.PUMPFUN_PRIORITY_FEE,
            "pool": "pump",
        })
        if not tx_bytes:
            return LaunchResult(success=False, error="TX build failed")

    sig = await _sign_and_send(tx_bytes, [wallet_kp, mint_kp])
    if not sig:
        return LaunchResult(success=False, error="TX submission failed")

    sol_spent = 0.0 if config.SIMULATE else (config.DEV_BUY_SOL + config.PUMPFUN_PRIORITY_FEE)

    # ── Dev sell after delay ──────────────────────────────────────────────────
    sell_sig = ""
    if not config.SIMULATE:
        logger.info("Dev-buy confirmed. Waiting %ds before selling...", config.DEV_SELL_DELAY_SECONDS)
        await asyncio.sleep(config.DEV_SELL_DELAY_SECONDS)
        sell_sig = await _sell_all(wallet_pubkey, mint_pubkey, wallet_kp) or ""
        if sell_sig:
            logger.info("Dev-sell complete: %s", sell_sig)
        else:
            logger.warning("Dev-sell failed or skipped for %s", mint_pubkey)

    return LaunchResult(
        success=True,
        tx_sig=sig,
        mint_address=mint_pubkey,
        metadata_uri=metadata_uri,
        sol_spent=sol_spent,
        sell_sig=sell_sig,
    )
