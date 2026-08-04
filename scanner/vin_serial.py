"""Serial barcode scanner for VIN / frame number (keyboard-wedge alternative)."""

from __future__ import annotations

import os
import re
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import serial

TRIGGER_ON = b"\x16T\r"
TRIGGER_OFF = b"\x16U\r"

_DEFAULT_PORT = "COM8"
_DEFAULT_BAUDRATE = 115200
_DEFAULT_READ_TIMEOUT_S = 3.0
_POLL_INTERVAL_S = 0.05

_lock = threading.Lock()


class VinSerialError(Exception):
    """Raised when serial VIN scan fails."""


def _env_port() -> str:
    return os.environ.get("SN_SCANNER_PORT", _DEFAULT_PORT).strip() or _DEFAULT_PORT


def _env_baudrate() -> int:
    raw = os.environ.get("SN_SCANNER_BAUDRATE", str(_DEFAULT_BAUDRATE)).strip()
    try:
        return int(raw)
    except ValueError:
        return _DEFAULT_BAUDRATE


def _env_read_timeout_s() -> float:
    raw = os.environ.get("SN_SCANNER_READ_TIMEOUT", str(_DEFAULT_READ_TIMEOUT_S)).strip()
    try:
        value = float(raw)
        return value if value > 0 else _DEFAULT_READ_TIMEOUT_S
    except ValueError:
        return _DEFAULT_READ_TIMEOUT_S


def normalize_vin(raw: str) -> str:
    """Strip control characters (matches frontend normalizeVin)."""
    return re.sub(r"[\x00-\x1f\x7f]", "", raw).strip()


def scan_vin_once() -> str:
    """
    Open serial port, trigger scanner, read one barcode, turn laser off.

    Returns normalized VIN string. Raises VinSerialError on failure.
    """
    import serial
    from serial import SerialException

    port = _env_port()
    baudrate = _env_baudrate()
    read_timeout_s = _env_read_timeout_s()

    with _lock:
        ser: serial.Serial | None = None
        try:
            ser = serial.Serial(port, baudrate, timeout=1)
            ser.write(TRIGGER_ON)

            deadline = time.time() + read_timeout_s
            barcode = ""
            while time.time() < deadline:
                if ser.in_waiting > 0:
                    raw_data = ser.readline()
                    candidate = normalize_vin(
                        raw_data.decode("utf-8", errors="ignore")
                    )
                    if candidate:
                        barcode = candidate
                        break
                time.sleep(_POLL_INTERVAL_S)

            if not barcode:
                raise VinSerialError(
                    f"No barcode within {read_timeout_s:.0f}s on {port}. "
                    "Point the scanner at the VIN label and try again."
                )
            return barcode
        except SerialException as exc:
            raise VinSerialError(f"Serial port {port!r} unavailable: {exc}") from exc
        finally:
            if ser is not None and ser.is_open:
                try:
                    ser.write(TRIGGER_OFF)
                except SerialException:
                    pass
                ser.close()
