"""Equity curve chart widget — renders a neon ASCII line chart."""
from __future__ import annotations

import math
from typing import List

from rich.text import Text
from textual.widget import Widget
from textual.reactive import reactive


class EquityChart(Widget):
    """
    A custom widget that renders the P&L equity curve as a green line chart
    drawn with Unicode block characters on a dark background.
    """

    DEFAULT_CSS = """
    EquityChart {
        border: solid #1a1a2e;
        background: #05050a;
        padding: 1 2;
    }
    """

    history: reactive[List[float]] = reactive(list)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._history: List[float] = []

    def update_history(self, values: List[float]) -> None:
        self._history = values[-200:]  # keep last 200 points
        self.refresh()

    def render(self) -> Text:
        width = self.size.width - 4
        height = self.size.height - 2
        if width < 10 or height < 4:
            return Text("Loading chart...", style="dim")

        history = self._history
        if len(history) < 2:
            return self._placeholder(width, height)

        return self._draw_chart(history, width, height)

    def _placeholder(self, width: int, height: int) -> Text:
        text = Text()
        for row in range(height):
            text.append("│", style="bright_black")
            text.append("─" * (width - 2), style="bright_black")
            text.append("│\n", style="bright_black")
        text.append(f"  {'Waiting for launches...':^{width-4}}", style="dim cyan")
        return text

    def _draw_chart(self, values: List[float], width: int, height: int) -> Text:
        # Normalize values to chart height
        min_v = min(values)
        max_v = max(values)
        span = max_v - min_v
        if span < 0.01:
            span = 1.0

        # Downsample to chart width
        n = len(values)
        cols = width - 4
        rows = height - 2

        sampled = []
        for i in range(cols):
            idx = int(i * (n - 1) / max(cols - 1, 1))
            sampled.append(values[idx])

        # Convert to row coordinates (0 = top)
        def to_row(v: float) -> int:
            norm = (v - min_v) / span
            return int((1.0 - norm) * (rows - 1))

        # Build a 2D grid of characters
        grid = [[" "] * cols for _ in range(rows)]

        # Draw the line with vertical fill
        for i in range(len(sampled)):
            row = to_row(sampled[i])
            row = max(0, min(rows - 1, row))

            # Vertical segment between consecutive points
            if i > 0:
                prev_row = to_row(sampled[i - 1])
                lo = min(row, prev_row)
                hi = max(row, prev_row)
                for r in range(lo, hi + 1):
                    if 0 <= r < rows:
                        grid[r][i] = "│"

            if 0 <= row < rows:
                grid[row][i] = "●"

        # Determine trend for color
        trend_up = sampled[-1] >= sampled[0]
        line_color = "bright_green" if trend_up else "bright_red"
        dim_color  = "green" if trend_up else "red"

        text = Text()

        # Y-axis labels
        label_hi = f"{max_v:+.0f}"
        label_lo = f"{min_v:+.0f}"
        label_mid = f"{(max_v+min_v)/2:+.0f}"

        for r in range(rows):
            # Y-axis label at specific rows
            if r == 0:
                text.append(f"{label_hi:>6}", style="bright_cyan")
            elif r == rows // 2:
                text.append(f"{label_mid:>6}", style="cyan")
            elif r == rows - 1:
                text.append(f"{label_lo:>6}", style="bright_cyan")
            else:
                text.append("      ")

            text.append("┤", style="bright_black")

            for c in range(cols):
                ch = grid[r][c]
                if ch == "●":
                    text.append(ch, style=f"bold {line_color}")
                elif ch == "│":
                    text.append(ch, style=dim_color)
                else:
                    text.append(ch)

            text.append("\n")

        # X-axis
        text.append("      └", style="bright_black")
        text.append("─" * cols, style="bright_black")
        text.append("\n")

        # Launch count summary
        current = int(values[-1]) if values else 0
        delta = int(values[-1] - values[0]) if values else 0
        delta_color = "bright_green" if delta >= 0 else "bright_red"

        text.append(f"\n  TOTAL LAUNCHED: ", style="dim")
        text.append(f"{current}", style="bold bright_magenta")
        text.append(f"   SINCE START: ", style="dim")
        text.append(f"+{delta}", style=f"bold {delta_color}")

        return text
