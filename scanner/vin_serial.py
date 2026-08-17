"""Continuously monitor a serial barcode scanner for VIN / frame numbers."""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    import serial
    from serial.tools.list_ports_common import ListPortInfo

TRIGGER_ON = b"\x16T\r"
TRIGGER_OFF = b"\x16U\r"

_DEFAULT_BAUDRATE = 115200
_DEFAULT_READ_TIMEOUT_S = 3.0
_SERIAL_POLL_TIMEOUT_S = 0.5
_RECONNECT_DELAY_S = 1.0
_SCANNER_PORT_KEYWORDS = ("barcode", "scanner", "scan", "条码", "扫码")


class VinSerialError(Exception):
    """Raised when waiting for serial VIN output fails."""


def _configured_port() -> str | None:
    """Return an explicit scanner port, or ``None`` when auto-detection is enabled."""
    value = os.environ.get("SN_SCANNER_PORT", "").strip()
    return None if not value or value.lower() == "auto" else value


def _port_sort_key(port: ListPortInfo) -> tuple[int, int, str]:
    """Rank likely barcode-scanner ports before other serial interfaces."""
    metadata = " ".join(
        str(value or "")
        for value in (
            getattr(port, "device", ""),
            getattr(port, "description", ""),
            getattr(port, "hwid", ""),
            getattr(port, "manufacturer", ""),
            getattr(port, "product", ""),
            getattr(port, "interface", ""),
        )
    ).lower()
    scanner_rank = (
        0 if any(word in metadata for word in _SCANNER_PORT_KEYWORDS) else 1
    )
    usb_rank = 0 if getattr(port, "vid", None) is not None or "usb" in metadata else 1
    natural_device = re.sub(
        r"\d+",
        lambda match: f"{int(match.group()):010d}",
        port.device.lower(),
    )
    return scanner_rank, usb_rank, natural_device


def _available_ports() -> list[str]:
    """Enumerate serial ports with likely USB barcode scanners first."""
    from serial.tools import list_ports

    ports = sorted(list_ports.comports(), key=_port_sort_key)
    return list(dict.fromkeys(port.device for port in ports if port.device))


def _candidate_ports() -> list[str]:
    """Return the configured port or all currently detected serial ports."""
    configured_port = _configured_port()
    return [configured_port] if configured_port else _available_ports()


def _env_baudrate() -> int:
    """Return the configured baud rate, falling back on invalid input."""
    raw = os.environ.get("SN_SCANNER_BAUDRATE", str(_DEFAULT_BAUDRATE)).strip()
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_BAUDRATE


def _env_read_timeout_s() -> float:
    """Return the configured foreground wait timeout in seconds."""
    raw = os.environ.get("SN_SCANNER_READ_TIMEOUT", str(_DEFAULT_READ_TIMEOUT_S)).strip()
    try:
        value = float(raw)
        return value if value > 0 else _DEFAULT_READ_TIMEOUT_S
    except ValueError:
        return _DEFAULT_READ_TIMEOUT_S


def normalize_vin(raw: str) -> str:
    """Strip serial control characters and surrounding whitespace."""
    return re.sub(r"[\x00-\x1f\x7f]", "", raw).strip()


