"""Central configuration — loaded once from .env on startup."""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Solana / pump.fun ──────────────────────────────────────────────────────────
SOLANA_RPC_URL: str = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
# Base58 string or JSON byte array [1,2,...,64] — set once via dashboard
SOLANA_PRIVATE_KEY: str = os.getenv("SOLANA_PRIVATE_KEY", "")
PUMPFUN_INITIAL_BUY_SOL: float = float(os.getenv("PUMPFUN_INITIAL_BUY_SOL", "0.0001"))
# Dev buy: purchased in the same tx as the create, then sold after DEV_SELL_DELAY_SECONDS.
DEV_BUY_SOL: float = float(os.getenv("DEV_BUY_SOL", "0.1"))
DEV_SELL_DELAY_SECONDS: int = int(os.getenv("DEV_SELL_DELAY_SECONDS", "5"))
PUMPFUN_PRIORITY_FEE: float = float(os.getenv("PUMPFUN_PRIORITY_FEE", "0.0005"))
PUMPFUN_SLIPPAGE: int = int(os.getenv("PUMPFUN_SLIPPAGE", "5"))

# ── Jito (atomic create + dev-buy bundle) ─────────────────────────────────────
# In live mode the create tx and buy tx ship as a Jito bundle so they land in
# the same block atomically. The tip (last instruction of the buy tx) goes to
# one of Jito's 8 tip accounts.
JITO_BUNDLE_URL: str = os.getenv(
    "JITO_BUNDLE_URL", "https://frankfurt.mainnet.block-engine.jito.wtf/api/v1/bundles"
)
JITO_TIP_LAMPORTS: int = int(os.getenv("JITO_TIP_LAMPORTS", "10000"))

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
# Only confirmed + submission feed the launch queue. Newsworthy/deadpool are noise.
KYM_CATEGORIES: list = ["confirmed", "submission"]
KYM_MAX_ENTRIES_PER_CATEGORY: int = int(os.getenv("KYM_MAX_ENTRIES_PER_CATEGORY", "100"))
# How many newest entries to pull from each KYM category at startup. Default
# is 1 (= last confirmed + last submission). The remaining current entries are
# marked seen at startup so the scanner only picks up genuinely new memes that
# appear AFTER the bot is running, instead of flooding the queue with backlog.
STARTUP_SEED_PER_CATEGORY: int = int(os.getenv("STARTUP_SEED_PER_CATEGORY", "1"))

# ── Launch control ─────────────────────────────────────────────────────────────
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
# Minimum gap between successive launches (seconds). Pace control: even if the
# queue has 10 entries we still launch one per LAUNCH_INTERVAL_SECONDS.
LAUNCH_INTERVAL_SECONDS: int = int(os.getenv("LAUNCH_INTERVAL_SECONDS", "300"))  # 5 min
DASHBOARD_REFRESH_SECONDS: float = float(os.getenv("DASHBOARD_REFRESH_SECONDS", "2.0"))

# ── OpenRouter (AI naming / description / quality) ────────────────────────────
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "").strip()
OPENROUTER_BASE_URL: str = os.getenv(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
).rstrip("/")
# Per-task model override. Defaults are tuned for cost: Haiku for creative writes,
# Gemini Flash (cheap vision) for the quality gate.
OPENROUTER_MODEL_NAMING: str = os.getenv("OPENROUTER_MODEL_NAMING", "anthropic/claude-haiku-4.5")
OPENROUTER_MODEL_DESCRIPTION: str = os.getenv("OPENROUTER_MODEL_DESCRIPTION", "anthropic/claude-haiku-4.5")
OPENROUTER_MODEL_QUALITY: str = os.getenv("OPENROUTER_MODEL_QUALITY", "google/gemini-2.5-flash")
OPENROUTER_MODEL_DEDUPE: str = os.getenv("OPENROUTER_MODEL_DEDUPE", "anthropic/claude-haiku-4.5")
# Toggle each AI step. Quality gate is OFF by default (KYM is curated already).
NAMING_ENABLED: bool = os.getenv("NAMING_ENABLED", "true").lower() == "true"
DESCRIPTION_ENABLED: bool = os.getenv("DESCRIPTION_ENABLED", "true").lower() == "true"
QUALITY_GATE_ENABLED: bool = os.getenv("QUALITY_GATE_ENABLED", "false").lower() == "true"
DEDUPE_ENABLED: bool = os.getenv("DEDUPE_ENABLED", "true").lower() == "true"
# How far back semantic dedup looks. After this window passes, a meme
# (same URL or near-duplicate) becomes eligible to relaunch. Default 7 days.
DEDUPE_WINDOW_SECONDS: int = int(os.getenv("DEDUPE_WINDOW_SECONDS", str(7 * 86400)))
# Optional referer/title for OpenRouter analytics (visible on their dashboard).
OPENROUTER_REFERER: str = os.getenv("OPENROUTER_REFERER", "https://github.com/tyrant-bot")
OPENROUTER_TITLE: str = os.getenv("OPENROUTER_TITLE", "TYRANT//BOT")

# ── Database ───────────────────────────────────────────────────────────────────
DB_PATH: str = os.getenv("DB_PATH", "tyrant_launches.db")

# ── Misc ───────────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
