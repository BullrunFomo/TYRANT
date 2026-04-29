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

# Buyback fee recipients — the on-chain pump program (newer than the public IDL)
# requires all 8 of these to be appended as `remaining_accounts` on every buy/sell.
# Sourced from Global.buyback_fee_recipients[8] at PDA "global". Omitting any of
# them returns custom error 6062 (BuybackFeeRecipientMissing); passing the wrong
# count returns 6061 (WrongBuybackFeeRecipientsCount). All 8 are marked writable
# because the program picks one at runtime to credit.
_BUYBACK_FEE_RECIPIENTS = [
    "5YxQFdt3Tr9zJLvkFccqXVUwhdTWJQc1fFg2YPbxvxeD",
    "9M4giFFMxmFGXtc3feFzRai56WbBqehoSeRE5GK7gf7",
    "GXPFM2caqTtQYC2cJ5yJRi9VDkpsYZXzYdwYpGnLmtDL",
    "3BpXnfJaUTiwXnJNe7Ej1rcbzqTTQUvLShZaWazebsVR",
    "5cjcW9wExnJJiqgLjq7DEG75Pm6JBgE1hNv4B2vHXUW6",
    "EHAAiTxcdDwQ3U4bU6YcMsQGaekdzLS3B5SmYo46kJtL",
    "5eHhjP8JaYkz83CWwvGU2uMUXefd3AazWGx4gpcuEEYD",
    "A7hAgCzFw14fejgCp387JUJRMNyz4j89JKnhtKU8piqW",
]

# Jito tip accounts (https://docs.jito.wtf/lowlatencytxnsend/) — pick one at random
# per bundle. The tip goes in the last instruction of the last bundle tx.
_JITO_TIP_ACCOUNTS = [
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4wVV8bD44PvwucfZ2bU7gRe",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2DTLSokTSzL1zt6iGPaS49",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
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
    """PDA seed ['bonding-curve-v2', mint]. The account need not be initialized;
    it just needs to be present in the instruction's account list, otherwise the
    program reads garbage and returns the misleading 6024 'Overflow' error."""
    return _pda([b"bonding-curve-v2", bytes(mint)], _pk(_PUMP_PROGRAM))


def _creator_vault(creator) -> object:
    return _pda([b"creator-vault", bytes(creator)], _pk(_PUMP_PROGRAM))


def _global_volume_accumulator() -> object:
    return _pda([b"global_volume_accumulator"], _pk(_PUMP_PROGRAM))


def _user_volume_accumulator(user) -> object:
    return _pda([b"user_volume_accumulator", bytes(user)], _pk(_PUMP_PROGRAM))


def _fee_config() -> object:
    return _pda([b"fee_config", bytes(_pk(_PUMP_PROGRAM))], _pk(_PUMP_FEE_PROGRAM))


def _jito_tip_account() -> object:
    return _pk(random.choice(_JITO_TIP_ACCOUNTS))


def _buyback_recipient_metas() -> list:
    """The 8 buyback fee recipients as remaining_accounts (all writable)."""
    from solders.instruction import AccountMeta as AM
    return [
        AM(pubkey=_pk(addr), is_signer=False, is_writable=True)
        for addr in _BUYBACK_FEE_RECIPIENTS
    ]


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
    """Buy instruction — 16 accounts per official IDL.
    Args: amount (u64), max_sol_cost (u64), track_volume (OptionBool).
    """
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
    user_ata = _ata_t22(wallet_pk, mint_pk)
    cv  = _creator_vault(wallet_pk)   # creator = wallet for self-launched tokens
    gva = _global_volume_accumulator()
    uva = _user_volume_accumulator(wallet_pk)
    fc  = _fee_config()
    bcv2 = _bonding_curve_v2(mint_pk)

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
            AM(pubkey=global_acc, is_signer=False, is_writable=False),  # 0  global
            AM(pubkey=fee,        is_signer=False, is_writable=True),   # 1  fee_recipient
            AM(pubkey=mint_pk,    is_signer=False, is_writable=False),  # 2  mint
            AM(pubkey=bc,         is_signer=False, is_writable=True),   # 3  bonding_curve
            AM(pubkey=abc,        is_signer=False, is_writable=True),   # 4  associated_bonding_curve
            AM(pubkey=user_ata,   is_signer=False, is_writable=True),   # 5  associated_user
            AM(pubkey=wallet_pk,  is_signer=True,  is_writable=True),   # 6  user
            AM(pubkey=system,     is_signer=False, is_writable=False),  # 7  system_program
            AM(pubkey=tok22,      is_signer=False, is_writable=False),  # 8  token_program
            AM(pubkey=cv,         is_signer=False, is_writable=True),   # 9  creator_vault
            AM(pubkey=event_auth, is_signer=False, is_writable=False),  # 10 event_authority
            AM(pubkey=pump,       is_signer=False, is_writable=False),  # 11 program
            AM(pubkey=gva,        is_signer=False, is_writable=False),  # 12 global_volume_accumulator
            AM(pubkey=uva,        is_signer=False, is_writable=True),   # 13 user_volume_accumulator
            AM(pubkey=fc,         is_signer=False, is_writable=False),  # 14 fee_config
            AM(pubkey=fee_prog,   is_signer=False, is_writable=False),  # 15 fee_program
            AM(pubkey=bcv2,       is_signer=False, is_writable=False),  # 16 bonding_curve_v2 (remaining)
            *_buyback_recipient_metas(),                                # 17-24 buyback recipients (remaining, 8x writable)
        ],
    )


