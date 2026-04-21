"""Source activity heatmap and execution log widgets."""
from __future__ import annotations

import time
from typing import Dict, List, Tuple

from rich.table import Table
from rich.text import Text
from textual.widget import Widget

from pulse import config

HEAT_CHARS = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"]

KYM_SOURCES = ["confirmed", "submission", "newsworthy", "deadpool"]

SOURCE_COLORS = {
    "confirmed":  "bright_green",
    "submission": "cyan",
    "newsworthy": "yellow",
    "deadpool":   "bright_red",
}


def _heat_char(value: float, max_val: float) -> Tuple[str, str]:
    if max_val <= 0:
        return "▁", "bright_black"
    norm = min(1.0, value / max_val)
    idx = int(norm * (len(HEAT_CHARS) - 1))
    if norm > 0.75:
        color = "bright_green"
    elif norm > 0.4:
        color = "yellow"
    elif norm > 0.1:
        color = "cyan"
    else:
        color = "bright_black"
    return HEAT_CHARS[idx], color


class SourceHeatmap(Widget):
    """Shows per-source launch activity as a color-coded heatmap bar."""

    DEFAULT_CSS = """
    SourceHeatmap {
        border: solid #1a1a2e;
        background: #05050a;
        padding: 0 1;
        height: auto;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._activity: Dict[str, int] = {s: 0 for s in KYM_SOURCES}

    def record_activity(self, source: str, count: int = 1) -> None:
        self._activity[source] = self._activity.get(source, 0) + count
        self.refresh()

    def render(self) -> Text:
        text = Text()
        max_val = max(self._activity.values()) if self._activity else 1

        text.append("KYM SOURCE  ", style="bold dim cyan")

        for source in KYM_SOURCES:
            count = self._activity.get(source, 0)
            short = source[:4].upper()
            ch, heat_color = _heat_char(count, max_val)
            src_color = SOURCE_COLORS.get(source, "white")
            text.append(f" {short}:", style=f"dim {src_color}")
            text.append(ch * 3, style=heat_color)
            text.append(f"{count:>3} ", style="bright_black")

        return text


class ExecLogPanel(Widget):
    """Color-coded launch execution log."""

    DEFAULT_CSS = """
    ExecLogPanel {
        border: solid #1a1a2e;
        background: #05050a;
        padding: 0 1;
        overflow-y: auto;
    }
    """

    ENTRY_COLORS = {
        "LAUNCH":  "#7c3aed",   # purple
        "DRY":     "#f59e0b",   # amber
        "FAILED":  "#ef4444",   # bright red
        "SCAN":    "#0891b2",   # teal
        "SYSTEM":  "#6b7280",   # gray
        "OK":      "#16a34a",   # green
        "ERROR":   "#dc2626",   # red
        "INFO":    "#2563eb",   # blue
        "WARN":    "#f59e0b",   # amber
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._entries: List[Tuple[float, str, str, str]] = []

    def add_entry(self, tag: str, source: str, detail: str) -> None:
        self._entries.append((time.time(), tag.upper(), source, detail))
        if len(self._entries) > 200:
            self._entries = self._entries[-200:]
        self.refresh()

    def render(self) -> Text:
        text = Text(overflow="fold")
        available = max(1, self.size.height - 1)
        entries = self._entries[-available:]

        for ts, tag, source, detail in entries:
            color = self.ENTRY_COLORS.get(tag, "white")
            ts_str = time.strftime("%H:%M:%S", time.localtime(ts))

            text.append(f"{ts_str} ", style="bright_black")
            text.append(f"[{tag:<7}]", style=f"bold {color}")
            text.append(f" {source:<12}", style="bright_white")
            text.append(f" {detail}\n", style="white")

        return text
