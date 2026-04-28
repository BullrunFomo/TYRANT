# TYRANT//BOT

> Autonomous KnowYourMeme → pump.fun token launcher.
> FastAPI web dashboard with live scan log, launch history, and in-browser config.

```
 ████████╗██╗   ██╗██████╗  █████╗ ███╗   ██╗████████╗
 ╚══██╔══╝╚██╗ ██╔╝██╔══██╗██╔══██╗████╗  ██║╚══██╔══╝
    ██║    ╚████╔╝ ██████╔╝███████║██╔██╗ ██║   ██║
    ██║     ╚██╔╝  ██╔══██╗██╔══██║██║╚██╗██║   ██║
    ██║      ██║   ██║  ██║██║  ██║██║ ╚████║   ██║
    ╚═╝      ╚═╝   ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝
```

---

## Architecture

```
pulse/
├── config.py                  — All settings, loaded from .env
├── web_main.py                — Entry point: FastAPI + scan-launch loop
│
├── data/
│   └── knowyourmeme.py        — KYM RSS scrape + og:image fallback
│
├── market/
│   └── meme_scanner.py        — Deduplicated stream of unseen memes
│
├── launchers/
│   └── pumpfun.py             — IPFS upload + create tx + sign/submit (or simulate)
│
├── db/
│   └── database.py            — Async SQLite (aiosqlite): launches + history
│
└── web/
    ├── server.py              — REST + WebSocket endpoints
    ├── dashboard.html         — Live dashboard UI
    └── docs.html              — Built-in API reference
```

---

## Quick Start

### 1. Setup

```bash
chmod +x setup.sh
./setup.sh
```

Or manually:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Configure `.env`

Minimum for DRY_RUN (nothing touches Solana):

```
DRY_RUN=true
SOLANA_RPC_URL=https://api.mainnet-beta.solana.com
```

For SIMULATE (full deploy path, no SOL spent — recommended before going live):

```
DRY_RUN=false
SIMULATE=true
SOLANA_PRIVATE_KEY=<base58 or JSON byte array>
SOLANA_RPC_URL=<private RPC recommended>
```

For LIVE:

```
DRY_RUN=false
SIMULATE=false
SOLANA_PRIVATE_KEY=<base58 or JSON byte array>
SOLANA_RPC_URL=<private RPC recommended>
PUMPFUN_INITIAL_BUY_SOL=0.0001
```

### 3. Run

```bash
source .venv/bin/activate
python -m pulse.web_main
```

Dashboard: http://localhost:8000 · API docs: http://localhost:8000/docs

---

## Run Modes

| Mode      | `DRY_RUN` | `SIMULATE` | Behavior                                                                 |
|-----------|-----------|------------|--------------------------------------------------------------------------|
| Dry run   | `true`    | any        | Full scrape/scoring, no IPFS upload, no tx. Records marked `DRY_RUN`.    |
| Simulate  | `false`   | `true`     | Full path executes. `simulateTransaction` instead of `sendTransaction`. No SOL spent. |
| Live      | `false`   | `false`    | Real pump.fun launch. Spends SOL.                                        |

---

## Running Locally (non-Railway)

- `PORT` is optional — defaults to `8000`.
- The dashboard binds to `0.0.0.0` — anyone on your LAN can reach it **and** the `/api/config` endpoint which can write `SOLANA_PRIVATE_KEY` to `.env`. Bind to `127.0.0.1` (edit `web_main.py`) or keep the machine off public networks.
- On macOS, prevent sleep-induced scan pauses: `caffeinate -i python -m pulse.web_main`.

---

## Disclaimer

Educational / research use. Launching tokens on pump.fun spends real SOL and carries financial and reputational risk. Always start with `DRY_RUN=true`, validate with `SIMULATE=true`, then do a single tiny live launch before scaling up.
