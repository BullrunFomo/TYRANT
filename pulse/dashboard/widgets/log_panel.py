"""Scrolling system log panel widget."""
from __future__ import annotations

import time
from collections import deque
from typing import Deque, Tuple

from rich.text import Text
from textual.widget import Widget
from textual.scroll_view import ScrollView
from textual.reactive import reactive


MAX_LINES = 500

# (timestamp, level, message)
LogLine = Tuple[float, str, str]

LEVEL_STYLES = {
    "INFO":    ("bright_cyan",   "•"),
    "OK":      ("bright_green",  "✓"),
    "WARN":    ("bright_yellow", "⚠"),
    "ERROR":   ("bright_red",    "✗"),
    "TRADE":   ("bright_magenta","◈"),
    "SYSTEM":  ("blue",          "⬡"),
    "SCAN":    ("cyan",          "⟳"),
    "RISK":    ("yellow",        "⚡"),
}


class LogPanel(Widget):
    """Real-time scrolling log panel with color-coded level indicators."""

    DEFAULT_CSS = """
    LogPanel {
        border: solid #1a1a2e;
        background: #05050a;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lines: Deque[LogLine] = deque(maxlen=MAX_LINES)

    def log(self, message: str, level: str = "INFO") -> None:
        self._lines.append((time.time(), level.upper(), message))
        self.refresh()

    def render(self) -> Text:
        text = Text(overflow="fold")
        available = max(1, self.size.height - 2)

        lines = list(self._lines)[-available:]

        for ts, level, msg in lines:
            style, icon = LEVEL_STYLES.get(level, ("white", "·"))
            time_str = time.strftime("%H:%M:%S", time.localtime(ts))

            text.append(f"{time_str} ", style="bright_black")
            text.append(f"{icon} ", style=f"bold {style}")
            text.append(f"[{level:<5}] ", style=style)
            text.append(f"{msg}\n", style="white" if level == "INFO" else style)

        return text

    def clear(self) -> None:
        self._lines.clear()
        self.refresh()
