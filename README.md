# PULSE//BOT — Weather Market Alpha Engine

> Autonomous trading bot for Polymarket weather prediction markets.
> Terminal-style dashboard with real-time P&L, risk management, and Telegram alerts.

```
 ██████╗ ██╗   ██╗██╗     ███████╗███████╗
 ██╔══██╗██║   ██║██║     ██╔════╝██╔════╝
 ██████╔╝██║   ██║██║     ███████╗█████╗
 ██╔═══╝ ██║   ██║██║     ╚════██║██╔══╝
 ██║     ╚██████╔╝███████╗███████║███████╗
 ╚═╝      ╚═════╝ ╚══════╝╚══════╝╚══════╝
```

---

## Architecture

```
pulse/
├── config.py              — All settings, loaded from .env
├── main.py                — Entry point + orchestration loop
│
├── data/
│   ├── weather.py         — Open-Meteo GFS forecasts (async, cached)
│   └── models.py          — Gaussian + ensemble probability models
│
├── market/
│   ├── polymarket.py      — Polymarket CLOB API client wrapper
│   ├── parser.py          — Market title → structured data (city, date, temp)
│   └── scanner.py         — Full scan pipeline → Opportunity list
│
├── trading/
│   ├── edge.py            — Edge calculation helpers
│   ├── kelly.py           — Fractional Kelly criterion sizing
│   ├── execution.py       — Order placement with FOK + fallback
│   └── risk.py            — Daily loss / drawdown / circuit breaker
│
├── db/
│   └── database.py        — Async SQLite (aiosqlite) for trade logging
│
├── alerts/
│   └── telegram.py        — Trade + daily summary Telegram notifications
│
└── dashboard/
    ├── app.py             — Textual TUI application
    └── widgets/
        ├── equity_chart.py — ASCII P&L equity curve
        ├── log_panel.py    — Scrolling system log
        ├── trades_panel.py — Active trades table
        ├── stats_panel.py  — Win rate, drawdown, exposure metrics
        └── heatmap.py      — City activity heatmap + exec log
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
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Configure `.env`

```bash
# Minimum required for DRY RUN (no real money):
DRY_RUN=true
INITIAL_CAPITAL=1000.0

# Required for LIVE trading:
PRIVATE_KEY=0xYOUR_WALLET_PRIVATE_KEY
POLY_API_KEY=...
POLY_API_SECRET=...
POLY_API_PASSPHRASE=...

# Optional: Telegram alerts
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### 3. Generate Polymarket API Keys

```python
# Run once to generate your API credentials:
from py_clob_client.client import ClobClient

client = ClobClient(
    host="https://clob.polymarket.com",
    chain_id=137,
    key="0xYOUR_PRIVATE_KEY",
)
creds = client.create_or_derive_api_creds()
print(creds)
# Save the api_key, api_secret, api_passphrase to your .env
```

### 4. Run

```bash
source .venv/bin/activate
python -m pulse.main
```

---

## Dashboard Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  PULSE//BOT  │  2024-04-15 14:23:07 UTC  │  UP 02:15:43  │  DRY RUN │
├─────────────┬───────────────────────────────────────┬───────────────┤
│ SYSTEM LOG  │                                       │ ACTIVE TRADES │
│             │         EQUITY CURVE                  │               │
│ 14:23:01 ✓  │  ●                                    │ Miami    YES  │
│ [OK   ] ... │   ●●●    ●●                           │ Phoenix  NO   │
│ 14:23:05 ⟳  │      ●●●●  ●●●●●●                    │ Chicago  YES  │
│ [SCAN ] ... │                                       │               │
│ 14:23:07 ◈  │  EQUITY: $1,082.50  P&L: +$82.50     │               │
│ [TRADE] ... │                                       │               │
├─────────────┴───────────────────────────────────────┴───────────────┤
│  TOTAL P&L  +$82.50  │  TODAY  +$12.00  │  EQUITY  $1,082.50        │
├─────────────────────────────────────────────────────────────────────┤
│ TOTAL P&L   TODAY P&L   EQUITY   WIN RATE   AVG PROFIT   EXPOSURE   │
│ +$82.50     +$12.00     $1082    62.5%      +$8.25       $200        │
│ TRADES      WINS/LOSS   DRAWDOWN CONSEC LOS CIRCUIT      SCANS       │
│ 16          10/6        2.1%     0          ● CLOSED      47         │
├──────────────────────────────────┬──────────────────────────────────┤
│ EXECUTION LOG                    │ CITY ACTIVITY                    │
│ 14:23:07 [ENTRY  ] Miami   YES @ │ MIA:███ 3  PHX:█ 1  CHI:██ 2   │
│ 14:23:08 [EXEC   ] Miami   order │ NYC:  0   LAX:█ 1  HOU:  0     │
│ 14:23:09 [FILLED ] Miami  +$4.20 │ DAL:  0   SEA:  0              │
└──────────────────────────────────┴──────────────────────────────────┘
```

**Keybindings:**
| Key | Action |
|-----|--------|
| `q` | Quit |
| `r` | Reset circuit breaker |
| `c` | Clear system log |
| `l` | Toggle live/dry run mode |

---

## Trading Logic

### Edge Calculation

```
edge = model_probability - market_implied_probability

Model prob:  Gaussian fit to Open-Meteo GFS ensemble (30 members)
Market prob: Polymarket YES token price (0–1)

Only trade when: |edge| > MIN_EDGE_THRESHOLD (default 8%)
```

### Position Sizing (Fractional Kelly)

```
full_kelly  = (p * b - q) / b     where b = (1-price)/price
trade_size  = bankroll × full_kelly × KELLY_FRACTION
capped_size = min(trade_size, MAX_TRADE_SIZE_USD)
```

### Risk Rules

| Rule | Default | Description |
|------|---------|-------------|
| Daily loss limit | $200 | Stops trading for the day |
| Max drawdown | 15% | Trips circuit breaker |
| Consecutive losses | 5 | Trips circuit breaker |
| Max exposure | $1,000 | Total open position cap |
| One trade per event | Always | No duplicates per city+date |

---

## Weather Data

Forecasts come from [Open-Meteo](https://open-meteo.com/) — **free, no API key**.

- Model: GFS Seamless (updated 4x daily)
- Ensemble: 30 members for probability distribution
- Locations: 8 US cities (configurable in `config.py`)
- Cache TTL: 5 minutes (matches scan interval)
- Fallback: Gaussian distribution (mean ± 3.5°F) if ensemble unavailable

---

## Disclaimer

This software is for educational and research purposes.
Prediction market trading involves financial risk.
Always start with `DRY_RUN=true` and understand the system before enabling live trading.
Past performance does not guarantee future results.
