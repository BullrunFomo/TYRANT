"""pump.fun token launcher — direct on-chain, Token2022, updated for 2026-04-28 upgrade."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import re
import struct
from dataclasses import dataclass
from typing import Optional

import aiohttp

from pulse import config

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Pinata / IPFS
# ─────────────────────────────────────────────────────────────────────────────
PINATA_UPLOAD_URL = "https://uploads.pinata.cloud/v3/files"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


def _ipfs_url(cid: str) -> str:
    gateway = config.PINATA_GATEWAY or "ipfs.io"
    return f"https://{gateway}/ipfs/{cid}"


# ─────────────────────────────────────────────────────────────────────────────
# Pump.fun addresses — updated 2026-04-28
# ─────────────────────────────────────────────────────────────────────────────
_PUMP_PROGRAM        = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
_PUMP_GLOBAL         = "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf"   # fixed (not PDA)
_PUMP_EVENT_AUTH     = "Ce6TQqeHC9p8KetsN6JsjHK7UTZk7nasjjnr7XxXp9F1"   # fixed
_PUMP_FEE            = "CebN5WGQ4jvEPvsVU4EoHEpgzq1VV7AbicfhtW4xC9iM"   # updated
_PUMP_MINT_AUTHORITY = "TSLvdd1pWpHVjahSpsvCXUbgwsL3JAcvokwaKt1eokM"    # fixed
_PUMP_FEE_PROGRAM    = "pfeeUxB6jkeY1Hxd7CsFCAjcbHA9rWtchMGdZ6VojVZ"
_PUMP_MAYHEM_PROGRAM = "MAyhSmzXzV1pTf7LsNkrNwkWKTo4ougAJ1PPg47MD4e"   # new mayhem program
_TOKEN_2022_PROGRAM  = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"    # Token2022
_ASSOC_TOKEN_PROGRAM = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"   # updated
_SYSTEM_PROGRAM      = "11111111111111111111111111111111"
_COMPUTE_BUDGET      = "ComputeBudget111111111111111111111111111111"

# 8 breaking-upgrade fee recipients added 2026-04-28 — one is appended (writable)
# after bonding-curve-v2 on every buy/sell. Pick one at random per tx.
_BREAKING_FEE_RECIPIENTS = [
    "5YxQFdt3Tr9zJLvkFccqXVUwhdTWJQc1fFg2YPbxvxeD",
    "9M4giFFMxmFGXtc3feFzRai56WbBqehoSeRE5GK7gf7",
    "GXPFM2caqTtQYC2cJ5yJRi9VDkpsYZXzYdwYpGnLmtDL",
    "3BpXnfJaUTiwXnJNe7Ej1rcbzqTTQUvLShZaWazebsVR",
    "5cjcW9wExnJJiqgLjq7DEG75Pm6JBgE1hNv4B2vHXUW6",
    "EHAAiTxcdDwQ3U4bU6YcMsQGaekdzLS3B5SmYo46kJtL",
    "5eHhjP8JaYkz83CWwvGU2uMUXefd3AazWGx4gpcuEEYD",
    "A7hAgCzFw14fejgCp387JUJRMNyz4j89JKnhtKU8piqW",
]

# ─────────────────────────────────────────────────────────────────────────────
# Discriminators
# ─────────────────────────────────────────────────────────────────────────────
_DISC_CREATE_V2 = bytes([214, 144, 76, 236, 95, 139, 49, 180])
_DISC_EXTEND    = bytes([234, 102, 194, 203, 150, 72, 62, 229])
_DISC_BUY       = bytes([102, 6, 61, 18, 1, 218, 235, 234])
_DISC_SELL      = bytes([51, 230, 133, 164, 1, 127, 131, 173])

# ─────────────────────────────────────────────────────────────────────────────
# Bonding curve initial virtual reserves
# ─────────────────────────────────────────────────────────────────────────────
_INIT_VIRTUAL_TOKEN = 1_073_000_000_000_000
_INIT_VIRTUAL_SOL   = 30_000_000_000
LAMPORTS_PER_SOL    = 1_000_000_000


# ─────────────────────────────────────────────────────────────────────────────
# Data types
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class LaunchResult:
    success: bool
    tx_sig: str = ""
    mint_address: str = ""
    metadata_uri: str = ""
    error: str = ""
    sol_spent: float = 0.0
    sell_sig: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Ticker helper
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# Bonding curve math
# ─────────────────────────────────────────────────────────────────────────────
def _get_tokens_for_sol(sol_lamports: int) -> int:
    """Raw token amount (6 decimals) received for sol_lamports at curve start."""
    k = _INIT_VIRTUAL_SOL * _INIT_VIRTUAL_TOKEN
    return _INIT_VIRTUAL_TOKEN - k // (_INIT_VIRTUAL_SOL + sol_lamports)


# ─────────────────────────────────────────────────────────────────────────────
# Borsh helpers
# ─────────────────────────────────────────────────────────────────────────────
def _enc_str(s: str) -> bytes:
    enc = s.encode("utf-8")
    return struct.pack("<I", len(enc)) + enc


# ─────────────────────────────────────────────────────────────────────────────
# Solana PDA helpers (lazy solders imports)
# ─────────────────────────────────────────────────────────────────────────────
def _pk(addr: str):
    from solders.pubkey import Pubkey
    return Pubkey.from_string(addr)


def _pda(seeds: list, program_id) -> object:
    from solders.pubkey import Pubkey
    return Pubkey.find_program_address(seeds, program_id)[0]


def _ata_t22(owner, mint) -> object:
    """ATA derived with Token2022 in the seed (pump.fun's convention)."""
    tok22 = _pk(_TOKEN_2022_PROGRAM)
    assoc = _pk(_ASSOC_TOKEN_PROGRAM)
    return _pda([bytes(owner), bytes(tok22), bytes(mint)], assoc)


# ─────────────────────────────────────────────────────────────────────────────
# PDA derivations
# ─────────────────────────────────────────────────────────────────────────────
def _bonding_curve(mint) -> object:
    return _pda([b"bonding-curve", bytes(mint)], _pk(_PUMP_PROGRAM))


def _bonding_curve_v2(mint) -> object:
    return _pda([b"bonding-curve-v2", bytes(mint)], _pk(_PUMP_PROGRAM))


def _creator_vault(creator) -> object:
    return _pda([b"creator-vault", bytes(creator)], _pk(_PUMP_PROGRAM))


def _global_volume_accumulator() -> object:
    return _pda([b"global_volume_accumulator"], _pk(_PUMP_PROGRAM))


def _user_volume_accumulator(user) -> object:
    return _pda([b"user_volume_accumulator", bytes(user)], _pk(_PUMP_PROGRAM))


def _fee_config() -> object:
    return _pda([b"fee_config", bytes(_pk(_PUMP_PROGRAM))], _pk(_PUMP_FEE_PROGRAM))


def _breaking_fee_recipient():
    return _pk(random.choice(_BREAKING_FEE_RECIPIENTS))


def _mayhem_global_params() -> object:
    return _pda([b"global-params"], _pk(_PUMP_MAYHEM_PROGRAM))


def _mayhem_sol_vault() -> object:
    return _pda([b"sol-vault"], _pk(_PUMP_MAYHEM_PROGRAM))


def _mayhem_state(mint) -> object:
    return _pda([b"mayhem-state", bytes(mint)], _pk(_PUMP_MAYHEM_PROGRAM))


def _mayhem_token_vault(mint) -> object:
    """ATA of the mayhem sol_vault PDA, holding Token2022 of `mint`."""
    sol_vault = _mayhem_sol_vault()
    return _ata_t22(sol_vault, mint)


# ─────────────────────────────────────────────────────────────────────────────
# Instruction builders
# ─────────────────────────────────────────────────────────────────────────────
def _ix_cu_price(micro_lamports: int):
    from solders.instruction import Instruction
    return Instruction(
        program_id=_pk(_COMPUTE_BUDGET),
        data=bytes([3]) + struct.pack("<Q", micro_lamports),
        accounts=[],
    )


def _ix_cu_limit(units: int):
    from solders.instruction import Instruction
    return Instruction(
        program_id=_pk(_COMPUTE_BUDGET),
        data=bytes([2]) + struct.pack("<I", units),
        accounts=[],
    )


def _ix_create_v2(wallet_pk, mint_pk, name: str, symbol: str, metadata_uri: str):
    """create_v2 instruction — Token2022, no Metaplex.

    Account layout per official IDL (pump-fun/pump-public-docs/idl/pump.json):
    16 accounts, including 5 mayhem-program accounts added in the 2026 upgrade.
    Args: name, symbol, uri, creator (pubkey), is_mayhem_mode (bool),
          is_cashback_enabled (OptionBool).
    """
    from solders.instruction import Instruction, AccountMeta as AM

    pump        = _pk(_PUMP_PROGRAM)
    tok22       = _pk(_TOKEN_2022_PROGRAM)
    assoc_tok   = _pk(_ASSOC_TOKEN_PROGRAM)
    system      = _pk(_SYSTEM_PROGRAM)
    global_acc  = _pk(_PUMP_GLOBAL)
    mint_auth   = _pk(_PUMP_MINT_AUTHORITY)
    event_auth  = _pk(_PUMP_EVENT_AUTH)
    mayhem_prog = _pk(_PUMP_MAYHEM_PROGRAM)

    bc          = _bonding_curve(mint_pk)
    abc         = _ata_t22(bc, mint_pk)
    mh_params   = _mayhem_global_params()
    mh_vault    = _mayhem_sol_vault()
    mh_state    = _mayhem_state(mint_pk)
    mh_tok_vlt  = _mayhem_token_vault(mint_pk)

    data = (
        _DISC_CREATE_V2
        + _enc_str(name[:32])
        + _enc_str(symbol[:10])
        + _enc_str(metadata_uri)
        + bytes(wallet_pk)   # creator pubkey (32 bytes)
        + bytes([0])         # is_mayhem_mode = false (bool)
        + bytes([0])         # is_cashback_enabled = None (OptionBool)
    )

    return Instruction(
        program_id=pump,
        data=data,
        accounts=[
            AM(pubkey=mint_pk,     is_signer=True,  is_writable=True),   # 0  mint
            AM(pubkey=mint_auth,   is_signer=False, is_writable=False),  # 1  mint_authority
            AM(pubkey=bc,          is_signer=False, is_writable=True),   # 2  bonding_curve
            AM(pubkey=abc,         is_signer=False, is_writable=True),   # 3  associated_bonding_curve
            AM(pubkey=global_acc,  is_signer=False, is_writable=False),  # 4  global
            AM(pubkey=wallet_pk,   is_signer=True,  is_writable=True),   # 5  user
            AM(pubkey=system,      is_signer=False, is_writable=False),  # 6  system_program
            AM(pubkey=tok22,       is_signer=False, is_writable=False),  # 7  token_program (Token2022)
            AM(pubkey=assoc_tok,   is_signer=False, is_writable=False),  # 8  associated_token_program
            AM(pubkey=mayhem_prog, is_signer=False, is_writable=True),   # 9  mayhem_program_id
            AM(pubkey=mh_params,   is_signer=False, is_writable=False),  # 10 global_params
            AM(pubkey=mh_vault,    is_signer=False, is_writable=True),   # 11 sol_vault
            AM(pubkey=mh_state,    is_signer=False, is_writable=True),   # 12 mayhem_state
            AM(pubkey=mh_tok_vlt,  is_signer=False, is_writable=True),   # 13 mayhem_token_vault
            AM(pubkey=event_auth,  is_signer=False, is_writable=False),  # 14 event_authority
            AM(pubkey=pump,        is_signer=False, is_writable=False),  # 15 program
        ],
    )


def _ix_extend_account(wallet_pk, mint_pk):
    """extend_account — required after create_v2 for frontend visibility."""
    from solders.instruction import Instruction, AccountMeta as AM

    pump       = _pk(_PUMP_PROGRAM)
    system     = _pk(_SYSTEM_PROGRAM)
    event_auth = _pk(_PUMP_EVENT_AUTH)
    bc         = _bonding_curve(mint_pk)

    return Instruction(
        program_id=pump,
        data=_DISC_EXTEND,
        accounts=[
            AM(pubkey=bc,         is_signer=False, is_writable=True),
            AM(pubkey=wallet_pk,  is_signer=True,  is_writable=True),
            AM(pubkey=system,     is_signer=False, is_writable=False),
            AM(pubkey=event_auth, is_signer=False, is_writable=False),
            AM(pubkey=pump,       is_signer=False, is_writable=False),
        ],
    )


def _ix_create_ata_idempotent(payer, owner, mint):
    """Create Token2022 ATA idempotently (data byte = 1)."""
    from solders.instruction import Instruction, AccountMeta as AM

    tok22     = _pk(_TOKEN_2022_PROGRAM)
    assoc_tok = _pk(_ASSOC_TOKEN_PROGRAM)
    system    = _pk(_SYSTEM_PROGRAM)
    ata       = _ata_t22(owner, mint)

    return Instruction(
        program_id=assoc_tok,
        data=bytes([1]),  # 1 = CreateIdempotent
        accounts=[
            AM(pubkey=payer,   is_signer=True,  is_writable=True),
            AM(pubkey=ata,     is_signer=False, is_writable=True),
            AM(pubkey=owner,   is_signer=False, is_writable=False),
            AM(pubkey=mint,    is_signer=False, is_writable=False),
            AM(pubkey=system,  is_signer=False, is_writable=False),
            AM(pubkey=tok22,   is_signer=False, is_writable=False),
        ],
    )


def _ix_buy(wallet_pk, mint_pk, sol_lamports: int, slippage_pct: int):
    """Buy instruction — 18 accounts."""
    from solders.instruction import Instruction, AccountMeta as AM

    pump       = _pk(_PUMP_PROGRAM)
    system     = _pk(_SYSTEM_PROGRAM)
    tok22      = _pk(_TOKEN_2022_PROGRAM)
    event_auth = _pk(_PUMP_EVENT_AUTH)
    fee        = _pk(_PUMP_FEE)
    fee_prog   = _pk(_PUMP_FEE_PROGRAM)
    global_acc = _pk(_PUMP_GLOBAL)

    bc  = _bonding_curve(mint_pk)
    abc = _ata_t22(bc, mint_pk)
    user_ata  = _ata_t22(wallet_pk, mint_pk)
    cv  = _creator_vault(wallet_pk)   # creator = wallet for self-launched tokens
    gva = _global_volume_accumulator()
    uva = _user_volume_accumulator(wallet_pk)
    fc  = _fee_config()
    bcv2 = _bonding_curve_v2(mint_pk)
    breaking = _breaking_fee_recipient()

    token_amount = _get_tokens_for_sol(sol_lamports)
    max_sol_cost = int(sol_lamports * (1 + slippage_pct / 100))

    data = (
        _DISC_BUY
        + struct.pack("<Q", token_amount)
        + struct.pack("<Q", max_sol_cost)
        + bytes([1, 1])   # track_volume = Some(true)
    )

    return Instruction(
        program_id=pump,
        data=data,
        accounts=[
            AM(pubkey=global_acc,  is_signer=False, is_writable=False),  # 0
            AM(pubkey=fee,         is_signer=False, is_writable=True),   # 1
            AM(pubkey=mint_pk,     is_signer=False, is_writable=False),  # 2
            AM(pubkey=bc,          is_signer=False, is_writable=True),   # 3
            AM(pubkey=abc,         is_signer=False, is_writable=True),   # 4
            AM(pubkey=user_ata,    is_signer=False, is_writable=True),   # 5
            AM(pubkey=wallet_pk,   is_signer=True,  is_writable=True),   # 6
            AM(pubkey=system,      is_signer=False, is_writable=False),  # 7
            AM(pubkey=tok22,       is_signer=False, is_writable=False),  # 8
            AM(pubkey=cv,          is_signer=False, is_writable=True),   # 9  creator_vault
            AM(pubkey=event_auth,  is_signer=False, is_writable=False),  # 10
            AM(pubkey=pump,        is_signer=False, is_writable=False),  # 11
            AM(pubkey=gva,         is_signer=False, is_writable=False),  # 12 global_vol_acc
            AM(pubkey=uva,         is_signer=False, is_writable=True),   # 13 user_vol_acc
            AM(pubkey=fc,          is_signer=False, is_writable=False),  # 14 fee_config
            AM(pubkey=fee_prog,    is_signer=False, is_writable=False),  # 15 fee_program
            AM(pubkey=bcv2,        is_signer=False, is_writable=False),  # 16 bonding_curve_v2
            AM(pubkey=breaking,    is_signer=False, is_writable=True),   # 17 breaking fee
        ],
    )


def _ix_sell(wallet_pk, mint_pk, token_amount: int, min_sol_out: int):
    """Sell instruction — 16 accounts (non-cashback coin)."""
    from solders.instruction import Instruction, AccountMeta as AM

    pump       = _pk(_PUMP_PROGRAM)
    system     = _pk(_SYSTEM_PROGRAM)
    tok22      = _pk(_TOKEN_2022_PROGRAM)
    event_auth = _pk(_PUMP_EVENT_AUTH)
    fee        = _pk(_PUMP_FEE)
    fee_prog   = _pk(_PUMP_FEE_PROGRAM)
    global_acc = _pk(_PUMP_GLOBAL)

    bc  = _bonding_curve(mint_pk)
    abc = _ata_t22(bc, mint_pk)
    user_ata  = _ata_t22(wallet_pk, mint_pk)
    cv   = _creator_vault(wallet_pk)
    fc   = _fee_config()
    bcv2 = _bonding_curve_v2(mint_pk)
    breaking = _breaking_fee_recipient()

    data = (
        _DISC_SELL
        + struct.pack("<Q", token_amount)
        + struct.pack("<Q", min_sol_out)
        + bytes([1, 1])   # track_volume = Some(true)
    )

    return Instruction(
        program_id=pump,
        data=data,
        accounts=[
            AM(pubkey=global_acc, is_signer=False, is_writable=False),  # 0
            AM(pubkey=fee,        is_signer=False, is_writable=True),   # 1
            AM(pubkey=mint_pk,    is_signer=False, is_writable=False),  # 2
            AM(pubkey=bc,         is_signer=False, is_writable=True),   # 3
            AM(pubkey=abc,        is_signer=False, is_writable=True),   # 4
            AM(pubkey=user_ata,   is_signer=False, is_writable=True),   # 5
            AM(pubkey=wallet_pk,  is_signer=True,  is_writable=True),   # 6
            AM(pubkey=system,     is_signer=False, is_writable=False),  # 7
            AM(pubkey=cv,         is_signer=False, is_writable=True),   # 8  creator_vault
            AM(pubkey=tok22,      is_signer=False, is_writable=False),  # 9
            AM(pubkey=event_auth, is_signer=False, is_writable=False),  # 10
            AM(pubkey=pump,       is_signer=False, is_writable=False),  # 11
            AM(pubkey=fc,         is_signer=False, is_writable=False),  # 12 fee_config
            AM(pubkey=fee_prog,   is_signer=False, is_writable=False),  # 13 fee_program
            AM(pubkey=bcv2,       is_signer=False, is_writable=False),  # 14 bonding_curve_v2
            AM(pubkey=breaking,   is_signer=False, is_writable=True),   # 15 breaking fee
        ],
    )


# ─────────────────────────────────────────────────────────────────────────────
# RPC helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _get_latest_blockhash() -> Optional[str]:
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getLatestBlockhash",
        "params": [{"commitment": "confirmed"}],
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config.SOLANA_RPC_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                data = await resp.json()
                return data.get("result", {}).get("value", {}).get("blockhash")
    except Exception as exc:
        logger.error("getLatestBlockhash error: %s", exc)
        return None


async def _build_sign_send(instructions: list, signers: list) -> Optional[str]:
    """Compile → legacy Message → Transaction, sign, and submit."""
    blockhash = await _get_latest_blockhash()
    if not blockhash:
        logger.error("Could not fetch recent blockhash")
        return None

    try:
        from solders.message import Message
        from solders.transaction import Transaction
        from solders.hash import Hash

        msg = Message(instructions, signers[0].pubkey())
        tx = Transaction(signers, msg, Hash.from_string(blockhash))
        tx_b64 = base64.b64encode(bytes(tx)).decode()
    except Exception as exc:
        logger.error("TX build/sign error: %s", exc)
        return None

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

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
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
                                     sim.get("err"), sim.get("logs", [])[-8:])
                        return None
                    logger.info("TX simulated OK: units=%s", sim.get("unitsConsumed"))
                    return "SIM_OK"
                sig = result.get("result", "")
                logger.info("TX sent: %s", sig)
                return sig
    except Exception as exc:
        logger.error("RPC send error: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# IPFS upload helpers (unchanged)
# ─────────────────────────────────────────────────────────────────────────────
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
        logger.error("PINATA_JWT not set")
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


# ─────────────────────────────────────────────────────────────────────────────
# Token balance (for dev-sell)
# ─────────────────────────────────────────────────────────────────────────────
async def _get_token_balance(wallet_pubkey: str, mint_pubkey: str) -> Optional[int]:
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


# ─────────────────────────────────────────────────────────────────────────────
# Dev sell
# ─────────────────────────────────────────────────────────────────────────────
async def _sell_all(wallet_pubkey: str, mint_pubkey: str, wallet_kp) -> Optional[str]:
    logger.info("Fetching token balance for dev-sell...")
    balance = await _get_token_balance(wallet_pubkey, mint_pubkey)
    if not balance or balance == 0:
        logger.warning("Dev-sell: no tokens found, skipping")
        return None

    logger.info("Dev-sell: selling %d raw tokens for %s", balance, mint_pubkey)

    from solders.pubkey import Pubkey
    mint_pk = Pubkey.from_string(mint_pubkey)
    wallet_pk = wallet_kp.pubkey()

    cu_limit = 150_000
    cu_price = max(1, int(config.PUMPFUN_PRIORITY_FEE * LAMPORTS_PER_SOL * 1_000_000) // cu_limit)

    instructions = [
        _ix_cu_price(cu_price),
        _ix_cu_limit(cu_limit),
        _ix_sell(wallet_pk, mint_pk, balance, 0),
    ]
    sig = await _build_sign_send(instructions, [wallet_kp])
    if sig:
        logger.info("Dev-sell TX: %s", sig)
    return sig


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────
async def launch_token(
    name: str,
    ticker: str,
    image_url: str,
    description: str = "",
) -> LaunchResult:
    """
    Full pump.fun token launch (direct on-chain, Token2022):
    1. Download meme image
    2. Upload metadata + image to Pinata IPFS
    3. create_v2 + extend_account + create_user_ATA + buy — one transaction
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
        return LaunchResult(
            success=False,
            error="No wallet configured — paste your private key in the dashboard",
        )

    try:
        from solders.keypair import Keypair as SoldersKeypair

        raw = config.SOLANA_PRIVATE_KEY.strip()
        if raw.startswith("["):
            wallet_kp = SoldersKeypair.from_bytes(bytes(json.loads(raw)))
        else:
            wallet_kp = SoldersKeypair.from_base58_string(raw)
        mint_kp   = SoldersKeypair()
        wallet_pk = wallet_kp.pubkey()
        mint_pk   = mint_kp.pubkey()
    except Exception as exc:
        return LaunchResult(success=False, error=f"Keypair error: {exc}")

    # ── IPFS upload ───────────────────────────────────────────────────────────
    async with aiohttp.ClientSession() as session:
        image_data = await _download_image(session, image_url)
        metadata_uri = await _upload_metadata(
            session, name, ticker, description, image_data, image_url
        )
    if not metadata_uri:
        return LaunchResult(success=False, error="IPFS upload failed")

    # ── TX 1: create + extend ─────────────────────────────────────────────────
    # The post-2026-04-28 create_v2 has 16 accounts (5 mayhem additions). Combining
    # it with create_ata + buy in one tx blows past the 1232-byte legacy limit, so
    # the dev buy is sent as a follow-up tx instead.
    cu_limit_create = 350_000
    cu_price_create = max(
        1, int(config.PUMPFUN_PRIORITY_FEE * LAMPORTS_PER_SOL * 1_000_000) // cu_limit_create
    )

    create_ixs = [
        _ix_cu_price(cu_price_create),
        _ix_cu_limit(cu_limit_create),
        _ix_create_v2(wallet_pk, mint_pk, name, ticker, metadata_uri),
        _ix_extend_account(wallet_pk, mint_pk),
    ]

    sig = await _build_sign_send(create_ixs, [wallet_kp, mint_kp])
    if not sig:
        return LaunchResult(success=False, error="Create TX submission failed")

    mint_address = str(mint_pk)

    # ── TX 2: dev buy ─────────────────────────────────────────────────────────
    # Skipped entirely in SIMULATE mode because the bonding curve doesn't exist
    # on-chain yet — simulating the buy would fail with "account not found".
    if config.DEV_BUY_SOL > 0 and not config.SIMULATE and not config.DRY_RUN:
        sol_lamports = int(config.DEV_BUY_SOL * LAMPORTS_PER_SOL)
        cu_limit_buy = 200_000
        cu_price_buy = max(
            1, int(config.PUMPFUN_PRIORITY_FEE * LAMPORTS_PER_SOL * 1_000_000) // cu_limit_buy
        )
        buy_ixs = [
            _ix_cu_price(cu_price_buy),
            _ix_cu_limit(cu_limit_buy),
            _ix_create_ata_idempotent(wallet_pk, wallet_pk, mint_pk),
            _ix_buy(wallet_pk, mint_pk, sol_lamports, config.PUMPFUN_SLIPPAGE),
        ]
        buy_sig = await _build_sign_send(buy_ixs, [wallet_kp])
        if not buy_sig:
            logger.warning("Dev-buy TX failed for %s", mint_address)

    sol_spent = 0.0 if config.SIMULATE else (config.DEV_BUY_SOL + config.PUMPFUN_PRIORITY_FEE)

    # ── Dev sell after delay ──────────────────────────────────────────────────
    sell_sig = ""
    if not config.SIMULATE and not config.DRY_RUN and config.DEV_BUY_SOL > 0:
        logger.info("Dev-buy confirmed. Waiting %ds before selling...", config.DEV_SELL_DELAY_SECONDS)
        await asyncio.sleep(config.DEV_SELL_DELAY_SECONDS)
        sell_sig = await _sell_all(str(wallet_pk), mint_address, wallet_kp) or ""
        if sell_sig:
            logger.info("Dev-sell complete: %s", sell_sig)
        else:
            logger.warning("Dev-sell failed or skipped for %s", mint_address)

    return LaunchResult(
        success=True,
        tx_sig=sig,
        mint_address=mint_address,
        metadata_uri=metadata_uri,
        sol_spent=sol_spent,
        sell_sig=sell_sig,
    )