class VinSerialMonitor:
    """Keep the scanner serial port open and publish physical-button scan output.

    Background monitoring never sends trigger or illumination commands. The
    explicit ``trigger_and_wait`` method preserves the original manual workflow.
    """

    def __init__(self) -> None:
        """Initialize monitor state without opening the serial port."""
        self._condition = threading.Condition()
        self._serial_lock = threading.Lock()
        self._trigger_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._serial: serial.Serial | None = None
        self._sequence = 0
        self._latest: dict[str, Any] | None = None
        self._connected = False
        self._port: str | None = None
        self._last_error: str | None = None

    @property
    def sequence(self) -> int:
        """Return the sequence number of the latest decoded scan."""
        with self._condition:
            return self._sequence

    def status(self) -> dict[str, Any]:
        """Return connection state and the latest scan sequence."""
        with self._condition:
            return {
                "connected": self._connected,
                "sequence": self._sequence,
                "port": self._port or _configured_port() or "auto",
                "last_error": self._last_error,
            }

    def _port_label(self) -> str:
        """Return the active/configured port name for user-facing diagnostics."""
        with self._condition:
            return self._port or _configured_port() or "an auto-detected serial port"

    def start(self) -> None:
        """Start the background serial reader if it is not already running."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="VinSerialMonitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the background serial reader and wait briefly for it to exit."""
        self._stop.set()
        with self._condition:
            self._condition.notify_all()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None

    def wait_for_scan(
        self,
        *,
        after_sequence: int | None = None,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        """Wait for a decoded value newer than ``after_sequence``.

        If no sequence is supplied, scans already received before this call are
        ignored so a manual start always waits for the next hardware-button scan.
        """
        timeout = timeout_s if timeout_s is not None else _env_read_timeout_s()
        deadline = time.monotonic() + timeout

        with self._condition:
            cursor = self._sequence if after_sequence is None else after_sequence
            while self._sequence <= cursor:
                if self._stop.is_set():
                    raise VinSerialError("Serial scanner monitor has stopped.")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    detail = f" Last serial error: {self._last_error}" if self._last_error else ""
                    raise VinSerialError(
                        f"No barcode output within {timeout:g}s on {self._port_label()}."
                        f" Press the scanner button and try again.{detail}"
                    )
                self._condition.wait(timeout=remaining)

            if self._latest is None:
                raise VinSerialError("Serial scanner reported a scan without data.")
            return dict(self._latest)

    def trigger_and_wait(self, timeout_s: float | None = None) -> dict[str, Any]:
        """Run the original manual flow: trigger, wait for output, then turn off.

        The command is written through the monitor's existing serial connection so
        manual calibration does not compete with continuous monitoring for the port.
        """
        timeout = timeout_s if timeout_s is not None else _env_read_timeout_s()
        deadline = time.monotonic() + timeout

        with self._trigger_lock:
            with self._condition:
                cursor = self._sequence
                while not self._connected:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        detail = (
                            f": {self._last_error}" if self._last_error else ""
                        )
                        raise VinSerialError(
                            f"Serial port {self._port_label()!r} unavailable{detail}"
                        )
                    self._condition.wait(timeout=remaining)

            self._write_command(TRIGGER_ON)
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise VinSerialError(
                        f"No barcode within {timeout:g}s on {self._port_label()}."
                    )
                return self.wait_for_scan(
                    after_sequence=cursor,
                    timeout_s=remaining,
                )
            finally:
                try:
                    self._write_command(TRIGGER_OFF)
                except VinSerialError:
                    pass

    def _publish(self, vin: str) -> None:
        """Publish one normalized VIN and wake all waiting requests."""
        with self._condition:
            self._sequence += 1
            self._latest = {
                "vin": vin,
                "sequence": self._sequence,
                "ts": time.time(),
            }
            self._condition.notify_all()

    def _set_connection(
        self,
        connected: bool,
        error: str | None = None,
        *,
        port: str | None = None,
    ) -> None:
        """Update serial connection state exposed by the status endpoint."""
        with self._condition:
            self._connected = connected
            self._last_error = error
            if port is not None:
                self._port = port
            self._condition.notify_all()

    def _write_command(self, command: bytes) -> None:
        """Write a manual trigger command through the monitored serial port."""
        from serial import SerialException

        with self._serial_lock:
            if self._serial is None or not self._serial.is_open:
                raise VinSerialError(
                    f"Serial port {self._port_label()!r} is not connected."
                )
            try:
                self._serial.write(command)
            except (SerialException, OSError) as exc:
                raise VinSerialError(
                    f"Failed to write scanner command on {self._port_label()!r}: {exc}"
                ) from exc

    def _run_loop(self) -> None:
        """Reconnect as needed and read scanner output without sending commands."""
        import serial
        from serial import SerialException

        while not self._stop.is_set():
            try:
                candidates = _candidate_ports()
            except (SerialException, OSError) as exc:
                self._set_connection(False, f"Failed to enumerate serial ports: {exc}")
                self._stop.wait(_RECONNECT_DELAY_S)
                continue
            if not candidates:
                self._set_connection(
                    False,
                    "No serial ports found. Connect the barcode scanner and retry.",
                )
                self._stop.wait(_RECONNECT_DELAY_S)
                continue

            for port in candidates:
                scanner_port: serial.Serial | None = None
                opened = False
                try:
                    scanner_port = serial.Serial(
                        port,
                        _env_baudrate(),
                        timeout=_SERIAL_POLL_TIMEOUT_S,
                    )
                    opened = True
                    with self._serial_lock:
                        self._serial = scanner_port
                    self._set_connection(True, port=port)

                    while not self._stop.is_set():
                        raw_data = scanner_port.readline()
                        if not raw_data:
                            continue
                        candidate = normalize_vin(
                            raw_data.decode("utf-8", errors="ignore")
                        )
                        if candidate:
                            self._publish(candidate)
                except (SerialException, OSError) as exc:
                    self._set_connection(False, str(exc), port=port)
                finally:
                    with self._serial_lock:
                        self._serial = None
                        if scanner_port is not None and scanner_port.is_open:
                            try:
                                scanner_port.close()
                            except SerialException:
                                pass
                    self._set_connection(False, self._last_error)

                if opened or self._stop.is_set():
                    break

            self._stop.wait(_RECONNECT_DELAY_S)


_monitor: VinSerialMonitor | None = None
_monitor_lock = threading.Lock()


def get_vin_serial_monitor() -> VinSerialMonitor:
    """Return the process-wide serial scanner monitor."""
    global _monitor
    with _monitor_lock:
        if _monitor is None:
            _monitor = VinSerialMonitor()
        return _monitor