def _ix_sell(wallet_pk, mint_pk, token_amount: int, min_sol_out: int):
    """Sell instruction — 14 accounts per official IDL.
    Args: amount (u64), min_sol_output (u64). NO track_volume.
    """
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
    user_ata = _ata_t22(wallet_pk, mint_pk)
    cv  = _creator_vault(wallet_pk)
    fc  = _fee_config()
    bcv2 = _bonding_curve_v2(mint_pk)

    data = (
        _DISC_SELL
        + struct.pack("<Q", token_amount)
        + struct.pack("<Q", min_sol_out)
    )

    return Instruction(
        program_id=pump,
        data=data,
        accounts=[
            AM(pubkey=global_acc, is_signer=False, is_writable=False),  # 0  global
            AM(pubkey=fee,        is_signer=False, is_writable=True),   # 1  fee_recipient
            AM(pubkey=mint_pk,    is_signer=False, is_writable=False),  # 2  mint
            AM(pubkey=bc,         is_signer=False, is_writable=True),   # 3  bonding_curve
            AM(pubkey=abc,        is_signer=False, is_writable=True),   # 4  associated_bonding_curve
            AM(pubkey=user_ata,   is_signer=False, is_writable=True),   # 5  associated_user
            AM(pubkey=wallet_pk,  is_signer=True,  is_writable=True),   # 6  user
            AM(pubkey=system,     is_signer=False, is_writable=False),  # 7  system_program
            AM(pubkey=cv,         is_signer=False, is_writable=True),   # 8  creator_vault
            AM(pubkey=tok22,      is_signer=False, is_writable=False),  # 9  token_program
            AM(pubkey=event_auth, is_signer=False, is_writable=False),  # 10 event_authority
            AM(pubkey=pump,       is_signer=False, is_writable=False),  # 11 program
            AM(pubkey=fc,         is_signer=False, is_writable=False),  # 12 fee_config
            AM(pubkey=fee_prog,   is_signer=False, is_writable=False),  # 13 fee_program
            AM(pubkey=bcv2,       is_signer=False, is_writable=False),  # 14 bonding_curve_v2 (remaining)
            *_buyback_recipient_metas(),                                # 15-22 buyback recipients (remaining, 8x writable)
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


def _build_sign(instructions: list, signers: list, blockhash: str) -> Optional[tuple]:
    """Compile → legacy Message → Transaction, sign. Returns (tx, signature_str, tx_b64)."""
    try:
        from solders.message import Message
        from solders.transaction import Transaction
        from solders.hash import Hash

        msg = Message(instructions, signers[0].pubkey())
        tx = Transaction(signers, msg, Hash.from_string(blockhash))
        tx_b64 = base64.b64encode(bytes(tx)).decode()
        sig_str = str(tx.signatures[0])
        return tx, sig_str, tx_b64
    except Exception as exc:
        logger.error("TX build/sign error: %s", exc)
        return None


async def _simulate_tx(tx_b64: str) -> Optional[str]:
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
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config.SOLANA_RPC_URL, json=rpc_payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                result = await resp.json()
                if "error" in result:
                    logger.error("RPC error: %s", result["error"])
                    return None
                sim = result.get("result", {}).get("value", {})
                if sim.get("err") is not None:
                    logger.error("Simulation failed: err=%s logs=%s",
                                 sim.get("err"), sim.get("logs", [])[-8:])
                    return None
                logger.info("TX simulated OK: units=%s", sim.get("unitsConsumed"))
                return "SIM_OK"
    except Exception as exc:
        logger.error("RPC simulate error: %s", exc)
        return None


async def _send_tx(tx_b64: str) -> Optional[str]:
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
                config.SOLANA_RPC_URL, json=rpc_payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                result = await resp.json()
                if "error" in result:
                    logger.error("RPC error: %s", result["error"])
                    return None
                sig = result.get("result", "")
                logger.info("TX sent: %s", sig)
                return sig
    except Exception as exc:
        logger.error("RPC send error: %s", exc)
        return None


async def _build_sign_send(instructions: list, signers: list) -> Optional[str]:
    """Build → sign → simulate or send (single-tx, non-Jito path)."""
    blockhash = await _get_latest_blockhash()
    if not blockhash:
        logger.error("Could not fetch recent blockhash")
        return None
    built = _build_sign(instructions, signers, blockhash)
    if not built:
        return None
    _, sig_str, tx_b64 = built
    if config.SIMULATE:
        return await _simulate_tx(tx_b64)
    return await _send_tx(tx_b64)


async def _send_jito_bundle(txs_b64: list) -> Optional[str]:
    """Submit a Jito bundle (max 5 base64-encoded signed transactions).
    Retries on rate-limit errors (-32097) up to 3 times with backoff.
    """
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "sendBundle",
        "params": [txs_b64, {"encoding": "base64"}],
    }
    backoff = 1.0
    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    config.JITO_BUNDLE_URL, json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    result = await resp.json()
                    err = result.get("error")
                    if err:
                        if err.get("code") == -32097 and attempt < 2:
                            logger.warning("Jito rate-limited, retrying in %.1fs", backoff)
                            await asyncio.sleep(backoff)
                            backoff *= 2
                            continue
                        logger.error("Jito error: %s", err)
                        return None
                    bundle_id = result.get("result", "")
                    logger.info("Jito bundle submitted: %s", bundle_id)
                    return bundle_id
        except Exception as exc:
            logger.error("Jito send error: %s", exc)
            return None
    return None


async def _wait_for_confirmation(sig: str, timeout_s: int = 30) -> bool:
    """Poll getSignatureStatuses until the tx lands (confirmed/finalized) or fails."""
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getSignatureStatuses",
        "params": [[sig], {"searchTransactionHistory": False}],
    }
    deadline = asyncio.get_event_loop().time() + timeout_s
    async with aiohttp.ClientSession() as session:
        while asyncio.get_event_loop().time() < deadline:
            try:
                async with session.post(
                    config.SOLANA_RPC_URL, json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json()
                    statuses = (data.get("result") or {}).get("value") or [None]
                    status = statuses[0]
                    if status:
                        if status.get("err") is not None:
                            logger.error("TX %s failed on chain: %s", sig, status["err"])
                            return False
                        cs = status.get("confirmationStatus")
                        if cs in ("confirmed", "finalized"):
                            return True
            except Exception as exc:
                logger.warning("getSignatureStatuses transient error: %s", exc)
            await asyncio.sleep(1)
    logger.warning("Timed out waiting for confirmation of %s", sig)
    return False


def _ix_jito_tip(payer_pk, lamports: int):
    """SystemProgram::Transfer of `lamports` from payer to a random Jito tip account."""
    from solders.system_program import transfer, TransferParams
    return transfer(TransferParams(
        from_pubkey=payer_pk,
        to_pubkey=_jito_tip_account(),
        lamports=lamports,
    ))


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
    meme_url: str = "",
    source: str = "",
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

    # Build a richer description: include KYM source/url instead of a flat tag line.
    base_desc = description.strip()
    if base_desc:
        body = base_desc[:400]
    else:
        body = f"Meme coin auto-launched from KnowYourMeme."
    if meme_url:
        kym_tag = f" Source: KnowYourMeme [{source.title()}] — {meme_url}" if source else f" Source: {meme_url}"
        body = (body + kym_tag)[:500]

    from urllib.parse import quote
    metadata = {
        "name": name[:32],
        "symbol": ticker[:10],
        "description": body,
        "image": image_field,
        "showName": True,
        "createdOn": "https://pump.fun",
    }
    if meme_url:
        metadata["website"] = meme_url
    # Twitter search for the meme name — there's no specific tweet, but the search
    # surfaces current activity which is what most pump.fun launches link to.
    metadata["twitter"] = f"https://x.com/search?q={quote(name)}"

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
    """Fetch the wallet's Token-2022 balance for `mint`. Derives the ATA directly
    instead of using getTokenAccountsByOwner (which can return stale empty results
    right after a buy). Retries a few times to ride out RPC indexing lag.
    """
    from solders.pubkey import Pubkey
    ata = _ata_t22(Pubkey.from_string(wallet_pubkey), Pubkey.from_string(mint_pubkey))
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "getTokenAccountBalance",
        "params": [str(ata), {"commitment": "confirmed"}],
    }
    backoff = 1.0
    for attempt in range(5):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    config.SOLANA_RPC_URL, json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = await resp.json()
                    err = data.get("error")
                    if err:
                        # account not found yet — ATA hasn't propagated
                        if attempt < 4:
                            await asyncio.sleep(backoff)
                            backoff *= 1.5
                            continue
                        logger.error("Token balance RPC error: %s", err)
                        return None
                    val = data.get("result", {}).get("value", {})
                    amount = int(val.get("amount", "0"))
                    if amount > 0 or attempt == 4:
                        return amount
                    await asyncio.sleep(backoff)
                    backoff *= 1.5
        except Exception as exc:
            logger.warning("Token balance fetch transient: %s", exc)
            await asyncio.sleep(backoff)
            backoff *= 1.5
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
    meme_url: str = "",
    source: str = "",
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
            session, name, ticker, description, image_data, image_url,
            meme_url=meme_url, source=source,
        )
    if not metadata_uri:
        return LaunchResult(success=False, error="IPFS upload failed")

    mint_address = str(mint_pk)

    # ── Common create instructions ────────────────────────────────────────────
    # The post-2026-04-28 create_v2 has 16 accounts (5 mayhem additions). With
    # create_ata + buy on top, the legacy 1232-byte tx limit is blown — so live
    # mode atomically pairs create-tx and buy-tx in a single Jito bundle (same
    # block, no front-running). SIMULATE mode just simulates the create tx.
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

    # ── SIMULATE / no-buy path: just send/simulate the create tx ──────────────
    if config.SIMULATE or config.DEV_BUY_SOL <= 0:
        sig = await _build_sign_send(create_ixs, [wallet_kp, mint_kp])
        if not sig:
            return LaunchResult(success=False, error="Create TX submission failed")
        sol_spent = 0.0 if config.SIMULATE else config.PUMPFUN_PRIORITY_FEE
        return LaunchResult(
            success=True, tx_sig=sig, mint_address=mint_address,
            metadata_uri=metadata_uri, sol_spent=sol_spent,
        )

    # ── LIVE path: atomic Jito bundle [create_tx, buy_tx] ─────────────────────
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
        _ix_jito_tip(wallet_pk, config.JITO_TIP_LAMPORTS),
    ]

    blockhash = await _get_latest_blockhash()
    if not blockhash:
        return LaunchResult(success=False, error="Could not fetch blockhash")

    create_built = _build_sign(create_ixs, [wallet_kp, mint_kp], blockhash)
    buy_built    = _build_sign(buy_ixs, [wallet_kp], blockhash)
    if not create_built or not buy_built:
        return LaunchResult(success=False, error="TX build/sign failed")

    _, create_sig, create_b64 = create_built
    _, buy_sig,    buy_b64    = buy_built

    bundle_id = await _send_jito_bundle([create_b64, buy_b64])
    if not bundle_id:
        return LaunchResult(success=False, error="Jito bundle submission failed")

    # Wait for the buy tx to land before the dev-sell. If it fails, abort sell.
    if not await _wait_for_confirmation(buy_sig, timeout_s=30):
        return LaunchResult(
            success=False,
            tx_sig=create_sig, mint_address=mint_address, metadata_uri=metadata_uri,
            error="Bundle did not confirm — buy tx not landed",
        )

    sol_spent = config.DEV_BUY_SOL + config.PUMPFUN_PRIORITY_FEE + (
        config.JITO_TIP_LAMPORTS / LAMPORTS_PER_SOL
    )

    # ── Dev sell after delay ──────────────────────────────────────────────────
    logger.info("Dev-buy confirmed. Waiting %ds before selling...", config.DEV_SELL_DELAY_SECONDS)
    await asyncio.sleep(config.DEV_SELL_DELAY_SECONDS)
    sell_sig = await _sell_all(str(wallet_pk), mint_address, wallet_kp) or ""
    if sell_sig:
        logger.info("Dev-sell complete: %s", sell_sig)
    else:
        logger.warning("Dev-sell failed or skipped for %s", mint_address)

    return LaunchResult(
        success=True,
        tx_sig=create_sig,
        mint_address=mint_address,
        metadata_uri=metadata_uri,
        sol_spent=sol_spent,
        sell_sig=sell_sig,
    )
