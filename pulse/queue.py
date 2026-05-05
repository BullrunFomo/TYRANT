"""In-memory FIFO launch queue.

The scanner pushes new memes; the launcher pops one every LAUNCH_INTERVAL_SECONDS.
URL-level dedup against the queue's own contents lives here. Dedup against
already-launched memes is the DB's job (`db.is_meme_seen`) and is checked at
push-time by the scanner.

In-memory is intentional: on restart we re-seed from the latest KYM RSS entries,
which is a fresh start by design.
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from pulse.data.knowyourmeme import MemeEntry


@dataclass
class QueuedMeme:
    entry: MemeEntry
    attempts: int = 0  # incremented when launcher requeues after a transient failure


class LaunchQueue:
    def __init__(self) -> None:
        self._items: deque[QueuedMeme] = deque()
        self._urls: set[str] = set()
        self._lock = asyncio.Lock()

    async def push_many(self, entries: list[MemeEntry]) -> int:
        added = 0
        async with self._lock:
            for e in entries:
                if e.url in self._urls:
                    continue
                self._items.append(QueuedMeme(entry=e))
                self._urls.add(e.url)
                added += 1
        return added

    async def pop(self) -> Optional[QueuedMeme]:
        async with self._lock:
            if not self._items:
                return None
            qm = self._items.popleft()
            self._urls.discard(qm.entry.url)
            return qm

    async def requeue(self, qm: QueuedMeme) -> None:
        """Re-add to tail after a transient launch failure. Caller bumps attempts."""
        async with self._lock:
            qm.attempts += 1
            self._items.append(qm)
            self._urls.add(qm.entry.url)

    async def size(self) -> int:
        async with self._lock:
            return len(self._items)

    async def snapshot(self) -> list[QueuedMeme]:
        async with self._lock:
            return list(self._items)

    async def contains(self, url: str) -> bool:
        async with self._lock:
            return url in self._urls


# Module-level singleton — there's only one queue per process.
queue = LaunchQueue()
