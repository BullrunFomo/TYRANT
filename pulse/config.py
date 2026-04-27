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

# ── IPFS (Pinata) ──────────────────────────────────────────────────────────────
# Pump.fun's old /api/ipfs is deprecated. Get a free JWT at https://pinata.cloud
# (Profile → API Keys → New Key → "Pinning service" scope → copy JWT).
PINATA_JWT: str = os.getenv("PINATA_JWT", "")
# Optional dedicated Pinata gateway (Pinata → Gateways → copy the subdomain,
# e.g. "turquoise-immediate-lobster-357.mypinata.cloud"). Strongly recommended:
# fresh CIDs are served instantly here, while public ipfs.io can take 30-60s to
# propagate, which makes pumpportal reject the URI as unreachable.
PINATA_GATEWAY: str = os.getenv("PINATA_GATEWAY", "").strip().rstrip("/")

# ── KnowYourMeme scraping ──────────────────────────────────────────────────────
KYM_CATEGORIES: list = ["confirmed", "submission", "newsworthy", "deadpool"]
KYM_MAX_ENTRIES_PER_CATEGORY: int = int(os.getenv("KYM_MAX_ENTRIES_PER_CATEGORY", "100"))

# ── Launch control ─────────────────────────────────────────────────────────────
MAX_LAUNCHES_PER_CYCLE: int = int(os.getenv("MAX_LAUNCHES_PER_CYCLE", "3"))
# Failed launches retry on the next cycle. After this many FAILED attempts
# on the same meme, give up and mark seen so it stops blocking the queue.
MAX_LAUNCH_RETRIES: int = int(os.getenv("MAX_LAUNCH_RETRIES", "3"))
DRY_RUN: bool = os.getenv("DRY_RUN", "true").lower() == "true"  # safe default
# SIMULATE=true runs the full launch path (IPFS upload, tx build, sign) but submits
# simulateTransaction instead of sendTransaction — no SOL spent, no on-chain state.
# Only honored when DRY_RUN=false. Use it to validate the real deploy flow.
SIMULATE: bool = os.getenv("SIMULATE", "false").lower() == "true"

# ── Timing ─────────────────────────────────────────────────────────────────────
SCAN_INTERVAL_SECONDS: int = int(os.getenv("SCAN_INTERVAL_SECONDS", "300"))  # 5 min
DASHBOARD_REFRESH_SECONDS: float = float(os.getenv("DASHBOARD_REFRESH_SECONDS", "2.0"))

# ── Database ───────────────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "tyrant_launches.db")

# ── Misc ───────────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
