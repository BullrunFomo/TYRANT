"""Async SQLite persistence for meme launches and KYM dedup tracking."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import List, Optional

import aiosqlite

from pulse import config


# ── Data classes ───────────────────────────────────────────────────────────────

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


# ── Launch operations ──────────────────────────────────────────────────────────

async def insert_launch(launch: Launch) -> int:
    db = await get_db()
    async with _lock:
        cur = await db.execute(
            """INSERT INTO launched_memes
               (timestamp, name, ticker, source, meme_url, image_url,
                description, tx_sig, mint_address, status, sol_spent, error)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (launch.timestamp, launch.name, launch.ticker, launch.source,
             launch.meme_url, launch.image_url, launch.description,
             launch.tx_sig, launch.mint_address, launch.status,
             launch.sol_spent, launch.error),
        )
        await db.commit()
        return cur.lastrowid


async def get_launches(limit: int = 50) -> List[Launch]:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM launched_memes ORDER BY timestamp DESC LIMIT ?", (limit,)
    )
    return [_row_to_launch(r) for r in rows]


async def get_today_launches() -> List[Launch]:
    db = await get_db()
    midnight = time.time() - (time.time() % 86400)
    rows = await db.execute_fetchall(
        "SELECT * FROM launched_memes WHERE timestamp >= ? ORDER BY timestamp DESC",
        (midnight,),
    )
    return [_row_to_launch(r) for r in rows]


async def get_total_launches() -> int:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT COUNT(*) AS cnt FROM launched_memes "
        "WHERE status IN ('LAUNCHED','SIMULATED','DRY_RUN')"
    )
    return int(rows[0]["cnt"]) if rows else 0


async def get_total_sol_spent() -> float:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT COALESCE(SUM(sol_spent),0) AS total FROM launched_memes WHERE status='LAUNCHED'"
    )
    return float(rows[0]["total"]) if rows else 0.0


# ── KYM dedup ──────────────────────────────────────────────────────────────────

async def is_meme_seen(url: str, ttl_seconds: int = 7 * 86400) -> bool:
    """True if this URL was seen within `ttl_seconds`. After the TTL expires
    the same meme becomes eligible again — semantic dedup at launch-time keeps
    near-duplicates out within the window.
    """
    db = await get_db()
    cutoff = time.time() - ttl_seconds
    rows = await db.execute_fetchall(
        "SELECT url FROM kym_seen WHERE url=? AND first_seen >= ?",
        (url, cutoff),
    )
    return len(rows) > 0


async def mark_meme_seen(url: str) -> None:
    """Record the URL with the current timestamp. Subsequent calls refresh the
    timestamp so re-attempts within a session don't get a stale `first_seen`.
    """
    db = await get_db()
    async with _lock:
        await db.execute(
            "INSERT INTO kym_seen (url, first_seen) VALUES (?, ?) "
            "ON CONFLICT(url) DO UPDATE SET first_seen = excluded.first_seen",
            (url, time.time()),
        )
        await db.commit()


async def get_recent_launches(within_seconds: int = 7 * 86400, limit: int = 100) -> List[Launch]:
    """Successful launches in the past `within_seconds`. Used by semantic dedup
    to compare a candidate against the recent launch history.
    """
    db = await get_db()
    cutoff = time.time() - within_seconds
    rows = await db.execute_fetchall(
        "SELECT * FROM launched_memes "
        "WHERE timestamp >= ? AND status IN ('LAUNCHED','SIMULATED','DRY_RUN') "
        "ORDER BY timestamp DESC LIMIT ?",
        (cutoff, limit),
    )
    return [_row_to_launch(r) for r in rows]


async def count_failed_launches(meme_url: str) -> int:
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT COUNT(*) AS cnt FROM launched_memes "
        "WHERE meme_url = ? AND status = 'FAILED'",
        (meme_url,),
    )
    return int(rows[0]["cnt"]) if rows else 0


# ── Launch history (for chart) ─────────────────────────────────────────────────

async def snapshot_launch_count() -> None:
    db = await get_db()
    total = await get_total_launches()
    async with _lock:
        await db.execute(
            "INSERT INTO launch_history (timestamp, total_count) VALUES (?,?)",
            (time.time(), total),
        )
        await db.commit()


async def get_launch_history(limit: int = 200) -> List[LaunchSnapshot]:
    db = await get_db()
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
    )
