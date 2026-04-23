"""Central configuration — loaded once from .env on startup."""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Solana / pump.fun ──────────────────────────────────────────────────────────
SOLANA_RPC_URL: str = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
# Base58 string or JSON byte array [1,2,...,64] — set once via dashboard
SOLANA_PRIVATE_KEY: str = os.getenv("SOLANA_PRIVATE_KEY", "")
PUMPFUN_INITIAL_BUY_SOL: float = float(os.getenv("PUMPFUN_INITIAL_BUY_SOL", "0.0001"))
PUMPFUN_PRIORITY_FEE: float = float(os.getenv("PUMPFUN_PRIORITY_FEE", "0.0005"))
PUMPFUN_SLIPPAGE: int = int(os.getenv("PUMPFUN_SLIPPAGE", "10"))

# ── KnowYourMeme scraping ──────────────────────────────────────────────────────
KYM_CATEGORIES: list = ["confirmed", "submission", "newsworthy", "deadpool"]
KYM_MAX_ENTRIES_PER_CATEGORY: int = int(os.getenv("KYM_MAX_ENTRIES_PER_CATEGORY", "100"))

# ── Launch control ─────────────────────────────────────────────────────────────
MAX_LAUNCHES_PER_CYCLE: int = int(os.getenv("MAX_LAUNCHES_PER_CYCLE", "3"))
DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() == "true"  # safe default
# SIMULATE=true runs the full launch path (IPFS upload, tx build, sign) but submits
# simulateTransaction instead of sendTransaction — no SOL spent, no on-chain state.
# Only honored when DRY_RUN=false. Use it to validate the real deploy flow.
SIMULATE: bool = os.getenv("SIMULATE", "false").lower() == "true"

# ── Timing ─────────────────────────────────────────────────────────────────────
SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))  # 5 min
DASHBOARD_REFRESH_SECONDS: float = float(os.getenv("DASHBOARD_REFRESH_SECONDS", "2.0"))

# ── Telegram ───────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Database ───────────────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "tyrant_launches.db")

# ── Misc ───────────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
