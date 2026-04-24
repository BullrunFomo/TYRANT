"""Async SQLite persistence for meme launches and KYM dedup tracking."""
from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass
from typing import List, Optional

import aiosqlite

from pulse import config


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class Account:
    id: Optional[int]
    access_key: str
    label: str
    created_at: float


@dataclass
class Launch:
    id: Optional[int]
    timestamp: float
    name: str
    ticker: str
    source: str          # confirmed / submission / newsworthy / deadpool
    meme_url: str
    image_url: str
    description: str
    tx_sig: str
    mint_address: str
    status: str          # LAUNCHED / FAILED / DRY_RUN
    sol_spent: float = 0.0
    error: str = ""
    account_id: Optional[int] = None


@dataclass
class LaunchSnapshot:
    timestamp: float
    count: int           # cumulative launches at this point


# ── Database singleton ─────────────────────────────────────────────────────────

_db: Optional[aiosqlite.Connection] = None
_lock = asyncio.Lock()


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        _db = await aiosqlite.connect(config.DB_PATH)
        _db.row_factory = aiosqlite.Row
        await _migrate(_db)
    return _db


async def _migrate(db: aiosqlite.Connection) -> None:
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            access_key  TEXT    UNIQUE NOT NULL,
            label       TEXT    NOT NULL DEFAULT '',
            created_at  REAL    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS launched_memes (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    REAL    NOT NULL,
            name         TEXT    NOT NULL,
            ticker       TEXT    NOT NULL,
            source       TEXT    NOT NULL,
            meme_url     TEXT    NOT NULL,
            image_url    TEXT    NOT NULL DEFAULT '',
            description  TEXT    NOT NULL DEFAULT '',
            tx_sig       TEXT    NOT NULL DEFAULT '',
            mint_address TEXT    NOT NULL DEFAULT '',
            status       TEXT    NOT NULL DEFAULT 'PENDING',
            sol_spent    REAL    NOT NULL DEFAULT 0.0,
            error        TEXT    NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS kym_seen (
            url          TEXT PRIMARY KEY,
            first_seen   REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS launch_history (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    REAL    NOT NULL,
            total_count  INTEGER NOT NULL
        );
    """)
    await db.commit()

    # Add account_id columns to existing tables if not present
    for stmt in (
        "ALTER TABLE launched_memes ADD COLUMN account_id INTEGER REFERENCES accounts(id)",
        "ALTER TABLE launch_history ADD COLUMN account_id INTEGER REFERENCES accounts(id)",
    ):
        try:
            await db.execute(stmt)
            await db.commit()
        except Exception:
            pass


# ── Account operations ─────────────────────────────────────────────────────────

async def create_account(label: str = "") -> Account:
    db = await get_db()
    key = secrets.token_urlsafe(32)
    now = time.time()
    async with _lock:
        cur = await db.execute(
            "INSERT INTO accounts (access_key, label, created_at) VALUES (?,?,?)",
            (key, label, now),
        )
        await db.commit()
        return Account(id=cur.lastrowid, access_key=key, label=label, created_at=now)


async def get_account_by_key(access_key: str) -> Optional[Account]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM accounts WHERE access_key=?", (access_key,)
    )
    if not rows:
        return None
    r = rows[0]
    return Account(id=r["id"], access_key=r["access_key"], label=r["label"], created_at=r["created_at"])


async def get_all_accounts() -> List[Account]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM accounts ORDER BY created_at DESC"
    )
    return [Account(id=r["id"], access_key=r["access_key"], label=r["label"], created_at=r["created_at"]) for r in rows]


async def delete_account(account_id: int) -> None:
    db = await get_db()
    async with _lock:
        await db.execute("DELETE FROM accounts WHERE id=?", (account_id,))
        await db.commit()


# ── Launch operations ──────────────────────────────────────────────────────────

async def insert_launch(launch: Launch) -> int:
    db = await get_db()
    async with _lock:
        cur = await db.execute(
            """INSERT INTO launched_memes
               (timestamp, name, ticker, source, meme_url, image_url,
                description, tx_sig, mint_address, status, sol_spent, error, account_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (launch.timestamp, launch.name, launch.ticker, launch.source,
             launch.meme_url, launch.image_url, launch.description,
             launch.tx_sig, launch.mint_address, launch.status,
             launch.sol_spent, launch.error, launch.account_id),
        )
        await db.commit()
        return cur.lastrowid


async def get_launches(limit: int = 50, account_id: Optional[int] = None) -> List[Launch]:
    db = await get_db()
    if account_id is not None:
        rows = await db.execute_fetchall(
            "SELECT * FROM launched_memes WHERE account_id=? ORDER BY timestamp DESC LIMIT ?",
            (account_id, limit),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM launched_memes ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
    return [_row_to_launch(r) for r in rows]


async def get_today_launches(account_id: Optional[int] = None) -> List[Launch]:
    db = await get_db()
    midnight = time.time() - (time.time() % 86400)
    if account_id is not None:
        rows = await db.execute_fetchall(
            "SELECT * FROM launched_memes WHERE timestamp >= ? AND account_id=? ORDER BY timestamp DESC",
            (midnight, account_id),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT * FROM launched_memes WHERE timestamp >= ? ORDER BY timestamp DESC",
            (midnight,),
        )
    return [_row_to_launch(r) for r in rows]


async def get_total_launches(account_id: Optional[int] = None) -> int:
    db = await get_db()
    if account_id is not None:
        rows = await db.execute_fetchall(
            "SELECT COUNT(*) AS cnt FROM launched_memes WHERE status IN ('LAUNCHED','DRY_RUN') AND account_id=?",
            (account_id,),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT COUNT(*) AS cnt FROM launched_memes WHERE status IN ('LAUNCHED','DRY_RUN')"
        )
    return int(rows[0]["cnt"]) if rows else 0


async def get_total_sol_spent(account_id: Optional[int] = None) -> float:
    db = await get_db()
    if account_id is not None:
        rows = await db.execute_fetchall(
            "SELECT COALESCE(SUM(sol_spent),0) AS total FROM launched_memes WHERE status='LAUNCHED' AND account_id=?",
            (account_id,),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT COALESCE(SUM(sol_spent),0) AS total FROM launched_memes WHERE status='LAUNCHED'"
        )
    return float(rows[0]["total"]) if rows else 0.0


# ── KYM dedup ──────────────────────────────────────────────────────────────────

async def is_meme_seen(url: str) -> bool:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT url FROM kym_seen WHERE url=?", (url,)
    )
    return len(rows) > 0


async def mark_meme_seen(url: str) -> None:
    db = await get_db()
    async with _lock:
        await db.execute(
            "INSERT OR IGNORE INTO kym_seen (url, first_seen) VALUES (?,?)",
            (url, time.time()),
        )
        await db.commit()


# ── Launch history (for chart) ─────────────────────────────────────────────────

async def snapshot_launch_count(account_id: Optional[int] = None) -> None:
    db = await get_db()
    total = await get_total_launches(account_id)
    async with _lock:
        await db.execute(
            "INSERT INTO launch_history (timestamp, total_count, account_id) VALUES (?,?,?)",
            (time.time(), total, account_id),
        )
        await db.commit()


async def get_launch_history(limit: int = 200, account_id: Optional[int] = None) -> List[LaunchSnapshot]:
    db = await get_db()
    if account_id is not None:
        rows = await db.execute_fetchall(
            "SELECT timestamp, total_count FROM launch_history WHERE account_id=? ORDER BY timestamp DESC LIMIT ?",
            (account_id, limit),
        )
    else:
        rows = await db.execute_fetchall(
            "SELECT timestamp, total_count FROM launch_history ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
    return [LaunchSnapshot(r["timestamp"], r["total_count"]) for r in reversed(rows)]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _row_to_launch(row) -> Launch:
    return Launch(
        id=row["id"],
        timestamp=row["timestamp"],
        name=row["name"],
        ticker=row["ticker"],
        source=row["source"],
        meme_url=row["meme_url"],
        image_url=row["image_url"],
        description=row["description"],
        tx_sig=row["tx_sig"],
        mint_address=row["mint_address"],
        status=row["status"],
        sol_spent=row["sol_spent"],
        error=row["error"],
        account_id=row["account_id"] if "account_id" in row.keys() else None,
    )
