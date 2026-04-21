"""
TYRANT — Terminal meme-launch dashboard.
Dark hedge-fund aesthetic built with Textual.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Callable, List, Optional

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Footer, Header, Label, Static

from pulse import config
from pulse.dashboard.widgets.equity_chart import EquityChart
from pulse.dashboard.widgets.heatmap import SourceHeatmap, ExecLogPanel
from pulse.dashboard.widgets.log_panel import LogPanel
from pulse.dashboard.widgets.stats_panel import Stats, StatsPanel
from pulse.dashboard.widgets.trades_panel import LaunchesPanel
from pulse.db import database as db


# ── Header banner ──────────────────────────────────────────────────────────────

class PulseHeader(Widget):
    """Glowing header banner with live clock and system status."""

    DEFAULT_CSS = """
    PulseHeader {
        background: #05050a;
        border-bottom: solid #7c3aed;
        height: 4;
        padding: 0 2;
        layout: horizontal;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._start_time = time.time()
        self._scan_status = "INITIALIZING"

    def set_scan_status(self, status: str) -> None:
        self._scan_status = status
        self.refresh()

    def render(self) -> Text:
        now = datetime.utcnow()
        uptime = int(time.time() - self._start_time)
        h, m, s = uptime // 3600, (uptime % 3600) // 60, uptime % 60
        mode_badge = "[DRY RUN]" if config.DRY_RUN else "[● LIVE]"
        mode_color = "yellow" if config.DRY_RUN else "bright_green"

        text = Text()
        text.append("  TYRANT", style="bold bright_magenta")
        text.append("//BOT  ", style="bold cyan")
        text.append("│", style="bright_black")
        text.append(f"  {now.strftime('%Y-%m-%d %H:%M:%S')} UTC  ", style="bright_cyan")
        text.append("│", style="bright_black")
        text.append(f"  UP {h:02d}:{m:02d}:{s:02d}  ", style="dim cyan")
        text.append("│", style="bright_black")
        text.append(f"  {mode_badge}  ", style=f"bold {mode_color}")
        text.append("│", style="bright_black")
        text.append(f"  SCAN: {self._scan_status}  ", style="cyan")
        return text


class LaunchDisplay(Widget):
    """Large glowing launch counter — centerpiece of the dashboard."""

    DEFAULT_CSS = """
    LaunchDisplay {
        background: #05050a;
        border: solid #1a1a2e;
        height: 5;
        content-align: center middle;
        text-align: center;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._total = 0
        self._today = 0
        self._sol_spent = 0.0

    def update(self, total: int, today: int, sol_spent: float) -> None:
        self._total = total
        self._today = today
        self._sol_spent = sol_spent
        self.refresh()

    def render(self) -> Text:
        text = Text(justify="center")
        text.append("\n")
        text.append("  TOTAL LAUNCHED  ", style="bold dim cyan")
        text.append(f"{self._total}  ", style="bold bright_magenta")
        text.append("│", style="bright_black")
        text.append("  TODAY  ", style="dim cyan")
        text.append(f"{self._today}  ", style="bold bright_green")
        text.append("│", style="bright_black")
        text.append("  SOL SPENT  ", style="dim cyan")
        text.append(f"◎{self._sol_spent:.4f}", style="bold bright_white")
        return text


# ── Main application ───────────────────────────────────────────────────────────

class PulseApp(App):
    """
    Full-screen terminal meme-launch dashboard.

    Layout (12-column grid):
    ┌────────────────────────────────────────────────┐
    │                   HEADER (12)                  │
    ├──────────┬─────────────────────┬───────────────┤
    │  LOGS    │   LAUNCH CHART      │   LAUNCHES    │
    │  (3)     │     (6)             │    (3)        │
    │          ├─────────────────────┤               │
    │          │   LAUNCH DISPLAY    │               │
    ├──────────┴─────────────────────┴───────────────┤
    │                STATS BAR (12)                  │
    ├────────────────────────────────────────────────┤
    │  EXEC LOG (6)              │  SOURCE MAP (6)   │
    └────────────────────────────────────────────────┘
    """

    TITLE = "TYRANT//BOT — Meme Coin Auto Launcher"
    CSS = """
    Screen {
        background: #0a0a0f;
        layout: vertical;
    }

    #main-grid {
        layout: horizontal;
        height: 1fr;
    }

    #left-col {
        width: 28%;
        layout: vertical;
        height: 100%;
    }

    #center-col {
        width: 44%;
        layout: vertical;
        height: 100%;
    }

    #right-col {
        width: 28%;
        layout: vertical;
        height: 100%;
    }

    LogPanel {
        height: 1fr;
        border: solid #1a1a2e;
        border-title-color: cyan;
        background: #05050a;
    }

    EquityChart {
        height: 1fr;
        border: solid #7c3aed;
        border-title-color: #d946ef;
    }

    LaunchDisplay {
        height: 5;
    }

    LaunchesPanel {
        height: 1fr;
        border: solid #1a1a2e;
        border-title-color: cyan;
    }

    StatsPanel {
        height: 9;
        border: solid #1a1a2e;
        border-title-color: #0e7490;
    }

    #bottom-row {
        layout: horizontal;
        height: 10;
    }

    ExecLogPanel {
        width: 65%;
        border: solid #1a1a2e;
        border-title-color: magenta;
    }

    SourceHeatmap {
        width: 35%;
        border: solid #1a1a2e;
        border-title-color: cyan;
    }

    PulseHeader {
        height: 3;
        background: #05050a;
        border-bottom: solid #7c3aed;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("c", "clear_logs", "Clear Logs"),
        Binding("l", "toggle_live", "Toggle Live/Dry"),
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._trading_loop_task: Optional[asyncio.Task] = None
        self._refresh_task: Optional[asyncio.Task] = None
        self._on_scan_callback: Optional[Callable] = None

    # ── Layout ─────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield PulseHeader(id="header")

        with Horizontal(id="main-grid"):
            with Vertical(id="left-col"):
                log = LogPanel(id="log-panel")
                log.border_title = "◈ SYSTEM LOG"
                yield log

            with Vertical(id="center-col"):
                chart = EquityChart(id="equity-chart")
                chart.border_title = "◈ LAUNCH RATE"
                yield chart
                yield LaunchDisplay(id="launch-display")

            with Vertical(id="right-col"):
                launches = LaunchesPanel(id="launches-panel")
                launches.border_title = "◈ RECENT LAUNCHES"
                yield launches

        stats = StatsPanel(id="stats-panel")
        stats.border_title = "◈ LAUNCH METRICS"
        yield stats

        with Horizontal(id="bottom-row"):
            exec_log = ExecLogPanel(id="exec-log")
            exec_log.border_title = "◈ EXECUTION LOG"
            yield exec_log

            heatmap = SourceHeatmap(id="heatmap")
            heatmap.border_title = "◈ SOURCE ACTIVITY"
            yield heatmap

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def on_mount(self) -> None:
        self.log_msg("TYRANT//BOT v1.0 initializing...", "SYSTEM")
        self.log_msg(f"Mode: {'DRY RUN' if config.DRY_RUN else 'LIVE LAUNCH'}", "SYSTEM")
        self.log_msg(f"Scan interval: {config.SCAN_INTERVAL_SECONDS}s", "SYSTEM")
        self.log_msg(f"Max launches/cycle: {config.MAX_LAUNCHES_PER_CYCLE}", "SYSTEM")
        self.log_msg(f"Categories: {', '.join(config.KYM_CATEGORIES)}", "SYSTEM")

        self._refresh_task = asyncio.create_task(self._refresh_loop())

        if self._on_scan_callback:
            self._trading_loop_task = asyncio.create_task(
                self._on_scan_callback(self)
            )

    async def on_unmount(self) -> None:
        if self._refresh_task:
            self._refresh_task.cancel()

    # ── Public API ─────────────────────────────────────────────────────────────

    def log_msg(self, msg: str, level: str = "INFO") -> None:
        self.query_one("#log-panel", LogPanel).log(msg, level)

    def add_exec_entry(self, tag: str, source: str, detail: str) -> None:
        self.query_one("#exec-log", ExecLogPanel).add_entry(tag, source, detail)

    def set_scan_status(self, status: str) -> None:
        self.query_one("#header", PulseHeader).set_scan_status(status)

    def record_source_activity(self, source: str) -> None:
        self.query_one("#heatmap", SourceHeatmap).record_activity(source)

    def register_trading_loop(self, callback: Callable) -> None:
        self._on_scan_callback = callback

    # ── Periodic refresh ───────────────────────────────────────────────────────

    async def _refresh_loop(self) -> None:
        while True:
            try:
                await self._refresh_widgets()
            except Exception as exc:
                self.log_msg(f"Refresh error: {exc}", "ERROR")
            await asyncio.sleep(config.DASHBOARD_REFRESH_SECONDS)

    async def _refresh_widgets(self) -> None:
        # Launch count history for chart
        history = await db.get_launch_history(200)
        if history:
            values = [float(h.count) for h in history]
            self.query_one("#equity-chart", EquityChart).update_history(values)

        # Launch totals
        total = await db.get_total_launches()
        today_launches = await db.get_today_launches()
        sol_spent = await db.get_total_sol_spent()
        self.query_one("#launch-display", LaunchDisplay).update(total, len(today_launches), sol_spent)

        # Recent launches table
        launches = await db.get_launches(30)
        self.query_one("#launches-panel", LaunchesPanel).update_launches(launches)

        # Stats
        n_ok = sum(1 for l in launches if l.status in ("LAUNCHED", "DRY_RUN"))
        n_fail = sum(1 for l in launches if l.status == "FAILED")
        stats = Stats(
            total_launches=total,
            today_launches=len(today_launches),
            sol_spent=sol_spent,
            n_ok=n_ok,
            n_fail=n_fail,
            dry_run=config.DRY_RUN,
        )
        self.query_one("#stats-panel", StatsPanel).update_stats(stats)

    # ── Key bindings ───────────────────────────────────────────────────────────

    def action_clear_logs(self) -> None:
        self.query_one("#log-panel", LogPanel).clear()

    def action_toggle_live(self) -> None:
        config.DRY_RUN = not config.DRY_RUN
        mode = "DRY RUN" if config.DRY_RUN else "LIVE"
        self.log_msg(f"Mode switched to {mode}", "WARN")
