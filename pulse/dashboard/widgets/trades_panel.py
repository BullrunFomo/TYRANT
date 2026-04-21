"""Launches panel — live table of recent pump.fun token launches."""
from __future__ import annotations

from typing import List

from rich.table import Table
from rich.text import Text
from textual.widget import Widget

from pulse.db.database import Launch


SOURCE_COLORS = {
    "confirmed":  "bright_green",
    "submission": "cyan",
    "newsworthy": "yellow",
    "deadpool":   "bright_red",
}


class LaunchesPanel(Widget):
    """Displays recent meme launches with status coloring."""

    DEFAULT_CSS = """
    LaunchesPanel {
        border: solid #1a1a2e;
        background: #05050a;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._launches: List[Launch] = []

    def update_launches(self, launches: List[Launch]) -> None:
        self._launches = launches
        self.refresh()

    def render(self) -> Table:
        table = Table(
            show_header=True,
            header_style="bold cyan",
            border_style="bright_black",
            show_edge=False,
            padding=(0, 1),
            expand=True,
        )

        table.add_column("NAME",    style="bright_white",  width=16)
        table.add_column("TICKER",  style="bright_magenta", width=7)
        table.add_column("SOURCE",  style="cyan",           width=10)
        table.add_column("STATUS",  style="dim",            width=9)
        table.add_column("MINT",    style="bright_black",   width=10)

        for launch in self._launches[:20]:
            status_color = {
                "LAUNCHED": "bright_green",
                "DRY_RUN":  "yellow",
                "FAILED":   "bright_red",
                "PENDING":  "dim",
            }.get(launch.status, "white")

            src_color = SOURCE_COLORS.get(launch.source, "white")
            mint_short = (launch.mint_address[:8] + "...") if launch.mint_address and not launch.mint_address.startswith("DRY") else "—"

            table.add_row(
                launch.name[:16],
                launch.ticker,
                Text(launch.source[:10], style=src_color),
                Text(launch.status, style=status_color),
                Text(mint_short, style="bright_black"),
            )

        if not self._launches:
            table.add_row("—", "—", "—", "—", "Waiting for memes...")

        return table
