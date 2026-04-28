"""
FastAPI web server — serves the dashboard and broadcasts real-time events
to all connected browsers via WebSocket.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Deque, List, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from pulse import config

_startup_handlers: List[Callable] = []


def register_startup(fn: Callable) -> Callable:
    _startup_handlers.append(fn)
    return fn


@asynccontextmanager
async def _lifespan(app: FastAPI):
    for fn in _startup_handlers:
        await fn()
    yield


app = FastAPI(title="TYRANT//BOT", lifespan=_lifespan, docs_url=None, redoc_url=None)


# ── WebSocket connection manager ───────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, data: dict):
        msg = json.dumps(data)
        dead = set()
        for ws in self.active:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        self.active -= dead


manager = ConnectionManager()
_log_buffer: Deque[dict] = deque(maxlen=200)


# ── Public emit helpers (called by the main loop) ──────────────────────────────

async def emit_log(msg: str, level: str = "INFO"):
    entry = {"type": "log", "level": level, "msg": msg, "ts": time.time()}
    _log_buffer.append(entry)
    await manager.broadcast(entry)


async def emit_exec(tag: str, city: str, detail: str):
    await manager.broadcast({"type": "exec", "tag": tag,
                              "city": city, "detail": detail,
                              "ts": time.time()})


async def emit_stats(stats: dict):
    await manager.broadcast({"type": "stats", "stats": stats})


async def emit_pnl_history(data):
    if isinstance(data, dict):
        await manager.broadcast({"type": "pnl_history", **data})
    else:
        await manager.broadcast({"type": "pnl_history", "values": data, "timestamps": []})


async def emit_trade(data: dict):
    """Compatibility shim — broadcasts a launch record as a 'trade' event."""
    await manager.broadcast({"type": "trade", "trade": data})


# ── REST endpoints ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    html_path = Path(__file__).parent / "dashboard.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/docs", response_class=HTMLResponse)
async def docs_page():
    html_path = Path(__file__).parent / "docs.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/api/stats")
async def get_stats():
    from pulse.db import database as db
    total = await db.get_total_launches()
    today = await db.get_today_launches()
    sol = await db.get_total_sol_spent()
    launches = await db.get_launches(200)
    n_ok = sum(1 for l in launches if l.status in ("LAUNCHED", "SIMULATED", "DRY_RUN"))
    n_fail = sum(1 for l in launches if l.status == "FAILED")
    n_real_ok = sum(1 for l in launches if l.status in ("LAUNCHED", "SIMULATED"))
    n_real_attempts = n_real_ok + n_fail
    return {
        "total_launches": total,
        "today_launches": len(today),
        "sol_spent": sol,
        "n_ok": n_ok,
        "n_fail": n_fail,
        "n_real_attempts": n_real_attempts,
        "success_rate": (n_real_ok / n_real_attempts) if n_real_attempts else 0.0,
        "dry_run": config.DRY_RUN,
    }


@app.get("/api/launches")
async def get_launches():
    from pulse.db import database as db
    launches = await db.get_launches(50)
    return [_launch_dict(l) for l in launches]


@app.get("/api/pnl-history")
async def get_pnl_history():
    from pulse.db import database as db
    history = await db.get_launch_history(200)
    return {
        "timestamps": [h.timestamp for h in history],
        "values": [float(h.count) for h in history],
    }


@app.get("/api/wallet-balance")
async def get_wallet_balance():
    """Return the SOL balance of the configured wallet, or null if no wallet set."""
    if not config.SOLANA_PRIVATE_KEY:
        return {"balance": None}
    try:
        import json as _json
        import aiohttp
        from solders.keypair import Keypair

        raw = config.SOLANA_PRIVATE_KEY.strip()
        if raw.startswith("["):
            kp = Keypair.from_bytes(bytes(_json.loads(raw)))
        else:
            kp = Keypair.from_base58_string(raw)
        pubkey = str(kp.pubkey())

        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "getBalance",
            "params": [pubkey, {"commitment": "confirmed"}],
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(
                config.SOLANA_RPC_URL,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                lamports = data.get("result", {}).get("value", 0)
                return {"balance": lamports / 1_000_000_000, "pubkey": pubkey}
    except Exception as exc:
        return {"balance": None, "error": str(exc)}


@app.get("/api/config")
async def get_config_endpoint():
    return {
        "DRY_RUN": config.DRY_RUN,
        "SCAN_INTERVAL_SECONDS": config.SCAN_INTERVAL_SECONDS,
        "MAX_LAUNCHES_PER_CYCLE": config.MAX_LAUNCHES_PER_CYCLE,
        "PUMPFUN_INITIAL_BUY_SOL": config.PUMPFUN_INITIAL_BUY_SOL,
        "PUMPFUN_PRIORITY_FEE": config.PUMPFUN_PRIORITY_FEE,
        "SOLANA_RPC_URL": config.SOLANA_RPC_URL,
        "KYM_MAX_ENTRIES_PER_CATEGORY": config.KYM_MAX_ENTRIES_PER_CATEGORY,
        "KYM_CATEGORIES": config.KYM_CATEGORIES,
        "SOLANA_PRIVATE_KEY": bool(config.SOLANA_PRIVATE_KEY),  # presence only, never expose key
    }


@app.post("/api/config")
async def set_config_endpoint(data: dict):
    _BOOL  = {"DRY_RUN"}
    _FLOAT = {"PUMPFUN_INITIAL_BUY_SOL", "PUMPFUN_PRIORITY_FEE"}
    _INT   = {"SCAN_INTERVAL_SECONDS", "MAX_LAUNCHES_PER_CYCLE",
              "KYM_MAX_ENTRIES_PER_CATEGORY"}
    _STR   = {"SOLANA_RPC_URL", "SOLANA_PRIVATE_KEY"}
    _LIST  = {"KYM_CATEGORIES"}

    for key, value in data.items():
        if not hasattr(config, key):
            continue
        if key in _BOOL:
            value = bool(value)
        elif key in _FLOAT:
            value = float(value)
        elif key in _INT:
            value = int(value)
        elif key in _LIST:
            value = list(value) if isinstance(value, list) else value
        setattr(config, key, value)

    _write_env(data)
    return {"ok": True}


def _write_env(updates: dict):
    from pathlib import Path
    env_path = Path(__file__).parent.parent.parent / ".env"
    if not env_path.exists():
        # Create from .env.example if available, otherwise start fresh
        example = env_path.parent / ".env.example"
        if example.exists():
            import shutil
            shutil.copy(example, env_path)
        else:
            env_path.write_text("", encoding="utf-8")
    lines = env_path.read_text(encoding="utf-8").splitlines()
    written: set = set()
    result = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                val = updates[key]
                if isinstance(val, bool):
                    val = str(val).lower()
                result.append(f"{key}={val}")
                written.add(key)
                continue
        result.append(line)
    for key, val in updates.items():
        if key not in written:
            if isinstance(val, bool):
                val = str(val).lower()
            result.append(f"{key}={val}")
    env_path.write_text("\n".join(result) + "\n", encoding="utf-8")


# ── WebSocket ──────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        from pulse.db import database as db
        total = await db.get_total_launches()
        today = await db.get_today_launches()
        sol = await db.get_total_sol_spent()
        launches = await db.get_launches(30)
        history = await db.get_launch_history(200)
        n_ok = sum(1 for l in launches if l.status in ("LAUNCHED", "SIMULATED", "DRY_RUN"))
        n_fail = sum(1 for l in launches if l.status == "FAILED")
        n_real_ok = sum(1 for l in launches if l.status in ("LAUNCHED", "SIMULATED"))
        n_real_attempts = n_real_ok + n_fail

        await ws.send_text(json.dumps({
            "type": "init",
            "stats": {
                "total_launches": total,
                "today_launches": len(today),
                "sol_spent": sol,
                "n_ok": n_ok,
                "n_fail": n_fail,
                "n_real_attempts": n_real_attempts,
                "success_rate": (n_real_ok / n_real_attempts) if n_real_attempts else 0.0,
                "dry_run": config.DRY_RUN,
            },
            "pnl_history": {
                "timestamps": [h.timestamp for h in history],
                "values": [float(h.count) for h in history],
            },
            "trades": [_launch_dict(l) for l in launches],
            "log_history": list(_log_buffer),
        }))
    except Exception:
        pass

    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _launch_dict(l) -> dict:
    return {
        "id": l.id,
        "timestamp": l.timestamp,
        "name": l.name,
        "ticker": l.ticker,
        "source": l.source,
        "meme_url": l.meme_url,
        "image_url": l.image_url,
        "tx_sig": l.tx_sig,
        "mint_address": l.mint_address,
        "status": l.status,
        "sol_spent": l.sol_spent,
    }
