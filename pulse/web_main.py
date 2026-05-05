"""
TYRANT — Web dashboard entry point.

Runs FastAPI on localhost:8000 + two cooperating async loops:

  - scanner_loop  : every SCAN_INTERVAL_SECONDS, scrape KYM (confirmed +
                    submission), push new memes to the in-memory launch queue.
  - launcher_loop : every LAUNCH_INTERVAL_SECONDS (5 min default), pop ONE
                    meme from the queue, semantic-dedup against past-7d
                    launches, AI-rewrite name + description, launch.

Empty queue → no launch (just wait). Many queued → still one per interval.
On startup the queue is seeded with the latest STARTUP_SEED_PER_CATEGORY
entries from each KYM category so we don't sit idle on first run.
"""
from __future__ import annotations

import asyncio
import logging
import time

import aiohttp
import uvicorn

from pulse import config
from pulse.ai import dedupe, description as ai_description, naming as ai_naming, quality
from pulse.data.knowyourmeme import fetch_og_image, scrape_category
from pulse.db import database as db
from pulse.db.database import Launch
from pulse.launchers.pumpfun import launch_token
from pulse.market.meme_scanner import scan_for_new_memes
from pulse.queue import queue
from pulse.web.server import (
    app,
    emit_exec,
    emit_log,
    emit_pnl_history,
    emit_stats,
    register_startup,
)

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.FileHandler("tyrant.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# Tracks when the launcher will next attempt a launch. Pushed to the dashboard
# in stats so the frontend can render a live countdown.
_next_launch_at: float = 0.0


# ── Startup seed ───────────────────────────────────────────────────────────────

async def seed_queue() -> None:
    """At startup, push the newest STARTUP_SEED_PER_CATEGORY entries from each
    KYM category to the queue, and mark the REST of the current KYM list as
    already-seen. That way the first scanner_loop tick won't flood the queue
    with backlog — it only picks up entries that appear AFTER the bot started.
    """
    await emit_log("Seeding launch queue from KnowYourMeme…", "SYSTEM")
    total_queued = 0
    total_suppressed = 0
    async with aiohttp.ClientSession() as session:
        for cat in config.KYM_CATEGORIES:
            try:
                entries = await scrape_category(session, cat)
            except Exception as exc:
                logger.warning("Seed: %s scrape failed: %s", cat, exc)
                await emit_log(f"  Seed [{cat}] failed: {exc}", "ERROR")
                continue
            if not entries:
                continue

            to_seed = entries[: config.STARTUP_SEED_PER_CATEGORY]
            backlog = entries[config.STARTUP_SEED_PER_CATEGORY :]

            queued: list = []
            for e in to_seed:
                if await db.is_meme_seen(e.url):
                    continue
                if not e.image_url:
                    e.image_url = await fetch_og_image(session, e.url) or ""
                queued.append(e)
            added = await queue.push_many(queued)
            total_queued += added

            # Mark the rest as seen so scanner_loop skips them on its first run.
            suppressed = 0
            for e in backlog:
                if not await db.is_meme_seen(e.url):
                    await db.mark_meme_seen(e.url)
                    suppressed += 1
            total_suppressed += suppressed

            await emit_log(
                f"  Seed [{cat}]: queued {added}, suppressed {suppressed} backlog",
                "OK",
            )
    await emit_log(
        f"Queue seeded: {total_queued} memes ready, {total_suppressed} backlog suppressed — "
        f"size now {await queue.size()}",
        "SYSTEM",
    )


# ── Scanner loop ───────────────────────────────────────────────────────────────

async def scanner_loop() -> None:
    """Every SCAN_INTERVAL_SECONDS, scrape KYM and add new memes to the queue.

    Sleeps FIRST so the seed (which already ran at startup) isn't immediately
    duplicated by a scrape. The first real scan is at t = SCAN_INTERVAL_SECONDS.
    """
    scan_count = 0
    await emit_log(
        f"Scanner armed — first scrape in {config.SCAN_INTERVAL_SECONDS}s",
        "SCAN",
    )
    while True:
        await _sleep_seconds(config.SCAN_INTERVAL_SECONDS)
        scan_count += 1
        try:
            await emit_log(f"Scan #{scan_count} — scraping KnowYourMeme…", "SCAN")
            new_memes = await scan_for_new_memes()
            added = await queue.push_many(new_memes) if new_memes else 0
            qsize = await queue.size()
            if added:
                await emit_log(
                    f"Scan #{scan_count}: +{added} new, queue size {qsize}", "OK"
                )
            else:
                await emit_log(
                    f"Scan #{scan_count}: no new memes, queue size {qsize}", "INFO"
                )
        except Exception as exc:
            logger.exception("Scanner loop error: %s", exc)
            await emit_log(f"Scanner error: {exc}", "ERROR")

        await _push_stats(scan_count)
        await emit_log(
            f"Scan #{scan_count} complete — next scan in {config.SCAN_INTERVAL_SECONDS}s",
            "SCAN",
        )


# ── Launcher loop ──────────────────────────────────────────────────────────────

async def launcher_loop() -> None:
    """Pops one queued meme per LAUNCH_INTERVAL_SECONDS and launches it.

    Empty queue → wait the full interval. Dedup-skip → wait the full interval
    too (we don't blast LLM calls; the next scan adds fresh candidates anyway).
    Transient failure → requeue and wait.
    """
    global _next_launch_at
    await emit_log(
        f"Launcher armed — first launch in {config.LAUNCH_INTERVAL_SECONDS}s "
        f"(set LAUNCH_INTERVAL_SECONDS in .env to change)",
        "SYSTEM",
    )
    # First launch waits the full interval too — gives the operator time to
    # eyeball the seeded queue and abort with Ctrl-C if something looks wrong.
    _next_launch_at = time.time() + config.LAUNCH_INTERVAL_SECONDS
    await _push_stats()
    while True:
        await _sleep_seconds(config.LAUNCH_INTERVAL_SECONDS)
        try:
            await _launch_one_step()
        except Exception as exc:
            logger.exception("Launcher loop error: %s", exc)
            await emit_log(f"Launcher error: {exc}", "ERROR")
        _next_launch_at = time.time() + config.LAUNCH_INTERVAL_SECONDS
        await _push_stats()  # broadcast new countdown + queue snapshot


async def _launch_one_step() -> None:
    qm = await queue.pop()
    if qm is None:
        await emit_log("Queue empty — no launch this tick", "INFO")
        return

    entry = qm.entry

    # 1. Semantic dedup against past-7d launches.
    is_dup, dup_reason = await dedupe.is_duplicate(entry)
    if is_dup:
        await emit_log(f"  ⌫ Dedup-skip {entry.title} — {dup_reason}", "WARN")
        await db.mark_meme_seen(entry.url)
        return

    # 2. AI-rewrite the name + ticker. Falls back to algorithmic on failure.
    name, ticker, twitter_query = await ai_naming.generate_name_and_ticker(
        title=entry.title,
        description=entry.description,
        source=entry.source,
    )
    if name != entry.title:
        await emit_log(f"  ✎ Renamed: {entry.title!r} → {name!r} ({ticker})", "INFO")

    # 3. AI-rewrite the description. Falls back to current template on failure.
    ai_desc = await ai_description.generate_description(
        name=name,
        ticker=ticker,
        title=entry.title,
        kym_description=entry.description,
    )
    description_final = ai_desc or (
        entry.description or f"KYM {entry.source} meme. Source: {entry.url}"
    )

    # 4. Optional vision quality gate. OFF by default for KYM (curated source).
    if config.QUALITY_GATE_ENABLED:
        verdict = await quality.score_launchability(
            title=entry.title,
            description=entry.description,
            source=entry.source,
            image_url=entry.image_url,
        )
        if not verdict["pass"]:
            await emit_log(
                f"  ⌫ Quality-skip {entry.title} (score {verdict['score']}): {verdict['reasons']}",
                "WARN",
            )
            await db.mark_meme_seen(entry.url)
            return

    # 5. Launch.
    attempt = qm.attempts + 1
    retry_tag = (
        f" (retry {attempt}/{config.MAX_LAUNCH_RETRIES})" if attempt > 1 else ""
    )
    await emit_log(f"  → Launching: {name} ({ticker}){retry_tag}…", "INFO")
    await emit_exec("LAUNCH", entry.source.upper(), f"{name[:28]} ({ticker})")

    result = await launch_token(
        name=name,
        ticker=ticker,
        image_url=entry.image_url or "",
        description=description_final,
        meme_url=entry.url,
        source=entry.source,
    )

    if config.DRY_RUN:
        status = "DRY_RUN"
    elif config.SIMULATE:
        status = "SIMULATED" if result.success else "FAILED"
    else:
        status = "LAUNCHED" if result.success else "FAILED"

    record = Launch(
        id=None,
        timestamp=time.time(),
        name=name,
        ticker=ticker,
        source=entry.source,
        meme_url=entry.url,
        image_url=entry.image_url or "",
        description=description_final,
        tx_sig=result.tx_sig,
        mint_address=result.mint_address,
        status=status,
        sol_spent=result.sol_spent,
        error=result.error,
    )
    await db.insert_launch(record)
    await db.snapshot_launch_count()

    if result.success:
        await db.mark_meme_seen(entry.url)
        tag = "[DRY] " if config.DRY_RUN else ("[SIM] " if config.SIMULATE else "")
        await emit_log(
            f"  ✓ {tag}Launched {name} ({ticker})"
            f" mint={result.mint_address[:8]} tx={result.tx_sig[:16]}",
            "OK",
        )
        if result.sell_sig:
            await emit_log(
                f"  ↩ Dev-sold {name} ({ticker}) sell={result.sell_sig[:16]}", "OK"
            )
        elif not config.DRY_RUN and not config.SIMULATE:
            await emit_log(
                f"  ⚠ Dev-sell skipped/failed for {name} ({ticker})", "WARN"
            )
        return

    # Failure — decide retry vs give-up.
    if attempt >= config.MAX_LAUNCH_RETRIES:
        await db.mark_meme_seen(entry.url)
        await emit_log(
            f"  ✗ Launch failed: {result.error} — giving up after {attempt} attempts",
            "ERROR",
        )
    else:
        await queue.requeue(qm)
        remaining = config.MAX_LAUNCH_RETRIES - attempt
        await emit_log(
            f"  ✗ Launch failed: {result.error} — requeued, {remaining} retry left",
            "ERROR",
        )


# ── Stats / dashboard ─────────────────────────────────────────────────────────

async def _push_stats(scan_count: int = 0) -> None:
    launches = await db.get_launches(200)
    total = await db.get_total_launches()
    today = await db.get_today_launches()
    sol_spent = await db.get_total_sol_spent()
    history = await db.get_launch_history(200)

    n_ok = sum(1 for l in launches if l.status in ("LAUNCHED", "SIMULATED", "DRY_RUN"))
    n_fail = sum(1 for l in launches if l.status == "FAILED")
    n_real_ok = sum(1 for l in launches if l.status in ("LAUNCHED", "SIMULATED"))
    n_real_attempts = n_real_ok + n_fail

    snap = await queue.snapshot()
    queue_payload = [
        {
            "title": qm.entry.title,
            "source": qm.entry.source,
            "image_url": qm.entry.image_url,
            "url": qm.entry.url,
            "attempts": qm.attempts,
        }
        for qm in snap[:30]  # cap so the WS frame stays small
    ]

    await emit_stats({
        "total_launches": total,
        "today_launches": len(today),
        "sol_spent": sol_spent,
        "n_ok": n_ok,
        "n_fail": n_fail,
        "n_real_attempts": n_real_attempts,
        "success_rate": (n_real_ok / n_real_attempts) if n_real_attempts else 0.0,
        "dry_run": config.DRY_RUN,
        "scan_count": scan_count,
        "queue_size": len(snap),
        "queue": queue_payload,
        "next_launch_at": _next_launch_at,
        "launch_interval_seconds": config.LAUNCH_INTERVAL_SECONDS,
    })
    await emit_pnl_history({
        "timestamps": [h.timestamp for h in history],
        "values": [float(h.count) for h in history],
    })


# ── Sleep helper (yields cleanly so cancellation works) ───────────────────────

async def _sleep_seconds(seconds: int) -> None:
    elapsed = 0
    while elapsed < seconds:
        await asyncio.sleep(1)
        elapsed += 1


# ── FastAPI startup hook ──────────────────────────────────────────────────────

@register_startup
async def on_startup():
    await emit_log("TYRANT//BOT initializing…", "SYSTEM")
    await emit_log(f"Mode: {'DRY RUN' if config.DRY_RUN else 'LIVE'}", "SYSTEM")
    await emit_log(f"Scan interval: {config.SCAN_INTERVAL_SECONDS}s", "SYSTEM")
    await emit_log(f"Launch interval: {config.LAUNCH_INTERVAL_SECONDS}s", "SYSTEM")
    await emit_log(
        f"AI: naming={config.NAMING_ENABLED} desc={config.DESCRIPTION_ENABLED} "
        f"dedupe={config.DEDUPE_ENABLED} quality={config.QUALITY_GATE_ENABLED}",
        "SYSTEM",
    )
    try:
        await seed_queue()
    except Exception as exc:
        logger.exception("Seed failed: %s", exc)
        await emit_log(f"Seed failed: {exc}", "ERROR")
    asyncio.create_task(scanner_loop())
    asyncio.create_task(launcher_loop())


def main():
    import os
    port = int(os.environ.get("PORT", 8000))
    logger.info("Starting TYRANT//BOT web dashboard on http://0.0.0.0:%d", port)
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
