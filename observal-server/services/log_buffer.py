# SPDX-FileCopyrightText: 2026 Naraen Rammoorthi <naraen13@gmail.com>
# SPDX-License-Identifier: AGPL-3.0-only

"""Thread-safe bounded ring buffer for structured log entries.

Used by the support bundle ``logs`` collector to return recent log
lines without touching the filesystem.  A structlog processor
(configured in ``logging_config.py``) appends entries here.
"""

from __future__ import annotations

import collections
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime


class LogRingBuffer:
    """Thread-safe bounded ring buffer for structured log entries."""

    def __init__(self, maxlen: int = 2000) -> None:
        self._buffer: collections.deque[dict] = collections.deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def append(self, entry: dict) -> None:
        """Append a structured log entry to the buffer."""
        with self._lock:
            self._buffer.append(entry)

    def get_since(self, since: datetime) -> list[dict]:
        """Return entries with a timestamp at or after *since*."""
        since_iso = since.isoformat()
        with self._lock:
            return [e for e in self._buffer if e.get("timestamp", "") >= since_iso]

    def get_all(self) -> list[dict]:
        """Return all entries currently in the buffer."""
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        """Remove all entries from the buffer."""
        with self._lock:
            self._buffer.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._buffer)


_log_buffer = LogRingBuffer()


def get_log_buffer() -> LogRingBuffer:
    """Return the singleton log ring buffer instance."""
    return _log_buffer
