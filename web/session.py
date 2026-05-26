"""Device session: IMV camera, TCP scan, and MJPEG preview."""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any

from scanner.device_config import read_device_config, write_device_config
from scanner.preview import PreviewStream
from scanner.tcp_scan import TcpScanClient
from scanner_reader import ScannerReader
from scanner_utils import ScannerProtocolError
from web.log_buffer import LogBuffer


class DeviceSession:
    """Singleton-style session serializing IMV SDK access."""

    def __init__(self) -> None:
        self._imv_lock = threading.RLock()
        self.reader = ScannerReader()
        self.logs = LogBuffer()
        self._preview: PreviewStream | None = None
        self._tcp: TcpScanClient | None = None
        self._tcp_port = 3000
        self._scan_subscribers: list[Any] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def _log(self, level: str, message: str, **extra: Any) -> None:
        self.logs.add(level, message, **extra)

    @property
    def connected(self) -> bool:
        return self.reader.connected

    @property
    def preview_running(self) -> bool:
        return self._preview is not None and self._preview.running

    @property
    def tcp_connected(self) -> bool:
        return self._tcp is not None and self._tcp.connected

    def list_devices(self, interface: str | None = None) -> list[dict[str, Any]]:
        with self._imv_lock:
            devices = self.reader.enum_devices(interface_name=interface)
        self._log("info", f"Enumerated {len(devices)} device(s)")
        return devices

    def connect(
        self,
        *,
        serial_number: str | None = None,
        ip: str | None = None,
        interface: str | None = None,
        tcp_port: int = 3000,
        start_preview: bool = True,
        start_tcp: bool = True,
    ) -> dict[str, Any]:
        was_connected = self.reader.connected
        self.disconnect(log=False)
        if was_connected:
            time.sleep(0.5)
        self._tcp_port = tcp_port

        with self._imv_lock:
            device_info = self.reader.connect(
                serial_number=serial_number,
                ip=ip,
                interface_name=interface,
            )
        self._log("info", "IMV device connected", ip=device_info.get("ip_address"))

        if start_tcp:
            host = str(device_info.get("ip_address") or ip or "")
            if host:
                self._start_tcp(host, tcp_port)
            else:
                self._log("warning", "No device IP for TCP scan client")

        if start_preview and self.reader.cam is not None:
            with self._imv_lock:
                self._start_preview_locked()

        return {
            "device": device_info,
            "preview_running": self.preview_running,
            "tcp_connected": self.tcp_connected,
            "tcp_port": tcp_port,
        }

    def disconnect(self, *, log: bool = True) -> None:
        self._stop_tcp()
        self._stop_preview()
        was_connected = self.reader.connected
        with self._imv_lock:
            if was_connected:
                self.reader.disconnect()
        if log and was_connected:
            self._log("info", "Device disconnected")

    def get_device_status(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "device": self.reader.device_info,
            "preview_running": self.preview_running,
            "tcp_connected": self.tcp_connected,
            "tcp_port": self._tcp_port,
            "tcp_last_error": self._tcp.last_error if self._tcp else None,
            "sdk_version": self.reader.get_sdk_version() if self.connected else None,
        }

    def read_config(self) -> dict[str, Any]:
        with self._imv_lock:
            self._ensure_imv()
            assert self.reader.cam is not None
            return read_device_config(self.reader.cam)

    def write_config(self, updates: dict[str, Any], *, persist: bool = True) -> dict[str, Any]:
        was_preview = self.preview_running
        if was_preview:
            self._stop_preview()
        with self._imv_lock:
            self._ensure_imv()
            assert self.reader.cam is not None
            result = write_device_config(self.reader.cam, updates, persist=persist)
        if was_preview and self.reader.cam is not None:
            with self._imv_lock:
                self._start_preview_locked()
        self._log("info", "Config updated", keys=list(updates.keys()))
        return result

    def export_configs(self, output_dir: Path) -> dict[str, str]:
        with self._imv_lock:
            self._ensure_imv()
            return self.reader.export_configs(output_dir)

    def import_config(self, *, persist: bool = True) -> dict[str, Any]:
        was_preview = self.preview_running
        if was_preview:
            self._stop_preview()
        with self._imv_lock:
            self._ensure_imv()
            result = self.reader.import_device_config(persist=persist)
        if was_preview and self.reader.cam is not None:
            with self._imv_lock:
                self._start_preview_locked()
        self._log("info", "Camera config imported", path=result.get("config_path"))
        return result

    def start_preview(self) -> None:
        with self._imv_lock:
            self._ensure_imv()
            if self.preview_running:
                return
            self._start_preview_locked()

    def stop_preview(self) -> None:
        self._stop_preview()

    def get_preview_frame(self, timeout: float = 2.0) -> bytes | None:
        if self._preview is None:
            return None
        return self._preview.get_frame(timeout=timeout)

    def subscribe_scan(self, callback: Any) -> None:
        if self._tcp is None:
            raise ScannerProtocolError("TCP scan client is not running.")
        self._tcp.subscribe(callback)

    def unsubscribe_scan(self, callback: Any) -> None:
        if self._tcp is not None:
            self._tcp.unsubscribe(callback)

    def get_latest_scan(self) -> dict[str, Any] | None:
        if self._tcp is None:
            return None
        return self._tcp.get_latest()

    def _ensure_imv(self) -> None:
        if not self.reader.connected or self.reader.cam is None:
            raise ScannerProtocolError("Device is not connected.")

    def _start_preview_locked(self) -> None:
        assert self.reader.cam is not None
        self._preview = PreviewStream(self.reader.cam)
        self._preview.start()
        self._log("info", "Preview stream started")

    def _stop_preview(self) -> None:
        if self._preview is not None:
            self._preview.stop()
            self._preview = None
            self._log("info", "Preview stream stopped")

    def _start_tcp(self, host: str, port: int) -> None:
        self._stop_tcp()
        self._tcp = TcpScanClient(host=host, port=port)

        def on_scan(item: dict[str, Any]) -> None:
            loop = self._loop
            if loop is None or not loop.is_running():
                return
            for ws_queue in list(self._scan_subscribers):
                try:
                    loop.call_soon_threadsafe(ws_queue.put_nowait, item)
                except Exception:
                    pass

        self._tcp.subscribe(on_scan)
        self._tcp.start()
        self._log("info", f"TCP scan client started ({host}:{port})")

    def _stop_tcp(self) -> None:
        if self._tcp is not None:
            self._tcp.stop()
            self._tcp = None

    def register_ws_queue(self, q: asyncio.Queue) -> None:
        self._scan_subscribers.append(q)

    def unregister_ws_queue(self, q: asyncio.Queue) -> None:
        if q in self._scan_subscribers:
            self._scan_subscribers.remove(q)


_session: DeviceSession | None = None


def get_session() -> DeviceSession:
    global _session
    if _session is None:
        _session = DeviceSession()
    return _session
