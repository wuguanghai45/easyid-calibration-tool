"""TCP client for Huaray AGV scan results (x;y;theta;code)."""

from __future__ import annotations

import logging
import math
import re
import socket
import threading
import time
from collections import deque
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Huaray AGV result: (x_offset;y_offset;theta;barcode)
_SCAN_PATTERN = re.compile(r"\(([^)]+)\)")


def radians_to_huaray_theta(theta_rad: float) -> int:
    """Convert radians to Huaray theta: clockwise [0, 3599], 0.1 deg per unit."""
    return int(theta_rad / math.pi * 1800 + 1800) % 3600


def huaray_theta_to_degrees(theta: int) -> float:
    """Camera theta unit -> signed offset degrees in (-180, 180]."""
    deg = (int(theta) % 3600) / 10.0
    if deg > 180:
        deg -= 360
    return deg


def parse_scan_payload(text: str) -> list[dict[str, str | int]]:
    """Parse one or more (x;y;theta;code) messages from TCP text."""
    results: list[dict[str, str | int]] = []
    for match in _SCAN_PATTERN.finditer(text):
        parts = match.group(1).split(";")
        if len(parts) < 4:
            continue
        try:
            results.append(
                {
                    "x_offset": int(parts[0]),
                    "y_offset": int(parts[1]),
                    "theta": int(parts[2]) % 3600,
                    "code": ";".join(parts[3:]),
                }
            )
        except ValueError:
            continue
    return results


def enrich_scan_item(item: dict[str, str | int]) -> dict[str, Any]:
    theta = int(item["theta"])
    return {
        "x_offset": int(item["x_offset"]),
        "y_offset": int(item["y_offset"]),
        "theta": theta,
        "theta_deg": huaray_theta_to_degrees(theta),
        "code": str(item["code"]),
        "ts": time.time(),
    }


class TcpScanClient:
    """Background TCP reader with reconnect and subscriber callbacks."""

    def __init__(
        self,
        *,
        host: str,
        port: int = 3000,
        reconnect_delay_sec: float = 5.0,
        recv_timeout_sec: float = 5.0,
        history_size: int = 200,
    ) -> None:
        self.host = host
        self.port = port
        self.reconnect_delay_sec = reconnect_delay_sec
        self.recv_timeout_sec = recv_timeout_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[dict[str, Any]], None]] = []
        self._history: deque[dict[str, Any]] = deque(maxlen=history_size)
        self._connected = False
        self._last_error: str | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = list(self._history)
        return items[-limit:]

    def get_latest(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._history:
                return None
            return dict(self._history[-1])

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, name="TcpScanClient", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        self._thread = None
        self._connected = False

    def _emit(self, item: dict[str, Any]) -> None:
        with self._lock:
            self._history.append(item)
            subs = list(self._subscribers)
        for cb in subs:
            try:
                cb(item)
            except Exception:
                logger.exception("TCP scan subscriber failed")

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            client: socket.socket | None = None
            try:
                client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                client.settimeout(self.recv_timeout_sec)
                client.connect((self.host, self.port))
                client.settimeout(None)
                self._connected = True
                self._last_error = None
                logger.info("TCP scan connected to %s:%s", self.host, self.port)

                buffer = ""
                while not self._stop.is_set():
                    data = client.recv(4096)
                    if not data:
                        logger.warning("TCP scan connection closed by device")
                        break
                    buffer += data.decode("utf-8", errors="ignore")
                    while True:
                        start = buffer.find("(")
                        end = buffer.find(")", start + 1) if start >= 0 else -1
                        if start < 0 or end < 0:
                            if len(buffer) > 8192:
                                buffer = buffer[-4096:]
                            break
                        chunk = buffer[start : end + 1]
                        buffer = buffer[end + 1 :]
                        for raw in parse_scan_payload(chunk):
                            self._emit(enrich_scan_item(raw))
            except OSError as exc:
                self._last_error = str(exc)
                logger.warning("TCP scan error: %s", exc)
            finally:
                self._connected = False
                if client is not None:
                    try:
                        client.close()
                    except OSError:
                        pass
            if self._stop.is_set():
                break
            time.sleep(self.reconnect_delay_sec)
