"""Statistics panel — launch counts, success rate, SOL spent."""
from __future__ import annotations

from dataclasses import dataclass, field

from rich.table import Table
from rich.text import Text
from textual.widget import Widget


@dataclass
class Stats:
    total_launches: int = 0
    today_launches: int = 0
    sol_spent: float = 0.0
    n_ok: int = 0
    n_fail: int = 0
    scan_count: int = 0
    dry_run: bool = True
    opportunities_found: int = 0  # kept for compat with main loop patches


class StatsPanel(Widget):
    """Dense stats bar — quant terminal style."""

    DEFAULT_CSS = """
    StatsPanel {
        border: solid #1a1a2e;
        background: #05050a;
        padding: 0 1;
        height: auto;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stats = Stats()

    def update_stats(self, stats: Stats) -> None:
        self._stats = stats
        self.refresh()

    def render(self) -> Table:
        s = self._stats
        total = s.n_ok + s.n_fail
        success_rate = s.n_ok / max(total, 1)

        mode_color   = "yellow" if s.dry_run else "bright_green"
        mode_text    = "DRY RUN" if s.dry_run else "● LIVE"
        rate_color   = "bright_green" if success_rate >= 0.8 else "yellow" if success_rate >= 0.5 else "bright_red"

        table = Table(
            show_header=False,
            border_style="bright_black",
            show_edge=False,
            padding=(0, 2),
            expand=True,
        )
        table.add_column(width=18)
        table.add_column(width=18)
        table.add_column(width=18)
        table.add_column(width=18)
        table.add_column(width=18)
        table.add_column(width=18)
        table.add_column(width=16)

        def stat(label: str, value: str, color: str = "white") -> Text:
            t = Text()
            t.append(f"{label}\n", style="dim cyan")
            t.append(value, style=f"bold {color}")
            return t

        table.add_row(
            stat("TOTAL LAUNCHED", str(s.total_launches),    "bright_magenta"),
            stat("TODAY",          str(s.today_launches),    "bright_green"),
            stat("SOL SPENT",      f"◎{s.sol_spent:.4f}",   "bright_white"),
            stat("LAUNCHED OK",    str(s.n_ok),              "bright_green"),
            stat("FAILED",         str(s.n_fail),            "bright_red" if s.n_fail else "dim"),
            stat("SUCCESS RATE",   f"{success_rate:.1%}",    rate_color),
            stat("MODE",           mode_text,                mode_color),
        )

        table.add_row(
            stat("SCANS",          str(s.scan_count),        "cyan"),
            stat("NEW/CYCLE",      str(s.opportunities_found), "magenta"),
            stat("CONFIRMED",      "—", "bright_green"),
            stat("SUBMISSION",     "—", "cyan"),
            stat("NEWSWORTHY",     "—", "yellow"),
            stat("DEADPOOL",       "—", "bright_red"),
            stat("NETWORK",        "SOLANA", "bright_cyan"),
        )

        return table
