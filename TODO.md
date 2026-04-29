# TYRANT — TODO

Open work items, ordered by priority (highest first).

---

## 1. AI-generated names + tickers (Claude Haiku 4.5)

**Why:** current `make_ticker()` is algorithmic — produces ugly initials like `CTCBCP` for "Cryana Twitch Chat Badge Controversy (Pragmata)". And token names are the raw KYM titles, often clunky. AI rewriting will give launches actual marketing punch.

**Plan:**
- New module `pulse/launchers/naming.py` exposing `async def generate_name_and_ticker(title, description, source) -> (name, ticker)`.
- Raw aiohttp `POST https://api.anthropic.com/v1/messages` (no SDK — matches project pattern).
- Headers: `x-api-key`, `anthropic-version: 2023-06-01`, `content-type: application/json`.
- Model: `claude-haiku-4-5` (alias).
- JSON output via `output_config.format` with a `json_schema` of `{name: str ≤32, ticker: str 3–6 uppercase}`.
- System prompt: pump.fun-savvy meme-naming rules — punchy, pronounceable, prefer puns/abbreviations over initials, no special chars beyond `.,!&`, ticker uppercase letters/digits only.
- **Fallback:** on API error/timeout/schema-invalid → algorithmic `make_ticker()` + raw KYM title. Loop never blocks on Claude.
- Wire into `web_main.py:70`: replace `ticker = make_ticker(entry.title)` with the helper, pass both AI name and ticker to `launch_token()`.
- Config: `ANTHROPIC_API_KEY` + `NAMING_MODEL` (default `claude-haiku-4-5`). Empty key → skip the call (graceful no-op).

**Cost:** ~$0.0004 per call (Haiku 4.5 at $1 input / $5 output per MTok, ~150 input + ~30 output tokens). 1000 launches ≈ $0.40.

**Caching note:** Haiku 4.5 minimum cacheable prefix is 4096 tokens. Our system prompt is ~300–500 tokens — caching won't activate at all (silent — no error, just `cache_creation_input_tokens: 0`). Don't bother adding `cache_control` markers; it's a no-op at this size.

**Open question:** does the user want me to implement now, or wait until they have the `ANTHROPIC_API_KEY` ready in `.env`?

---

## 2. Minimize per-launch SOL cost

**Why:** current cost is ~0.0153 SOL per round-trip (≈ $2.30 at $150 SOL). At 1 launch per 30s = ~120/hour = ~$275/hour. The fixed overheads (tip, priority fee, compute units) are tunable; some are over-provisioned.

**Current settings (`.env` + `pulse/config.py`):**
- `JITO_TIP_LAMPORTS=1000000` (0.001 SOL ≈ $0.15) — empirically lands; **untested below this**.
- `PUMPFUN_PRIORITY_FEE=0.0005` (default) — applied to both create and buy txs.
- `cu_limit_create=350_000`, `cu_limit_buy=200_000` — set as ceilings, **actual sim usage is ~117k and ~97k respectively**.
- `PUMPFUN_SLIPPAGE=5` (down from 10).

**Optimization plan:**

a. **Tip floor sweep.** We know 1M lands and 100k drops. Test 500k → 250k → 150k. Find the lowest tip that lands reliably (e.g. 9/10 attempts in 5 min). The Jito tip-floor API reports landed-tip percentiles — useful as a sanity check but not authoritative for free tier.

b. **Compute units tuning.** Lower `cu_limit_create` from 350k → 130k (sim shows 117k peak + 10% margin). Lower `cu_limit_buy` from 200k → 110k. Lower CU = lower priority fee paid (since `cu_price = priority_fee / cu_limit`).

c. **Priority fee floor sweep.** 0.0005 SOL is conservative. Test 0.0001 SOL — should still land in the same block as the Jito bundle since Jito tip drives inclusion. Priority fee mostly matters for the regular sell tx (sent via RPC, not Jito).

d. **Sell tx routing.** The dev-sell currently goes via regular RPC (Helius `sendTransaction`). It lands but has no special priority. Consider: (i) bundle the sell with a Jito tip too — adds ~0.0005 SOL but eliminates the no-confirm risk; or (ii) add `getSignatureStatuses` polling to confirm the sell, with retry on timeout.

