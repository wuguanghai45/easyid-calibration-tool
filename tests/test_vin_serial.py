"""Tests for automatic VIN scanner serial-port discovery."""

from __future__ import annotations

import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scanner import vin_serial


def _port(
    device: str,
    *,
    description: str = "",
    hwid: str = "",
    vid: int | None = None,
) -> SimpleNamespace:
    """Build the subset of serial-port metadata used by the discovery logic."""
    return SimpleNamespace(
        device=device,
        description=description,
        hwid=hwid,
        manufacturer="",
        product="",
        interface="",
        vid=vid,
    )


class VinSerialDiscoveryTests(unittest.TestCase):
    """Verify port selection and reconnect behavior without serial hardware."""

    def test_configured_port_defaults_to_auto(self) -> None:
        """Treat missing, blank, and explicit auto settings as auto-detection."""
        for value in (None, "", " auto ", "AUTO"):
            environment = {} if value is None else {"SN_SCANNER_PORT": value}
            with self.subTest(value=value), patch.dict(
                os.environ,
                environment,
                clear=True,
            ):
                self.assertIsNone(vin_serial._configured_port())

    def test_explicit_port_bypasses_discovery(self) -> None:
        """Preserve SN_SCANNER_PORT as an override for multi-device systems."""
        with patch.dict(os.environ, {"SN_SCANNER_PORT": " COM23 "}, clear=True), patch(
            "scanner.vin_serial._available_ports"
        ) as available_ports:
            self.assertEqual(vin_serial._candidate_ports(), ["COM23"])
            available_ports.assert_not_called()

    def test_auto_mode_uses_discovered_ports(self) -> None:
        """Use the live enumeration result when no fixed port is configured."""
        with patch.dict(os.environ, {}, clear=True), patch(
            "scanner.vin_serial._available_ports",
            return_value=["COM7", "COM11"],
        ):
            self.assertEqual(vin_serial._candidate_ports(), ["COM7", "COM11"])

    def test_port_ranking_prefers_scanner_then_usb(self) -> None:
        """Prioritize scanner-labelled and USB ports over built-in serial ports."""
        ports = [
            _port("COM10", description="USB Serial Port", vid=0x1234),
            _port("COM2", description="Communications Port"),
            _port("COM12", description="Barcode Scanner"),
            _port("COM3", description="USB Serial Port", vid=0x1234),
        ]

        ordered = [port.device for port in sorted(ports, key=vin_serial._port_sort_key)]

        self.assertEqual(ordered, ["COM12", "COM3", "COM10", "COM2"])

    def test_run_loop_falls_back_when_first_port_cannot_open(self) -> None:
        """Try the next detected port when a higher-ranked candidate is busy."""

        class FakeSerialException(Exception):
            """Represent pyserial connection errors in the fake module."""

        monitor = vin_serial.VinSerialMonitor()
        attempts: list[str] = []

        class FakePort:
            """Return one VIN and then stop the synchronous monitor loop."""

            is_open = True

            def readline(self) -> bytes:
                """Simulate one scanner result and request loop shutdown."""
                monitor._stop.set()
                return b"TESTVIN123\r\n"

            def close(self) -> None:
                """Record the fake port as closed."""
                self.is_open = False

        def open_port(port: str, baudrate: int, *, timeout: float) -> FakePort:
            """Fail COM3 and connect the scanner exposed as COM10."""
            del baudrate, timeout
            attempts.append(port)
            if port == "COM3":
                raise FakeSerialException("busy")
            return FakePort()

        serial_module = types.ModuleType("serial")
        serial_module.Serial = open_port
        serial_module.SerialException = FakeSerialException

        with patch.dict(sys.modules, {"serial": serial_module}), patch(
            "scanner.vin_serial._candidate_ports",
            return_value=["COM3", "COM10"],
        ):
            monitor._run_loop()

        self.assertEqual(attempts, ["COM3", "COM10"])
        self.assertEqual(monitor.sequence, 1)
        self.assertEqual(monitor.status()["port"], "COM10")


if __name__ == "__main__":
    unittest.main()
