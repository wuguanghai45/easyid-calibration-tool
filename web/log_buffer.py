"""In-memory ring buffer for operation logs."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any


class LogBuffer:
    def __init__(self, maxlen: int = 500) -> None:
        self._entries: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()

    def add(self, level: str, message: str, **extra: Any) -> dict[str, Any]:
        entry = {
            "ts": time.time(),
            "level": level,
            "message": message,
            **extra,
        }
        with self._lock:
            self._entries.append(entry)
        return entry

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._entries)
        return items[-limit:]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