e. **DEV_BUY_SOL roundtrip cost.** Currently 0.1 SOL in → ~0.099 SOL out (pump.fun trade fee + ~0.5% slippage on entry/exit). The launch fee itself is fixed regardless of buy size — so a smaller `DEV_BUY_SOL` (e.g. 0.01) gives better unit economics if the buy is just for "I created this token" signaling rather than serious position-taking.

**Target:** sub-0.005 SOL per launch (≈ $0.75) without losing reliability.

---

## 3. Token-fetching strategy — define what we actually want to launch

**Why:** we currently scrape three KYM RSS feeds (`confirmed`, `submission`, `newsworthy`) and launch the first new entry per cycle. This is naive on multiple axes:

- **Freshness:** by the time a meme is on KYM `confirmed`, it's days/weeks old. Pump.fun rewards being first to a viral wave, not last.
- **Quality signal:** we don't read KYM's view count, score, or "trending" status. A `confirmed` meme with 200 views is a worse launch than a `submission` with 50K views.
- **Source coverage:** KYM is one source. The biggest meme coins of 2025 came from Twitter/X clips, TikTok sounds, Reddit threads, and live events — not KYM.
- **Anti-spam:** no dedupe across launches of similar-themed memes; no blocklist for low-effort/offensive content; no rate-quality tradeoff.

**Plan — investigation phase (do this before building):**

a. **Audit current KYM data quality.** Sample the last 50 entries returned by each feed. For each: how old is the meme (origin date vs today)? What's the view count if KYM exposes it? Would a human launch this? Goal: ground-truth the assumption that KYM is a useful source at all.

b. **Survey alternative sources.** For each, write a one-pager: how to fetch (API or scrape), rate limits, quality signal, freshness. Candidates:
   - X/Twitter trending hashtags (X API v2 free tier is now severely limited; consider scraping or unofficial APIs)
   - Reddit `r/MemeEconomy`, `r/dankmemes`, `r/cryptocurrency` hot posts
   - Google Trends spike API
   - TikTok trending sounds/effects (no public API; needs scraping)
   - Solana Explorer / DEX Screener "trending tokens" — what's already pumping that we can ride
   - Pump.fun's own new-launch firehose (look at what's getting buys, mimic with variations)

c. **Define "good meme" criteria.** Concrete predicates:
   - **Freshness:** first appeared in the wild within last N hours (need to define N)
   - **Velocity:** mention rate increasing over last hour (not flat or declining)
   - **Reach:** hit some minimum exposure threshold (followers reached, upvote count, etc.)
   - **Originality:** not a near-duplicate of something we've already launched
   - **Launch fitness:** has a clear visual + short pithy name (memes that are essays don't pump-coin well)

d. **Scoring + selection logic.** Replace "first new entry per cycle" with a ranked queue: each candidate gets a score from the predicates above, top-K per cycle gets launched. Drop everything below a quality threshold rather than launching marginal candidates.

e. **Persistence.** Track launched memes (already in DB) — extend with the source signals that scored each one, so we can backtest "did high-velocity Twitter memes outperform high-view KYM memes" once we have data.

**Open question:** is the bot trying to (i) be first to viral memes for max upside, or (ii) consistent volume on mid-tier memes for fee farming? The data sources and scoring change a lot based on which.

---

## Reference — known constraints (don't relearn these)

- Jito free-tier `getInflightBundleStatuses` returns `Invalid` for bundles that actually landed. Don't trust it; use `getSignatureStatuses` on the buy sig (already done in `_wait_for_confirmation`).
- Pump.fun's public IDL is missing the `buyback_fee_recipients` remaining-accounts contract. The on-chain Anchor IDL (fetchable via the IDL PDA) has the full picture including error 6062 (`BuybackFeeRecipientMissing`).
- Token-2022 (not legacy SPL Token). When querying balances, ATAs don't always show up via `getTokenAccountsByOwner` immediately after a buy — derive the ATA and call `getTokenAccountBalance` directly with retries (already done in `_get_token_balance`).
